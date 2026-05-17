"""RED tests for ASPIndexLastRebuiltSensor (Phase 33, IDX-03).

These tests intentionally fail at collection (ImportError) until Wave 2 plan 03
adds ``ASPIndexLastRebuiltSensor`` to
``custom_components/asp_parking/sensor.py``. They lock the contract for the new
diagnostic sensor that exposes the spatial-index ``build_timestamp`` parsed from
``build_info.json``:
  - unique_id format ``{entry_id}_index_last_rebuilt``
  - translation_key == "index_last_rebuilt"
  - icon == "mdi:clock-check"
  - has_entity_name is True (inherited from _ASPDiagnosticSensor)
  - device_class == SensorDeviceClass.TIMESTAMP
  - entity_category == EntityCategory.DIAGNOSTIC (inherited from base)
  - native_value returns the coordinator's ``_last_rebuilt`` LIVE
  - native_value MUST be a tz-aware datetime (Pitfall 6: TIMESTAMP rejects naive)
  - native_value is None when ``_last_rebuilt`` is None
  - device_info groups with the rest of the ASP Parking entities

The structure mirrors tests/test_debug_switch.py (SimpleNamespace + MagicMock
pattern; no HA test harness required).
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.helpers.entity import EntityCategory

from custom_components.asp_parking.sensor import ASPIndexLastRebuiltSensor


def _make_coordinator(last_rebuilt: datetime | None = None):
    """Build a minimal coordinator stub matching the sensor's contract."""
    entry = SimpleNamespace(entry_id="test_entry_33")
    coord = SimpleNamespace(
        entry=entry,
        _last_rebuilt=last_rebuilt,
        async_add_update_callback=MagicMock(),
        async_remove_update_callback=MagicMock(),
    )
    return coord


def test_unique_id_pattern():
    """Sensor unique_id must follow f"{entry_id}_index_last_rebuilt"."""
    coord = _make_coordinator()
    s = ASPIndexLastRebuiltSensor(coord)
    assert s.unique_id == "test_entry_33_index_last_rebuilt"


def test_translation_key_and_icon():
    """Sensor must expose translation_key='index_last_rebuilt' and the mdi icon."""
    coord = _make_coordinator()
    s = ASPIndexLastRebuiltSensor(coord)
    assert s.translation_key == "index_last_rebuilt"
    assert s.icon == "mdi:clock-check"


def test_has_entity_name_attribute():
    """has_entity_name must be True (inherited from _ASPDiagnosticSensor)."""
    coord = _make_coordinator()
    s = ASPIndexLastRebuiltSensor(coord)
    assert s.has_entity_name is True


def test_device_class_is_timestamp():
    """TIMESTAMP device class enables HA's native datetime rendering."""
    coord = _make_coordinator()
    s = ASPIndexLastRebuiltSensor(coord)
    assert s.device_class == SensorDeviceClass.TIMESTAMP


def test_entity_category_is_diagnostic():
    """Diagnostic category inherited from _ASPDiagnosticSensor base."""
    coord = _make_coordinator()
    s = ASPIndexLastRebuiltSensor(coord)
    assert s.entity_category == EntityCategory.DIAGNOSTIC


def test_native_value_none_when_unset():
    """native_value must be None when coordinator._last_rebuilt is None."""
    coord = _make_coordinator(last_rebuilt=None)
    s = ASPIndexLastRebuiltSensor(coord)
    assert s.native_value is None


def test_native_value_returns_tz_aware_datetime():
    """Pitfall 6: TIMESTAMP device class rejects naive datetimes.

    The sensor must surface the coordinator's tz-aware datetime unchanged
    (the coordinator parses build_info.json's ISO-Z timestamp via
    dt_util.parse_datetime, which always returns tz-aware).
    """
    expected = datetime(2026, 3, 3, 15, 9, 11, tzinfo=timezone.utc)
    coord = _make_coordinator(last_rebuilt=expected)
    s = ASPIndexLastRebuiltSensor(coord)
    assert s.native_value is not None
    assert s.native_value == expected
    assert s.native_value.tzinfo is not None


def test_native_value_reads_live():
    """native_value is a LIVE property — mutations to coord._last_rebuilt
    after construction must be observable.
    """
    coord = _make_coordinator(last_rebuilt=None)
    s = ASPIndexLastRebuiltSensor(coord)
    assert s.native_value is None
    new_dt = datetime(2026, 5, 14, 12, 0, 0, tzinfo=timezone.utc)
    coord._last_rebuilt = new_dt
    assert s.native_value == new_dt
    assert s.native_value.tzinfo is not None


def test_device_info_groups_with_other_entities():
    """device_info identifiers must match every other ASP Parking entity."""
    from custom_components.asp_parking.const import DOMAIN

    coord = _make_coordinator()
    s = ASPIndexLastRebuiltSensor(coord)
    info = s.device_info
    assert info["identifiers"] == {(DOMAIN, "test_entry_33")}
    assert info["name"] == "ASP Parking Monitor"
