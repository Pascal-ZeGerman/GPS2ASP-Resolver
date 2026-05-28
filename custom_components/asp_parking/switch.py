"""Switch platform for the ASP Parking integration.

Provides ASPDebugModeSwitch -- a writable dashboard control that toggles
the coordinator's ``_debug_enabled`` flag in-memory (Phase 29, D-01/D-03).
Replaces the 5-click options-flow toggle from Phase 24. State is NOT
persisted to entry.options; debug mode resets to False on every HA
restart by design.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, VERSION
from .coordinator import ASPParkingCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the ASP Parking switch platform from a config entry."""
    coordinator: ASPParkingCoordinator = entry.runtime_data
    async_add_entities([ASPDebugModeSwitch(coordinator)])


class ASPDebugModeSwitch(SwitchEntity):
    """Writable switch for toggling coordinator debug mode (Phase 29).

    Per D-01: state is in-memory only -- async_turn_on/off mutate
    ``coordinator._debug_enabled`` directly and never touch
    ``entry.options``. Debug mode always resets to False on HA restart.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "debug_switch"
    _attr_icon = "mdi:bug"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ASPParkingCoordinator) -> None:
        """Initialize the switch.

        Args:
            coordinator: The ASP Parking coordinator instance.
        """
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.entry_id}_debug_switch"

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
        """Return device info for grouping entities under the same device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._coordinator.entry.entry_id)},
            name="ASP Parking Monitor",
            manufacturer="GPS2ASP",
            model="ASP Schedule Resolver",
            sw_version=VERSION,
        )

    @property
    def is_on(self) -> bool:
        """Return True when coordinator debug mode is active."""
        return bool(self._coordinator._debug_enabled)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable debug mode in-memory (D-01: no entry.options write)."""
        self._coordinator._debug_enabled = True
        self._coordinator.async_update_listeners()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable debug mode in-memory (D-01: no entry.options write)."""
        self._coordinator._debug_enabled = False
        self._coordinator.async_update_listeners()

    @property
    def extra_state_attributes(self) -> dict[str, str | float | None]:
        """Return current debug override values for visibility (D-09).

        Exposes only the three GPS-and-time override fields the retired
        ASPDebugModeSensor exposed. The notification-suppression flag is
        intentionally excluded -- it lives only in entry.options now.
        """
        c = self._coordinator
        return {
            "debug_lat": c._debug_lat,
            "debug_lon": c._debug_lon,
            "debug_datetime": (
                c._debug_datetime.isoformat() if c._debug_datetime else None
            ),
        }
