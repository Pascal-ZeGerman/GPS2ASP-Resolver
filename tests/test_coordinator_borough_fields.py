"""Unit tests for Phase 30 Plan 03: coordinator borough mapping and diagnostic fields.

Verifies:
  - Module-level _BOROUGH_NAMES constant maps CSCL borocode (str) to
    human-readable borough name (D-12).
  - ASPParkingData has 4 new optional diagnostic fields with None defaults
    (D-10): borough, distance_ft, street_width_ft, segment_id.
  - Coordinator success branch populates all 4 fields from the
    ResolutionResult, using the borocode-to-name mapping for `borough` (D-09,
    D-11).
  - Unmapped or None borocode yields `borough=None` while keeping the
    remaining 3 fields populated correctly (D-11 None-safe coalesce).
  - Both error branches (OutsideNYCError, NoSegmentFoundError /
    AmbiguousResolutionError) reset all 4 new fields to None to avoid stale
    data leaking across resolutions (D-09, mirrors existing soda_level reset).
"""

from __future__ import annotations

import dataclasses
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.asp_parking.coordinator import (
    ASPParkingCoordinator,
    ASPParkingData,
    _BOROUGH_NAMES,
)
from custom_components.asp_parking.const import CONF_DEVICE_TRACKER
from custom_components.asp_parking.gps2asp.resolver.exceptions import (
    NoSegmentFoundError,
    OutsideNYCError,
)
from custom_components.asp_parking.gps2asp.resolver.models import ResolutionResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def make_coordinator():
    """Build a minimally wired coordinator with a MagicMock hass + entry.

    Mirrors the pattern from tests/test_coordinator_cache.py — no real HA
    harness is required because the tests bypass async_start and exercise
    _async_resolve_pipeline directly with patched dependencies.
    """

    def _make(options: dict | None = None):
        hass = MagicMock()
        entry = MagicMock()
        entry.data = {CONF_DEVICE_TRACKER: "device_tracker.car"}
        entry.options = options or {}

        def _close_coro_and_return_task(_hass, coro, name=None):
            try:
                coro.close()
            except Exception:  # noqa: BLE001
                pass
            t = MagicMock()
            t.name = name
            return t

        entry.async_create_background_task = MagicMock(
            side_effect=_close_coro_and_return_task
        )
        return ASPParkingCoordinator(hass, entry), hass, entry

    return _make


def _make_resolution(
    *,
    on_street: str = "PROSPECT PL",
    from_street: str = "VANDERBILT AVE",
    to_street: str = "UNDERHILL AVE",
    side_of_street: str = "N",
    confidence: float = 0.85,
    has_asp: bool = True,
    borocode: str | None = "3",
    perpendicular_distance_ft: float | None = 12.34,
    street_width_ft: float | None = 30.0,
    segment_id: int | None = 987654,
) -> ResolutionResult:
    """Construct a real ResolutionResult so that frozen-dataclass attribute
    access in the coordinator behaves identically to production."""
    return ResolutionResult(
        on_street=on_street,
        from_street=from_street,
        to_street=to_street,
        side_of_street=side_of_street,
        confidence=confidence,
        has_asp=has_asp,
        borocode=borocode,
        perpendicular_distance_ft=perpendicular_distance_ft,
        street_width_ft=street_width_ft,
        segment_id=segment_id,
    )


def _make_sign_result():
    """Build a benign sign result that satisfies isinstance(SignRetrievalSuccess)
    checks via patching at the call site."""
    sign_result = MagicMock()
    sign_result.signs = []
    sign_result.soda_level = 1
    return sign_result


def _make_schedule():
    """Build a benign schedule that satisfies the success-branch isinstance
    checks (ScheduleFound/AllUnparseable for parse_failures access)."""
    schedule = MagicMock()
    schedule.status = "schedule_found"
    schedule.parse_failures = []
    schedule.next_window = None
    return schedule


# ---------------------------------------------------------------------------
# Test 1: _BOROUGH_NAMES module-level constant
# ---------------------------------------------------------------------------


def test_borough_names_constant_exists():
    """D-12: _BOROUGH_NAMES maps the 5 CSCL borocodes (str keys) to human names."""
    assert _BOROUGH_NAMES == {
        "1": "Manhattan",
        "2": "Bronx",
        "3": "Brooklyn",
        "4": "Queens",
        "5": "Staten Island",
    }
    assert all(isinstance(k, str) for k in _BOROUGH_NAMES), (
        "Keys must be str (matching CSCL borocode type) — not int."
    )
    assert all(isinstance(v, str) for v in _BOROUGH_NAMES.values())


# ---------------------------------------------------------------------------
# Test 2: ASPParkingData has 4 new fields with None defaults
# ---------------------------------------------------------------------------


def test_asp_parking_data_has_new_fields():
    """D-10: ASPParkingData gets 4 new optional fields with None defaults."""
    data = ASPParkingData()
    assert data.borough is None
    assert data.distance_ft is None
    assert data.street_width_ft is None
    assert data.segment_id is None

    field_names = {f.name for f in dataclasses.fields(ASPParkingData)}
    for new_field in ("borough", "distance_ft", "street_width_ft", "segment_id"):
        assert new_field in field_names, (
            f"ASPParkingData must declare `{new_field}` as a dataclass field (D-10)."
        )


# ---------------------------------------------------------------------------
# Test 3: Success branch populates borough = "Brooklyn" for borocode="3"
# ---------------------------------------------------------------------------


async def test_resolve_pipeline_success_populates_borough_brooklyn(make_coordinator):
    """D-09, D-11: Success branch maps borocode='3' to borough='Brooklyn' and
    populates the other 3 diagnostic fields straight off resolution."""
    coord, _hass, _entry = make_coordinator()
    coord._pending_lat = 40.6778
    coord._pending_lon = -73.9690

    resolution = _make_resolution(
        borocode="3",
        perpendicular_distance_ft=12.34,
        street_width_ft=30.0,
        segment_id=987654,
    )

    with (
        patch(
            "custom_components.asp_parking.coordinator.resolve",
            new=AsyncMock(return_value=resolution),
        ),
        patch(
            "custom_components.asp_parking.coordinator.retrieve_signs",
            new=AsyncMock(return_value=_make_sign_result()),
        ),
        patch(
            "custom_components.asp_parking.coordinator.compute_schedule",
            return_value=_make_schedule(),
        ),
        patch.object(
            ASPParkingCoordinator,
            "_async_maybe_send_notification",
            new=AsyncMock(),
        ),
    ):
        await coord._async_resolve_pipeline()

    assert coord.data.borough == "Brooklyn"
    assert coord.data.distance_ft == 12.34
    assert coord.data.street_width_ft == 30.0
    assert coord.data.segment_id == 987654


# ---------------------------------------------------------------------------
# Test 4: Success branch populates borough = "Manhattan" for borocode="1"
# ---------------------------------------------------------------------------


async def test_resolve_pipeline_success_populates_borough_manhattan(make_coordinator):
    """D-11: Mapping covers Manhattan (borocode='1') as well as Brooklyn."""
    coord, _hass, _entry = make_coordinator()
    coord._pending_lat = 40.7831
    coord._pending_lon = -73.9712

    resolution = _make_resolution(
        on_street="WEST 86 STREET",
        from_street="WEST END AVENUE",
        to_street="BROADWAY",
        side_of_street="N",
        borocode="1",
        perpendicular_distance_ft=8.5,
        street_width_ft=34.0,
        segment_id=123456,
    )

    with (
        patch(
            "custom_components.asp_parking.coordinator.resolve",
            new=AsyncMock(return_value=resolution),
        ),
        patch(
            "custom_components.asp_parking.coordinator.retrieve_signs",
            new=AsyncMock(return_value=_make_sign_result()),
        ),
        patch(
            "custom_components.asp_parking.coordinator.compute_schedule",
            return_value=_make_schedule(),
        ),
        patch.object(
            ASPParkingCoordinator,
            "_async_maybe_send_notification",
            new=AsyncMock(),
        ),
    ):
        await coord._async_resolve_pipeline()

    assert coord.data.borough == "Manhattan"
    assert coord.data.distance_ft == 8.5
    assert coord.data.street_width_ft == 34.0
    assert coord.data.segment_id == 123456


# ---------------------------------------------------------------------------
# Test 5: Unmapped borocode yields None borough but keeps other fields
# ---------------------------------------------------------------------------


async def test_resolve_pipeline_unmapped_borocode_yields_none_borough(make_coordinator):
    """D-11: Unmapped borocode (e.g. '99') leaves borough=None while the other
    3 diagnostic fields remain populated."""
    coord, _hass, _entry = make_coordinator()
    coord._pending_lat = 40.6778
    coord._pending_lon = -73.9690

    resolution = _make_resolution(
        borocode="99",  # not in the 1-5 mapping
        perpendicular_distance_ft=12.34,
        street_width_ft=30.0,
        segment_id=987654,
    )

    with (
        patch(
            "custom_components.asp_parking.coordinator.resolve",
            new=AsyncMock(return_value=resolution),
        ),
        patch(
            "custom_components.asp_parking.coordinator.retrieve_signs",
            new=AsyncMock(return_value=_make_sign_result()),
        ),
        patch(
            "custom_components.asp_parking.coordinator.compute_schedule",
            return_value=_make_schedule(),
        ),
        patch.object(
            ASPParkingCoordinator,
            "_async_maybe_send_notification",
            new=AsyncMock(),
        ),
    ):
        await coord._async_resolve_pipeline()

    assert coord.data.borough is None
    assert coord.data.distance_ft == 12.34
    assert coord.data.street_width_ft == 30.0
    assert coord.data.segment_id == 987654


# ---------------------------------------------------------------------------
# Test 6: None borocode yields None borough (guards `or ""` coalesce)
# ---------------------------------------------------------------------------


async def test_resolve_pipeline_none_borocode_yields_none_borough(make_coordinator):
    """D-11: borocode=None must coalesce safely to borough=None — guards
    `_BOROUGH_NAMES.get(resolution.borocode or "")` from a TypeError on None."""
    coord, _hass, _entry = make_coordinator()
    coord._pending_lat = 40.6778
    coord._pending_lon = -73.9690

    resolution = _make_resolution(
        borocode=None,
        perpendicular_distance_ft=None,
        street_width_ft=None,
        segment_id=None,
    )

    with (
        patch(
            "custom_components.asp_parking.coordinator.resolve",
            new=AsyncMock(return_value=resolution),
        ),
        patch(
            "custom_components.asp_parking.coordinator.retrieve_signs",
            new=AsyncMock(return_value=_make_sign_result()),
        ),
        patch(
            "custom_components.asp_parking.coordinator.compute_schedule",
            return_value=_make_schedule(),
        ),
        patch.object(
            ASPParkingCoordinator,
            "_async_maybe_send_notification",
            new=AsyncMock(),
        ),
    ):
        await coord._async_resolve_pipeline()

    assert coord.data.borough is None
    assert coord.data.distance_ft is None
    assert coord.data.street_width_ft is None
    assert coord.data.segment_id is None


# ---------------------------------------------------------------------------
# Test 7: OutsideNYCError resets all 4 new fields
# ---------------------------------------------------------------------------


async def test_outside_nyc_error_resets_new_fields(make_coordinator):
    """D-09: OutsideNYCError handler resets all 4 new fields to None to avoid
    stale data leaking across resolutions (mirrors existing soda_level=0 reset)."""
    coord, _hass, _entry = make_coordinator()

    # Prime stale data from a prior successful resolution
    coord.data.borough = "Brooklyn"
    coord.data.distance_ft = 12.34
    coord.data.street_width_ft = 30.0
    coord.data.segment_id = 987654

    coord._pending_lat = 51.5074  # London — outside NYC
    coord._pending_lon = -0.1278

    with patch(
        "custom_components.asp_parking.coordinator.resolve",
        new=AsyncMock(side_effect=OutsideNYCError(51.5074, -0.1278)),
    ):
        await coord._async_resolve_pipeline()

    assert coord.data.special_state == "outside_coverage"
    assert coord.data.borough is None
    assert coord.data.distance_ft is None
    assert coord.data.street_width_ft is None
    assert coord.data.segment_id is None


# ---------------------------------------------------------------------------
# Test 8: NoSegmentFoundError resets all 4 new fields
# ---------------------------------------------------------------------------


async def test_no_segment_found_error_resets_new_fields(make_coordinator):
    """D-09: NoSegmentFoundError handler resets all 4 new fields to None."""
    coord, _hass, _entry = make_coordinator()

    # Prime stale data from a prior successful resolution
    coord.data.borough = "Brooklyn"
    coord.data.distance_ft = 12.34
    coord.data.street_width_ft = 30.0
    coord.data.segment_id = 987654

    coord._pending_lat = 40.6778
    coord._pending_lon = -73.9690

    with patch(
        "custom_components.asp_parking.coordinator.resolve",
        new=AsyncMock(side_effect=NoSegmentFoundError(987654.0, 178432.0, 164.0)),
    ):
        await coord._async_resolve_pipeline()

    assert coord.data.special_state == "no_street_match"
    assert coord.data.borough is None
    assert coord.data.distance_ft is None
    assert coord.data.street_width_ft is None
    assert coord.data.segment_id is None
