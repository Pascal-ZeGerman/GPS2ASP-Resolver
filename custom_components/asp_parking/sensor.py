"""Sensor platform for the ASP Parking integration.

Provides ASPNextMoveTimeSensor which maps coordinator data to a sensor state:
- ISO datetime when next cleaning window is found (ScheduleFound)
- "No restrictions" when no ASP schedule or signs exist
- "Outside coverage area" when car is outside NYC
- "No street match" when GPS is valid but no street segment found

Rich attributes cover schedule, location, window, metadata, and error groups.

Also provides 10 diagnostic sensors for debugging and dashboards:
ASPCarNameSensor, ASPVINSensor, ASPLatitudeSensor, ASPLongitudeSensor,
ASPResolvedStreetSensor, ASPResolutionStatusSensor,
ASPConfidenceScoreSensor, ASPSODALevelSensor, ASPLastResolvedSensor,
ASPLastErrorSensor, ASPIndexLastRebuiltSensor (Phase 33, IDX-03).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .gps2asp.schedule.models import (
    AllUnparseable,
    ASPActiveNow,
    NoASPSchedule,
    NoMatchSchedule,
    ScheduleFound,
)
from .gps2asp.suspension import apply_suspension

from .const import CONF_STALE_TIMEOUT, DEFAULT_STALE_TIMEOUT, DOMAIN, VERSION
from .coordinator import ASPParkingCoordinator
from .util import now_ha_local


# Phase 36 SENSOR-01: cardinal-direction → human-readable label mapping.
# Mirrors the _BOROUGH_NAMES precedent in coordinator.py:117 (typed dict[str, str],
# module level, hardcoded English). Used by ASPNextMoveTimeSensor and
# ASPResolvedStreetSensor to surface a display-friendly 'side_label' attribute
# alongside the raw 'side_of_street' single-letter code (which remains unchanged
# for backward compatibility). Unrecognized values cause the side_label key to
# be omitted entirely (not inserted as None) — per locked SPEC edge case.
_SIDE_LABELS: dict[str, str] = {
    "N": "North side",
    "S": "South side",
    "E": "East side",
    "W": "West side",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the ASP Parking sensor from a config entry."""
    coordinator: ASPParkingCoordinator = entry.runtime_data
    async_add_entities(
        [
            ASPNextMoveTimeSensor(coordinator),
            ASPCarNameSensor(coordinator),
            ASPVINSensor(coordinator),
            ASPLatitudeSensor(coordinator),
            ASPLongitudeSensor(coordinator),
            ASPResolvedStreetSensor(coordinator),
            ASPResolutionStatusSensor(coordinator),
            # DIAG-04 (Phase 27): four diagnostic sensors surfacing coordinator state
            ASPConfidenceScoreSensor(coordinator),
            ASPSODALevelSensor(coordinator),
            ASPLastResolvedSensor(coordinator),
            ASPLastErrorSensor(coordinator),
            # Phase 33 IDX-03: spatial-index last-rebuilt timestamp sensor
            ASPIndexLastRebuiltSensor(coordinator),
        ]
    )


class ASPNextMoveTimeSensor(SensorEntity):
    """Sensor showing the next time the car must be moved for ASP.

    Maps all 5 ScheduleResult variants plus special states to sensor values.
    No device_class set because text states break timestamp device class.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "next_move_time"
    _attr_icon = "mdi:car-clock"

    def __init__(self, coordinator: ASPParkingCoordinator) -> None:
        """Initialize the sensor.

        Args:
            coordinator: The ASP Parking coordinator instance.
        """
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.entry_id}_next_move_time"

    async def async_added_to_hass(self) -> None:
        """Register update callback when entity is added to HA."""
        self._coordinator.async_add_update_callback(self.async_write_ha_state)
        self.async_on_remove(
            lambda: self._coordinator.async_remove_update_callback(
                self.async_write_ha_state
            )
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for grouping entities."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._coordinator.entry.entry_id)},
            name="ASP Parking Monitor",
            manufacturer="GPS2ASP",
            model="ASP Schedule Resolver",
            sw_version=VERSION,
        )

    def _format_move_time(self, dt: datetime, today: date | None = None) -> str:
        """Return human-friendly move time string with date-aware tier.

        Three tiers (FMT-01, D-01):
          - Today    -> "\u26a0 Today, 8:30 AM"
          - Tomorrow -> "Tomorrow, 8:30 AM"
          - Other    -> "Friday (5/15), 8:30 AM"

        All date comparisons use HA's configured local timezone via
        now_ha_local(); the 12-hour seconds heuristic is removed (D-02).

        ``today`` may be pre-captured by the caller (e.g. extra_state_attributes)
        so that a single snapshot is shared across multiple reads, eliminating a
        midnight race where native_value and extra_state_attributes resolve "today"
        independently and can disagree for one state cycle (WR-03).
        """
        local_dt = dt_util.as_local(dt)
        if today is None:
            today = now_ha_local().date()
        target_date = local_dt.date()
        time_str = local_dt.strftime("%I:%M %p").lstrip("0")

        if target_date == today:
            return f"\u26a0 Today, {time_str}"
        if target_date == today + timedelta(days=1):
            return f"Tomorrow, {time_str}"

        weekday = local_dt.strftime("%A")
        md = f"{local_dt.month}/{local_dt.day}"
        return f"{weekday} ({md}), {time_str}"

    @property
    def native_value(self) -> str | None:
        """Return the sensor state based on coordinator data.

        Maps coordinator data to one of:
        - Human-friendly time string (ScheduleFound or ASPActiveNow)
          Today: "⚠ Today, 8:30 AM"
          Tomorrow: "Tomorrow, 8:30 AM"
          Other: "Thursday (5/3), 8:30 AM"
        - "No restrictions" (NoASPSchedule, NoMatchSchedule, AllUnparseable)
        - "Outside coverage area" (special_state)
        - "No street match" (special_state)
        - None (loading/initial state)
        """
        data = self._coordinator.data

        # Special states take priority
        if data.special_state == "outside_coverage":
            return "Outside coverage area"
        if data.special_state == "no_street_match":
            return "No street match"

        # No schedule result yet (initial/loading state)
        if data.schedule_result is None:
            return None

        # Lazy merge suspension at read time
        schedule = apply_suspension(data.schedule_result, data.suspension_state)

        # Suspension branch (before normal schedule branches)
        if isinstance(schedule, (ScheduleFound, ASPActiveNow)) and schedule.suspended:
            return "Suspended"

        if isinstance(schedule, ScheduleFound):
            if schedule.next_window is None:
                return None  # find_next_window returned None (no windows in schedule)
            return self._format_move_time(schedule.next_window.start_datetime)

        if isinstance(schedule, ASPActiveNow):
            # Show when the active window ends
            return self._format_move_time(schedule.active_window.end_datetime)

        if isinstance(schedule, NoASPSchedule):
            return "No restrictions"

        if isinstance(schedule, NoMatchSchedule):
            # No SODA data = no restrictions
            return "No restrictions"

        if isinstance(schedule, AllUnparseable):
            # Signs exist but unparseable -- fallback to no restrictions
            return "No restrictions"

        return None

    @property
    def available(self) -> bool:
        """Return True if the sensor is available.

        Becomes unavailable when GPS data is stale (exceeds stale_timeout hours).
        """
        data = self._coordinator.data

        # Initial state: not yet stale (no GPS update received yet)
        if data.last_gps_update is None:
            return True

        stale_timeout = self._coordinator.entry.options.get(
            CONF_STALE_TIMEOUT, DEFAULT_STALE_TIMEOUT
        )
        elapsed = (dt_util.utcnow() - data.last_gps_update).total_seconds()
        return elapsed <= stale_timeout * 3600

    @property
    def extra_state_attributes(self) -> dict[str, str | float | int | list | None]:
        """Return rich state attributes across 5 groups.

        Groups: schedule, location, window, metadata, error.
        When special_state is set, retains previous schedule attributes
        since coordinator preserves schedule_result.
        """
        data = self._coordinator.data
        attrs: dict[str, str | float | int | list | None] = {}

        # Capture "today" once so that urgency and the boolean attributes
        # (next_move_is_today, next_move_is_tomorrow) within extra_state_attributes
        # share a single date snapshot (intra-property race fix).
        # Note: native_value evaluates its own date independently via _format_move_time;
        # a one-cycle display/attribute disagreement at exact midnight is accepted.
        today = now_ha_local().date()

        # Date-relationship booleans (D-06: always present, default False)
        # Set defaults BEFORE branching so attributes are present even when no
        # concrete _move_dt exists (Claude's discretion: never None, never omitted).
        attrs["next_move_is_today"] = False
        attrs["next_move_is_tomorrow"] = False

        schedule = data.schedule_result

        # Lazy merge suspension at read time
        if schedule is not None:
            schedule = apply_suspension(schedule, data.suspension_state)

        # --- Schedule group ---
        if isinstance(schedule, (ScheduleFound, ASPActiveNow)):
            if isinstance(schedule, ScheduleFound):
                weekly = schedule.weekly_schedule
            else:
                # ASPActiveNow does not have weekly_schedule; derive from active_window
                weekly = None

            if weekly is not None:
                day_names = sorted(
                    {w.day.name.title() for w in weekly.windows},
                    key=lambda d: [
                        "Monday",
                        "Tuesday",
                        "Wednesday",
                        "Thursday",
                        "Friday",
                        "Saturday",
                        "Sunday",
                    ].index(d),
                )
                attrs["cleaning_days"] = day_names
            elif isinstance(schedule, ASPActiveNow):
                # BUG-T-005 (Phase 35.1-05): minimum-viable; shows active cleaning day.
                # When the schedule is ASPActiveNow we have only the active_window;
                # surface its day so the UI never loses the cleaning_days chip on
                # active-now mornings.
                attrs["cleaning_days"] = [schedule.active_window.day.name.title()]

            # time_window_start/end: use next_window (the temporally-next window)
            # rather than windows[0] (the day-sorted first window), so these
            # attributes always reflect the window the user actually needs to act on.
            if isinstance(schedule, ScheduleFound) and schedule.next_window is not None:
                attrs["time_window_start"] = schedule.next_window.start_time.strftime(
                    "%H:%M"
                )
                attrs["time_window_end"] = schedule.next_window.end_time.strftime(
                    "%H:%M"
                )

            attrs["schedule_summary"] = schedule.summary

            # Urgency + date-relationship booleans — only when a concrete move
            # datetime exists. Single source-of-truth derivation (Pitfall 4):
            # is_today / is_tomorrow drive both urgency and the new booleans.
            _move_dt: datetime | None = None
            if isinstance(schedule, ScheduleFound) and schedule.next_window is not None:
                _move_dt = schedule.next_window.start_datetime
            elif isinstance(schedule, ASPActiveNow):
                _move_dt = schedule.active_window.end_datetime
            if _move_dt is not None:
                local_dt = dt_util.as_local(_move_dt)
                target_date = local_dt.date()
                is_today = target_date == today
                is_tomorrow = target_date == today + timedelta(days=1)
                attrs["urgency"] = "high" if is_today else "normal"
                attrs["next_move_is_today"] = is_today
                attrs["next_move_is_tomorrow"] = is_tomorrow

            # --- Location group ---
            attrs["street_name"] = schedule.on_street
            attrs["cross_streets"] = f"{schedule.from_street} to {schedule.to_street}"
            attrs["side_of_street"] = schedule.side_of_street
            # Phase 36 SENSOR-01: display-friendly cardinal label. Omitted when
            # side_of_street is not one of N/S/E/W (per locked SPEC edge case).
            if (side_label := _SIDE_LABELS.get(schedule.side_of_street)) is not None:
                attrs["side_label"] = side_label

        # --- Window group ---
        if isinstance(schedule, ScheduleFound):
            if schedule.next_window is not None:
                attrs["next_window_start"] = (
                    schedule.next_window.start_datetime.isoformat()
                )
                attrs["next_window_end"] = schedule.next_window.end_datetime.isoformat()
                attrs["next_window_day"] = schedule.next_window.day.name.title()
        elif isinstance(schedule, ASPActiveNow):
            attrs["current_window_start"] = (
                schedule.active_window.start_datetime.isoformat()
            )
            attrs["current_window_end"] = (
                schedule.active_window.end_datetime.isoformat()
            )

        # --- Suspension group ---
        if isinstance(schedule, (ScheduleFound, ASPActiveNow)) and schedule.suspended:
            attrs["suspension_reason"] = schedule.suspension_reason
            attrs["resolution_reason"] = schedule.resolution_reason

        # --- Metadata group ---
        attrs["last_resolved"] = (
            data.last_resolved.isoformat() if data.last_resolved else None
        )
        attrs["confidence_score"] = data.confidence_score
        attrs["borough"] = (
            data.borough
        )  # Phase 30 — always present (None when unresolved)
        attrs["sign_count"] = data.sign_count
        attrs["parse_failures"] = data.parse_failures
        attrs["soda_level"] = data.soda_level

        # --- Error group (only when error exists) ---
        if data.last_error is not None:
            attrs["last_error"] = data.last_error
            attrs["last_error_time"] = (
                data.last_error_time.isoformat() if data.last_error_time else None
            )

        return attrs


# ---------------------------------------------------------------------------
# Diagnostic sensors
# ---------------------------------------------------------------------------


class _ASPDiagnosticSensor(SensorEntity):
    """Base class for diagnostic sensors sharing coordinator and device info."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ASPParkingCoordinator) -> None:
        self._coordinator = coordinator

    async def async_added_to_hass(self) -> None:
        """Register update callback when entity is added to HA."""
        self._coordinator.async_add_update_callback(self.async_write_ha_state)
        self.async_on_remove(
            lambda: self._coordinator.async_remove_update_callback(
                self.async_write_ha_state
            )
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for grouping entities."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._coordinator.entry.entry_id)},
            name="ASP Parking Monitor",
            manufacturer="GPS2ASP",
            model="ASP Schedule Resolver",
            sw_version=VERSION,
        )


class ASPCarNameSensor(_ASPDiagnosticSensor):
    """Diagnostic sensor showing the friendly name of the tracked device."""

    _attr_icon = "mdi:car"
    _attr_translation_key = "car_name"

    def __init__(self, coordinator: ASPParkingCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_car_name"

    @property
    def native_value(self) -> str | None:
        """Return the friendly name of the device_tracker entity."""
        if self.hass is None:
            return None
        state = self.hass.states.get(self._coordinator.device_tracker_entity)
        if state is None:
            return None
        return state.name


class ASPVINSensor(_ASPDiagnosticSensor):
    """Diagnostic sensor showing the VIN of the tracked vehicle."""

    _attr_icon = "mdi:identifier"
    _attr_translation_key = "vin"

    def __init__(self, coordinator: ASPParkingCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_vin"

    @property
    def native_value(self) -> str | None:
        """Return the VIN from device_tracker attributes."""
        if self.hass is None:
            return None
        state = self.hass.states.get(self._coordinator.device_tracker_entity)
        if state is None:
            return None
        return state.attributes.get("vin")


class ASPLatitudeSensor(_ASPDiagnosticSensor):
    """Diagnostic sensor showing the last resolved GPS latitude."""

    _attr_icon = "mdi:latitude"
    _attr_translation_key = "latitude"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "°"

    def __init__(self, coordinator: ASPParkingCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_latitude"

    @property
    def native_value(self) -> float | None:
        """Return the last GPS latitude."""
        return self._coordinator.data.last_lat


class ASPLongitudeSensor(_ASPDiagnosticSensor):
    """Diagnostic sensor showing the last resolved GPS longitude."""

    _attr_icon = "mdi:longitude"
    _attr_translation_key = "longitude"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "°"

    def __init__(self, coordinator: ASPParkingCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_longitude"

    @property
    def native_value(self) -> float | None:
        """Return the last GPS longitude."""
        return self._coordinator.data.last_lon


class ASPResolvedStreetSensor(_ASPDiagnosticSensor):
    """Diagnostic sensor showing the resolved street name."""

    _attr_icon = "mdi:road"
    _attr_translation_key = "resolved_street"

    def __init__(self, coordinator: ASPParkingCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_resolved_street"

    @property
    def native_value(self) -> str | None:
        """Return the resolved street name, or None if not resolved."""
        schedule = self._coordinator.data.schedule_result
        if isinstance(schedule, (ScheduleFound, ASPActiveNow)):
            return schedule.on_street
        return None

    @property
    def extra_state_attributes(self) -> dict[str, str | float | int | None]:
        """Return cross streets, side, confidence, and Phase 30 diagnostic fields."""
        schedule = self._coordinator.data.schedule_result
        if not isinstance(schedule, (ScheduleFound, ASPActiveNow)):
            return {}
        attrs: dict[str, str | float | int | None] = {
            "from_street": schedule.from_street,
            "to_street": schedule.to_street,
            "side_of_street": schedule.side_of_street,
            "confidence_score": self._coordinator.data.confidence_score,
            "borough": self._coordinator.data.borough,
            "distance_ft": self._coordinator.data.distance_ft,
            "street_width_ft": self._coordinator.data.street_width_ft,
            "segment_id": self._coordinator.data.segment_id,
        }
        # Phase 36 SENSOR-01: display-friendly cardinal label. Omitted when
        # side_of_street is not one of N/S/E/W (per locked SPEC edge case).
        if (side_label := _SIDE_LABELS.get(schedule.side_of_street)) is not None:
            attrs["side_label"] = side_label
        return attrs


class ASPResolutionStatusSensor(_ASPDiagnosticSensor):
    """Diagnostic sensor showing the pipeline resolution status."""

    _attr_icon = "mdi:map-search"
    _attr_translation_key = "resolution_status"

    def __init__(self, coordinator: ASPParkingCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_resolution_status"

    @property
    def native_value(self) -> str | None:
        """Return the pipeline outcome string."""
        data = self._coordinator.data
        if data.special_state is not None:
            return data.special_state
        if data.schedule_result is not None:
            return data.schedule_result.status
        return None

    @property
    def extra_state_attributes(self) -> dict[str, str | int | None]:
        """Return metadata about the last pipeline run."""
        data = self._coordinator.data
        attrs: dict[str, str | int | None] = {
            "last_resolved": (
                data.last_resolved.isoformat() if data.last_resolved else None
            ),
            "sign_count": data.sign_count,
            "parse_failures": data.parse_failures,
        }
        if data.last_error is not None:
            attrs["last_error"] = data.last_error
        return attrs


class ASPConfidenceScoreSensor(_ASPDiagnosticSensor):
    """Diagnostic sensor showing the resolver confidence score (0-1).

    Per D-08: surfaces coordinator.data.confidence_score as the entity state.
    Reading frequency follows the coordinator's pipeline cadence (event-driven
    on GPS change; refreshed every refresh_interval hours).
    """

    _attr_icon = "mdi:gauge"
    _attr_translation_key = "confidence_score"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: ASPParkingCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_confidence_score"

    @property
    def native_value(self) -> float | None:
        """Return the resolver confidence (0..1) or None if not yet resolved."""
        return self._coordinator.data.confidence_score


class ASPSODALevelSensor(_ASPDiagnosticSensor):
    """Diagnostic sensor showing which SODA fallback level matched (0-4).

    Per D-08: surfaces coordinator.data.soda_level as the entity state. 0 means
    no resolution yet; 1-4 indicate which fallback strategy succeeded.
    """

    _attr_icon = "mdi:layers-search"
    _attr_translation_key = "soda_level"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: ASPParkingCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_soda_level"

    @property
    def native_value(self) -> int | None:
        """Return the SODA fallback level (0-4); 0 means not resolved."""
        return self._coordinator.data.soda_level


class ASPLastResolvedSensor(_ASPDiagnosticSensor):
    """Diagnostic sensor showing the timestamp of the last successful resolve.

    Per D-08: surfaces coordinator.data.last_resolved as ISO string entity state.
    Returns None when the pipeline has never produced a successful resolution.
    """

    _attr_icon = "mdi:clock-check"
    _attr_translation_key = "last_resolved"

    def __init__(self, coordinator: ASPParkingCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_last_resolved"

    @property
    def native_value(self) -> str | None:
        """Return ISO timestamp of last successful pipeline run, or None."""
        ts = self._coordinator.data.last_resolved
        return ts.isoformat() if ts else None


class ASPLastErrorSensor(_ASPDiagnosticSensor):
    """Diagnostic sensor showing the most recent pipeline error string.

    Per D-08: surfaces coordinator.data.last_error as the entity state.
    Returns None when no errors have occurred since startup.
    """

    _attr_icon = "mdi:alert-circle-outline"
    _attr_translation_key = "last_error"

    def __init__(self, coordinator: ASPParkingCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_last_error"

    @property
    def native_value(self) -> str | None:
        """Return the last error string, or None if no error."""
        return self._coordinator.data.last_error


class ASPIndexLastRebuiltSensor(_ASPDiagnosticSensor):
    """Diagnostic sensor exposing the spatial-index build timestamp (Phase 33, IDX-03).

    Surfaces ``coordinator._last_rebuilt`` -- a tz-aware datetime populated
    at ``async_start`` (from ``build_info.json``) and after each successful
    manual rebuild. With ``SensorDeviceClass.TIMESTAMP`` HA renders the
    value as a relative time string ("X days ago") in the UI.

    RESEARCH Pitfall 6: the TIMESTAMP device class REJECTS naive datetimes.
    The coordinator's ``_sync_read_build_timestamp`` helper guarantees the
    parsed value is tz-aware, so ``native_value`` can pass through unchanged.
    """

    _attr_icon = "mdi:clock-check"
    _attr_translation_key = "index_last_rebuilt"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: ASPParkingCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_index_last_rebuilt"

    @property
    def native_value(self) -> datetime | None:
        """Return tz-aware build_timestamp datetime, or None when unset."""
        return self._coordinator._last_rebuilt
