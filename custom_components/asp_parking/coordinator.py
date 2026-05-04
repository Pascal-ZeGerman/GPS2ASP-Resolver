"""Event-driven coordinator for the ASP Parking integration.

Orchestrates the full GPS-to-schedule pipeline: subscribes to device_tracker
state changes, debounces rapid GPS jitter, checks movement threshold, and
runs the three-phase pipeline (resolve -> retrieve_signs -> compute_schedule).

This is a custom coordinator (not DataUpdateCoordinator) since the data source
is event-driven (GPS updates), not polled.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.const import ATTR_LATITUDE, ATTR_LONGITUDE
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    HomeAssistant,
    callback,
)
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.location import has_location
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

from .const import (
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
    DEFAULT_DEBUG_DATETIME,
    DEFAULT_DEBUG_LAT,
    DEFAULT_DEBUG_LON,
    DEFAULT_MOVEMENT_THRESHOLD,
    DEFAULT_NOTIFY_LEAD_TIME,
    DEFAULT_NOTIFY_SERVICE,
    DEFAULT_NYC311_BRIDGE_ENTITY,
    DEFAULT_NYC311_ENTITY,
    DEFAULT_PARKING_RADIUS,
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_STALE_TIMEOUT,
    DEFAULT_SUPPRESS_NOTIFICATIONS,
    DEFAULT_SUSPENSION_INTERVAL,
    DOMAIN,
    GPS_DEBOUNCE_COOLDOWN,
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
        default_factory=lambda: SuspensionInfo(is_suspended=False, reason=None, source='none')
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
        self._nyc311_bridge_entity: str | None = None  # ha-nyc311 entity ID if bridge active

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
        # Value: list of raw SODA records (may be empty list = NoMatchFound after lookup)
        self._sign_cache: dict[tuple[str, str, str, str], list[dict]] = {}
        self._preseed_task = None  # type: ignore[var-annotated]  # handle for tests
        self._unsub_cache_rebuild = None  # type: ignore[var-annotated]  # cancel callback

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
        return self.entry.options.get(
            CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL
        )

    @property
    def stale_timeout(self) -> int:
        """Return the stale GPS timeout in hours."""
        return self.entry.options.get(CONF_STALE_TIMEOUT, DEFAULT_STALE_TIMEOUT)

    def _get_now(self) -> datetime:
        """Return debug datetime override when active, otherwise real now.

        Per D-08: replaces datetime.now(NYC_TZ) for ALL time-sensitive
        coordinator operations when debug mode is active.
        """
        if self._debug_enabled and self._debug_datetime is not None:
            return self._debug_datetime
        return datetime.now(NYC_TZ)

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
            except (ValueError, TypeError):
                self._debug_datetime = None
        elif isinstance(raw_dt, datetime):
            self._debug_datetime = raw_dt.astimezone(NYC_TZ) if raw_dt.tzinfo else raw_dt.replace(tzinfo=NYC_TZ)
        self._debug_suppress_notifications = self.entry.options.get(
            CONF_SUPPRESS_NOTIFICATIONS, DEFAULT_SUPPRESS_NOTIFICATIONS
        )
        self._notify_service = self.entry.options.get(
            CONF_NOTIFY_SERVICE, DEFAULT_NOTIFY_SERVICE
        )
        self._notify_lead_time = int(
            self.entry.options.get(
                CONF_NOTIFY_LEAD_TIME, DEFAULT_NOTIFY_LEAD_TIME
            )
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
            self._async_on_gps_update,
        )
        self._listeners.append(unsub_state)

        # Periodic refresh to keep schedule current as cleaning windows pass
        unsub_interval = async_track_time_interval(
            self.hass,
            self._async_periodic_refresh,
            timedelta(hours=self.refresh_interval),
        )
        self._listeners.append(unsub_interval)

        # --- Suspension startup ---
        self._holiday_calendar = HolidayCalendar()
        await self._holiday_calendar.load()

        today = self._get_now().date()
        holiday_info = self._holiday_calendar.is_suspended(today)
        if holiday_info.is_suspended:
            self.data.suspension_state = holiday_info

        api_key = self.entry.options.get(CONF_NYC311_API_KEY)
        if api_key:
            self._nyc311_client = NYC311Client(api_key=api_key)
            self.hass.async_create_task(self._async_initial_311_fetch())

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
                self._async_on_nyc311_state_change,
            )
            self._listeners.append(unsub_bridge)

            # D-10: Read current state immediately at startup
            self.data.suspension_state = self._bridge_state_to_info(
                bridge_state.state, bridge_state.attributes
            )

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
                self._parking_lat, self._parking_lon, self._parking_radius_m,
            )

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
        await self._debouncer.async_cancel()
        logger.info("ASP Parking coordinator stopped")

    # ------------------------------------------------------------------
    # ha-nyc311 bridge helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _bridge_state_to_info(
        state: str, attributes: dict | None = None
    ) -> SuspensionInfo:
        """Convert ha-nyc311 entity state to SuspensionInfo (D-06).

        Maps:
          "on"  -> suspended, reason from attributes
          "off" -> not suspended
          "unavailable"/"unknown" -> fail open (not suspended), source='none'
        """
        if state == "on":
            reason = (attributes or {}).get("reason")
            return SuspensionInfo(
                is_suspended=True, reason=reason, source="ha_nyc311"
            )
        if state == "off":
            return SuspensionInfo(
                is_suspended=False, reason=None, source="ha_nyc311"
            )
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
        self.data.suspension_state = self._bridge_state_to_info(
            new_state.state, new_state.attributes
        )
        self._async_notify_entities()

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
            pass

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
        self.hass.async_create_task(self._debouncer.async_call())

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
        if self._debug_enabled and self._debug_lat is not None and self._debug_lon is not None:
            lat = self._debug_lat
            lon = self._debug_lon

        if lat is None or lon is None:
            return

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
            cached_records = self._sign_cache.get(cache_key)
            if cached_records is not None:
                # Cache hit — synthesize result from pre-fetched records, NO live call
                sign_result = materialize_cached_records(
                    cached_records,
                    on_street=resolution.on_street,
                    from_street=resolution.from_street,
                    to_street=resolution.to_street,
                    side_of_street=resolution.side_of_street,
                    soda_level=1,
                )
                logger.debug("Phase 26: cache hit for %s", cache_key)
            else:
                # Cache miss — existing path. D-04: do NOT write back.
                sign_result = await retrieve_signs(
                    on_street=resolution.on_street,
                    from_street=resolution.from_street,
                    to_street=resolution.to_street,
                    side_of_street=resolution.side_of_street,
                )

            # Phase 3: Signs to schedule
            schedule = compute_schedule(sign_result)

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

            # --- Notification (Phase 24, D-12/D-14/D-15/D-16) ---
            await self._async_maybe_send_notification(schedule)

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
            # Retain last schedule_result per user decision
            logger.warning(
                "GPS coordinates (%.4f, %.4f) are outside NYC coverage area"
                " -- check that your device tracker is reporting a valid NYC location",
                lat, lon,
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
            # Retain last schedule_result per user decision
            logger.warning(
                "No street segment found at (%.4f, %.4f)"
                " -- check that your device tracker is reporting accurate"
                " coordinates within a mapped NYC street: %s",
                lat, lon, err,
            )

        except Exception as err:  # noqa: BLE001
            # SODA API errors, network errors, unexpected exceptions
            # Fall back to last known state -- do NOT clear schedule or special_state
            self.data.last_error = str(err)
            self.data.last_error_time = dt_util.utcnow()
            logger.warning(
                "Pipeline error at (%.4f, %.4f): %s", lat, lon, err
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
        try:
            info = await self._nyc311_client.fetch_status()
            if info.is_suspended:
                self.data.suspension_state = info
                self._async_notify_entities()
        except NYC311AuthError:
            logger.warning("NYC 311 API auth error during startup, failing open")
        except Exception:  # noqa: BLE001
            logger.warning("NYC 311 startup fetch failed, failing open")

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
                lat, lon, radius_m,
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
                lat, lon,
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
            logger.warning("Phase 26: spatial query failed during pre-seed", exc_info=True)
            return

        if not candidates:
            logger.info(
                "Phase 26: pre-seed found 0 segments within %d m of (%s, %s)",
                radius_m, lat, lon,
            )
            self._sign_cache = {}
            return

        client = SODAClient()  # uses NYC_OPEN_DATA_APP_TOKEN env var if set
        new_cache: dict[tuple[str, str, str, str], list[dict]] = {}
        for cand in candidates:
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
                try:
                    records = await client.fetch_signs(query)
                except Exception:  # noqa: BLE001
                    logger.debug(
                        "Phase 26: pre-seed fetch failed for %s/%s/%s/%s",
                        cand.full_street_name, cand.from_street, cand.to_street, side,
                        exc_info=True,
                    )
                    continue
                # Only cache non-empty results; empty = Level 1 miss, allow live L2/L3/L4 fallback
                if not records:
                    continue
                # Cache key uses canonical CSCL names to match the resolution result
                key = (
                    cand.full_street_name,
                    cand.from_street,
                    cand.to_street,
                    side,
                )
                new_cache[key] = records

        self._sign_cache = new_cache
        logger.info(
            "Phase 26: pre-seed complete — %d (segment, side) entries cached "
            "for %d-segment parking area",
            len(new_cache), len(candidates),
        )

    @callback
    def _async_suspension_poll(self, now: datetime) -> None:
        """Periodic suspension status check."""
        self.hass.async_create_task(self._async_update_suspension())

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
                self.data.suspension_state = self._bridge_state_to_info(
                    bridge_state.state, bridge_state.attributes
                )
                self._async_notify_entities()
                return
            # Bridge unavailable/unknown: fall through to direct sources

        # D-07/D-08: No bridge or bridge unavailable -- use holiday calendar + 311 API
        today = self._get_now().date()

        info = self._holiday_calendar.is_suspended(today)

        if not info.is_suspended and self._nyc311_client is not None:
            try:
                info = await self._nyc311_client.fetch_status()
            except Exception:  # noqa: BLE001
                logger.warning("311 suspension poll failed, failing open")
                info = SuspensionInfo(is_suspended=False, reason=None, source='none')

        self.data.suspension_state = info
        self._async_notify_entities()

    async def _async_maybe_send_notification(
        self, schedule: ScheduleResult
    ) -> None:
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
        now_utc = dt_util.utcnow()
        window_start_utc = dt_util.as_utc(window.start_datetime)
        seconds_until = (window_start_utc - now_utc).total_seconds()

        if not (0 < seconds_until <= self._notify_lead_time * 60):
            return
        if window == self.data.last_notified_window:
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
            service_name = service_name[len("notify."):]
        try:
            await self.hass.services.async_call(
                "notify",
                service_name,
                {"message": message, "title": "ASP Parking"},
                blocking=True,
            )
            self.data.last_notified_window = window   # only set on confirmed delivery
            logger.info("ASP notification sent for window at %s", time_str)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to send ASP notification via %s", self._notify_service)

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
    def _async_periodic_refresh(self, now: datetime) -> None:
        """Periodic callback to refresh the schedule.

        Re-runs the pipeline with the last known GPS coordinates to keep
        next_move_time current as cleaning windows pass.

        Args:
            now: Current datetime (provided by async_track_time_interval).
        """
        if self.data.last_lat is not None and self.data.last_lon is not None:
            if self._pending_lat is None:
                self._pending_lat = self.data.last_lat
            if self._pending_lon is None:
                self._pending_lon = self.data.last_lon
            self.hass.async_create_task(self._debouncer.async_call())
        else:
            logger.debug("Periodic refresh skipped: no GPS coordinates yet")
