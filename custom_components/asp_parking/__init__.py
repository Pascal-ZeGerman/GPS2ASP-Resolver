"""ASP Parking - Alternate Side Parking integration for Home Assistant.

Creates the ASPParkingCoordinator, stores it in runtime_data, forwards
sensor and binary_sensor platforms, registers the resolve_now service,
and sets up an options update listener for reconfiguration.
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN, INDEX_DOWNLOAD_URL, PLATFORMS
from .coordinator import ASPParkingCoordinator

logger = logging.getLogger(__name__)

_INDEX_DIR = Path(__file__).parent / "gps2asp" / "data" / "index"
_INDEX_FILES = ("segments.idx", "segments.dat", "segments.json", "graph.json")
_DOWNLOAD_TASK_KEY = f"{DOMAIN}_index_task"


async def _async_ensure_index(hass: HomeAssistant) -> None:
    """Ensure spatial index files are present, downloading on first setup.

    Raises ConfigEntryNotReady while the download is in progress so HA retries
    automatically. After the download completes, the next retry succeeds.
    """
    if all((_INDEX_DIR / f).exists() for f in _INDEX_FILES):
        return

    task = hass.data.get(_DOWNLOAD_TASK_KEY)

    if task is None:
        task = hass.async_create_task(
            _async_download_index(hass),
            name="asp_parking_index_download",
        )
        hass.data[_DOWNLOAD_TASK_KEY] = task
    elif task.done() and (exc := task.exception()) is not None:
        raise ConfigEntryNotReady(
            f"Spatial index download failed: {exc}. "
            "See documentation for manual setup."
        ) from exc

    raise ConfigEntryNotReady(
        "Downloading NYC street index (~73 MB), will retry automatically"
    )


async def _async_download_index(hass: HomeAssistant) -> None:
    """Download and extract the spatial index ZIP from the GitHub release."""
    from homeassistant.components.persistent_notification import (
        async_create as pn_create,
        async_dismiss as pn_dismiss,
    )

    import httpx

    pn_create(
        hass,
        "Downloading NYC street index (~73 MB). ASP Parking will start automatically when complete.",
        title="ASP Parking: First-Time Setup",
        notification_id="asp_parking_index_download",
    )

    def _sync_download() -> None:
        _INDEX_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _INDEX_DIR / "_download.zip"
        try:
            with httpx.Client(timeout=300, follow_redirects=True) as client:
                with client.stream("GET", INDEX_DOWNLOAD_URL) as resp:
                    resp.raise_for_status()
                    with open(tmp, "wb") as f:
                        for chunk in resp.iter_bytes(chunk_size=65536):
                            f.write(chunk)
            with zipfile.ZipFile(tmp) as zf:
                zf.extractall(_INDEX_DIR)
        finally:
            tmp.unlink(missing_ok=True)

    try:
        await hass.async_add_executor_job(_sync_download)
        pn_dismiss(hass, "asp_parking_index_download")
        logger.info("ASP Parking: spatial index downloaded to %s", _INDEX_DIR)
    except Exception as err:
        pn_dismiss(hass, "asp_parking_index_download")
        pn_create(
            hass,
            f"Failed to download spatial index: {err}. "
            "Place index files manually — see documentation.",
            title="ASP Parking: Setup Error",
            notification_id="asp_parking_index_error",
        )
        logger.error("ASP Parking: index download failed: %s", err)
        raise


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
    # Ensure spatial index is present (downloads on first setup)
    await _async_ensure_index(hass)

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
