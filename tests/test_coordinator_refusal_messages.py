"""Spike 011: the two refusal paths must tell the truth, and nothing else may change.

The resolver raises two distinct refusals: ``NoSegmentFoundError`` (there is no
candidate segment at all) and ``AmbiguousResolutionError`` (the segment is
certain, the curb side is not — the fix sits near the centre of the roadway).
The coordinator used to catch both in one ``except`` branch and log *"No street
segment found"* for both. In the user's Aug 28 – Sep 4 logs **all 16 refusals
were ``AmbiguousResolutionError``** with the segment known perfectly well,
including a two-day park on the user's own home block.

These tests pin two things:

1. **The message.** An Ambiguous refusal must name the street and say the curb
   side is undetermined; a NoSegment refusal must keep its existing actionable
   "No street segment found" text verbatim.
2. **That nothing else changed.** The refusal is KEPT (user decision
   2026-09-12 — no degraded both-curbs schedule mode) and the availability
   contract is byte-identical for both paths: ``special_state`` stays
   ``"no_street_match"``, ``_last_pipeline_error`` is cleared, ``last_error`` is
   None, and the last ``schedule_result`` is retained.

Tests 4 and 5 additionally pin the defensive message construction (T-tt5-02):
``ResolutionDebugInfo.candidates`` may be empty and
``perpendicular_distance_ft`` / ``street_width_ft`` are ``float | None``, so a
formatting error must never escalate a clean refusal into the broad-``Exception``
branch (which would set ``_last_pipeline_error = True`` and make every entity
unavailable).
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.asp_parking.const import CONF_DEVICE_TRACKER
from custom_components.asp_parking.coordinator import ASPParkingCoordinator
from custom_components.asp_parking.gps2asp.resolver.exceptions import (
    AmbiguousResolutionError,
    NoSegmentFoundError,
)
from custom_components.asp_parking.gps2asp.resolver.models import ResolutionDebugInfo

COORDINATOR_LOGGER = "custom_components.asp_parking.coordinator"

FIX_LAT = 40.6778
FIX_LON = -73.9690


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def make_coordinator():
    """Build a minimally wired coordinator with a MagicMock hass + entry.

    Mirrors tests/test_coordinator_borough_fields.py lines 44-72 (itself a copy
    of tests/test_coordinator_cache.py). The fixture is deliberately file-local
    rather than in tests/conftest.py — that is the established pattern in this
    repo for coordinator tests that bypass async_start and drive
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


def _make_ambiguous_error(
    *,
    candidates: list[dict] | None = None,
    selected_segment_id: int | None = 39224,
    perpendicular_distance_ft: float | None = 21.3,
    street_width_ft: float | None = 58.0,
    confidence: float = 0.12,
) -> AmbiguousResolutionError:
    """Build a REAL ResolutionDebugInfo + AmbiguousResolutionError.

    Using the real frozen dataclass (not a MagicMock) means attribute access in
    the coordinator's handler behaves exactly as it does in production — a
    MagicMock would happily answer any attribute and hide a typo.
    """
    debug_info = ResolutionDebugInfo(
        input_lat=FIX_LAT,
        input_lon=FIX_LON,
        state_plane_x=992400.0,
        state_plane_y=186300.0,
        candidates=[] if candidates is None else candidates,
        selected_segment_id=selected_segment_id,
        perpendicular_distance_ft=perpendicular_distance_ft,
        confidence=confidence,
        side=None,
        outcome="ambiguous_centerline",
        street_width_ft=street_width_ft,
    )
    return AmbiguousResolutionError(
        message=(
            f"Resolution confidence {confidence:.2f} is below threshold 0.33 "
            f"for segment PROSPECT PL"
        ),
        debug_info=debug_info,
        confidence=confidence,
    )


async def _drive_pipeline(coord, err, caplog):
    """Run _async_resolve_pipeline with `resolve` raising `err`, capturing WARNINGs."""
    coord._pending_lat = FIX_LAT
    coord._pending_lon = FIX_LON

    with caplog.at_level(logging.WARNING, logger=COORDINATOR_LOGGER):
        with patch(
            "custom_components.asp_parking.coordinator.resolve",
            new=AsyncMock(side_effect=err),
        ):
            await coord._async_resolve_pipeline()


# ---------------------------------------------------------------------------
# Test 1: the Ambiguous message names the street and the real problem
# ---------------------------------------------------------------------------


async def test_ambiguous_logs_found_street_and_curb_side_undetermined(
    make_coordinator, caplog
):
    """An Ambiguous refusal must NOT claim the segment was not found.

    The segment is certain; only the curb side is undetermined. The log must
    name the street and report the geometry that caused the refusal.
    """
    coord, _hass, _entry = make_coordinator()
    err = _make_ambiguous_error(
        candidates=[
            {"segment_id": 39224, "street": "PROSPECT PL", "distance_ft": 21.3}
        ],
        selected_segment_id=39224,
        perpendicular_distance_ft=21.3,
        street_width_ft=58.0,
    )

    await _drive_pipeline(coord, err, caplog)

    text = caplog.text
    assert "could not determine the curb side" in text, (
        "Ambiguous refusal must say the curb side is undetermined; got:\n" + text
    )
    assert "PROSPECT PL" in text, (
        "Ambiguous refusal must name the street it DID find; got:\n" + text
    )
    assert "21.3" in text, "Ambiguous refusal must report the perpendicular distance"
    assert "58" in text, "Ambiguous refusal must report the street width"
    assert "No street segment found" not in text, (
        "The segment WAS found — this is the misleading message spike 011 removes"
    )


# ---------------------------------------------------------------------------
# Test 2: availability semantics are byte-identical to a plain miss
# ---------------------------------------------------------------------------


async def test_ambiguous_preserves_availability_semantics(make_coordinator, caplog):
    """Only the MESSAGE changes — entity state stays exactly as it was.

    User decision 2026-09-12: keep the refusal, no degraded both-curbs schedule
    mode. The pipeline ran cleanly, so the health flag must be cleared and the
    last known schedule retained.
    """
    coord, _hass, _entry = make_coordinator()

    sentinel_schedule = object()
    coord.data.schedule_result = sentinel_schedule
    # Prime stale diagnostics from a prior successful resolution.
    coord.data.borough = "Brooklyn"
    coord.data.distance_ft = 12.34
    coord.data.street_width_ft = 30.0
    coord.data.segment_id = 987654
    coord.data.soda_level = 2
    coord.data.last_error = "a stale transient error"
    coord._last_pipeline_error = True

    await _drive_pipeline(coord, _make_ambiguous_error(), caplog)

    assert coord.data.special_state == "no_street_match", (
        "No new special_state value may be introduced (it would ripple into "
        "sensor availability and binary sensors)"
    )
    assert coord.data.last_error is None
    assert coord.data.last_error_time is None
    assert coord._last_pipeline_error is False, (
        "A refusal is a CLEAN pipeline outcome — the health flag must be cleared "
        "or entities go permanently unavailable"
    )
    assert coord.data.soda_level == 0
    assert coord.data.borough is None
    assert coord.data.distance_ft is None
    assert coord.data.street_width_ft is None
    assert coord.data.segment_id is None
    assert coord.data.last_lat == FIX_LAT
    assert coord.data.last_lon == FIX_LON
    assert coord.data.schedule_result is sentinel_schedule, (
        "The last schedule_result is retained per user decision — the refusal "
        "handler must not touch it"
    )


# ---------------------------------------------------------------------------
# Test 3: the NoSegmentFound message is unchanged
# ---------------------------------------------------------------------------


async def test_no_segment_found_still_logs_no_street_segment_found(
    make_coordinator, caplog
):
    """A genuine miss keeps its existing actionable message verbatim."""
    coord, _hass, _entry = make_coordinator()

    await _drive_pipeline(
        coord, NoSegmentFoundError(987654.0, 178432.0, 164.0), caplog
    )

    text = caplog.text
    assert "No street segment found" in text, (
        "A genuine miss must keep the existing actionable message; got:\n" + text
    )
    assert "could not determine the curb side" not in text, (
        "The Ambiguous wording must not leak into the no-segment path"
    )
    assert coord.data.special_state == "no_street_match"
    assert coord._last_pipeline_error is False


# ---------------------------------------------------------------------------
# Test 4: empty candidates -> fall back to the segment id (T-tt5-02)
# ---------------------------------------------------------------------------


async def test_ambiguous_with_empty_candidates_falls_back_to_segment_id(
    make_coordinator, caplog
):
    """`candidates` may legitimately be empty — the label falls back to the id.

    A raise from inside the exception handler would escalate a clean refusal
    into the broad-`Exception` branch and make every entity unavailable.
    """
    coord, _hass, _entry = make_coordinator()
    err = _make_ambiguous_error(candidates=[], selected_segment_id=39224)

    # Must not propagate.
    await _drive_pipeline(coord, err, caplog)

    assert "39224" in caplog.text, (
        "With no candidate summaries the selected segment id is the fallback "
        "label; got:\n" + caplog.text
    )
    assert coord.data.special_state == "no_street_match"


# ---------------------------------------------------------------------------
# Test 5: every optional geometry field None -> still a clean refusal (T-tt5-02)
# ---------------------------------------------------------------------------


async def test_ambiguous_with_missing_geometry_fields_does_not_crash(
    make_coordinator, caplog
):
    """`perpendicular_distance_ft` / `street_width_ft` are `float | None`.

    A `%.1f` applied to None would raise TypeError inside the handler. The
    values must be pre-formatted defensively and interpolated with `%s`.
    """
    coord, _hass, _entry = make_coordinator()
    err = _make_ambiguous_error(
        candidates=[],
        selected_segment_id=None,
        perpendicular_distance_ft=None,
        street_width_ft=None,
    )

    # Must not raise TypeError/ValueError out of _async_resolve_pipeline.
    await _drive_pipeline(coord, err, caplog)

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "A refusal must still emit a WARNING even with no geometry detail"
    assert coord.data.special_state == "no_street_match"
    assert coord._last_pipeline_error is False, (
        "A formatting failure must never escalate a clean refusal into the "
        "broad-Exception branch"
    )
