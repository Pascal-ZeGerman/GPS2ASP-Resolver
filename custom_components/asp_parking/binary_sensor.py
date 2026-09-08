"""Binary sensor platform for the ASP Parking integration.

Provides ASPActiveNowBinarySensor which is ON when the car is currently
parked during an active ASP cleaning window. Minimal attributes per
user decision -- only shows current window times when active.

Also provides ASPIndexRebuildingBinarySensor (Phase 33, IDX-02) which
mirrors the coordinator's ``_is_rebuilding`` flag while a spatial-index
rebuild background task is running.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .gps2asp.schedule.models import ASPActiveNow
from .gps2asp.suspension import apply_suspension

from .const import DOMAIN, VERSION
from .coordinator import ASPParkingCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the ASP Parking binary sensor from a config entry."""
    coordinator: ASPParkingCoordinator = entry.runtime_data
    async_add_entities(
        [
            ASPActiveNowBinarySensor(coordinator),
            ASPIndexRebuildingBinarySensor(coordinator),
            ASPGpsPipelineHealthBinarySensor(coordinator),
        ]
    )


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
        """Return True when the underlying pipeline data should be trusted.

        Shares ``coordinator.gps_data_available`` (the three-gate policy
        also used by ``ASPNextMoveTimeSensor.available``) so this sensor
        stops reporting "not active" as a confident answer -- rather than a
        stale one -- under the same conditions the main sensor does.
        """
        return self._coordinator.gps_data_available

    @property
    def is_on(self) -> bool:
        """Return True only when ASP cleaning is currently active and not suspended."""
        schedule = self._coordinator.data.schedule_result
        if not isinstance(schedule, ASPActiveNow):
            return False
        merged = apply_suspension(schedule, self._coordinator.data.suspension_state)
        return isinstance(merged, ASPActiveNow) and not merged.suspended

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return minimal attributes -- only current window times when active and not suspended."""
        schedule = self._coordinator.data.schedule_result
        if not isinstance(schedule, ASPActiveNow):
            return {}
        merged = apply_suspension(schedule, self._coordinator.data.suspension_state)
        if not isinstance(merged, ASPActiveNow) or merged.suspended:
            return {}
        return {
            "current_window_start": merged.active_window.start_datetime.isoformat(),
            "current_window_end": merged.active_window.end_datetime.isoformat(),
        }


class ASPIndexRebuildingBinarySensor(BinarySensorEntity):
    """Diagnostic binary sensor mirroring the spatial-index rebuild state.

    ON while ``coordinator._is_rebuilding`` is True (a rebuild background
    task is running); OFF otherwise. The property is LIVE -- read directly
    from the coordinator on every poll so manual mutations in tests are
    immediately observable.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "index_rebuilding"
    _attr_icon = "mdi:progress-download"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ASPParkingCoordinator) -> None:
        """Initialize the binary sensor.

        Args:
            coordinator: The ASP Parking coordinator instance.
        """
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.entry_id}_index_rebuilding"

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
        """Return True while a spatial-index rebuild is in progress."""
        return self._coordinator._is_rebuilding


class ASPGpsPipelineHealthBinarySensor(BinarySensorEntity):
    """Diagnostic binary sensor: ON when GPS is recent and no pipeline error has occurred.

    ON when ``last_gps_update`` is within ``stale_timeout`` hours AND
    ``coordinator._last_pipeline_error`` is False.  Reflects the GPS watchdog
    and pipeline error state LIVE via ``coordinator.gps_data_available`` --
    the same three-gate policy used by ``ASPNextMoveTimeSensor.available``.

    OFF when:
    - ``last_gps_update`` is None (no GPS fix yet)
    - the tracked device_tracker self-reports ``unavailable`` / ``unknown``
    - GPS age > stale_timeout * 3600 seconds (GPS has gone silent)
    - ``_last_pipeline_error`` is True (last pipeline run raised an exception)

    The tracker-health check is what keeps this entity a useful diagnostic now
    that ``stale_timeout`` defaults to 7 days: the age test alone would stay ON
    for a week after the source integration died. Silence means "parked"; an
    explicit unavailable state means "broken".
    """

    _attr_has_entity_name = True
    _attr_translation_key = "gps_pipeline_healthy"
    _attr_icon = "mdi:signal"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ASPParkingCoordinator) -> None:
        """Initialize the binary sensor.

        Args:
            coordinator: The ASP Parking coordinator instance.
        """
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.entry_id}_gps_pipeline_healthy"

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
        """Return True when GPS is recent and the last pipeline run succeeded.

        Delegates the pipeline-error / tracker-health / staleness checks to
        ``coordinator.gps_data_available`` -- the same three-gate policy used
        by ``ASPNextMoveTimeSensor.available`` -- so the two entities cannot
        silently drift apart. Unlike ``available``, "no GPS fix yet" is
        reported as unhealthy (False) here rather than as trivially current.
        """
        if self._coordinator.data.last_gps_update is None:
            return False
        return self._coordinator.gps_data_available

    @property
    def extra_state_attributes(self) -> dict[str, bool]:
        """Return diagnostic attributes including last pipeline error flag."""
        return {"last_pipeline_error": self._coordinator._last_pipeline_error}
