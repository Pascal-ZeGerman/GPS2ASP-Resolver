"""RED tests for ASPIndexRebuildButton (Phase 33, IDX-01).

These tests intentionally fail at collection (ImportError) until Wave 2 plan 03
creates ``custom_components/asp_parking/button.py``. They lock the contract for
the new HA button entity:
  - unique_id format ``{entry_id}_rebuild_index``
  - translation_key == "rebuild_index"
  - icon == "mdi:database-refresh"
  - has_entity_name is True
  - entity_category == EntityCategory.CONFIG
  - async_press() delegates to coordinator.async_request_rebuild()
  - device_info groups with the rest of the ASP Parking entities
  - async_setup_entry() instantiates exactly one ASPIndexRebuildButton

The structure mirrors tests/test_debug_switch.py (SimpleNamespace + MagicMock
+ AsyncMock pattern; no HA test harness required).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from homeassistant.helpers.entity import EntityCategory

from custom_components.asp_parking.button import (
    ASPIndexRebuildButton,
    async_setup_entry,
)


def _make_coordinator():
    """Build a minimal coordinator stub matching the button's contract."""
    entry = SimpleNamespace(
        entry_id="test_entry_33",
        runtime_data=None,
    )
    coord = SimpleNamespace(
        entry=entry,
        _is_rebuilding=False,
        async_request_rebuild=AsyncMock(),
        async_add_update_callback=MagicMock(),
        async_remove_update_callback=MagicMock(),
    )
    # Allow setup_entry test to retrieve coordinator via entry.runtime_data
    entry.runtime_data = coord
    return coord


def test_unique_id_pattern():
    """Button unique_id must follow the f"{entry_id}_rebuild_index" pattern."""
    coord = _make_coordinator()
    btn = ASPIndexRebuildButton(coord)
    assert btn.unique_id == "test_entry_33_rebuild_index"


def test_translation_key_and_icon():
    """Button must expose translation_key='rebuild_index' and the mdi icon."""
    coord = _make_coordinator()
    btn = ASPIndexRebuildButton(coord)
    assert btn.translation_key == "rebuild_index"
    assert btn.icon == "mdi:database-refresh"


def test_has_entity_name_attribute():
    """has_entity_name must be True for the translation_key to be picked up."""
    coord = _make_coordinator()
    btn = ASPIndexRebuildButton(coord)
    assert btn.has_entity_name is True


def test_entity_category():
    """Button is a user-facing config control -> EntityCategory.CONFIG."""
    coord = _make_coordinator()
    btn = ASPIndexRebuildButton(coord)
    assert btn.entity_category == EntityCategory.CONFIG


async def test_async_press_calls_coordinator_request_rebuild():
    """async_press() must await coordinator.async_request_rebuild() exactly once."""
    coord = _make_coordinator()
    btn = ASPIndexRebuildButton(coord)
    await btn.async_press()
    coord.async_request_rebuild.assert_awaited_once()


def test_device_info_groups_with_other_entities():
    """device_info identifiers must match every other ASP Parking entity."""
    from custom_components.asp_parking.const import DOMAIN

    coord = _make_coordinator()
    btn = ASPIndexRebuildButton(coord)
    info = btn.device_info
    assert info["identifiers"] == {(DOMAIN, "test_entry_33")}
    assert info["name"] == "ASP Parking Monitor"


async def test_async_setup_entry_adds_one_entity():
    """async_setup_entry must instantiate exactly one ASPIndexRebuildButton."""
    coord = _make_coordinator()
    entry = SimpleNamespace(runtime_data=coord)

    added: list = []

    def _async_add_entities(entities):
        added.extend(entities)

    await async_setup_entry(
        hass=None, entry=entry, async_add_entities=_async_add_entities
    )
    assert len(added) == 1
    assert isinstance(added[0], ASPIndexRebuildButton)
    assert added[0].unique_id == "test_entry_33_rebuild_index"
