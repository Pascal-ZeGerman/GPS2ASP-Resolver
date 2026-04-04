"""ASP Parking - Alternate Side Parking integration for Home Assistant.

Creates the ASPParkingCoordinator, stores it in runtime_data, forwards
sensor and binary_sensor platforms, registers the resolve_now service,
and sets up an options update listener for reconfiguration.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN, PLATFORMS
from .coordinator import ASPParkingCoordinator

logger = logging.getLogger(__name__)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate config entry from version 1 to 2.

    No data shape change needed -- NYC311 API key defaults to not-configured.
    """
    if config_entry.version == 1:
        hass.config_entries.async_update_entry(config_entry, version=2)
        logger.info("Migrated ASP Parking config entry from v1 to v2")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ASP Parking from a config entry.

    Creates the coordinator, starts GPS tracking, forwards entity platforms,
    registers the resolve_now service, and sets up options change listener.

    Args:
        hass: Home Assistant instance.
        entry: Config entry for this integration instance.

    Returns:
        True if setup was successful.
    """
    # Create and start the coordinator
    coordinator = ASPParkingCoordinator(hass, entry)
    entry.runtime_data = coordinator
    await coordinator.async_start()

    # Forward entity platforms (sensor, binary_sensor)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register resolve_now service (idempotent -- only if not already registered)
    async def async_resolve_now(call: ServiceCall) -> None:
        """Service handler for resolve_now."""
        await coordinator.async_force_resolve()

    if not hass.services.has_service(DOMAIN, "resolve_now"):
        hass.services.async_register(DOMAIN, "resolve_now", async_resolve_now)

    # Reload integration when options change (e.g., threshold reconfiguration)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    logger.info("ASP Parking integration setup complete for %s", entry.title)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an ASP Parking config entry.

    Stops the coordinator and unloads entity platforms.

    Args:
        hass: Home Assistant instance.
        entry: Config entry being unloaded.

    Returns:
        True if unload was successful.
    """
    # Stop the coordinator (cancels listeners, debouncer)
    await entry.runtime_data.async_stop()

    # Unload entity platforms
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_options_updated(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Handle options update by reloading the integration.

    This ensures the coordinator picks up new threshold values.

    Args:
        hass: Home Assistant instance.
        entry: Config entry whose options were updated.
    """
    await hass.config_entries.async_reload(entry.entry_id)
