"""Binary sensor platform for the ASP Parking integration.

Provides ASPActiveNowBinarySensor which is ON when the car is currently
parked during an active ASP cleaning window. Minimal attributes per
user decision -- only shows current window times when active.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from gps2asp.schedule.models import ASPActiveNow

from .const import DOMAIN
from .coordinator import ASPParkingCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the ASP Parking binary sensor from a config entry."""
    coordinator: ASPParkingCoordinator = entry.runtime_data
    async_add_entities([ASPActiveNowBinarySensor(coordinator)])


class ASPActiveNowBinarySensor(BinarySensorEntity):
    """Binary sensor indicating whether ASP cleaning is currently active.

    ON when the car is parked during an active ASP cleaning window.
    OFF in all other states.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "active_now"
    _attr_icon = "mdi:broom"

    def __init__(self, coordinator: ASPParkingCoordinator) -> None:
        """Initialize the binary sensor.

        Args:
            coordinator: The ASP Parking coordinator instance.
        """
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.entry_id}_active_now"

    async def async_added_to_hass(self) -> None:
        """Register update callback when entity is added to HA."""
        self._coordinator.async_add_update_callback(self.async_write_ha_state)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for grouping entities under the same device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._coordinator.entry.entry_id)},
            name="ASP Parking Monitor",
            manufacturer="GPS2ASP",
            model="ASP Schedule Resolver",
            sw_version="0.1.0",
        )

    @property
    def is_on(self) -> bool:
        """Return True only when ASP cleaning is currently active."""
        return isinstance(self._coordinator.data.schedule_result, ASPActiveNow)

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return minimal attributes -- only current window times when active."""
        schedule = self._coordinator.data.schedule_result
        if isinstance(schedule, ASPActiveNow):
            return {
                "current_window_start": (
                    schedule.active_window.start_datetime.isoformat()
                ),
                "current_window_end": (
                    schedule.active_window.end_datetime.isoformat()
                ),
            }
        return {}
