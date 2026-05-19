"""Button platform for the ASP Parking integration (Phase 33, IDX-01).

Provides ASPIndexRebuildButton -- a user-facing config button that triggers
a fire-and-forget rebuild of the local NYC spatial index. Pressing the button
delegates to ``coordinator.async_request_rebuild()`` which spawns the
download/extract/swap pipeline as a background task; concurrent presses are
no-ops while a rebuild is in progress.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    """Set up the ASP Parking button platform from a config entry."""
    coordinator: ASPParkingCoordinator = entry.runtime_data
    async_add_entities([ASPIndexRebuildButton(coordinator)])


class ASPIndexRebuildButton(ButtonEntity):
    """Writable button entity that triggers a spatial-index rebuild.

    Per Phase 33 IDX-01: ``async_press()`` awaits
    ``coordinator.async_request_rebuild()`` which performs the
    fire-and-forget download + extract + atomic-swap dance. The button is
    safe to press at any time; the coordinator's ``_is_rebuilding`` flag
    + ``_rebuild_lock`` ensure repeated presses do not spawn parallel
    rebuilds (RESEARCH Pitfall 1).
    """

    _attr_has_entity_name = True
    _attr_translation_key = "rebuild_index"
    _attr_icon = "mdi:database-refresh"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ASPParkingCoordinator) -> None:
        """Initialize the button.

        Args:
            coordinator: The ASP Parking coordinator instance.
        """
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.entry_id}_rebuild_index"

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
    def available(self) -> bool:
        """Return False while a rebuild is in progress (button greys out in UI)."""
        return not self._coordinator._is_rebuilding

    async def async_press(self) -> None:
        """Handle the button press by requesting a rebuild from the coordinator.

        The coordinator gates concurrent presses internally; this method
        always awaits the request, but the request is a no-op when
        ``_is_rebuilding`` is True.
        """
        await self._coordinator.async_request_rebuild()
