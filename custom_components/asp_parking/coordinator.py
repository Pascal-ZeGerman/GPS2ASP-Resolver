"""Event-driven coordinator for the ASP Parking integration.

Orchestrates the full GPS-to-schedule pipeline: subscribes to device_tracker
state changes, debounces rapid GPS jitter, checks movement threshold, and
runs the three-phase pipeline (resolve -> retrieve_signs -> compute_schedule).

This is a custom coordinator (not DataUpdateCoordinator) since the data source
is event-driven (GPS updates), not polled.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal, cast

import httpx

from homeassistant.const import ATTR_LATITUDE, ATTR_LONGITUDE
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    HomeAssistant,
    callback,
)
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.location import has_location
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util import location as location_util

from zoneinfo import ZoneInfo

from .gps2asp.resolver import convert, resolve
from .gps2asp.resolver.exceptions import (
    AmbiguousResolutionError,
    NoSegmentFoundError,
    OutsideNYCError,
)
from .gps2asp.resolver.spatial_index import SpatialIndex
from .gps2asp.schedule import compute_schedule
from .gps2asp.schedule.models import (
    AllUnparseable,
    ASPActiveNow,
    CleaningWindow,
    ScheduleFound,
    ScheduleResult,
)
from .gps2asp.signs import materialize_cached_records, retrieve_signs
from .gps2asp.signs.client import SODAClient
from .gps2asp.signs.models import SignRetrievalSuccess
from .gps2asp.signs.normalize import name_variants
from .gps2asp.suspension import HolidayCalendar, NYC311Client, SuspensionInfo
from .gps2asp.suspension.poller import NYC311AuthError

from . import caldav_sync
from .caldav_sync import CalDAVConfig, _sanitise as _caldav_sanitise
from .const import (
    CONF_CALDAV_CALENDAR,
    CONF_CALDAV_PASSWORD,
    CONF_CALDAV_SAFETY_WINDOW,
    CONF_CALDAV_URL,
    CONF_CALDAV_USERNAME,
    CONF_DEBUG_DATETIME,
    CONF_DEBUG_LAT,
    CONF_DEBUG_LON,
    CONF_DEVICE_TRACKER,
    CONF_MOVEMENT_THRESHOLD,
    CONF_NOTIFY_LEAD_TIME,
    CONF_NOTIFY_SERVICE,
    CONF_NYC311_API_KEY,
    CONF_NYC311_ENTITY,
    CONF_PARKING_LAT,
    CONF_PARKING_LON,
    CONF_PARKING_RADIUS,
    CONF_REFRESH_INTERVAL,
    CONF_STALE_TIMEOUT,
    CONF_SUPPRESS_NOTIFICATIONS,
    DEFAULT_CALDAV_SAFETY_WINDOW,
    DEFAULT_DEBUG_DATETIME,
    DEFAULT_DEBUG_LAT,
    DEFAULT_DEBUG_LON,
    DEFAULT_MOVEMENT_THRESHOLD,
    DEFAULT_NOTIFY_LEAD_TIME,
    DEFAULT_NOTIFY_SERVICE,
    DEFAULT_NYC311_BRIDGE_ENTITY,
    DEFAULT_NYC311_ENTITY,
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_STALE_TIMEOUT,
    DEFAULT_SUPPRESS_NOTIFICATIONS,
    DEFAULT_SUSPENSION_INTERVAL,
    DOMAIN,
    GPS_DEBOUNCE_COOLDOWN,
    GITHUB_INDEX_RELEASE_TAG,
    GITHUB_RELEASES_API_BASE,
    BUTTON_DOUBLE_PRESS_WINDOW_HOURS,
    INDEX_DOWNLOAD_URL,
    REMOTE_FRESH_DAYS,
    STALE_CHECK_INTERVAL_HOURS,
    STALE_INDEX_DAYS,
)
from .index_io import (
    INDEX_DIR,
    _sync_atomic_swap,
    _sync_build_from_source,
    _sync_cleanup_stale,
    _sync_download_and_extract,
    _sync_read_build_timestamp,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

logger = logging.getLogger(__name__)

NYC_TZ = ZoneInfo("America/New_York")

_METRES_TO_FEET = 3.28084  # 1 metre = 3.28084 US survey feet

_BOROUGH_NAMES: dict[str, str] = {
    "1": "Manhattan",
    "2": "Bronx",
    "3": "Brooklyn",
    "4": "Queens",
    "5": "Staten Island",
}


class RebuildPath(Enum):
    """Phase 38 (IDX-05): which executor strategy services a rebuild request.

    DOWNLOAD       — fast-path GitHub release zip (_sync_download_and_extract)
    FROM_SOURCE    — full CSCL rebuild from live API (_sync_build_from_source)
    """

    DOWNLOAD = "download"
    FROM_SOURCE = "from_source"


@dataclass
class ASPParkingData:
    """Container for all coordinator state read by entities.

    Mutable (not frozen) because the coordinator updates it incrementally
    as pipeline results arrive or errors occur.

    Attributes:
        schedule_result: Latest pipeline result from compute_schedule.
        special_state: Sentinel for non-schedule states:
            "outside_coverage", "no_street_match", or None.
        last_lat: Last GPS latitude coordinate.
        last_lon: Last GPS longitude coordinate.
        last_resolved: Timestamp of last successful pipeline run.
        last_gps_update: Timestamp of last GPS state change event.
        last_error: String description of last error, if any.
        last_error_time: Timestamp of last error, if any.
        confidence_score: Confidence score from resolver.
        sign_count: Number of signs retrieved from SODA.
        parse_failures: Count of unparseable signs.
        soda_level: Which SODA fallback level matched (1–4); 0 if not resolved.
        borough: Human-readable borough name ("Manhattan", "Bronx", "Brooklyn",
            "Queens", "Staten Island"); None if not resolved or unmapped (Phase 30, D-11).
        distance_ft: Perpendicular distance from GPS point to segment centerline
            (feet, rounded to 2 decimals). None if not resolved (Phase 30).
        street_width_ft: Effective street width used in confidence calc (feet,
            post-fallback). None if not resolved (Phase 30).
        segment_id: CSCL physical segment ID. None if not resolved (Phase 30).
    """

    schedule_result: ScheduleResult | None = None
    special_state: str | None = None
    last_lat: float | None = None
    last_lon: float | None = None
    last_resolved: datetime | None = None
    last_gps_update: datetime | None = None
    last_error: str | None = None
    last_error_time: datetime | None = None
    confidence_score: float | None = None
    sign_count: int = 0
    parse_failures: int = 0
    soda_level: int = 0  # which SODA fallback level matched (1–4); 0 if not resolved
    borough: str | None = None
    distance_ft: float | None = None
    street_width_ft: float | None = None
    segment_id: int | None = None
    suspension_state: SuspensionInfo = field(
        default_factory=lambda: SuspensionInfo(
            is_suspended=False, reason=None, source="none"
        )
    )
    last_notified_window: CleaningWindow | None = None


def _legal_sides_for(candidate) -> tuple[str, ...]:
    """Return the two legal compass sides for a segment based on nominaldir.

    For N–S oriented streets (nominaldir N or S) sides are E/W.
    For E–W oriented streets (nominaldir E or W) sides are N/S.
    Defaults to all four if nominaldir is unknown so the cache stays correct.
    """
    nd = (candidate.nominaldir or "").upper().strip()
    if nd in ("N", "S"):
        return ("E", "W")
    if nd in ("E", "W"):
        return ("N", "S")
    return ("N", "S", "E", "W")


class ASPParkingCoordinator:
    """Event-driven coordinator for ASP Parking.

    Subscribes to device_tracker state changes and runs the GPS-to-schedule
    pipeline when significant movement is detected. Provides debouncing for
    GPS jitter, periodic refresh for schedule currency, and fallback to last
    known state on errors.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator.

        Args:
            hass: Home Assistant instance.
            entry: Config entry for this integration instance.
        """
        self.hass = hass
        self.entry = entry
        self.data = ASPParkingData()

        # Suspension state
        self._holiday_calendar: HolidayCalendar | None = None
        self._nyc311_client: NYC311Client | None = None
        self._nyc311_bridge_entity: str | None = (
            None  # ha-nyc311 entity ID if bridge active
        )

        # Cleanup callables for event subscriptions
        self._listeners: list[CALLBACK_TYPE] = []

        # Entity notification callbacks
        self._entity_update_callbacks: list[CALLBACK_TYPE] = []

        # Pending coordinates for debounced pipeline execution
        self._pending_lat: float | None = None
        self._pending_lon: float | None = None

        # Debug overrides (Phase 24)
        self._debug_enabled: bool = False
        self._debug_lat: float | None = None
        self._debug_lon: float | None = None
        self._debug_datetime: datetime | None = None
        self._debug_suppress_notifications: bool = False
        self._notify_service: str = ""
        self._notify_lead_time: int = DEFAULT_NOTIFY_LEAD_TIME

        # Parking area + sign cache (Phase 26)
        self._parking_lat: float | None = None
        self._parking_lon: float | None = None
        self._parking_radius_m: int | None = None
        # Cache key: (on_street, from_street, to_street, side_of_street)
        # Value (BUG-S-007 / Phase 35.1-05): dict with two keys:
        #   - "records": list of raw SODA records (may be empty after lookup
        #     — empty currently skipped at write time, so all entries are
        #     non-empty)
        #   - "soda_level": int 1..4 — the SODA fallback level that produced
        #     these records; propagated into materialize_cached_records() so
        #     the sensor's soda_level attribute reflects the actual fallback
        #     level rather than a hardcoded 1.
        self._sign_cache: dict[
            tuple[str, str, str, str], dict[str, list[dict] | int]
        ] = {}
        self._preseed_task: asyncio.Task[None] | None = None
        self._unsub_cache_rebuild: CALLBACK_TYPE | None = None
        # Phase 39: one-shot window-boundary timer handle (D-03).
        # Dedicated attribute — NOT appended to self._listeners.
        # async_stop() explicitly calls self._boundary_timer_cancel().
        self._boundary_timer_unsub: CALLBACK_TYPE | None = None
        # GPS stale watchdog: fires persistent notification when GPS goes silent
        # for longer than stale_timeout hours.  NOT appended to self._listeners;
        # explicitly cancelled by async_stop() via _gps_watchdog_cancel().
        self._gps_stale_unsub: CALLBACK_TYPE | None = None
        self._last_pipeline_error: bool = False

        # Phase 33: index rebuild lifecycle (IDX-02..IDX-04).
        # Lock is constructed inside __init__ (NOT at class scope) so it binds
        # to the current event loop per RESEARCH Pitfall 1.
        self._is_rebuilding: bool = False
        self._rebuild_task: asyncio.Task[None] | None = None
        self._rebuild_lock: asyncio.Lock = asyncio.Lock()
        self._last_rebuilt: datetime | None = None

        # Phase 38: dual-path rebuild + stale detection (IDX-05).
        # ``_index_stale_store`` is initialised by Plan 03 in ``async_start``;
        # this plan writes through it defensively when present so the
        # 24h double-press window survives HA restarts once Plan 03 lands.
        # ``_remote_age_cache`` caches the GitHub Releases response for
        # 10 minutes to absorb the 60-req/hour anonymous rate limit
        # (RESEARCH Pitfall 2).
        self._index_stale_store: Store | None = None
        self._last_button_press: datetime | None = None
        self._last_stale_check: datetime | None = None
        self._remote_age_cache: tuple[datetime, float | None] | None = None

        # Phase 34: CalDAV calendar sync (CALDAV-03..CALDAV-06).
        # Lock is constructed inside __init__ (NOT at class scope — Pitfall 2).
        self._caldav_store: Store | None = None  # set in async_start when configured
        self._caldav_uid: str | None = None
        self._caldav_write_error_notified: bool = False
        self._caldav_delete_error_notified: bool = False
        self._last_suspension_state: bool = False  # refreshed in async_start
        self._caldav_lock: asyncio.Lock = asyncio.Lock()
        self._caldav_write_task: asyncio.Task[None] | None = None
        self._caldav_delete_task: asyncio.Task[None] | None = None

        # Pipeline-level reentrancy guard (T-PR19-04): serialises
        # _async_resolve_pipeline so concurrent invocations (Debouncer,
        # boundary-timer fire closure, async_force_resolve) cannot interleave
        # their self.data mutations. None of the three callers invoke the
        # pipeline from within itself, so this Lock cannot self-deadlock.
        self._pipeline_lock: asyncio.Lock = asyncio.Lock()

        # Debouncer: coalesce rapid GPS updates into a single pipeline run
        self._debouncer = Debouncer(
            hass,
            logger,
            cooldown=GPS_DEBOUNCE_COOLDOWN,
            immediate=False,
            function=self._async_resolve_pipeline,
        )

    # ------------------------------------------------------------------
    # Properties (read from config entry)
    # ------------------------------------------------------------------

    @property
    def device_tracker_entity(self) -> str:
        """Return the device_tracker entity ID from config."""
        return self.entry.data[CONF_DEVICE_TRACKER]

    @property
    def movement_threshold(self) -> float:
        """Return the movement threshold in meters."""
        return self.entry.options.get(
            CONF_MOVEMENT_THRESHOLD, DEFAULT_MOVEMENT_THRESHOLD
        )

    @property
    def refresh_interval(self) -> int:
        """Return the periodic refresh interval in hours."""
        return self.entry.options.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL)

    @property
    def stale_timeout(self) -> int:
        """Return the stale GPS timeout in hours."""
        return self.entry.options.get(CONF_STALE_TIMEOUT, DEFAULT_STALE_TIMEOUT)

    def _get_now(self) -> datetime:
        """Return debug datetime override when active, otherwise real now.

        Per D-08: returns the debug datetime override for ALL time-sensitive
        coordinator operations when debug mode is active.

        BUG-H-005 (Phase 35.1-05): In normal mode, delegate to ``dt_util.now()``
        — Home Assistant's configured timezone — instead of
        ``datetime.now(NYC_TZ)``. This matches the project convention
        (MEMORY.md: "Use dt_util.now() (HA configured TZ) not hardcoded
        NYC_TZ for day-boundary display labels") and lets the coordinator
        respect a non-NYC HA installation timezone for downstream day/week
        boundary computations.

        WARNING: this returns HA-local time. Use ``_get_now_nyc()`` for any
        operation that must use NYC's calendar date (holiday suspension
        lookups, NYC-specific calendar boundaries). See WR-07.
        """
        if self._debug_enabled and self._debug_datetime is not None:
            return self._debug_datetime
        return dt_util.now()

    def _get_now_nyc(self) -> datetime:
        """Return current time in NYC timezone for calendar-date operations.

        WR-07: ``_get_now()`` returns HA-local time, which is correct for
        display labels ("Today" / "Tomorrow" in the user's UI timezone)
        but WRONG for NYC-specific calendar lookups such as holiday
        suspension checks. An HA installation in ``Pacific/Honolulu``
        (UTC-10) running ``self._get_now().date()`` to look up "is today
        a NYC ASP holiday?" will return the previous NYC day for ~10
        hours after NYC midnight — silently mis-classifying the holiday.

        Use this method (not ``_get_now``) when feeding a date into
        ``HolidayCalendar.is_suspended(date)`` or any other NYC-calendar
        operation. Use ``_get_now`` for display labels and for next-move
        scheduling (which already carries timezone info via the
        ``ScheduleFound.next_move`` datetime).
        """
        return self._get_now().astimezone(NYC_TZ)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_start(self) -> None:
        """Start listening for GPS updates and schedule periodic refreshes.

        Subscribes to device_tracker state change events and sets up a
        periodic timer to refresh the schedule even without GPS movement.
        """
        # --- Debug overrides (Phase 24) — loaded FIRST so _get_now() is correct
        # for ALL subsequent calls in this method (suspension startup, bridge
        # detection, etc.).
        # D-02 (Phase 29): debug mode is in-memory only — switch.py is the
        # sole runtime setter. Always start as False on HA restart.
        self._debug_enabled = False
        self._debug_lat = self.entry.options.get(CONF_DEBUG_LAT, DEFAULT_DEBUG_LAT)
        self._debug_lon = self.entry.options.get(CONF_DEBUG_LON, DEFAULT_DEBUG_LON)
        raw_dt = self.entry.options.get(CONF_DEBUG_DATETIME, DEFAULT_DEBUG_DATETIME)
        if raw_dt and isinstance(raw_dt, str):
            try:
                parsed = datetime.fromisoformat(raw_dt)
                if parsed.tzinfo is not None:
                    self._debug_datetime = parsed.astimezone(NYC_TZ)
                else:
                    self._debug_datetime = parsed.replace(tzinfo=NYC_TZ)
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "ASP Parking: invalid debug datetime %r — ignoring (%s)",
                    raw_dt,
                    exc,
                )
                self._debug_datetime = None
        elif isinstance(raw_dt, datetime):
            self._debug_datetime = (
                raw_dt.astimezone(NYC_TZ)
                if raw_dt.tzinfo
                else raw_dt.replace(tzinfo=NYC_TZ)
            )
        self._debug_suppress_notifications = self.entry.options.get(
            CONF_SUPPRESS_NOTIFICATIONS, DEFAULT_SUPPRESS_NOTIFICATIONS
        )
        self._notify_service = self.entry.options.get(
            CONF_NOTIFY_SERVICE, DEFAULT_NOTIFY_SERVICE
        )
        self._notify_lead_time = int(
            self.entry.options.get(CONF_NOTIFY_LEAD_TIME, DEFAULT_NOTIFY_LEAD_TIME)
        )

        # Phase 26: parking area + sign cache config
        raw_lat = self.entry.options.get(CONF_PARKING_LAT)
        raw_lon = self.entry.options.get(CONF_PARKING_LON)
        raw_radius = self.entry.options.get(CONF_PARKING_RADIUS)
        self._parking_lat = float(raw_lat) if raw_lat is not None else None
        self._parking_lon = float(raw_lon) if raw_lon is not None else None
        self._parking_radius_m = int(raw_radius) if raw_radius is not None else None

        # Subscribe to GPS state changes
        unsub_state = async_track_state_change_event(
            self.hass,
            [self.device_tracker_entity],
            self._async_on_gps_update,  # type: ignore[arg-type]
        )
        self._listeners.append(unsub_state)

        # Periodic heartbeat: re-fetch ICS, re-check suspension, trigger pipeline
        unsub_interval = async_track_time_interval(
            self.hass,
            self._async_periodic_heartbeat,
            timedelta(hours=self.refresh_interval),
        )
        self._listeners.append(unsub_interval)

        # Phase 34: CalDAV Store pre-load — must happen BEFORE first suspension check
        # so _caldav_uid is available when _async_apply_suspension_state fires the
        # False→True delete guard on startup (Finding 5 fix).
        if self.entry.options.get(CONF_CALDAV_URL):
            self._caldav_store = Store(
                self.hass,
                version=1,
                key=f"{DOMAIN}_caldav_{self.entry.entry_id}",
            )
            raw = await self._caldav_store.async_load()
            if isinstance(raw, dict):
                self._caldav_uid = raw.get("uid")
            else:
                if raw is not None:
                    # IN-05: include entry_id so multi-entry installs can
                    # identify which entry's store is corrupted.
                    logger.warning(
                        "CalDAV store contained unexpected type %s for "
                        "entry_id=%s; discarding",
                        type(raw).__name__,
                        self.entry.entry_id,
                    )
                self._caldav_uid = None

        # --- Suspension startup ---
        self._holiday_calendar = HolidayCalendar()
        await self._holiday_calendar.load()

        # WR-07: holiday calendar uses NYC calendar dates. ``_get_now()``
        # returns HA-local time -- correct for display, wrong for NYC date
        # lookups when HA is configured for a non-NYC timezone.
        today = self._get_now_nyc().date()
        holiday_info = self._holiday_calendar.is_suspended(today)
        if holiday_info.is_suspended:
            self._async_apply_suspension_state(holiday_info)

        api_key = self.entry.options.get(CONF_NYC311_API_KEY)
        if api_key:
            self._nyc311_client = NYC311Client(api_key=api_key)
            self.entry.async_create_background_task(
                self.hass,
                self._async_initial_311_fetch(),
                name="asp_parking_initial_311_fetch",
            )

        unsub_suspension = async_track_time_interval(
            self.hass,
            self._async_suspension_poll,
            timedelta(minutes=DEFAULT_SUSPENSION_INTERVAL),
        )
        self._listeners.append(unsub_suspension)

        # --- ha-nyc311 bridge detection (D-01, D-02, D-03, D-10) ---
        nyc311_entity_override = self.entry.options.get(
            CONF_NYC311_ENTITY, DEFAULT_NYC311_ENTITY
        )
        if nyc311_entity_override:
            # D-02: User specified a custom entity ID
            bridge_entity_id = nyc311_entity_override
        else:
            # D-01: Auto-detect default ha-nyc311 entity
            bridge_entity_id = DEFAULT_NYC311_BRIDGE_ENTITY

        bridge_state = self.hass.states.get(bridge_entity_id)
        if bridge_state is not None:
            self._nyc311_bridge_entity = bridge_entity_id

            # D-04: Subscribe to state changes
            unsub_bridge = async_track_state_change_event(
                self.hass,
                [bridge_entity_id],
                self._async_on_nyc311_state_change,  # type: ignore[arg-type]
            )
            self._listeners.append(unsub_bridge)

            # D-10: Read current state immediately at startup.
            # Bridge is authoritative: "on" overrides holiday calendar, "off" clears any
            # holiday suspension that was set above, "unavailable"/"unknown" fail open.
            _bridge_info = self._bridge_state_to_info(
                bridge_state.state, bridge_state.attributes
            )
            if (
                self.data.suspension_state.is_suspended
                and not _bridge_info.is_suspended
            ):
                logger.info(
                    "ha-nyc311 bridge reported '%s' — overriding holiday suspension '%s'",
                    bridge_state.state,
                    self.data.suspension_state.reason,
                )
            self._async_apply_suspension_state(_bridge_info)

            # D-11: Log bridge active
            logger.debug(
                "ha-nyc311 bridge active on %s -- direct 311 polling suppressed",
                bridge_entity_id,
            )

        # Phase 26: schedule sign cache pre-seed if parking area is configured
        # (D-03: fire-and-forget, lifecycle-tied to config entry)
        if (
            self._parking_lat is not None
            and self._parking_lon is not None
            and self._parking_radius_m is not None
            and self._parking_radius_m > 0
        ):
            self._preseed_task = self.entry.async_create_background_task(
                self.hass,
                self._async_preseed_cache(),
                name="asp_parking_preseed",
            )
            # Periodic cache rebuild on refresh_interval (D-02)
            self._unsub_cache_rebuild = async_track_time_interval(
                self.hass,
                self._async_periodic_cache_rebuild,
                timedelta(hours=self.refresh_interval),
            )
            self._listeners.append(self._unsub_cache_rebuild)
        else:
            logger.debug(
                "Phase 26: parking area not configured (lat=%s, lon=%s, radius=%s); "
                "sign cache pre-seed skipped (D-07 fallback)",
                self._parking_lat,
                self._parking_lon,
                self._parking_radius_m,
            )

        # Phase 34: capture final suspension state AFTER all startup checks.
        if self._caldav_store is not None:
            self._last_suspension_state = self.data.suspension_state.is_suspended

        # Phase 33: pre-populate _last_rebuilt from build_info.json so the
        # last_rebuilt sensor is non-None on first startup (RESEARCH Open Q3).
        self._last_rebuilt = await self.hass.async_add_executor_job(
            _sync_read_build_timestamp, INDEX_DIR
        )

        # Phase 38 Plan 03 (IDX-07 + IDX-05 persistence): init the
        # asp_parking_index_stale Store with a FIXED key, hydrate
        # last_button_press / last_stale_check, spawn the startup
        # fire-and-forget stale-check (D-01), and register the daily 24h
        # interval (D-02).  Must run AFTER _last_rebuilt is populated so
        # the startup task can compare against the actual index age.
        await self._async_init_stale_lifecycle()

        logger.info(
            "ASP Parking coordinator started: tracking %s, "
            "movement threshold %.0fm, refresh every %dh",
            self.device_tracker_entity,
            self.movement_threshold,
            self.refresh_interval,
        )

    async def async_stop(self) -> None:
        """Stop all listeners and cancel the debouncer."""
        for unsub in self._listeners:
            unsub()
        self._listeners.clear()
        self._entity_update_callbacks.clear()
        self._debouncer.async_cancel()
        self._boundary_timer_cancel()  # Phase 39 (D-03): explicit cancel, not via _listeners
        self._gps_watchdog_cancel()  # GPS stale watchdog (like _boundary_timer_cancel)
        logger.info("ASP Parking coordinator stopped")

    # ------------------------------------------------------------------
    # Phase 33: index rebuild orchestration (IDX-01..IDX-04)
    # ------------------------------------------------------------------

    async def async_request_rebuild(
        self, *, triggered_by: Literal["button", "stale_check"] = "button"
    ) -> None:
        """Public entry point: fire-and-forget spawn of the rebuild task.

        IDX-02 concurrent-press protection: if a rebuild is already in
        progress, this is a no-op (the flag is the gate; the lock alone
        would only serialize a second press behind the first one).

        Args:
            triggered_by: One of ``"button"`` (default — applies the
                24h double-press override per IDX-05) or ``"stale_check"``
                (skips the 24h override per D-03).  ``button.py`` calls
                with no args so the default keeps existing call sites
                byte-identical.

        RESEARCH Pitfall 1: uses ``entry.async_create_background_task`` so
        the task is auto-cancelled when the config entry is unloaded —
        ``async_stop`` does not need explicit handling.
        """
        if self._is_rebuilding:
            logger.info(
                "ASP Parking: rebuild already in progress (triggered_by=%s) "
                "-- request ignored",
                triggered_by,
            )
            return

        # Phase 38 / SPEC Requirement 1.6: write ``last_button_press``
        # BEFORE spawning so a second press during a running rebuild
        # still sees a recent press.  Stale-check requests MUST NOT
        # touch this anchor (D-03 — button-only double-press window).
        # The Store itself is owned by Plan 03; this plan writes through
        # it defensively if hydrated, otherwise is a no-op.
        # Set the flag BEFORE any await so a second press during the Store
        # write cannot bypass the IDX-02 concurrent-press guard (CR-01).
        self._is_rebuilding = True

        if triggered_by == "button":
            self._last_button_press = dt_util.utcnow()
            if self._index_stale_store is not None:
                try:
                    await self._index_stale_store.async_save(
                        {
                            "last_button_press": self._last_button_press.isoformat(),
                            "last_stale_check": (
                                self._last_stale_check.isoformat()
                                if self._last_stale_check
                                else None
                            ),
                        }
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "ASP Parking: could not persist last_button_press timestamp; "
                        "double-press window will not survive a restart",
                        exc_info=True,
                    )
        self._async_notify_entities()
        # Construct the coroutine via the class to keep this method testable
        # with a SimpleNamespace stub that binds only async_request_rebuild
        # (tests/test_coordinator_rebuild.py).  Behaviourally identical to
        # self._async_do_rebuild() since `self` is an ASPParkingCoordinator.
        self._rebuild_task = self.entry.async_create_background_task(
            self.hass,
            ASPParkingCoordinator._async_do_rebuild(self, triggered_by=triggered_by),
            name="asp_parking_index_rebuild",
        )

    async def _async_do_rebuild(
        self, *, triggered_by: Literal["button", "stale_check"] = "button"
    ) -> None:
        """Background task body — performs the full rebuild lifecycle.

        Strict ordering (RESEARCH Pitfall 2):
          cleanup_stale -> (download OR build_from_source) -> atomic_swap
          -> SpatialIndex.reset -> _sign_cache.clear -> read_build_timestamp

        Notification IDs are distinct from the first-time-setup IDs in
        ``__init__.py`` (RESEARCH Pitfall 7):
          - in-progress: ``asp_parking_index_rebuild``
          - success:     ``asp_parking_index_rebuild_success``
          - error:       ``asp_parking_index_rebuild_error``

        Args:
            triggered_by: Routed to ``_async_decide_rebuild_path`` so the
                24h double-press override is button-only (D-03).

        The ``finally`` block ALWAYS resets ``_is_rebuilding=False`` and
        re-notifies entities — D-06 guarantees the button never gets stuck.
        """
        # Lazy import (matches __init__.py pattern lines 36-38) so module
        # import does not pull in HA's persistent_notification module.
        from homeassistant.components.persistent_notification import (
            async_create as pn_create,
            async_dismiss as pn_dismiss,
        )

        async with self._rebuild_lock:
            pn_create(
                self.hass,
                "Rebuilding NYC spatial index (~15 MB compressed). "
                "ASP Parking will continue using the existing index until complete.",
                title="ASP Parking: Index Rebuild",
                notification_id="asp_parking_index_rebuild",
            )

            try:
                # Phase 38 (IDX-05): decide which executor strategy to run
                # BEFORE doing any work so the INFO log records intent even
                # if the chosen path fails.
                path, reason = await self._async_decide_rebuild_path(triggered_by)
                logger.info(
                    "asp_parking: index rebuild path=%s reason=%s",
                    path.value,
                    reason,
                )

                # RESEARCH Pitfall 5: wipe any stale _tmp/_bak/_download.zip
                # from a prior crash BEFORE writing fresh artifacts.
                await self.hass.async_add_executor_job(_sync_cleanup_stale, INDEX_DIR)

                if path == RebuildPath.DOWNLOAD:
                    await self.hass.async_add_executor_job(
                        _sync_download_and_extract, INDEX_DIR, INDEX_DOWNLOAD_URL
                    )
                else:
                    # FROM_SOURCE — full CSCL rebuild (Plan 01 IDX-06).
                    await self.hass.async_add_executor_job(
                        _sync_build_from_source, INDEX_DIR
                    )

                await self.hass.async_add_executor_job(_sync_atomic_swap, INDEX_DIR)

                # RESEARCH Pitfall 2: reset MUST happen AFTER atomic_swap so the
                # next SpatialIndex.get() re-opens the new files. reset() just
                # closes the rtree handle and nulls the singleton — safe to
                # call on the event loop (spatial_index.py line 89-99).
                SpatialIndex.reset()

                # IDX-04: drop pre-seeded SODA records so readers re-query
                # against the fresh on-disk index.
                self._sign_cache.clear()

                # Read the new build_info.json so _last_rebuilt reflects the
                # just-built index.
                self._last_rebuilt = await self.hass.async_add_executor_job(
                    _sync_read_build_timestamp, INDEX_DIR
                )

                pn_dismiss(self.hass, "asp_parking_index_rebuild")
                # Phase 38: dismiss the stale-check notification (if any) —
                # the rebuild that resolves staleness has just succeeded.
                pn_dismiss(self.hass, "asp_parking_index_stale")
                ts_str = (
                    self._last_rebuilt.strftime("%Y-%m-%d %H:%M UTC")
                    if self._last_rebuilt
                    else "unknown"
                )
                pn_create(
                    self.hass,
                    f"Spatial index updated. Built: {ts_str}.",
                    title="ASP Parking: Index Rebuild Complete",
                    notification_id="asp_parking_index_rebuild_success",
                )
                logger.info("ASP Parking: index rebuild complete (built %s)", ts_str)

            except Exception as err:  # noqa: BLE001
                pn_dismiss(self.hass, "asp_parking_index_rebuild")
                if isinstance(err, OSError):
                    if err.strerror and err.filename:
                        _err_summary = f"{err.strerror} ({err.filename})"
                    elif err.strerror:
                        _err_summary = err.strerror
                    else:
                        _err_summary = str(err)
                else:
                    _err_summary = str(err)
                pn_create(
                    self.hass,
                    f"Failed to rebuild spatial index: {_err_summary}. "
                    "Your existing index is still active.",
                    title="ASP Parking: Index Rebuild Failed",
                    notification_id="asp_parking_index_rebuild_error",
                )
                logger.error(
                    "ASP Parking: index rebuild failed: %s", err, exc_info=True
                )
                # Best-effort cleanup: wipe the partial _tmp dir.  Atomic-swap
                # guarantees the live index dir is untouched on failure.
                try:
                    await self.hass.async_add_executor_job(
                        _sync_cleanup_stale, INDEX_DIR
                    )
                except Exception:  # noqa: BLE001
                    logger.debug(
                        "ASP Parking: cleanup after rebuild failure errored",
                        exc_info=True,
                    )

            finally:
                # D-06: ALWAYS clear the flag and re-notify so the button
                # is usable again and the binary_sensor flips back to off.
                # _is_rebuilding is cleared FIRST so a second CancelledError
                # or exception inside pn_dismiss / _async_notify_entities
                # cannot leave the flag stuck True permanently.
                self._is_rebuilding = False
                pn_dismiss(self.hass, "asp_parking_index_rebuild")
                self._async_notify_entities()

    # ------------------------------------------------------------------
    # Phase 38: dual-path rebuild routing (IDX-05)
    # ------------------------------------------------------------------

    async def _async_decide_rebuild_path(
        self, triggered_by: str
    ) -> tuple[RebuildPath, str]:
        """Return ``(path, reason_log_tag)`` for the rebuild router.

        Decision matrix:
          * button + last press within 24h           -> FROM_SOURCE / double_press
          * either   + remote API failure / no asset -> FROM_SOURCE / github_api_failed
          * either   + remote asset age < 30 days     -> DOWNLOAD    / remote_fresh
          * either   + remote asset age >= 30 days    -> FROM_SOURCE / remote_stale

        D-03: ``triggered_by="stale_check"`` SKIPS the 24h double-press
        override entirely — that rule is button-only.
        """
        if triggered_by == "button" and self._last_button_press is not None:
            window = dt_util.utcnow() - self._last_button_press
            if window < timedelta(hours=BUTTON_DOUBLE_PRESS_WINDOW_HOURS):
                return RebuildPath.FROM_SOURCE, "double_press"

        age_days = await self._fetch_remote_asset_age_days()
        if age_days is None:
            return RebuildPath.FROM_SOURCE, "github_api_failed"
        if age_days < REMOTE_FRESH_DAYS:
            return RebuildPath.DOWNLOAD, "remote_fresh"
        return RebuildPath.FROM_SOURCE, "remote_stale"

    async def _fetch_remote_asset_age_days(self) -> float | None:
        """Return the GitHub-hosted prebuilt asset age in days, or None on failure.

        Caches the result for 10 minutes per coordinator instance to absorb
        the 60-req/hour anonymous GitHub rate limit (RESEARCH Pitfall 2).

        Reads ``created_at`` (NOT ``updated_at``) per Pitfall 3 — the
        asset's update timestamp is bumped by metadata edits and would
        misrepresent the actual rebuild age.

        URL uses ``GET /repos/.../releases/tags/index-v1`` (Pitfall 1).
        The "latest release" GitHub endpoint currently returns the v3.0.0
        entry which has ZERO assets, so we pin to the ``index-v1`` tag —
        the canonical home of ``index.zip``.
        """
        # 10-minute cache TTL.
        if self._remote_age_cache is not None:
            cached_at, cached_value = self._remote_age_cache
            if (dt_util.utcnow() - cached_at) < timedelta(minutes=10):
                return cached_value

        url = f"{GITHUB_RELEASES_API_BASE}/releases/tags/{GITHUB_INDEX_RELEASE_TAG}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    url, headers={"Accept": "application/vnd.github+json"}
                )
                resp.raise_for_status()
                data = resp.json()
            assets = data.get("assets") or []
            if not assets:
                logger.warning(
                    "asp_parking: github releases tag %s has no assets "
                    "-- falling back to from_source",
                    GITHUB_INDEX_RELEASE_TAG,
                )
                self._remote_age_cache = (dt_util.utcnow(), None)
                return None
            # Prefer the canonical index.zip asset; fall back to first.
            target = next(
                (a for a in assets if a.get("name") == "index.zip"),
                assets[0],
            )
            created_at_raw = target.get("created_at")  # Pitfall 3
            if not created_at_raw:
                self._remote_age_cache = (dt_util.utcnow(), None)
                return None
            created_at = dt_util.parse_datetime(created_at_raw)
            if created_at is None:
                self._remote_age_cache = (dt_util.utcnow(), None)
                return None
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            age_days = (dt_util.utcnow() - created_at).total_seconds() / 86400.0
            self._remote_age_cache = (dt_util.utcnow(), age_days)
            return age_days
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "asp_parking: github releases API failed (%s: %s) "
                "-- falling back to from_source",
                type(exc).__name__,
                exc,
            )
            self._remote_age_cache = (dt_util.utcnow(), None)
            return None

    # ------------------------------------------------------------------
    # Phase 38 Plan 03: stale detection lifecycle (IDX-07 + IDX-05 persistence)
    # ------------------------------------------------------------------

    async def _async_init_stale_lifecycle(self) -> None:
        """Initialise the index-stale Store, hydrate state, wire startup + daily check.

        SPEC §Requirement 3: Store uses a FIXED key
        (``"asp_parking_index_stale"``) — NOT per-entry-id — so the
        24h double-press window and last_stale_check are shared across
        any future multi-entry installs.

        Wiring sequence (called from ``async_start`` after ``_last_rebuilt``
        is populated):

          1. Construct ``Store(self.hass, version=1, key="asp_parking_index_stale")``
          2. ``async_load`` payload; hydrate ``_last_button_press`` and
             ``_last_stale_check`` if the payload is a dict with the expected
             keys.  Non-dict payloads emit a WARNING and fall back to None.
          3. D-01: spawn a fire-and-forget startup background task running
             ``_async_check_stale_and_rebuild`` (no args) via
             ``entry.async_create_background_task``.
          4. D-02: register a daily 24h ``async_track_time_interval``
             pointing at the SAME helper; unsub appended to
             ``self._listeners`` so ``async_stop`` cleans it up.
        """
        self._index_stale_store = Store(
            self.hass, version=1, key="asp_parking_index_stale"
        )
        raw = await self._index_stale_store.async_load()
        if isinstance(raw, dict):
            lbp_raw = raw.get("last_button_press")
            lsc_raw = raw.get("last_stale_check")
            if lbp_raw:
                parsed_lbp = dt_util.parse_datetime(lbp_raw)
                if parsed_lbp is None:
                    logger.warning(
                        "asp_parking: index_stale store has invalid "
                        "last_button_press %r; discarding",
                        lbp_raw,
                    )
                    self._last_button_press = None
                else:
                    self._last_button_press = parsed_lbp
            else:
                self._last_button_press = None
            if lsc_raw:
                parsed_lsc = dt_util.parse_datetime(lsc_raw)
                if parsed_lsc is None:
                    logger.warning(
                        "asp_parking: index_stale store has invalid "
                        "last_stale_check %r; discarding",
                        lsc_raw,
                    )
                    self._last_stale_check = None
                else:
                    self._last_stale_check = parsed_lsc
            else:
                self._last_stale_check = None
        else:
            if raw is not None:
                logger.warning(
                    "asp_parking: index_stale store contained unexpected type "
                    "%s; discarding",
                    type(raw).__name__,
                )
            self._last_button_press = None
            self._last_stale_check = None

        # D-01: startup fire-and-forget background task.
        self.entry.async_create_background_task(
            self.hass,
            self._async_check_stale_and_rebuild(),
            name="asp_parking_index_stale_check_startup",
        )

        # D-02: daily 24h interval — same helper as the startup task.
        unsub_stale = async_track_time_interval(
            self.hass,
            self._async_check_stale_and_rebuild,
            timedelta(hours=STALE_CHECK_INTERVAL_HOURS),
        )
        self._listeners.append(unsub_stale)

    async def _async_check_stale_and_rebuild(self, now: datetime | None = None) -> None:
        """Shared startup + daily-interval stale-check helper.

        Pitfall 12: the callback must accept BOTH zero args (startup
        fire-and-forget background task) AND a single positional
        ``datetime`` (``async_track_time_interval`` invokes with
        ``now: datetime``).  The default ``now=None`` makes both calling
        conventions valid.

        Branch semantics:
          * ``_last_rebuilt is None`` → first-install guard; skip rebuild,
            skip notification, but still persist ``last_stale_check``
            so the check progresses on every run.
          * ``age <= STALE_INDEX_DAYS`` → fresh; skip silently (no
            notification, no rebuild).  Boundary: exactly 60 days
            is NOT stale (SPEC "> 60 days" is strict-less).
          * ``self._is_rebuilding`` → rebuild already in progress; skip
            trigger (also skips notification to avoid double-notify).
          * Otherwise → post ``"asp_parking_index_stale"`` notification
            AND await ``async_request_rebuild(triggered_by="stale_check")``
            (D-03: stale_check skips the 24h double-press anchor).

        ``last_stale_check`` is always written inside the ``finally``
        block — every branch advances the Store record.
        """
        try:
            if self._last_rebuilt is None:
                logger.debug("ASP Parking: stale check skipped (_last_rebuilt is None)")
                return
            age = dt_util.utcnow() - self._last_rebuilt
            if age <= timedelta(days=STALE_INDEX_DAYS):
                return
            if self._is_rebuilding:
                logger.debug(
                    "ASP Parking: stale check skipped (rebuild already in progress)"
                )
                return
            # Lazy import (matches the rebuild-method pattern in this file).
            from homeassistant.components.persistent_notification import (
                async_create as pn_create,
            )

            pn_create(
                self.hass,
                (
                    f"Spatial index is {age.days} days old (threshold: "
                    f"{STALE_INDEX_DAYS} days). Auto-rebuilding in the background."
                ),
                title="ASP Parking: Index is stale",
                notification_id="asp_parking_index_stale",
            )
            await self.async_request_rebuild(triggered_by="stale_check")
        except Exception:  # noqa: BLE001
            logger.error(
                "ASP Parking: stale-check/rebuild encountered unexpected error",
                exc_info=True,
            )
            pn_create(
                self.hass,
                "The automatic stale-index check failed unexpectedly. "
                "Check your Home Assistant logs for details.",
                title="ASP Parking: Stale Check Failed",
                notification_id="asp_parking_index_stale_check_error",
            )
        finally:
            # SPEC AC: always write last_stale_check on every code path.
            self._last_stale_check = dt_util.utcnow()
            if self._index_stale_store is not None:
                try:
                    await self._index_stale_store.async_save(
                        {
                            "last_button_press": (
                                self._last_button_press.isoformat()
                                if self._last_button_press
                                else None
                            ),
                            "last_stale_check": self._last_stale_check.isoformat(),
                        }
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "ASP Parking: could not persist stale-check timestamp",
                        exc_info=True,
                    )

    # ------------------------------------------------------------------
    # ha-nyc311 bridge helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _bridge_state_to_info(
        state: str, attributes: Mapping[str, Any] | None = None
    ) -> SuspensionInfo:
        """Convert ha-nyc311 entity state to SuspensionInfo (D-06).

        Maps:
          "on"  -> suspended, reason from attributes
          "off" -> not suspended
          "unavailable"/"unknown" -> fail open (not suspended), source='none'
        """
        if state == "on":
            reason = (attributes or {}).get("reason")
            return SuspensionInfo(is_suspended=True, reason=reason, source="ha_nyc311")
        if state == "off":
            return SuspensionInfo(is_suspended=False, reason=None, source="ha_nyc311")
        # "unavailable", "unknown", or any other state: fail open
        logger.warning(
            "ha-nyc311 entity state is '%s' -- failing open (no suspension assumed)",
            state,
        )
        return SuspensionInfo(is_suspended=False, reason=None, source="none")

    @callback
    def _async_on_nyc311_state_change(self, event: Event) -> None:
        """Handle ha-nyc311 entity state changes (D-05).

        Converts ha-nyc311 state to SuspensionInfo and immediately
        notifies all entities -- no waiting for the 60-minute poll.
        """
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        self._async_apply_suspension_state(
            self._bridge_state_to_info(new_state.state, new_state.attributes)
        )
        self._async_notify_entities()

    @callback
    def _async_apply_suspension_state(self, new: SuspensionInfo) -> None:
        """Choke-point for all suspension_state mutations (D-08 / Pitfall 8 / T-34-06).

        Replaces all six direct mutation sites so every state transition passes
        through one place. On a False → True transition with a stored CalDAV
        event, a delete background task is spawned to remove the event from
        the calendar.

        Args:
            new: The new SuspensionInfo to apply.
        """
        was_suspended = self._last_suspension_state
        self.data.suspension_state = new
        self._last_suspension_state = new.is_suspended

        # D-08: on False → True transition, delete the active CalDAV event.
        # No-op when: (a) was already suspended, (b) no stored UID, (c) no store.
        if (
            new.is_suspended
            and not was_suspended
            and self._caldav_uid is not None
            and self._caldav_store is not None
        ):
            _uid_snapshot = self._caldav_uid
            # WR-08: clear the local pointer SYNCHRONOUSLY. The intent here
            # is "this event is being deleted" -- waiting for the background
            # task to clear the field leaves a window where the local field
            # contradicts the user-visible intent. Any concurrent write task
            # that observes ``self._caldav_uid is None`` will skip the
            # delete-stale-uid branch and never race the standalone delete
            # task. The delete task itself uses the snapshot, not the field.
            self._caldav_uid = None
            self._caldav_delete_task = self.entry.async_create_background_task(
                self.hass,
                ASPParkingCoordinator._async_caldav_delete_current(self, _uid_snapshot),
                name="asp_parking_caldav_delete_on_suspension",
            )

    async def _async_caldav_write_or_update(
        self,
        schedule: ScheduleResult,
        *,
        lat: float | None = None,
        lon: float | None = None,
    ) -> None:
        """Write or update the CalDAV VEVENT for the upcoming cleaning window.

        Wraps ``caldav_sync.write_or_update_event`` with:
        - asyncio.Lock serialisation (T-34-07 — no concurrent writes)
        - Store persistence after each successful write (CALDAV-06)
        - D-09 single-fire persistent notification per failure streak
        - T-34-01/T-34-05 password sanitisation in logs + notifications
        """
        from homeassistant.components.persistent_notification import (
            async_create as pn_create,
            async_dismiss as pn_dismiss,
        )

        async with self._caldav_lock:
            if self.data.suspension_state.is_suspended:
                logger.debug(
                    "CalDAV write skipped — suspension became active before lock acquired"
                )
                return
            try:
                # Build config inside the try so KeyError/ValueError from missing or
                # invalid options are caught and surfaced as user notifications (Critical #2).
                config = CalDAVConfig.from_options(dict(self.entry.options))
                new_uid = await caldav_sync.write_or_update_event(
                    config=config,
                    entry_id=self.entry.entry_id,
                    schedule=schedule,
                    stored_uid=self._caldav_uid,
                    lat=lat,
                    lon=lon,
                )
                # Success: persist UID via load-merge-save so future store keys are preserved.
                # Store persistence is in its own try/except so a disk/HA-storage
                # failure does NOT trigger the "CalDAV sync failed" notification —
                # the calendar event was written successfully.
                self._caldav_uid = new_uid
                try:
                    _store_data = await self._caldav_store.async_load() or {}  # type: ignore[union-attr]
                    _store_data["uid"] = new_uid
                    await self._caldav_store.async_save(_store_data)  # type: ignore[union-attr]
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "ASP Parking: CalDAV event written but UID persistence failed "
                        "(event is on the calendar; next restart may re-create it)",
                        exc_info=True,
                    )
                if self._caldav_write_error_notified:
                    pn_dismiss(self.hass, "asp_parking_caldav_error")
                    self._caldav_write_error_notified = False
                # BUG-C-002: re-check suspension state AFTER the network I/O.
                # The pre-await check at the top of the lock only proves we
                # were unsuspended when the await started. If a holiday
                # calendar refresh, a manual suspension service call, or any
                # other code path flipped is_suspended=True while
                # write_or_update_event was in flight, the event we just
                # wrote is now stale on the CalDAV server. Spawn a
                # delete-on-flip task for new_uid so the orphan does not
                # survive the race.
                if self.data.suspension_state.is_suspended:
                    logger.warning(
                        "ASP Parking: suspension became active during CalDAV "
                        "write; deleting stale event %s (BUG-C-002 race fix)",
                        new_uid,
                    )
                    self._caldav_delete_task = self.entry.async_create_background_task(
                        self.hass,
                        ASPParkingCoordinator._async_caldav_delete_current(
                            self, new_uid
                        ),
                        name="asp_parking_caldav_delete_on_suspension_race",
                    )
                    return
            except Exception as err:  # noqa: BLE001
                _pw = self.entry.options.get(CONF_CALDAV_PASSWORD, "")
                _un = self.entry.options.get(CONF_CALDAV_USERNAME, "")
                sanitised = _caldav_sanitise(str(err), _pw, _un)
                logger.warning(
                    "ASP Parking: CalDAV write failed: %s", sanitised, exc_info=True
                )
                if not self._caldav_write_error_notified:
                    _display = sanitised[:200] + ("…" if len(sanitised) > 200 else "")
                    pn_create(
                        self.hass,
                        f"CalDAV sync failed: {_display}. Your ASP schedule is still active.",
                        title="ASP Parking: CalDAV Sync Failed",
                        notification_id="asp_parking_caldav_error",
                    )
                    self._caldav_write_error_notified = True

    async def _async_caldav_delete_current(
        self, uid_to_delete: str | None = None
    ) -> None:
        """Delete the active CalDAV event by stored UID.

        Args:
            uid_to_delete: UID captured at spawn time (Finding 1 race fix). When
                provided, used instead of reading self._caldav_uid inside the lock,
                so a concurrent write cannot redirect the delete to the new event.
        """
        # Prefer the explicitly passed snapshot; fall back to current field.
        uid = uid_to_delete if uid_to_delete is not None else self._caldav_uid
        if uid is None or self._caldav_store is None:
            return  # Nothing to delete

        from homeassistant.components.persistent_notification import (
            async_create as pn_create,
            async_dismiss as pn_dismiss,
        )

        # Finding 4: use .get() — bare subscript raises KeyError if CalDAV URL
        # removed from options between task spawn and execution.
        url = self.entry.options.get(CONF_CALDAV_URL, "")
        if not url:
            return  # CalDAV deconfigured between task spawn and execution
        password = self.entry.options.get(CONF_CALDAV_PASSWORD, "")
        username = self.entry.options.get(CONF_CALDAV_USERNAME, "")

        async with self._caldav_lock:
            try:
                await caldav_sync.delete_event(
                    url=url,
                    username=username,
                    password=password,
                    calendar_url=self.entry.options.get(CONF_CALDAV_CALENDAR, ""),
                    uid=uid,
                )
                # Success: clear UID only if it still matches what we deleted (Finding 1).
                # WR-08: the suspension-flip path now pre-clears
                # ``self._caldav_uid`` synchronously before spawning this task,
                # so for that caller this branch is a defensive no-op. Other
                # callers (e.g. ``_maybe_delete_caldav_on_move`` which spawns
                # without pre-clearing) still rely on this conditional clear.
                if self._caldav_uid == uid:
                    self._caldav_uid = None
                # Only update the store if it still holds the UID we deleted,
                # so a concurrent write's newer UID is not wiped from the store.
                data = await self._caldav_store.async_load() or {}
                if data.get("uid") == uid:
                    data.pop("uid", None)
                    await self._caldav_store.async_save(data)
                # Finding 3: dismiss delete-specific notification.
                if self._caldav_delete_error_notified:
                    pn_dismiss(self.hass, "asp_parking_caldav_delete_error")
                    self._caldav_delete_error_notified = False
            except Exception as err:  # noqa: BLE001
                sanitised = _caldav_sanitise(str(err), password, username)
                logger.warning(
                    "ASP Parking: CalDAV delete failed: %s", sanitised, exc_info=True
                )
                # Finding 3: separate flag + notification ID from write path.
                if not self._caldav_delete_error_notified:
                    _display = sanitised[:200] + ("…" if len(sanitised) > 200 else "")
                    pn_create(
                        self.hass,
                        f"CalDAV sync failed: {_display}. Your ASP schedule is still active.",
                        title="ASP Parking: CalDAV Sync Failed",
                        notification_id="asp_parking_caldav_delete_error",
                    )
                    self._caldav_delete_error_notified = True

    async def _async_caldav_hook_after_resolve(
        self, schedule: ScheduleResult, lat: float | None, lon: float | None
    ) -> None:
        """Decide whether to spawn a CalDAV write or delete after a successful resolve.

        Called synchronously from ``_async_resolve_pipeline`` after
        ``_async_maybe_send_notification``. Spawns a background task (Pitfall 10
        — never awaited inline; all CalDAV I/O is off the event loop).

        Args:
            schedule: The pipeline's resolved schedule result.
            lat: The latitude computed by THIS pipeline invocation, passed
                explicitly by the caller rather than read from
                ``self.data.last_lat``.
            lon: The longitude computed by THIS pipeline invocation, passed
                explicitly by the caller.

        Guards (D-02, Pitfall 4, CALDAV-04):
        - No CalDAV configured (_caldav_store is None) → no-op
        - Suspended → no write (raw suspension_state.is_suspended, not schedule.suspended)
        - ScheduleFound with next_window → spawn write task
        - Any other schedule type → spawn delete task (no active window)
        """
        if self._caldav_store is None:
            return  # D-02: CalDAV not configured

        if self.data.suspension_state.is_suspended:
            return  # Pitfall 4: gate on raw suspension flag

        # Duck-type check: any schedule-like object with a non-None next_window
        # qualifies for a write. This covers both the real ScheduleFound dataclass
        # and SimpleNamespace stubs used in tests. The real pipeline only passes
        # ScheduleFound here (compute_schedule returns NoASPSchedule etc. otherwise),
        # so this is equivalent to isinstance(schedule, ScheduleFound) in practice.
        next_window = getattr(schedule, "next_window", None)
        if next_window is not None:
            # Write/update the VEVENT for the upcoming cleaning window using
            # this invocation's lat/lon.
            self._caldav_write_task = self.entry.async_create_background_task(
                self.hass,
                ASPParkingCoordinator._async_caldav_write_or_update(
                    self, schedule, lat=lat, lon=lon
                ),
                name="asp_parking_caldav_write",
            )
        else:
            # No active window (NoASPSchedule, NoMatchSchedule, etc.) — delete any stale event.
            # BUG-C-004: only spawn a delete task when there is actually a UID
            # to delete. Without this guard a fresh integration with no stored
            # event would spawn an asp_parking_caldav_delete_on_move task on
            # every No-ASP resolve; the task immediately returned (uid=None
            # short-circuit inside _async_caldav_delete_current), wasting one
            # background task per pipeline run.
            if self._caldav_uid is not None:
                _uid_snapshot = self._caldav_uid
                self._caldav_delete_task = self.entry.async_create_background_task(
                    self.hass,
                    ASPParkingCoordinator._async_caldav_delete_current(
                        self, _uid_snapshot
                    ),
                    name="asp_parking_caldav_delete_on_move",
                )

    async def _maybe_delete_caldav_on_move(self) -> None:
        """Safety-window guard: delete CalDAV event when the car has moved early.

        Called from ``_async_on_gps_update`` after the movement-threshold gate
        passes. Checks whether the current time is OUTSIDE the safety window
        (i.e., there is still enough time to move); if so, deletes the event
        so the calendar doesn't show a stale entry.

        CALDAV-03 / CALDAV-05 contract:
        - Outside safety window (> safety_window_minutes before next_move_dt):
          spawn asp_parking_caldav_delete_on_move
        - Inside safety window (≤ safety_window_minutes before next_move_dt):
          no-op (user is moving as instructed; don't remove the reminder)
        """
        if self._caldav_uid is None or self._caldav_store is None:
            return  # Nothing to delete or CalDAV not configured

        _schedule = self.data.schedule_result
        # Duck-type: any schedule with a non-None next_window has an active event to protect.
        if _schedule is None or getattr(_schedule, "next_window", None) is None:
            return  # No active window to protect
        schedule = cast(ScheduleFound, _schedule)

        safety_min = int(
            self.entry.options.get(
                CONF_CALDAV_SAFETY_WINDOW, DEFAULT_CALDAV_SAFETY_WINDOW
            )
        )
        from .util import now_ha_local

        next_window = cast(CleaningWindow, schedule.next_window)
        boundary = next_window.start_datetime - timedelta(minutes=safety_min)
        now = now_ha_local()

        if now >= boundary:
            # Inside the safety window — do NOT delete (car is on its way)
            return

        # Outside the safety window — the car is moving early; delete the CalDAV event
        _uid_snapshot = self._caldav_uid
        self._caldav_delete_task = self.entry.async_create_background_task(
            self.hass,
            ASPParkingCoordinator._async_caldav_delete_current(self, _uid_snapshot),
            name="asp_parking_caldav_delete_on_move",
        )

    # ------------------------------------------------------------------
    # Entity callback management
    # ------------------------------------------------------------------

    @callback
    def async_add_update_callback(self, cb: CALLBACK_TYPE) -> None:
        """Register a callback for entity state updates.

        Args:
            cb: Callback to invoke when new data is available.
        """
        self._entity_update_callbacks.append(cb)

    @callback
    def async_remove_update_callback(self, cb: CALLBACK_TYPE) -> None:
        """Deregister a previously registered entity update callback.

        Called automatically by entities via async_on_remove() to prevent
        stale closures accumulating across integration reloads.

        Args:
            cb: Callback to remove (same object that was passed to
                async_add_update_callback).
        """
        try:
            self._entity_update_callbacks.remove(cb)
        except ValueError:
            logger.debug(
                "async_remove_update_callback: callback %r was not registered or already removed",
                cb,
            )

    @callback
    def _async_notify_entities(self) -> None:
        """Notify all registered entity callbacks of new data."""
        for cb in self._entity_update_callbacks:
            cb()

    @callback
    def async_update_listeners(self) -> None:
        """Public alias for entity update notification.

        Used by the switch platform (Phase 29 / D-03) to push debug-mode
        state changes to all registered entities immediately after
        mutating ``_debug_enabled``.
        """
        self._async_notify_entities()

    # ------------------------------------------------------------------
    # GPS event handling
    # ------------------------------------------------------------------

    @callback
    def _async_on_gps_update(self, event: Event) -> None:
        """Handle device_tracker state change events.

        Checks if the new state has a valid GPS location, computes distance
        from the last known position, and triggers a debounced pipeline run
        if movement exceeds the threshold.

        Args:
            event: State change event from Home Assistant.
        """
        new_state = event.data.get("new_state")
        if new_state is None or not has_location(new_state):
            return

        new_lat = new_state.attributes[ATTR_LATITUDE]
        new_lon = new_state.attributes[ATTR_LONGITUDE]

        self.data.last_gps_update = dt_util.utcnow()
        self._gps_watchdog_rearm()  # Cancel prior watchdog, dismiss stale notif, rearm

        # Check movement threshold against last resolved position
        if self.data.last_lat is not None and self.data.last_lon is not None:
            distance = location_util.distance(
                self.data.last_lat,
                self.data.last_lon,
                new_lat,
                new_lon,
            )
            if distance is not None and distance < self.movement_threshold:
                return  # Below threshold -- skip

        # Store pending coordinates and trigger debounced pipeline
        self._pending_lat = new_lat
        self._pending_lon = new_lon

        # Phase 34 / CALDAV-05: if a CalDAV event is active and the car has moved
        # far enough before the safety window, delete the stale event.
        # WR-03: only spawn the move-guard task when CalDAV state is actually
        # live -- the body of ``_maybe_delete_caldav_on_move`` would no-op out
        # for users who never configured CalDAV, but spawning a coroutine per
        # GPS update on a fast tracker (taxi, ride-share) wastes hundreds of
        # task-frame allocations per hour. Mirrors the BUG-C-004 guard.
        if self._caldav_uid is not None and self._caldav_store is not None:
            self.entry.async_create_background_task(
                self.hass,
                self._maybe_delete_caldav_on_move(),
                name="asp_parking_caldav_move_guard",
            )

        self.entry.async_create_background_task(
            self.hass,
            self._debouncer.async_call(),
            name="asp_parking_debounce",
        )

    # ------------------------------------------------------------------
    # Phase 39: window-boundary timer (one-shot async_call_later)
    # ------------------------------------------------------------------

    @callback
    def _boundary_timer_cancel(self) -> None:
        """Cancel and clear the stored boundary timer handle.

        D-09: clears ``_boundary_timer_unsub`` to None BEFORE invoking the
        stored callable so a double-call on retry is impossible even if the
        cancel callable raises.  Safe to call when ``_boundary_timer_unsub``
        is already None (no-op).
        """
        if self._boundary_timer_unsub is not None:
            cancel = self._boundary_timer_unsub
            self._boundary_timer_unsub = None
            cancel()

    # ------------------------------------------------------------------
    # GPS stale watchdog (mirrors _boundary_timer_cancel pattern)
    # ------------------------------------------------------------------

    @callback
    def _gps_watchdog_cancel(self) -> None:
        """Cancel and clear the GPS stale watchdog handle (D-09 clear-first pattern).

        Safe to call when ``_gps_stale_unsub`` is already None (no-op).
        NOT appended to self._listeners; explicit cancel in async_stop().
        """
        if self._gps_stale_unsub is not None:
            cancel = self._gps_stale_unsub
            self._gps_stale_unsub = None
            cancel()

    @callback
    def _gps_watchdog_rearm(self) -> None:
        """Cancel prior GPS stale watchdog, dismiss stale notification, and arm a new timer.

        Called on every GPS state-change event so the timer always reflects the
        time of the last actual GPS update.  When the timer fires it posts the
        ``asp_parking_gps_stale`` persistent notification and triggers an entity
        state refresh via ``_async_notify_entities()``.
        """
        self._gps_watchdog_cancel()
        from homeassistant.components.persistent_notification import (
            async_dismiss as pn_dismiss,
        )

        pn_dismiss(self.hass, "asp_parking_gps_stale")

        delay = float(self.stale_timeout * 3600)

        @callback
        def _on_gps_stale(_now: datetime) -> None:
            from homeassistant.components.persistent_notification import (
                async_create as pn_create,
            )

            pn_create(
                self.hass,
                f"No GPS update has been received for {self.stale_timeout} hour(s). "
                "The GPS pipeline health sensor is now OFF. Check that your device "
                "tracker is reporting location updates.",
                title="ASP Parking: GPS Signal Lost",
                notification_id="asp_parking_gps_stale",
            )
            self._async_notify_entities()

        self._gps_stale_unsub = async_call_later(self.hass, delay, _on_gps_stale)

    @callback
    def _async_schedule_boundary_timer(self, schedule: ScheduleResult) -> None:
        """Register a one-shot timer that fires at the next window boundary.

        D-02: unconditionally cancels any prior timer first, then:
          - ASPActiveNow → fires at active_window.end_datetime
          - ScheduleFound with next_window → fires at next_window.start_datetime
          - ScheduleFound with next_window=None (D-01) → skips, logs DEBUG
          - Any other status (NoASPSchedule, NoMatchSchedule, AllUnparseable) → skips, logs DEBUG

        D-06: delay is clamped to max(0.0, ...) to handle race where the
        boundary has already passed by the time the pipeline completes.

        D-04/WR-01: the fire closure spawns ``_async_resolve_pipeline`` via
        ``entry.async_create_background_task`` so HA auto-cancels the in-flight
        task when the config entry unloads.

        NOTE: uses ``dt_util.utcnow()`` directly — NOT ``self._get_now()`` — so the
        wall-clock anchor is real loop time, not the debug-datetime override.
        """
        # D-02: cancel any prior timer unconditionally.
        # Inline the D-09 cancel pattern (clear-first) so this method works
        # both on real ASPParkingCoordinator instances and on SimpleNamespace
        # test stubs that do not forward method lookups to the class.
        if self._boundary_timer_unsub is not None:
            _cancel = self._boundary_timer_unsub
            self._boundary_timer_unsub = None
            _cancel()

        if isinstance(schedule, ASPActiveNow):
            boundary_dt = schedule.active_window.end_datetime
            kind = "active_window.end"
        elif isinstance(schedule, ScheduleFound):
            if schedule.next_window is None:
                logger.debug(
                    "ScheduleFound with next_window=None — boundary timer not scheduled"
                )
                return
            boundary_dt = schedule.next_window.start_datetime
            kind = "next_window.start"
        else:
            logger.debug(
                "schedule.status=%s — boundary timer not scheduled",
                getattr(schedule, "status", type(schedule).__name__),
            )
            return

        # D-06: clamp to 0.0 so past boundaries fire on the next event-loop tick.
        delay = max(
            0.0,
            (dt_util.as_utc(boundary_dt) - dt_util.utcnow()).total_seconds(),
        )

        @callback
        def _on_boundary_fire(_now: datetime) -> None:
            """Timer callback: spawn pipeline re-run as a lifecycle-tied background task."""
            self.entry.async_create_background_task(
                self.hass,
                self._async_resolve_pipeline(),
                name="asp_parking_boundary_timer",
            )

        self._boundary_timer_unsub = async_call_later(
            self.hass, delay, _on_boundary_fire
        )
        logger.debug(
            "Boundary timer scheduled: %s in %.1fs (%s)",
            kind,
            delay,
            boundary_dt.isoformat(),
        )

    # ------------------------------------------------------------------
    # Pipeline execution
    # ------------------------------------------------------------------

    async def _async_resolve_pipeline(self) -> None:
        """Run the full GPS-to-schedule pipeline.

        Reads pending coordinates, calls resolve -> retrieve_signs ->
        compute_schedule, and updates self.data with the result. Handles
        known resolution errors with distinct sentinel states and falls
        back to last known state for unexpected errors.
        """
        lat = self._pending_lat
        lon = self._pending_lon

        # Debug coordinate override (D-06)
        if (
            self._debug_enabled
            and self._debug_lat is not None
            and self._debug_lon is not None
        ):
            lat = self._debug_lat
            lon = self._debug_lon

        if lat is None or lon is None:
            return

        async with self._pipeline_lock:
            try:
                # Phase 1: GPS to street segment
                resolution = await resolve(lat, lon)

                # Phase 2: Street segment to signs — Phase 26 cache lookup first (D-04)
                cache_key = (
                    resolution.on_street,
                    resolution.from_street,
                    resolution.to_street,
                    resolution.side_of_street,
                )
                cached_entry = self._sign_cache.get(cache_key)
                if cached_entry is not None:
                    # Cache hit — synthesize result from pre-fetched records, NO live call.
                    # BUG-S-007 (Phase 35.1-05): extract both records and the SODA
                    # fallback level the records were produced at, so the sensor's
                    # soda_level attribute reflects reality (not hardcoded 1).
                    # isinstance guard: a bare-list entry from a rolling restart
                    # during the schema migration would crash on ["records"] — evict
                    # it and fall through to a live SODA call instead.
                    if not isinstance(cached_entry, dict):
                        del self._sign_cache[cache_key]
                        cached_entry = None
                if cached_entry is not None:
                    cached_records: list[dict[Any, Any]] = cached_entry["records"]  # type: ignore[assignment]
                    cached_level: int = cached_entry.get("soda_level", 1)  # type: ignore[assignment]
                    sign_result = materialize_cached_records(
                        cached_records,
                        on_street=resolution.on_street,
                        from_street=resolution.from_street,
                        to_street=resolution.to_street,
                        side_of_street=resolution.side_of_street,
                        soda_level=cached_level,
                    )
                    logger.debug(
                        "Phase 26: cache hit for %s (level=%d)",
                        cache_key,
                        cached_level,
                    )
                else:
                    # Cache miss — existing path. D-04: do NOT write back.
                    sign_result = await retrieve_signs(
                        on_street=resolution.on_street,
                        from_street=resolution.from_street,
                        to_street=resolution.to_street,
                        side_of_street=resolution.side_of_street,
                    )

                # Phase 3: Signs to schedule
                schedule = compute_schedule(
                    sign_result,
                    now=self._get_now(),
                    suspended_dates=(
                        self._holiday_calendar.suspended_dates
                        if self._holiday_calendar is not None
                        else None
                    ),
                )

                # Phase 39 (D-05): register one-shot boundary timer before
                # updating self.data — boundary scheduling is success-path only
                # (Pitfall 5: never add this call to an except branch).
                self._async_schedule_boundary_timer(schedule)

                # Success: update all data fields
                self.data.schedule_result = schedule
                self.data.special_state = None
                self.data.last_lat = lat
                self.data.last_lon = lon
                self.data.last_resolved = dt_util.utcnow()
                self.data.confidence_score = resolution.confidence

                # Phase 30: Extract new diagnostic fields from resolution (D-09, D-10, D-11)
                self.data.borough = _BOROUGH_NAMES.get(resolution.borocode or "")
                self.data.distance_ft = resolution.perpendicular_distance_ft
                self.data.street_width_ft = resolution.street_width_ft
                self.data.segment_id = resolution.segment_id

                # Extract sign count from Phase 2 result
                if isinstance(sign_result, SignRetrievalSuccess):
                    self.data.sign_count = len(sign_result.signs)
                else:
                    self.data.sign_count = 0

                # Extract SODA fallback level from Phase 2 result
                if isinstance(sign_result, SignRetrievalSuccess):
                    self.data.soda_level = sign_result.soda_level
                else:
                    self.data.soda_level = 0

                # Extract parse failure count from Phase 3 result
                if isinstance(schedule, (ScheduleFound, AllUnparseable)):
                    self.data.parse_failures = len(schedule.parse_failures)
                else:
                    self.data.parse_failures = 0

                # Clear error state on success
                self.data.last_error = None
                self.data.last_error_time = None
                self._last_pipeline_error = False

                # --- Notification (Phase 24, D-12/D-14/D-15/D-16) ---
                await self._async_maybe_send_notification(schedule)

                # --- CalDAV sync (Phase 34, CALDAV-04) --- Pitfall 10: hook is
                # async but spawns background task; never awaited inline.
                # This invocation's lat/lon are handed to the hook explicitly.
                await self._async_caldav_hook_after_resolve(schedule, lat, lon)

                logger.info(
                    "Pipeline resolved: %s (%s side), %d signs, schedule=%s",
                    resolution.on_street,
                    resolution.side_of_street,
                    self.data.sign_count,
                    schedule.status,
                )

            except OutsideNYCError:
                # GPS is outside NYC coverage area
                self.data.special_state = "outside_coverage"
                self.data.last_lat = lat
                self.data.last_lon = lon
                self.data.soda_level = 0  # reset: GPS outside coverage
                # Phase 30: reset new diagnostic fields
                self.data.borough = None
                self.data.distance_ft = None
                self.data.street_width_ft = None
                self.data.segment_id = None
                self.data.last_error = (
                    None  # clear stale errors on clean resolution failures
                )
                self.data.last_error_time = None
                # Retain last schedule_result per user decision
                logger.warning(
                    "GPS coordinates (%.4f, %.4f) are outside NYC coverage area"
                    " -- check that your device tracker is reporting a valid NYC location",
                    lat,
                    lon,
                )

            except (NoSegmentFoundError, AmbiguousResolutionError) as err:
                # GPS is valid but no matching street segment
                self.data.special_state = "no_street_match"
                self.data.last_lat = lat
                self.data.last_lon = lon
                self.data.soda_level = 0  # reset: no street match
                # Phase 30: reset new diagnostic fields
                self.data.borough = None
                self.data.distance_ft = None
                self.data.street_width_ft = None
                self.data.segment_id = None
                self.data.last_error = (
                    None  # clear stale errors on clean resolution failures
                )
                self.data.last_error_time = None
                # Retain last schedule_result per user decision
                logger.warning(
                    "No street segment found at (%.4f, %.4f)"
                    " -- check that your device tracker is reporting accurate"
                    " coordinates within a mapped NYC street: %s",
                    lat,
                    lon,
                    err,
                )

            except ValueError as err:
                # Data-integrity or programming errors (e.g. zero-length segment from
                # determine_side, or SpatialIndex path mismatch after rebuild).  These
                # are intentionally loud -- do NOT silently retain stale state.
                self.data.last_error = str(err)
                self.data.last_error_time = dt_util.utcnow()
                self._last_pipeline_error = True
                logger.error(
                    "Pipeline data-integrity error at (%.4f, %.4f): %s",
                    lat,
                    lon,
                    err,
                    exc_info=True,
                )
                from homeassistant.components.persistent_notification import (
                    async_create as pn_create,
                )

                pn_create(
                    self.hass,
                    f"A data-integrity error occurred at ({lat:.4f}, {lon:.4f}): {err}. "
                    "Sensor values may be stale. Check your Home Assistant logs for details.",
                    title="ASP Parking: Pipeline Error",
                    notification_id="asp_parking_pipeline_integrity_error",
                )

            except Exception as err:  # noqa: BLE001
                # SODA API errors, network errors, unexpected exceptions
                # Fall back to last known state -- do NOT clear schedule or special_state
                self.data.last_error = str(err)
                self.data.last_error_time = dt_util.utcnow()
                self._last_pipeline_error = True
                logger.warning(
                    "Pipeline error at (%.4f, %.4f): %s", lat, lon, err, exc_info=True
                )

            self._async_notify_entities()

    # ------------------------------------------------------------------
    # Suspension polling
    # ------------------------------------------------------------------

    async def _async_initial_311_fetch(self) -> None:
        """Startup 311 API fetch. Fail open on any error."""
        if self._nyc311_bridge_entity is not None:
            bridge_state = self.hass.states.get(self._nyc311_bridge_entity)
            if bridge_state is not None and bridge_state.state in ("on", "off"):
                return  # Bridge healthy — no need for direct 311 API fetch
            # Bridge unavailable/unknown at startup — fall through to direct 311 fetch
        if self._nyc311_client is None:
            return
        try:
            info = await self._nyc311_client.fetch_status()
            if info.is_suspended:
                self._async_apply_suspension_state(info)
                self._async_notify_entities()
        except NYC311AuthError:
            logger.warning("NYC 311 API auth error during startup, failing open")
        except Exception:  # noqa: BLE001
            logger.warning("NYC 311 startup fetch failed, failing open", exc_info=True)

    # ------------------------------------------------------------------
    # Phase 26: parking-area sign cache pre-seeding
    # ------------------------------------------------------------------

    async def _async_preseed_cache(self) -> None:
        """Pre-seed SODA sign cache for segments within the configured parking area.

        Fire-and-forget. Errors are logged but never propagated; a partial cache
        is acceptable per D-03. Cache key is (on_street, from_street, to_street,
        side_of_street) tuple — matches the resolution result shape so cache hits
        in _async_resolve_pipeline can short-circuit retrieve_signs.
        """
        # Snapshot inputs at task start (Pitfall 6: do not re-read self._parking_*
        # inside the loop — a parallel options-save reload starts a fresh task)
        lat = self._parking_lat
        lon = self._parking_lon
        radius_m = self._parking_radius_m
        if lat is None or lon is None or radius_m is None or radius_m <= 0:
            logger.warning(
                "Phase 26: pre-seed skipped — parking area not configured "
                "(lat=%s, lon=%s, radius=%s)",
                lat,
                lon,
                radius_m,
            )
            return

        # Pitfall 1: convert WGS84 → State Plane (R-tree is indexed in feet)
        try:
            cx_ft, cy_ft = convert(lat, lon)
        except OutsideNYCError:
            # Pitfall 2: D-07 says no crash; clear, actionable WARN instead
            logger.warning(
                "Phase 26: parking area (%s, %s) is outside NYC; "
                "pre-seed skipped — resolutions will use on-demand SODA calls",
                lat,
                lon,
            )
            return
        except Exception:  # noqa: BLE001
            logger.warning(
                "Phase 26: parking area coordinate conversion failed",
                exc_info=True,
            )
            return

        radius_ft = radius_m * _METRES_TO_FEET
        try:
            idx = await SpatialIndex.get()
            candidates = idx.query_radius(cx_ft, cy_ft, radius_ft)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Phase 26: spatial query failed during pre-seed", exc_info=True
            )
            return

        if not candidates:
            logger.info(
                "Phase 26: pre-seed found 0 segments within %d m of (%s, %s)",
                radius_m,
                lat,
                lon,
            )
            self._sign_cache = {}
            return

        client = SODAClient()  # uses NYC_OPEN_DATA_APP_TOKEN env var if set
        # BUG-S-007 (Phase 35.1-05): cache values are {records, soda_level} dicts.
        # Pre-seed only runs Level 1 block queries, so soda_level=1 here.
        new_cache: dict[tuple[str, str, str, str], dict[str, list[dict] | int]] = {}
        fetch_attempt_count = 0
        fetch_failure_count = 0
        for cand in candidates:
            # WR-02: skip segments with missing cross-street names. CSCL has
            # boundary segments / ramps / named-only intersections with empty
            # ``from_street`` / ``to_street`` -- building a block query with
            # ``from_street=''`` poisons the cache with unmatchable entries
            # and wastes a SODA round-trip per such segment per side. Mirrors
            # the BUG-S-003 guard already present in the L3 client-side filter.
            if not cand.from_street or not cand.to_street:
                logger.debug(
                    "Phase 26: skipping segment_id=%s — missing cross-street name",
                    cand.segment_id,
                )
                continue
            # Normalize CSCL names to SODA format for the API query (Level 1),
            # matching the name expansion done by retrieve_signs() -> name_variants().
            on_soda = name_variants(cand.full_street_name)[0]
            from_soda = name_variants(cand.from_street)[0]
            to_soda = name_variants(cand.to_street)[0]
            # Pre-seed both legal sides per segment (resolver picks one at lookup time)
            for side in _legal_sides_for(cand):
                query = client.build_block_query(
                    on_soda,
                    from_soda,
                    to_soda,
                    side,
                )
                fetch_attempt_count += 1
                try:
                    records = await client.fetch_signs(query)
                except Exception:  # noqa: BLE001
                    fetch_failure_count += 1
                    logger.debug(
                        "Phase 26: pre-seed fetch failed for %s/%s/%s/%s",
                        cand.full_street_name,
                        cand.from_street,
                        cand.to_street,
                        side,
                        exc_info=True,
                    )
                    continue
                # Only cache non-empty results; empty = Level 1 miss, allow live L2/L3/L4 fallback
                if not records:
                    continue
                # Cache key uses canonical CSCL names to match the resolution result.
                # BUG-S-007: value is {records, soda_level} dict; pre-seed uses L1.
                key = (
                    cand.full_street_name,
                    cand.from_street,
                    cand.to_street,
                    side,
                )
                new_cache[key] = {"records": records, "soda_level": 1}

        if fetch_failure_count > 0 and fetch_failure_count == fetch_attempt_count:
            logger.warning(
                "Phase 26: pre-seed completed with all %d fetch(es) failing "
                "and 0 cache entries; SODA may be unavailable",
                fetch_failure_count,
            )
        self._sign_cache = new_cache
        logger.info(
            "Phase 26: pre-seed complete — %d (segment, side) entries cached "
            "for %d-segment parking area",
            len(new_cache),
            len(candidates),
        )

    @callback
    def _async_suspension_poll(self, now: datetime) -> None:
        """Periodic suspension status check.

        WR-01: bind the task to the config entry so HA auto-cancels it on
        config-entry unload. Previously used ``self.hass.async_create_task``
        which leaks the in-flight network call past ``async_stop()`` and
        triggers "task was destroyed while it is pending" warnings on reload.
        """
        self.entry.async_create_background_task(
            self.hass,
            self._async_update_suspension(),
            name="asp_parking_suspension_poll",
        )

    async def _async_update_suspension(self) -> None:
        """Fetch suspension status from all sources and update data.

        When ha-nyc311 bridge is active and healthy, uses bridge state
        directly (D-09). Falls back to holiday calendar + 311 API when
        bridge is absent or unavailable.
        """
        # D-09: Bridge short-circuit
        if self._nyc311_bridge_entity is not None:
            bridge_state = self.hass.states.get(self._nyc311_bridge_entity)
            if bridge_state is not None and bridge_state.state in ("on", "off"):
                # Bridge healthy: re-apply its state, skip holiday calendar + 311 API
                self._async_apply_suspension_state(
                    self._bridge_state_to_info(
                        bridge_state.state, bridge_state.attributes
                    )
                )
                self._async_notify_entities()
                return
            # Bridge unavailable/unknown: fall through to direct sources

        # D-07/D-08: No bridge or bridge unavailable -- use holiday calendar + 311 API
        # WR-07: holiday calendar takes NYC calendar dates -- use NYC tz, not HA local.
        today = self._get_now_nyc().date()

        if self._holiday_calendar is None:
            logger.error(
                "ASP Parking: suspension poll skipped — holiday calendar not initialized "
                "(this is a bug; please report it)"
            )
            return
        info = self._holiday_calendar.is_suspended(today)

        if not info.is_suspended and self._nyc311_client is not None:
            # On failure retain the existing suspension rather than clearing it —
            # a transient network error must not overwrite an active 311 suspension.
            fallback_info = (
                self.data.suspension_state
                if self.data.suspension_state.is_suspended
                else SuspensionInfo(is_suspended=False, reason=None, source="none")
            )
            try:
                info = await self._nyc311_client.fetch_status()
            except NYC311AuthError as auth_err:
                logger.warning(
                    "311 suspension poll: auth error (%s) — failing open, check API key",
                    auth_err,
                    exc_info=True,
                )
                info = fallback_info
            except Exception:  # noqa: BLE001
                logger.warning(
                    "311 suspension poll failed, failing open", exc_info=True
                )
                info = fallback_info

        self._async_apply_suspension_state(info)
        self._async_notify_entities()

    async def _async_maybe_send_notification(self, schedule: ScheduleResult) -> None:
        """Send push notification if next ASP window is within self._notify_lead_time minutes.

        Guards:
        - CONF_NOTIFY_SERVICE must be configured (D-15)
        - Notification suppressed when debug_enabled AND suppress_notifications (D-15)
        - Only fires once per unique CleaningWindow (D-14)
        """
        if not self._notify_service:
            return
        if self._debug_enabled and self._debug_suppress_notifications:
            return
        if not isinstance(schedule, ScheduleFound):
            return
        if schedule.next_window is None:
            return

        window = schedule.next_window
        now_dt = self._get_now()
        now_utc = dt_util.as_utc(now_dt)
        window_start_utc = dt_util.as_utc(window.start_datetime)
        seconds_until = (window_start_utc - now_utc).total_seconds()

        if not (0 < seconds_until <= self._notify_lead_time * 60):
            return
        prev = self.data.last_notified_window
        if (
            prev is not None
            and window.day == prev.day
            and window.start_time == prev.start_time
            and window.start_datetime == prev.start_datetime
        ):
            return

        # Format the notification message
        time_str = window.start_datetime.strftime("%I:%M %p").lstrip("0")
        street = schedule.on_street
        message = (
            f"ASP parking cleaning starts at {time_str} on {street}. "
            f"Move your car before then."
        )

        service_name = self._notify_service
        if service_name.startswith("notify."):
            service_name = service_name[len("notify.") :]
        try:
            await self.hass.services.async_call(
                "notify",
                service_name,
                {"message": message, "title": "ASP Parking"},
                blocking=True,
            )
            self.data.last_notified_window = window  # only set on confirmed delivery
            logger.info("ASP notification sent for window at %s", time_str)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to send ASP notification via %s",
                self._notify_service,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Manual and periodic triggers
    # ------------------------------------------------------------------

    async def async_force_resolve(self) -> None:
        """Manually trigger a pipeline resolve for the resolve_now service.

        Bypasses the debouncer so the resolve runs immediately, regardless of
        any in-progress debounce cooldown. Uses the last known GPS coordinates.
        If no GPS coordinates have been received yet, logs an info message and
        returns.
        """
        lat = self._pending_lat if self._pending_lat is not None else self.data.last_lat
        lon = self._pending_lon if self._pending_lon is not None else self.data.last_lon
        # In debug mode, fall back to debug coordinates if no real GPS available
        if lat is None and self._debug_enabled and self._debug_lat is not None:
            lat = self._debug_lat
        if lon is None and self._debug_enabled and self._debug_lon is not None:
            lon = self._debug_lon
        if lat is not None and lon is not None:
            self._pending_lat = lat
            self._pending_lon = lon
            await self._async_resolve_pipeline()  # bypass debouncer for force path
        else:
            logger.info("Cannot force resolve: no GPS coordinates available yet")

    @callback
    def _async_periodic_cache_rebuild(self, now: datetime) -> None:
        """Periodic callback to rebuild the SODA sign cache (D-02).

        Spawns a new pre-seed task. Triggered every refresh_interval hours by
        async_track_time_interval. The live cache is NOT cleared here —
        _async_preseed_cache builds a local new_cache and swaps atomically at
        the end, so cache lookups continue to hit the old data during rebuild.
        """
        if (
            self._parking_lat is None
            or self._parking_lon is None
            or self._parking_radius_m is None
            or self._parking_radius_m <= 0
        ):
            return
        logger.info("Phase 26: periodic cache rebuild starting")
        self._preseed_task = self.entry.async_create_background_task(
            self.hass,
            self._async_preseed_cache(),
            name="asp_parking_preseed",
        )

    @callback
    def _async_periodic_heartbeat(self, now: datetime) -> None:
        """8h heartbeat: re-fetch ICS holiday calendar, re-check suspension, refresh pipeline.

        Spawns _async_do_heartbeat as a lifecycle-tied background task so HA auto-cancels
        any in-flight ICS fetch or 311 call on config-entry unload.
        Registered by async_start via async_track_time_interval.
        """
        self.entry.async_create_background_task(
            self.hass,
            self._async_do_heartbeat(),
            name="asp_parking_heartbeat",
        )

    async def _async_do_heartbeat(self) -> None:
        """Re-fetch ICS, re-check suspension, and fire the pipeline debouncer.

        Sequence:
        1. Re-fetch the ICS holiday calendar (if available) so emergency suspensions
           added after boot are reflected immediately.
        2. Re-run suspension check with freshly loaded holiday data.
        3. Trigger the pipeline debouncer when GPS coordinates are known.

        Failure modes are non-fatal: load() has built-in retry + fallback, and
        _async_update_suspension already handles network/auth errors gracefully.
        """
        if self._holiday_calendar is not None:
            try:
                await self._holiday_calendar.load()
                logger.debug(
                    "ASP Parking: heartbeat — ICS re-fetched, suspension re-checking"
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "ASP Parking: heartbeat — ICS re-fetch failed; "
                    "suspension state may be stale until next heartbeat",
                    exc_info=True,
                )
                # Continue to suspension check with existing calendar data.

        await self._async_update_suspension()

        lat = self.data.last_lat
        lon = self.data.last_lon
        # In debug mode, fall back to debug coordinates if no real GPS available
        if lat is None and self._debug_enabled and self._debug_lat is not None:
            lat = self._debug_lat
        if lon is None and self._debug_enabled and self._debug_lon is not None:
            lon = self._debug_lon
        if lat is not None and lon is not None:
            if self._pending_lat is None:
                self._pending_lat = lat
            if self._pending_lon is None:
                self._pending_lon = lon
            self.entry.async_create_background_task(
                self.hass,
                self._debouncer.async_call(),
                name="asp_parking_debounce",
            )
        else:
            logger.debug(
                "ASP Parking: heartbeat — no GPS coordinates, pipeline re-run skipped"
            )
