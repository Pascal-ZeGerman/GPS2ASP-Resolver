"""RED tests for ASPIndexRebuildingBinarySensor (Phase 33, IDX-02 entity contract).

These tests intentionally fail at collection (ImportError) until Wave 2 plan 03
adds ``ASPIndexRebuildingBinarySensor`` to
``custom_components/asp_parking/binary_sensor.py``. They lock the contract for
the new binary sensor that mirrors the coordinator's ``_is_rebuilding`` flag:
  - unique_id format ``{entry_id}_index_rebuilding``
  - translation_key == "index_rebuilding"
  - icon == "mdi:progress-download"
  - has_entity_name is True
  - entity_category == EntityCategory.DIAGNOSTIC
  - is_on reads ``coordinator._is_rebuilding`` LIVE (not captured at construction)
  - device_info groups with the rest of the ASP Parking entities

Coordinator-side asyncio.Lock + background-task semantics are covered by
plan 02 (not this plan).

The structure mirrors tests/test_debug_switch.py (SimpleNamespace + MagicMock
pattern; no HA test harness required).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from homeassistant.helpers.entity import EntityCategory

from custom_components.asp_parking.binary_sensor import (
    ASPIndexRebuildingBinarySensor,
)


def _make_coordinator(is_rebuilding: bool = False):
    """Build a minimal coordinator stub matching the binary sensor's contract."""
    entry = SimpleNamespace(entry_id="test_entry_33")
    coord = SimpleNamespace(
        entry=entry,
        _is_rebuilding=is_rebuilding,
        async_add_update_callback=MagicMock(),
        async_remove_update_callback=MagicMock(),
    )
    return coord


def test_unique_id_pattern():
    """Binary sensor unique_id must follow f"{entry_id}_index_rebuilding"."""
    coord = _make_coordinator()
    bs = ASPIndexRebuildingBinarySensor(coord)
    assert bs.unique_id == "test_entry_33_index_rebuilding"


def test_translation_key_and_icon():
    """Binary sensor must expose translation_key='index_rebuilding' and the mdi icon."""
    coord = _make_coordinator()
    bs = ASPIndexRebuildingBinarySensor(coord)
    assert bs.translation_key == "index_rebuilding"
    assert bs.icon == "mdi:progress-download"


def test_has_entity_name_attribute():
    """has_entity_name must be True for the translation_key to be picked up."""
    coord = _make_coordinator()
    bs = ASPIndexRebuildingBinarySensor(coord)
    assert bs.has_entity_name is True


def test_entity_category_is_diagnostic():
    """Diagnostic category groups this with debug-only entities in the UI."""
    coord = _make_coordinator()
    bs = ASPIndexRebuildingBinarySensor(coord)
    assert bs.entity_category == EntityCategory.DIAGNOSTIC


def test_is_on_false_when_not_rebuilding():
    """is_on must be False when coordinator._is_rebuilding is False."""
    coord = _make_coordinator(is_rebuilding=False)
    bs = ASPIndexRebuildingBinarySensor(coord)
    assert bs.is_on is False


def test_is_on_true_when_rebuilding():
    """is_on must be True when coordinator._is_rebuilding is True."""
    coord = _make_coordinator(is_rebuilding=True)
    bs = ASPIndexRebuildingBinarySensor(coord)
    assert bs.is_on is True


def test_is_on_flips_with_coordinator_state():
    """is_on is a LIVE property — flipping the coordinator flag after
    construction must be observable via the entity.
    """
    coord = _make_coordinator(is_rebuilding=False)
    bs = ASPIndexRebuildingBinarySensor(coord)
    assert bs.is_on is False
    coord._is_rebuilding = True
    assert bs.is_on is True
    coord._is_rebuilding = False
    assert bs.is_on is False


def test_device_info_groups_with_other_entities():
    """device_info identifiers must match every other ASP Parking entity."""
    from custom_components.asp_parking.const import DOMAIN

    coord = _make_coordinator()
    bs = ASPIndexRebuildingBinarySensor(coord)
    info = bs.device_info
    assert info["identifiers"] == {(DOMAIN, "test_entry_33")}
    assert info["name"] == "ASP Parking Monitor"
