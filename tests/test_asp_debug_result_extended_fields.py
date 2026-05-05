"""Failing tests for ASPDebugResult extended diagnostic fields — TDD RED phase (Plan 30-02).

These tests specify the contract that ASPDebugResult must satisfy after Plan 30-02:

    - 4 new top-level fields exposed on ASPDebugResult (separate from the nested
      `resolution` field): borocode, perpendicular_distance_ft, street_width_ft,
      segment_id (per D-07).
    - ASPDebugResult.from_resolution() reads these fields directly off the
      ResolutionResult argument and threads them onto the result (D-07).
    - ASPDebugResult.from_error() sets all four to None (D-04).
    - ASPResult (the lean variant) does NOT gain these fields — they are
      debug-only (D-08).
    - The vendored mirror under custom_components/asp_parking/gps2asp/api_models.py
      is byte-identical and exposes the same four new fields (D-15).

After Plan 01 (already merged), ResolutionResult already exposes the four new
optional fields with None defaults. This plan only changes api_models.py
(both copies).
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, time as dtime

from custom_components.asp_parking.gps2asp.api_models import (
    ASPDebugResult as MirrorADR,
)
from gps2asp.api_models import ASPDebugResult, ASPResult
from gps2asp.resolver.models import ResolutionResult
from gps2asp.schedule.models import (
    ASPDay,
    CleaningWindow,
    ScheduleFound,
    TimeWindow,
    WeeklySchedule,
)
from gps2asp.signs.models import SignRecord, SignRetrievalSuccess


# ---------------------------------------------------------------------------
# Local fixture builders (deliberately reproduced to avoid coupling
# this module to test_resolve_asp.py — same pattern as Plan 30-01's
# tests/test_resolver_extended_fields.py).
# ---------------------------------------------------------------------------


def _make_resolution_result(
    *,
    borocode: str | None = "3",
    perpendicular_distance_ft: float | None = 12.34,
    street_width_ft: float | None = 30.0,
    segment_id: int | None = 987654,
) -> ResolutionResult:
    """Build a ResolutionResult with all 4 new diagnostic fields populated by default."""
    return ResolutionResult(
        on_street="PROSPECT PL",
        from_street="VANDERBILT AVE",
        to_street="CARLTON AVE",
        side_of_street="N",
        confidence=0.85,
        has_asp=True,
        borocode=borocode,
        perpendicular_distance_ft=perpendicular_distance_ft,
        street_width_ft=street_width_ft,
        segment_id=segment_id,
    )


def _make_sign_success(soda_level: int = 1) -> SignRetrievalSuccess:
    return SignRetrievalSuccess(
        status="signs_found",
        signs=[SignRecord(sign_description="NO PARKING MON & THURS 8-9:30AM")],
        on_street="PROSPECT PL",
        from_street="VANDERBILT AVE",
        to_street="CARLTON AVE",
        side_of_street="N",
        soda_level=soda_level,
    )


def _make_schedule_found() -> ScheduleFound:
    window = TimeWindow(
        day=ASPDay.MONDAY,
        start_time=dtime(8, 0),
        end_time=dtime(9, 30),
        source_sign="NO PARKING MON & THURS 8-9:30AM",
    )
    cleaning = CleaningWindow(
        day=ASPDay.MONDAY,
        start_time=dtime(8, 0),
        end_time=dtime(9, 30),
        start_datetime=datetime(2026, 3, 2, 8, 0),
        end_datetime=datetime(2026, 3, 2, 9, 30),
        source_signs=["NO PARKING MON & THURS 8-9:30AM"],
    )
    return ScheduleFound(
        status="schedule_found",
        next_window=cleaning,
        weekly_schedule=WeeklySchedule(windows=(window,)),
        on_street="PROSPECT PL",
        from_street="VANDERBILT AVE",
        to_street="CARLTON AVE",
        side_of_street="N",
        source_signs=["NO PARKING MON & THURS 8-9:30AM"],
        summary="MON & THURS 8:00–9:30 AM",
        parse_failures=[],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_aspdebugresult_has_new_top_level_fields() -> None:
    """Test 1: ASPDebugResult exposes the four new fields as top-level attributes (D-07)."""
    rr = _make_resolution_result()
    sign_result = _make_sign_success(soda_level=1)
    schedule = _make_schedule_found()

    debug = ASPDebugResult(
        schedule=schedule,
        resolution_failed=False,
        resolution_error=None,
        on_street="PROSPECT PL",
        from_street="VANDERBILT AVE",
        to_street="CARLTON AVE",
        side_of_street="N",
        resolution=rr,
        sign_result=sign_result,
        confidence=0.85,
        state_plane_x=987654.0,
        state_plane_y=178432.0,
        soda_level=1,
        borocode="3",
        perpendicular_distance_ft=12.34,
        street_width_ft=30.0,
        segment_id=987654,
    )

    assert debug.borocode == "3"
    assert debug.perpendicular_distance_ft == 12.34
    assert debug.street_width_ft == 30.0
    assert debug.segment_id == 987654


def test_from_resolution_threads_new_fields() -> None:
    """Test 2: from_resolution reads all 4 new fields off the ResolutionResult argument (D-07)."""
    rr = _make_resolution_result(
        borocode="3",
        perpendicular_distance_ft=12.34,
        street_width_ft=30.0,
        segment_id=987654,
    )
    sign_result = _make_sign_success(soda_level=1)
    schedule = _make_schedule_found()

    debug = ASPDebugResult.from_resolution(
        resolution=rr,
        sign_result=sign_result,
        schedule=schedule,
        state_plane_x=987654.0,
        state_plane_y=178432.0,
        soda_level=1,
    )

    assert debug.borocode == rr.borocode == "3"
    assert debug.perpendicular_distance_ft == rr.perpendicular_distance_ft == 12.34
    assert debug.street_width_ft == rr.street_width_ft == 30.0
    assert debug.segment_id == rr.segment_id == 987654


def test_from_resolution_threads_none_when_resolution_has_none() -> None:
    """Test 3: from_resolution forwards None values intact when the ResolutionResult fields are None (D-04)."""
    rr = _make_resolution_result(
        borocode=None,
        perpendicular_distance_ft=None,
        street_width_ft=None,
        segment_id=None,
    )
    sign_result = _make_sign_success(soda_level=2)
    schedule = _make_schedule_found()

    debug = ASPDebugResult.from_resolution(
        resolution=rr,
        sign_result=sign_result,
        schedule=schedule,
        state_plane_x=1.0,
        state_plane_y=2.0,
        soda_level=2,
    )

    assert debug.borocode is None
    assert debug.perpendicular_distance_ft is None
    assert debug.street_width_ft is None
    assert debug.segment_id is None


def test_from_error_sets_new_fields_to_none() -> None:
    """Test 4: from_error sets all 4 new fields to None on the resolution-failure path (D-07)."""
    debug = ASPDebugResult.from_error(
        error="resolution failed",
        state_plane_x=0.0,
        state_plane_y=0.0,
    )

    assert debug.borocode is None
    assert debug.perpendicular_distance_ft is None
    assert debug.street_width_ft is None
    assert debug.segment_id is None


def test_aspresult_does_not_gain_new_fields() -> None:
    """Test 5: ASPResult (lean variant) does NOT gain the diagnostic fields (D-08)."""
    field_names = {f.name for f in dataclasses.fields(ASPResult)}

    assert "borocode" not in field_names
    assert "perpendicular_distance_ft" not in field_names
    assert "street_width_ft" not in field_names
    assert "segment_id" not in field_names

    # Confirm ASPResult still has exactly its original 4 fields.
    assert field_names == {
        "schedule",
        "resolution_failed",
        "resolution_error",
        "soda_level",
    }


def test_vendored_mirror_aspdebugresult_has_new_fields() -> None:
    """Test 6: vendored mirror exposes all 4 new fields with the same names (D-15)."""
    field_names = {f.name for f in dataclasses.fields(MirrorADR)}

    assert "borocode" in field_names
    assert "perpendicular_distance_ft" in field_names
    assert "street_width_ft" in field_names
    assert "segment_id" in field_names
