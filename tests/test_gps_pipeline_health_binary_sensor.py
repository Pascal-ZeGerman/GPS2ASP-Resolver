"""Unit tests for ASPGpsPipelineHealthBinarySensor.

These tests cover the GPS pipeline health binary sensor contract:
  - unique_id format ``{entry_id}_gps_pipeline_healthy``
  - translation_key == "gps_pipeline_healthy"
  - icon == "mdi:signal"
  - has_entity_name is True
  - entity_category == EntityCategory.DIAGNOSTIC
  - is_on logic: recent GPS + no pipeline error -> True; stale/None/error -> False
  - is_on is LIVE (reads coordinator attributes at call time)
  - extra_state_attributes exposes "last_pipeline_error" key
  - device_info groups with the rest of the ASP Parking entities

Structure mirrors tests/test_index_rebuilding_binary_sensor.py
(SimpleNamespace + MagicMock pattern; no HA test harness required).
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from homeassistant.helpers.entity import EntityCategory

from custom_components.asp_parking.binary_sensor import (
    ASPGpsPipelineHealthBinarySensor,
)


def _make_coordinator(
    last_gps_update: datetime.datetime | None = None,
    stale_timeout: int = 24,
    _last_pipeline_error: bool = False,
):
    """Build a minimal coordinator stub matching the binary sensor's contract.

    Args:
        last_gps_update: UTC-aware datetime of last GPS event, or None.
        stale_timeout: Hours after which GPS is considered stale (default 24).
        _last_pipeline_error: Simulates a pipeline error flag.
    """
    entry = SimpleNamespace(entry_id="test_entry_feq")
    data = SimpleNamespace(last_gps_update=last_gps_update)
    coord = SimpleNamespace(
        entry=entry,
        data=data,
        stale_timeout=stale_timeout,
        _last_pipeline_error=_last_pipeline_error,
        async_add_update_callback=MagicMock(),
        async_remove_update_callback=MagicMock(),
    )
    return coord


# ---------------------------------------------------------------------------
# Identity / metadata
# ---------------------------------------------------------------------------


def test_unique_id_pattern():
    """Binary sensor unique_id must follow f"{entry_id}_gps_pipeline_healthy"."""
    coord = _make_coordinator()
    bs = ASPGpsPipelineHealthBinarySensor(coord)
    assert bs.unique_id == "test_entry_feq_gps_pipeline_healthy"


def test_translation_key_and_icon():
    """Binary sensor must expose translation_key='gps_pipeline_healthy' and mdi:signal."""
    coord = _make_coordinator()
    bs = ASPGpsPipelineHealthBinarySensor(coord)
    assert bs.translation_key == "gps_pipeline_healthy"
    assert bs.icon == "mdi:signal"


def test_has_entity_name_attribute():
    """has_entity_name must be True for the translation_key to be picked up."""
    coord = _make_coordinator()
    bs = ASPGpsPipelineHealthBinarySensor(coord)
    assert bs.has_entity_name is True


def test_entity_category_is_diagnostic():
    """Diagnostic category groups this with debug-only entities in the UI."""
    coord = _make_coordinator()
    bs = ASPGpsPipelineHealthBinarySensor(coord)
    assert bs.entity_category == EntityCategory.DIAGNOSTIC


# ---------------------------------------------------------------------------
# is_on logic
# ---------------------------------------------------------------------------


def test_is_on_false_when_no_gps():
    """is_on must be False when last_gps_update is None (no GPS fix yet)."""
    coord = _make_coordinator(last_gps_update=None)
    bs = ASPGpsPipelineHealthBinarySensor(coord)
    assert bs.is_on is False


def test_is_on_false_when_stale():
    """is_on must be False when GPS age >= stale_timeout * 3600 seconds."""
    stale_ts = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=25)
    coord = _make_coordinator(last_gps_update=stale_ts, stale_timeout=24, _last_pipeline_error=False)
    bs = ASPGpsPipelineHealthBinarySensor(coord)
    assert bs.is_on is False


def test_is_on_true_when_recent_no_error():
    """is_on must be True when GPS is recent and _last_pipeline_error is False."""
    recent_ts = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)
    coord = _make_coordinator(last_gps_update=recent_ts, stale_timeout=24, _last_pipeline_error=False)
    bs = ASPGpsPipelineHealthBinarySensor(coord)
    assert bs.is_on is True


def test_is_on_false_when_pipeline_error():
    """is_on must be False when _last_pipeline_error is True, even with recent GPS."""
    recent_ts = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)
    coord = _make_coordinator(last_gps_update=recent_ts, stale_timeout=24, _last_pipeline_error=True)
    bs = ASPGpsPipelineHealthBinarySensor(coord)
    assert bs.is_on is False


def test_is_on_flips_live():
    """is_on is a LIVE property — mutating _last_pipeline_error on the stub is observable."""
    recent_ts = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)
    coord = _make_coordinator(last_gps_update=recent_ts, stale_timeout=24, _last_pipeline_error=False)
    bs = ASPGpsPipelineHealthBinarySensor(coord)
    assert bs.is_on is True

    coord._last_pipeline_error = True
    assert bs.is_on is False

    coord._last_pipeline_error = False
    assert bs.is_on is True


# ---------------------------------------------------------------------------
# extra_state_attributes
# ---------------------------------------------------------------------------


def test_extra_state_attributes_exposes_pipeline_error():
    """extra_state_attributes must include 'last_pipeline_error' bool key."""
    recent_ts = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)

    coord_ok = _make_coordinator(last_gps_update=recent_ts, _last_pipeline_error=False)
    bs_ok = ASPGpsPipelineHealthBinarySensor(coord_ok)
    attrs_ok = bs_ok.extra_state_attributes
    assert "last_pipeline_error" in attrs_ok
    assert attrs_ok["last_pipeline_error"] is False

    coord_err = _make_coordinator(last_gps_update=recent_ts, _last_pipeline_error=True)
    bs_err = ASPGpsPipelineHealthBinarySensor(coord_err)
    attrs_err = bs_err.extra_state_attributes
    assert attrs_err["last_pipeline_error"] is True


# ---------------------------------------------------------------------------
# device_info
# ---------------------------------------------------------------------------


def test_device_info_groups_with_other_entities():
    """device_info identifiers must match every other ASP Parking entity."""
    from custom_components.asp_parking.const import DOMAIN

    coord = _make_coordinator()
    bs = ASPGpsPipelineHealthBinarySensor(coord)
    info = bs.device_info
    assert info["identifiers"] == {(DOMAIN, "test_entry_feq")}
    assert info["name"] == "ASP Parking Monitor"
