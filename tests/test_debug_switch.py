"""Unit tests for ASPDebugModeSwitch (Phase 29, DBG-01).

Verifies the switch contract:
  - initial is_on reflects coordinator._debug_enabled
  - async_turn_on flips coordinator._debug_enabled to True
  - async_turn_off flips coordinator._debug_enabled to False
  - both turn_on and turn_off call coordinator.async_update_listeners()
  - extra_state_attributes mirrors coordinator debug_* fields
  - extra_state_attributes does NOT include suppress_notifications (D-09)
  - turn_on/off do NOT mutate entry.options (D-01)
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock


from custom_components.asp_parking.switch import (
    ASPDebugModeSwitch,
    async_setup_entry,
)


def _make_coordinator(
    debug_enabled: bool = False,
    debug_lat: float | None = None,
    debug_lon: float | None = None,
    debug_datetime: datetime | None = None,
):
    """Build a minimal coordinator stub matching the switch's contract."""
    entry = SimpleNamespace(
        entry_id="test_entry_123",
        options={"debug_enabled": False},  # tracked to assert no writes
    )
    coord = SimpleNamespace(
        entry=entry,
        _debug_enabled=debug_enabled,
        _debug_lat=debug_lat,
        _debug_lon=debug_lon,
        _debug_datetime=debug_datetime,
        async_update_listeners=MagicMock(),
        async_add_update_callback=MagicMock(),
    )
    return coord


def test_unique_id_pattern():
    coord = _make_coordinator()
    sw = ASPDebugModeSwitch(coord)
    assert sw.unique_id == "test_entry_123_debug_switch"


def test_translation_key_and_icon():
    coord = _make_coordinator()
    sw = ASPDebugModeSwitch(coord)
    assert sw.translation_key == "debug_switch"
    assert sw.icon == "mdi:bug"


def test_has_entity_name_attribute():
    """Translation key requires _attr_has_entity_name = True for HA to pick up the key."""
    coord = _make_coordinator()
    sw = ASPDebugModeSwitch(coord)
    assert sw.has_entity_name is True


def test_initial_is_on_false():
    coord = _make_coordinator(debug_enabled=False)
    sw = ASPDebugModeSwitch(coord)
    assert sw.is_on is False


def test_initial_is_on_true():
    coord = _make_coordinator(debug_enabled=True)
    sw = ASPDebugModeSwitch(coord)
    assert sw.is_on is True


async def test_turn_on_sets_flag_and_notifies():
    coord = _make_coordinator(debug_enabled=False)
    sw = ASPDebugModeSwitch(coord)
    await sw.async_turn_on()
    assert coord._debug_enabled is True
    coord.async_update_listeners.assert_called_once()


async def test_turn_off_sets_flag_and_notifies():
    coord = _make_coordinator(debug_enabled=True)
    sw = ASPDebugModeSwitch(coord)
    await sw.async_turn_off()
    assert coord._debug_enabled is False
    coord.async_update_listeners.assert_called_once()


async def test_turn_on_does_not_write_to_options():
    """D-01: switch state is in-memory only, never persisted."""
    coord = _make_coordinator(debug_enabled=False)
    original_opts = dict(coord.entry.options)
    sw = ASPDebugModeSwitch(coord)
    await sw.async_turn_on()
    assert coord.entry.options == original_opts


async def test_turn_off_does_not_write_to_options():
    """D-01: switch state is in-memory only, never persisted."""
    coord = _make_coordinator(debug_enabled=True)
    original_opts = dict(coord.entry.options)
    sw = ASPDebugModeSwitch(coord)
    await sw.async_turn_off()
    assert coord.entry.options == original_opts


def test_extra_state_attributes_three_keys_only():
    """D-09: exposes debug_lat, debug_lon, debug_datetime — no suppress_notifications."""
    coord = _make_coordinator(
        debug_lat=40.7128, debug_lon=-74.0060, debug_datetime=None
    )
    sw = ASPDebugModeSwitch(coord)
    attrs = sw.extra_state_attributes
    assert set(attrs.keys()) == {"debug_lat", "debug_lon", "debug_datetime"}
    assert attrs["debug_lat"] == 40.7128
    assert attrs["debug_lon"] == -74.0060
    assert attrs["debug_datetime"] is None
    assert "suppress_notifications" not in attrs


def test_extra_state_attributes_datetime_iso():
    dt = datetime(2026, 5, 2, 14, 30)
    coord = _make_coordinator(debug_datetime=dt)
    sw = ASPDebugModeSwitch(coord)
    assert sw.extra_state_attributes["debug_datetime"] == dt.isoformat()


def test_entity_category_is_diagnostic():
    from homeassistant.helpers.entity import EntityCategory

    coord = _make_coordinator()
    sw = ASPDebugModeSwitch(coord)
    assert sw.entity_category == EntityCategory.DIAGNOSTIC


async def test_async_added_to_hass_registers_callback():
    """Switch must register its async_write_ha_state with the coordinator."""
    coord = _make_coordinator()
    sw = ASPDebugModeSwitch(coord)
    # async_write_ha_state requires HA harness; we only check registration.
    # Replace the entity method with a sentinel so we can verify it was passed.
    sentinel = object()
    sw.async_write_ha_state = sentinel  # type: ignore[assignment]
    await sw.async_added_to_hass()
    coord.async_add_update_callback.assert_called_once_with(sentinel)


def test_device_info_groups_with_existing_entities():
    """DeviceInfo identifiers must match the binary_sensor / sensor pattern."""
    from custom_components.asp_parking.const import DOMAIN

    coord = _make_coordinator()
    sw = ASPDebugModeSwitch(coord)
    info = sw.device_info
    assert info["identifiers"] == {(DOMAIN, "test_entry_123")}
    assert info["name"] == "ASP Parking Monitor"
    assert info["manufacturer"] == "GPS2ASP"


async def test_async_setup_entry_adds_one_switch_entity():
    """async_setup_entry must instantiate exactly one ASPDebugModeSwitch."""
    coord = _make_coordinator()
    entry = SimpleNamespace(runtime_data=coord)

    added: list = []

    def _async_add_entities(entities):
        added.extend(entities)

    await async_setup_entry(
        hass=None, entry=entry, async_add_entities=_async_add_entities
    )
    assert len(added) == 1
    assert isinstance(added[0], ASPDebugModeSwitch)
    assert added[0].unique_id == "test_entry_123_debug_switch"
