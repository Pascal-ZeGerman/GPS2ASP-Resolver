"""Failing tests for resolve_asp() — TDD RED phase (Plan 07-01).

These tests specify the exact contract resolve_asp() must satisfy.
They fail at import because resolve_asp does not yet exist in gps2asp.__init__.
Plan 07-02 makes them pass by implementing resolve_asp().

Test coverage:
    1. Return type narrowing: debug=False → ASPResult, debug=True → ASPDebugResult
    2. AmbiguousResolutionError is caught and surfaced as structured fields
    3. OutsideNYCError is NOT caught — propagates to caller
    4. Successful pipeline result with mocked pipeline stages
    5. soda_level=0 when retrieve_signs returns NoMatchFound
"""

from __future__ import annotations

from datetime import time as dtime, datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from gps2asp import resolve_asp
from gps2asp.api_models import ASPDebugResult, ASPResult
from gps2asp.resolver.exceptions import AmbiguousResolutionError, OutsideNYCError
from gps2asp.resolver.models import ResolutionResult, ResolutionDebugInfo
from gps2asp.signs.models import NoMatchFound, SignRecord, SignRetrievalSuccess
from gps2asp.schedule.models import (
    ASPDay,
    CleaningWindow,
    ScheduleFound,
    TimeWindow,
    WeeklySchedule,
)
from gps2asp.suspension import SuspensionInfo

NYC_TZ = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_resolution_result(confidence: float = 0.85) -> ResolutionResult:
    """Build a minimal ResolutionResult for use in tests."""
    return ResolutionResult(
        on_street="PROSPECT PL",
        from_street="VANDERBILT AVE",
        to_street="CARLTON AVE",
        side_of_street="N",
        confidence=confidence,
        has_asp=True,
    )


def _make_sign_success(soda_level: int = 1) -> SignRetrievalSuccess:
    """Build a minimal SignRetrievalSuccess for use in tests."""
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
    """Build a minimal ScheduleFound for use in tests."""
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
        start_datetime=datetime(2026, 3, 2, 8, 0, tzinfo=NYC_TZ),
        end_datetime=datetime(2026, 3, 2, 9, 30, tzinfo=NYC_TZ),
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


def _make_debug_info(x: float = 987654.0, y: float = 178432.0) -> ResolutionDebugInfo:
    """Build a minimal ResolutionDebugInfo for use in tests."""
    return ResolutionDebugInfo(
        input_lat=40.677629,
        input_lon=-73.968527,
        state_plane_x=x,
        state_plane_y=y,
    )


# ---------------------------------------------------------------------------
# Test 1: Return type narrowing — runtime types
# ---------------------------------------------------------------------------


async def test_resolve_asp_returns_asp_result_by_default() -> None:
    """resolve_asp(lat, lon) with no debug flag returns ASPResult, not ASPDebugResult."""
    resolution = _make_resolution_result()
    signs = _make_sign_success(soda_level=1)
    schedule = _make_schedule_found()

    with (
        patch("gps2asp.pipeline.convert", return_value=(987654.0, 178432.0)),
        patch(
            "gps2asp.pipeline.resolve_segment",
            new_callable=AsyncMock,
            return_value=resolution,
        ),
        patch(
            "gps2asp.pipeline.retrieve_signs",
            new_callable=AsyncMock,
            return_value=signs,
        ),
        patch("gps2asp.pipeline.compute_schedule", return_value=schedule),
    ):
        result = await resolve_asp(40.677629, -73.968527)

    assert isinstance(result, ASPResult), (
        f"Expected ASPResult, got {type(result).__name__}"
    )
    assert not isinstance(result, ASPDebugResult), (
        "resolve_asp() without debug=True must NOT return ASPDebugResult"
    )


async def test_resolve_asp_debug_true_returns_asp_debug_result() -> None:
    """resolve_asp(lat, lon, debug=True) returns ASPDebugResult, not ASPResult."""
    resolution = _make_resolution_result()
    signs = _make_sign_success(soda_level=2)
    schedule = _make_schedule_found()

    with (
        patch("gps2asp.pipeline.convert", return_value=(987654.0, 178432.0)),
        patch(
            "gps2asp.pipeline.resolve_segment",
            new_callable=AsyncMock,
            return_value=resolution,
        ),
        patch(
            "gps2asp.pipeline.retrieve_signs",
            new_callable=AsyncMock,
            return_value=signs,
        ),
        patch("gps2asp.pipeline.compute_schedule", return_value=schedule),
    ):
        result = await resolve_asp(40.677629, -73.968527, debug=True)

    assert isinstance(result, ASPDebugResult), (
        f"Expected ASPDebugResult, got {type(result).__name__}"
    )


# ---------------------------------------------------------------------------
# Test 2: AmbiguousResolutionError is caught — surfaces as structured fields
# ---------------------------------------------------------------------------


async def test_ambiguous_resolution_error_caught_returns_asp_result() -> None:
    """AmbiguousResolutionError is caught by resolve_asp() and not propagated.

    The result must have resolution_failed=True, resolution_error as a string,
    and schedule=None (signs stage never ran).
    """
    debug_info = _make_debug_info()
    err = AmbiguousResolutionError(
        message="Confidence 0.0 below threshold 0.6",
        debug_info=debug_info,
        confidence=0.0,
    )

    with (
        patch("gps2asp.pipeline.convert", return_value=(987654.0, 178432.0)),
        patch(
            "gps2asp.pipeline.resolve_segment", new_callable=AsyncMock, side_effect=err
        ),
    ):
        result = await resolve_asp(40.677629, -73.968527)

    assert isinstance(result, ASPResult)
    assert result.resolution_failed is True
    assert result.resolution_error is not None
    assert isinstance(result.resolution_error, str)
    assert len(result.resolution_error) > 0
    assert result.schedule is None


async def test_ambiguous_resolution_error_caught_debug_true() -> None:
    """AmbiguousResolutionError caught in debug=True mode returns ASPDebugResult.

    resolution_failed must be True, resolution_error must be set,
    schedule must be None, and soda_level must be 0.
    """
    debug_info = _make_debug_info()
    err = AmbiguousResolutionError(
        message="Confidence 0.0 below threshold 0.6",
        debug_info=debug_info,
        confidence=0.0,
    )

    with (
        patch("gps2asp.pipeline.convert", return_value=(987654.0, 178432.0)),
        patch(
            "gps2asp.pipeline.resolve_segment", new_callable=AsyncMock, side_effect=err
        ),
    ):
        result = await resolve_asp(40.677629, -73.968527, debug=True)

    assert isinstance(result, ASPDebugResult)
    assert result.resolution_failed is True
    assert result.resolution_error is not None
    assert result.schedule is None
    assert result.soda_level == 0


# ---------------------------------------------------------------------------
# Test 3: OutsideNYCError propagates — NOT caught by resolve_asp
# ---------------------------------------------------------------------------


async def test_outside_nyc_error_propagates() -> None:
    """OutsideNYCError is NOT caught by resolve_asp() — it propagates to the caller."""
    with (
        patch("gps2asp.pipeline.convert", side_effect=OutsideNYCError(0.0, 0.0)),
    ):
        with pytest.raises(OutsideNYCError):
            await resolve_asp(0.0, 0.0)


# ---------------------------------------------------------------------------
# Test 4: Successful pipeline result — fields match mocked values
# ---------------------------------------------------------------------------


async def test_successful_pipeline_asp_result_fields() -> None:
    """Successful pipeline: ASPResult has resolution_failed=False and correct schedule."""
    resolution = _make_resolution_result(confidence=0.85)
    signs = _make_sign_success(soda_level=1)
    schedule = _make_schedule_found()

    with (
        patch("gps2asp.pipeline.convert", return_value=(987654.0, 178432.0)),
        patch(
            "gps2asp.pipeline.resolve_segment",
            new_callable=AsyncMock,
            return_value=resolution,
        ),
        patch(
            "gps2asp.pipeline.retrieve_signs",
            new_callable=AsyncMock,
            return_value=signs,
        ),
        patch("gps2asp.pipeline.compute_schedule", return_value=schedule),
    ):
        result = await resolve_asp(40.677629, -73.968527)

    assert isinstance(result, ASPResult)
    assert result.resolution_failed is False
    assert result.resolution_error is None
    assert result.schedule is schedule


async def test_successful_pipeline_debug_result_fields() -> None:
    """Successful pipeline with debug=True: ASPDebugResult carries correct field values.

    Specifically: confidence matches ResolutionResult.confidence, soda_level
    matches SignRetrievalSuccess.soda_level, and state_plane coordinates
    match the convert() output.
    """
    resolution = _make_resolution_result(confidence=0.6133)
    signs = _make_sign_success(soda_level=3)
    schedule = _make_schedule_found()
    sp_x, sp_y = 987654.0, 178432.0

    with (
        patch("gps2asp.pipeline.convert", return_value=(sp_x, sp_y)),
        patch(
            "gps2asp.pipeline.resolve_segment",
            new_callable=AsyncMock,
            return_value=resolution,
        ),
        patch(
            "gps2asp.pipeline.retrieve_signs",
            new_callable=AsyncMock,
            return_value=signs,
        ),
        patch("gps2asp.pipeline.compute_schedule", return_value=schedule),
    ):
        result = await resolve_asp(40.677629, -73.968527, debug=True)

    assert isinstance(result, ASPDebugResult)
    assert result.resolution_failed is False
    assert result.resolution_error is None
    assert result.schedule is schedule
    assert result.confidence == pytest.approx(0.6133)
    assert result.soda_level == 3
    assert result.state_plane_x == pytest.approx(sp_x)
    assert result.state_plane_y == pytest.approx(sp_y)
    assert result.on_street == "PROSPECT PL"
    assert result.from_street == "VANDERBILT AVE"
    assert result.to_street == "CARLTON AVE"
    assert result.side_of_street == "N"
    assert result.resolution is resolution
    assert result.sign_result is signs


# ---------------------------------------------------------------------------
# Test 5: soda_level=0 when retrieve_signs returns NoMatchFound
# ---------------------------------------------------------------------------


async def test_soda_level_zero_for_no_match_found() -> None:
    """When retrieve_signs returns NoMatchFound, debug result has soda_level=0."""
    resolution = _make_resolution_result(confidence=0.85)
    no_match = NoMatchFound()
    # compute_schedule receives NoMatchFound and returns NoMatchSchedule
    from gps2asp.schedule.models import NoMatchSchedule

    no_match_schedule = NoMatchSchedule()

    with (
        patch("gps2asp.pipeline.convert", return_value=(987654.0, 178432.0)),
        patch(
            "gps2asp.pipeline.resolve_segment",
            new_callable=AsyncMock,
            return_value=resolution,
        ),
        patch(
            "gps2asp.pipeline.retrieve_signs",
            new_callable=AsyncMock,
            return_value=no_match,
        ),
        patch("gps2asp.pipeline.compute_schedule", return_value=no_match_schedule),
    ):
        result = await resolve_asp(40.677629, -73.968527, debug=True)

    assert isinstance(result, ASPDebugResult)
    assert result.soda_level == 0
    assert result.resolution_failed is False


class TestASPResultSodaLevel:
    """Test that ASPResult.soda_level is populated on the non-debug path.

    These tests are RED until Plan 02 adds soda_level to ASPResult and
    populates it in pipeline.py.
    """

    async def test_asp_result_soda_level_populated(self) -> None:
        """Non-debug resolve_asp -> ASPResult.soda_level == sign_result.soda_level."""
        sign_success = _make_sign_success(soda_level=2)
        schedule = _make_schedule_found()
        resolution = _make_resolution_result()

        with (
            patch("gps2asp.pipeline.convert", return_value=(100.0, 200.0)),
            patch(
                "gps2asp.pipeline.resolve_segment",
                new=AsyncMock(return_value=resolution),
            ),
            patch(
                "gps2asp.pipeline.retrieve_signs",
                new=AsyncMock(return_value=sign_success),
            ),
            patch("gps2asp.pipeline.compute_schedule", return_value=schedule),
        ):
            result = await resolve_asp(40.676, -73.979)

        assert isinstance(result, ASPResult)
        # This assertion is RED until Plan 02 adds soda_level to ASPResult
        assert result.soda_level == 2

    async def test_asp_result_soda_level_zero_on_no_match(self) -> None:
        """Non-debug resolve_asp with NoMatchFound -> ASPResult.soda_level == 0."""
        no_match = NoMatchFound(status="no_match")
        schedule = _make_schedule_found()
        resolution = _make_resolution_result()

        with (
            patch("gps2asp.pipeline.convert", return_value=(100.0, 200.0)),
            patch(
                "gps2asp.pipeline.resolve_segment",
                new=AsyncMock(return_value=resolution),
            ),
            patch(
                "gps2asp.pipeline.retrieve_signs",
                new=AsyncMock(return_value=no_match),
            ),
            patch("gps2asp.pipeline.compute_schedule", return_value=schedule),
        ):
            result = await resolve_asp(40.676, -73.979)

        assert isinstance(result, ASPResult)
        # This assertion is RED until Plan 02 adds soda_level to ASPResult
        assert result.soda_level == 0


# ---------------------------------------------------------------------------
# GAP 1: SUSP-03 — suspension_status wires Stage 4 into resolve_asp()
# ---------------------------------------------------------------------------


async def test_resolve_asp_suspension_status_wires_stage4() -> None:
    """resolve_asp() with suspension_status passes SuspensionInfo through Stage 4.

    When suspension_status=SuspensionInfo(is_suspended=True, reason='MLK Day',
    source='holiday') is passed, the returned ASPResult.schedule must have
    suspended=True and resolution_reason='suspended_holiday'.
    """
    resolution = _make_resolution_result()
    signs = _make_sign_success(soda_level=1)
    schedule = _make_schedule_found()

    suspension = SuspensionInfo(is_suspended=True, reason="MLK Day", source="holiday")

    with (
        patch("gps2asp.pipeline.convert", return_value=(987654.0, 178432.0)),
        patch(
            "gps2asp.pipeline.resolve_segment",
            new_callable=AsyncMock,
            return_value=resolution,
        ),
        patch(
            "gps2asp.pipeline.retrieve_signs",
            new_callable=AsyncMock,
            return_value=signs,
        ),
        patch("gps2asp.pipeline.compute_schedule", return_value=schedule),
    ):
        result = await resolve_asp(40.677629, -73.968527, suspension_status=suspension)

    assert isinstance(result, ASPResult)
    assert result.schedule is not None
    assert result.schedule.suspended is True
    assert result.schedule.resolution_reason == "suspended_holiday"


async def test_resolve_asp_suspension_status_none_is_noop() -> None:
    """resolve_asp() with suspension_status=None (default) leaves schedule unchanged.

    Backwards compatibility: None means Stage 4 is a no-op.
    The returned schedule must have suspended=False (no annotation applied).
    """
    resolution = _make_resolution_result()
    signs = _make_sign_success(soda_level=1)
    schedule = _make_schedule_found()

    with (
        patch("gps2asp.pipeline.convert", return_value=(987654.0, 178432.0)),
        patch(
            "gps2asp.pipeline.resolve_segment",
            new_callable=AsyncMock,
            return_value=resolution,
        ),
        patch(
            "gps2asp.pipeline.retrieve_signs",
            new_callable=AsyncMock,
            return_value=signs,
        ),
        patch("gps2asp.pipeline.compute_schedule", return_value=schedule),
    ):
        result = await resolve_asp(40.677629, -73.968527)

    assert isinstance(result, ASPResult)
    assert result.schedule is not None
    assert result.schedule.suspended is False
    assert result.schedule.resolution_reason is None
