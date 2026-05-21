"""Tests for gps2asp.suspension.merge — apply_suspension() pure function.

RED phase: all tests fail until merge.py is implemented.
"""

from __future__ import annotations

import pytest

from gps2asp.schedule.models import (
    AllUnparseable,
    ASPActiveNow,
    CleaningWindow,
    NoASPSchedule,
    NoMatchSchedule,
    ParseFailure,
    ScheduleFound,
    WeeklySchedule,
)
from gps2asp.suspension import SuspensionInfo
from gps2asp.suspension.merge import apply_suspension


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def schedule_found() -> ScheduleFound:
    """Minimal valid ScheduleFound for testing."""
    return ScheduleFound(
        status="schedule_found",
        next_window=None,
        weekly_schedule=WeeklySchedule(windows=()),
        on_street="MAIN ST",
        from_street="1ST AVE",
        to_street="2ND AVE",
        side_of_street="N",
        source_signs=[],
        summary="Test",
        parse_failures=[],
    )


@pytest.fixture
def asp_active_now() -> ASPActiveNow:
    """Minimal valid ASPActiveNow for testing (using a real CleaningWindow)."""
    from datetime import datetime, time
    from gps2asp.schedule.models import ASPDay
    from zoneinfo import ZoneInfo

    nyc_tz = ZoneInfo("America/New_York")
    window = CleaningWindow(
        day=ASPDay.MONDAY,
        start_time=time(8, 0),
        end_time=time(9, 30),
        start_datetime=datetime(2026, 4, 6, 8, 0, tzinfo=nyc_tz),
        end_datetime=datetime(2026, 4, 6, 9, 30, tzinfo=nyc_tz),
        source_signs=["MONDAY 8-9:30 AM"],
    )
    return ASPActiveNow(
        status="asp_active_now",
        active_window=window,
        on_street="MAIN ST",
        from_street="1ST AVE",
        to_street="2ND AVE",
        side_of_street="N",
        source_signs=["MONDAY 8-9:30 AM"],
        summary="Test",
    )


# ---------------------------------------------------------------------------
# Holiday suspension on ScheduleFound
# ---------------------------------------------------------------------------


def test_apply_suspension_holiday_on_schedule_found(
    schedule_found: ScheduleFound,
) -> None:
    """Holiday suspension annotates ScheduleFound with suspended=True and reason."""
    info = SuspensionInfo(is_suspended=True, reason="MLK Day", source="holiday")
    result = apply_suspension(schedule_found, info)
    assert isinstance(result, ScheduleFound)
    assert result.suspended is True
    assert result.suspension_reason == "MLK Day"
    assert result.resolution_reason == "suspended_holiday"
    assert result.status == "schedule_found"


# ---------------------------------------------------------------------------
# Emergency suspension on ScheduleFound
# ---------------------------------------------------------------------------


def test_apply_suspension_emergency_on_schedule_found(
    schedule_found: ScheduleFound,
) -> None:
    """Emergency suspension annotates ScheduleFound with suspended_emergency."""
    info = SuspensionInfo(
        is_suspended=True, reason="Snow Emergency", source="emergency"
    )
    result = apply_suspension(schedule_found, info)
    assert isinstance(result, ScheduleFound)
    assert result.suspended is True
    assert result.suspension_reason == "Snow Emergency"
    assert result.resolution_reason == "suspended_emergency"


# ---------------------------------------------------------------------------
# Holiday suspension on ASPActiveNow
# ---------------------------------------------------------------------------


def test_apply_suspension_holiday_on_asp_active_now(
    asp_active_now: ASPActiveNow,
) -> None:
    """Holiday suspension annotates ASPActiveNow with suspended=True and reason."""
    info = SuspensionInfo(is_suspended=True, reason="Memorial Day", source="holiday")
    result = apply_suspension(asp_active_now, info)
    assert isinstance(result, ASPActiveNow)
    assert result.suspended is True
    assert result.suspension_reason == "Memorial Day"
    assert result.resolution_reason == "suspended_holiday"
    assert result.status == "asp_active_now"


# ---------------------------------------------------------------------------
# Not-suspended passthrough
# ---------------------------------------------------------------------------


def test_apply_suspension_not_suspended_passthrough(
    schedule_found: ScheduleFound,
) -> None:
    """Not-suspended SuspensionInfo leaves ScheduleFound unchanged."""
    info = SuspensionInfo(is_suspended=False, reason=None, source="none")
    result = apply_suspension(schedule_found, info)
    assert result.suspended is False
    assert result.suspension_reason is None


def test_apply_suspension_not_in_effect_not_conflated(
    schedule_found: ScheduleFound,
) -> None:
    """NOT_IN_EFFECT (normal Sunday) must never set suspended=True."""
    info = SuspensionInfo(is_suspended=False, reason=None, source="none")
    result = apply_suspension(schedule_found, info)
    assert result.suspended is False


# ---------------------------------------------------------------------------
# Pass-through for non-schedule types
# ---------------------------------------------------------------------------


def test_apply_suspension_no_asp_passthrough() -> None:
    """NoASPSchedule passes through unchanged even when suspended."""
    schedule = NoASPSchedule()
    info = SuspensionInfo(is_suspended=True, reason="MLK Day", source="holiday")
    result = apply_suspension(schedule, info)
    assert isinstance(result, NoASPSchedule)
    assert result is schedule


def test_apply_suspension_no_match_passthrough() -> None:
    """NoMatchSchedule passes through unchanged even when suspended."""
    schedule = NoMatchSchedule()
    info = SuspensionInfo(is_suspended=True, reason="MLK Day", source="holiday")
    result = apply_suspension(schedule, info)
    assert isinstance(result, NoMatchSchedule)
    assert result is schedule


def test_apply_suspension_all_unparseable_passthrough() -> None:
    """AllUnparseable passes through unchanged even when suspended."""
    schedule = AllUnparseable(
        status="all_unparseable",
        parse_failures=[ParseFailure(raw="SOME SIGN", reason="unrecognized format")],
    )
    info = SuspensionInfo(is_suspended=True, reason="MLK Day", source="holiday")
    result = apply_suspension(schedule, info)
    assert isinstance(result, AllUnparseable)
    assert result is schedule


# ---------------------------------------------------------------------------
# Phase 35.1 BUG-T-006: apply_suspension logs ERROR on unknown source
#
# Pre-fix, apply_suspension defaulted unknown SuspensionInfo.source values
# to "suspended_holiday" with only a DEBUG log. A future-introduced
# "weather" or "construction" source would silently mis-classify as a
# holiday. The fix elevates the log level to ERROR so the unknown-source
# event is surfaced via HA diagnostics; the default-to-holiday behaviour
# is intentionally preserved for backward compatibility per RESEARCH.md.
# ---------------------------------------------------------------------------


import logging  # noqa: E402


def test_apply_suspension_unknown_source_logs_error(
    schedule_found: ScheduleFound,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unknown source value logs ERROR; default-to-holiday classification preserved."""
    info = SuspensionInfo(
        is_suspended=True,
        reason="Hypothetical weather closure",
        source="future_unknown_source",  # type: ignore[arg-type]
    )
    with caplog.at_level(logging.ERROR, logger="gps2asp.suspension.merge"):
        result = apply_suspension(schedule_found, info)

    # Behaviour preserved: still annotated, still defaults to suspended_holiday.
    assert isinstance(result, ScheduleFound)
    assert result.suspended is True
    assert result.resolution_reason == "suspended_holiday"

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1, (
        f"Expected one ERROR log, got: {[r.getMessage() for r in caplog.records]}"
    )
    msg = error_records[0].getMessage()
    assert "unknown source" in msg.lower(), msg
    assert "future_unknown_source" in msg, msg


def test_apply_suspension_known_holiday_source_does_not_error(
    schedule_found: ScheduleFound,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Known source 'holiday' must NOT emit an ERROR log (regression guard)."""
    info = SuspensionInfo(is_suspended=True, reason="MLK", source="holiday")
    with caplog.at_level(logging.ERROR, logger="gps2asp.suspension.merge"):
        apply_suspension(schedule_found, info)
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert error_records == [], (
        f"Expected zero ERROR logs for known source, got: "
        f"{[r.getMessage() for r in error_records]}"
    )
