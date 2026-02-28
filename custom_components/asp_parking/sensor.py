"""Sensor platform for the ASP Parking integration.

Provides ASPNextMoveTimeSensor which maps coordinator data to a sensor state:
- ISO datetime when next cleaning window is found (ScheduleFound)
- "No restrictions" when no ASP schedule or signs exist
- "Outside coverage area" when car is outside NYC
- "No street match" when GPS is valid but no street segment found

Rich attributes cover schedule, location, window, metadata, and error groups.
"""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from gps2asp.schedule.models import (
    AllUnparseable,
    ASPActiveNow,
    NoASPSchedule,
    NoMatchSchedule,
    ScheduleFound,
)

from .const import CONF_STALE_TIMEOUT, DEFAULT_STALE_TIMEOUT, DOMAIN
from .coordinator import ASPParkingCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the ASP Parking sensor from a config entry."""
    coordinator: ASPParkingCoordinator = entry.runtime_data
    async_add_entities([ASPNextMoveTimeSensor(coordinator)])


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

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for grouping entities."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._coordinator.entry.entry_id)},
            name="ASP Parking Monitor",
            manufacturer="GPS2ASP",
            model="ASP Schedule Resolver",
            sw_version="0.1.0",
        )

    @property
    def native_value(self) -> str | None:
        """Return the sensor state based on coordinator data.

        Maps coordinator data to one of:
        - ISO datetime string (ScheduleFound or ASPActiveNow)
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

        schedule = data.schedule_result

        if isinstance(schedule, ScheduleFound):
            if schedule.next_window is None:
                return None  # find_next_window returned None (no windows in schedule)
            return schedule.next_window.start_datetime.isoformat()

        if isinstance(schedule, ASPActiveNow):
            # Show when the active window ends
            return schedule.active_window.end_datetime.isoformat()

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
        schedule = data.schedule_result

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
                if weekly.windows:
                    first_window = weekly.windows[0]
                    attrs["time_window_start"] = first_window.start_time.strftime(
                        "%H:%M"
                    )
                    attrs["time_window_end"] = first_window.end_time.strftime("%H:%M")

            attrs["schedule_summary"] = schedule.summary

            # --- Location group ---
            attrs["street_name"] = schedule.on_street
            attrs["cross_streets"] = f"{schedule.from_street} to {schedule.to_street}"
            attrs["side_of_street"] = schedule.side_of_street
            attrs["borough"] = None  # Not in current pipeline output

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

        # --- Metadata group ---
        attrs["last_resolved"] = (
            data.last_resolved.isoformat() if data.last_resolved else None
        )
        attrs["confidence_score"] = data.confidence_score
        attrs["sign_count"] = data.sign_count
        attrs["parse_failures"] = data.parse_failures

        # --- Error group (only when error exists) ---
        if data.last_error is not None:
            attrs["last_error"] = data.last_error
            attrs["last_error_time"] = (
                data.last_error_time.isoformat() if data.last_error_time else None
            )

        return attrs
