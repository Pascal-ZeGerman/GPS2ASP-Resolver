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

from .gps2asp.resolver import resolve
from .gps2asp.resolver.exceptions import (
    AmbiguousResolutionError,
    NoSegmentFoundError,
    OutsideNYCError,
)
from .gps2asp.schedule import compute_schedule
from .gps2asp.schedule.models import (
    AllUnparseable,
    ScheduleFound,
    ScheduleResult,
)
from .gps2asp.signs import retrieve_signs
from .gps2asp.signs.models import SignRetrievalSuccess
from .gps2asp.suspension import HolidayCalendar, NYC311Client, SuspensionInfo
from .gps2asp.suspension.poller import NYC311AuthError

from .const import (
    CONF_DEVICE_TRACKER,
    CONF_MOVEMENT_THRESHOLD,
    CONF_NYC311_API_KEY,
    CONF_NYC311_ENTITY,
    CONF_REFRESH_INTERVAL,
    CONF_STALE_TIMEOUT,
    DEFAULT_MOVEMENT_THRESHOLD,
    DEFAULT_NYC311_BRIDGE_ENTITY,
    DEFAULT_NYC311_ENTITY,
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_STALE_TIMEOUT,
    DEFAULT_SUSPENSION_INTERVAL,
    DOMAIN,
    GPS_DEBOUNCE_COOLDOWN,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

logger = logging.getLogger(__name__)

NYC_TZ = ZoneInfo("America/New_York")


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
    suspension_state: SuspensionInfo = field(
        default_factory=lambda: SuspensionInfo(is_suspended=False, reason=None, source='none')
    )


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

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_start(self) -> None:
        """Start listening for GPS updates and schedule periodic refreshes.

        Subscribes to device_tracker state change events and sets up a
        periodic timer to refresh the schedule even without GPS movement.
        """
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

        today = datetime.now(NYC_TZ).date()
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
    def _async_notify_entities(self) -> None:
        """Notify all registered entity callbacks of new data."""
        for cb in self._entity_update_callbacks:
            cb()

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
        if lat is None or lon is None:
            return

        try:
            # Phase 1: GPS to street segment
            resolution = await resolve(lat, lon)

            # Phase 2: Street segment to signs
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
            # Retain last schedule_result per user decision
            logger.info("GPS outside NYC coverage area (%.4f, %.4f)", lat, lon)

        except (NoSegmentFoundError, AmbiguousResolutionError) as err:
            # GPS is valid but no matching street segment
            self.data.special_state = "no_street_match"
            self.data.last_lat = lat
            self.data.last_lon = lon
            self.data.soda_level = 0  # reset: no street match
            # Retain last schedule_result per user decision
            logger.info("No street match at (%.4f, %.4f): %s", lat, lon, err)

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
            return  # Bridge active, no need for direct 311 API fetch
        try:
            info = await self._nyc311_client.fetch_status()
            if info.is_suspended:
                self.data.suspension_state = info
                self._async_notify_entities()
        except NYC311AuthError:
            logger.warning("NYC 311 API auth error during startup, failing open")
        except Exception:  # noqa: BLE001
            logger.warning("NYC 311 startup fetch failed, failing open")

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
        today = datetime.now(NYC_TZ).date()

        info = self._holiday_calendar.is_suspended(today)

        if not info.is_suspended and self._nyc311_client is not None:
            try:
                info = await self._nyc311_client.fetch_status()
            except Exception:  # noqa: BLE001
                logger.warning("311 suspension poll failed, failing open")
                info = SuspensionInfo(is_suspended=False, reason=None, source='none')

        self.data.suspension_state = info
        self._async_notify_entities()

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
        if self.data.last_lat is not None and self.data.last_lon is not None:
            self._pending_lat = self.data.last_lat
            self._pending_lon = self.data.last_lon
            await self._async_resolve_pipeline()  # bypass debouncer for force path
        else:
            logger.info("Cannot force resolve: no GPS coordinates available yet")

    @callback
    def _async_periodic_refresh(self, now: datetime) -> None:
        """Periodic callback to refresh the schedule.

        Re-runs the pipeline with the last known GPS coordinates to keep
        next_move_time current as cleaning windows pass.

        Args:
            now: Current datetime (provided by async_track_time_interval).
        """
        if self.data.last_lat is not None and self.data.last_lon is not None:
            self._pending_lat = self.data.last_lat
            self._pending_lon = self.data.last_lon
            self.hass.async_create_task(self._debouncer.async_call())
        else:
            logger.debug("Periodic refresh skipped: no GPS coordinates yet")
