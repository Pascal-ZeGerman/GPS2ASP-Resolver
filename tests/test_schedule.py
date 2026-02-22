"""Comprehensive unit tests for schedule merge, next-move, summary, and compute_schedule.

Tests the complete schedule computation pipeline: window merging, timezone-aware
next-occurrence computation, human-readable summary generation, and the
compute_schedule() public API entry point.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from gps2asp.schedule import (
    AllUnparseable,
    ASPActiveNow,
    ASPDay,
    CleaningWindow,
    NoASPSchedule,
    NoMatchSchedule,
    ScheduleFound,
    compute_schedule,
    find_active_window,
    find_next_window,
    format_summary,
    merge_windows,
)
from gps2asp.schedule.models import ParseFailure, TimeWindow, WeeklySchedule
from gps2asp.signs.models import (
    NoASPSigns,
    NoMatchFound,
    SignRecord,
    SignRetrievalSuccess,
)

NYC_TZ = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _tw(
    day: ASPDay,
    start_h: int,
    start_m: int,
    end_h: int,
    end_m: int,
    source: str = "test-sign",
) -> TimeWindow:
    """Create a TimeWindow for testing."""
    return TimeWindow(
        day=day,
        start_time=time(start_h, start_m),
        end_time=time(end_h, end_m),
        source_sign=source,
    )


def _make_sign_result(
    *descriptions: str,
    on_street: str = "PROSPECT PL",
    from_street: str = "VANDERBILT AVE",
    to_street: str = "UNDERHILL AVE",
    side: str = "N",
) -> SignRetrievalSuccess:
    """Create a SignRetrievalSuccess for testing."""
    return SignRetrievalSuccess(
        status="signs_found",
        signs=[SignRecord(sign_description=d) for d in descriptions],
        on_street=on_street,
        from_street=from_street,
        to_street=to_street,
        side_of_street=side,
    )


# ---------------------------------------------------------------------------
# TestMergeWindows
# ---------------------------------------------------------------------------


class TestMergeWindows:
    """Tests for merge_windows()."""

    def test_non_overlapping_same_day_preserved(self) -> None:
        """Non-overlapping windows on the same day are kept separate."""
        windows = [
            _tw(ASPDay.TUESDAY, 8, 0, 9, 0),
            _tw(ASPDay.TUESDAY, 11, 0, 12, 0),
        ]
        result = merge_windows(windows)
        assert len(result.windows) == 2
        assert result.windows[0].start_time == time(8, 0)
        assert result.windows[0].end_time == time(9, 0)
        assert result.windows[1].start_time == time(11, 0)
        assert result.windows[1].end_time == time(12, 0)

    def test_overlapping_windows_merge(self) -> None:
        """Overlapping windows (8-9:30 + 9-10:30 on Tuesday) merge to 8-10:30."""
        windows = [
            _tw(ASPDay.TUESDAY, 8, 0, 9, 30, source="sign-A"),
            _tw(ASPDay.TUESDAY, 9, 0, 10, 30, source="sign-B"),
        ]
        result = merge_windows(windows)
        assert len(result.windows) == 1
        assert result.windows[0].start_time == time(8, 0)
        assert result.windows[0].end_time == time(10, 30)

    def test_adjacent_windows_merge(self) -> None:
        """Adjacent windows (8-9 + 9-10 on Tuesday) merge to 8-10."""
        windows = [
            _tw(ASPDay.TUESDAY, 8, 0, 9, 0),
            _tw(ASPDay.TUESDAY, 9, 0, 10, 0),
        ]
        result = merge_windows(windows)
        assert len(result.windows) == 1
        assert result.windows[0].start_time == time(8, 0)
        assert result.windows[0].end_time == time(10, 0)

    def test_different_days_not_merged(self) -> None:
        """Windows on different days are NOT merged."""
        windows = [
            _tw(ASPDay.TUESDAY, 8, 0, 9, 30),
            _tw(ASPDay.FRIDAY, 8, 0, 9, 30),
        ]
        result = merge_windows(windows)
        assert len(result.windows) == 2
        assert result.windows[0].day == ASPDay.TUESDAY
        assert result.windows[1].day == ASPDay.FRIDAY

    def test_source_signs_concatenated(self) -> None:
        """Source signs are concatenated in merged window."""
        windows = [
            _tw(ASPDay.TUESDAY, 8, 0, 9, 30, source="sign-A"),
            _tw(ASPDay.TUESDAY, 9, 0, 10, 30, source="sign-B"),
        ]
        result = merge_windows(windows)
        assert len(result.windows) == 1
        assert "sign-A" in result.windows[0].source_sign
        assert "sign-B" in result.windows[0].source_sign

    def test_empty_input_returns_empty_schedule(self) -> None:
        """Empty input returns WeeklySchedule with empty tuple."""
        result = merge_windows([])
        assert result.windows == ()


# ---------------------------------------------------------------------------
# TestFindNextWindow
# ---------------------------------------------------------------------------


class TestFindNextWindow:
    """Tests for find_next_window()."""

    def _tue_fri_schedule(self) -> WeeklySchedule:
        """Create a TUE+FRI 8:30-10AM schedule."""
        return WeeklySchedule(
            windows=(
                _tw(ASPDay.TUESDAY, 8, 30, 10, 0),
                _tw(ASPDay.FRIDAY, 8, 30, 10, 0),
            )
        )

    def test_monday_3pm_returns_tuesday(self) -> None:
        """Monday 3PM with TUE+FRI schedule -> next Tuesday 8:30AM."""
        schedule = self._tue_fri_schedule()
        # 2026-02-23 is Monday
        now = datetime(2026, 2, 23, 15, 0, tzinfo=NYC_TZ)
        result = find_next_window(schedule, now)
        assert result is not None
        assert result.day == ASPDay.TUESDAY
        assert result.start_time == time(8, 30)
        assert result.start_datetime.date().isoformat() == "2026-02-24"

    def test_tuesday_7am_returns_tuesday_later(self) -> None:
        """Tuesday 7AM with TUE+FRI 8:30-10AM -> returns Tuesday 8:30AM (later today)."""
        schedule = self._tue_fri_schedule()
        # 2026-02-24 is Tuesday
        now = datetime(2026, 2, 24, 7, 0, tzinfo=NYC_TZ)
        result = find_next_window(schedule, now)
        assert result is not None
        assert result.day == ASPDay.TUESDAY
        assert result.start_datetime.date().isoformat() == "2026-02-24"

    def test_tuesday_9am_inside_window_returns_friday(self) -> None:
        """Tuesday 9AM (inside window) -> returns Friday 8:30AM (skips current)."""
        schedule = self._tue_fri_schedule()
        # 2026-02-24 is Tuesday
        now = datetime(2026, 2, 24, 9, 0, tzinfo=NYC_TZ)
        result = find_next_window(schedule, now)
        assert result is not None
        assert result.day == ASPDay.FRIDAY
        assert result.start_datetime.date().isoformat() == "2026-02-27"

    def test_saturday_5pm_returns_next_tuesday(self) -> None:
        """Saturday 5PM with TUE+FRI schedule -> returns next Tuesday."""
        schedule = self._tue_fri_schedule()
        # 2026-02-28 is Saturday
        now = datetime(2026, 2, 28, 17, 0, tzinfo=NYC_TZ)
        result = find_next_window(schedule, now)
        assert result is not None
        assert result.day == ASPDay.TUESDAY
        assert result.start_datetime.date().isoformat() == "2026-03-03"

    def test_all_datetimes_timezone_aware(self) -> None:
        """All datetimes in result are timezone-aware."""
        schedule = self._tue_fri_schedule()
        now = datetime(2026, 2, 23, 15, 0, tzinfo=NYC_TZ)
        result = find_next_window(schedule, now)
        assert result is not None
        assert result.start_datetime.tzinfo is not None
        assert result.end_datetime.tzinfo is not None

    def test_empty_schedule_returns_none(self) -> None:
        """Empty schedule returns None."""
        schedule = WeeklySchedule(windows=())
        now = datetime(2026, 2, 23, 15, 0, tzinfo=NYC_TZ)
        result = find_next_window(schedule, now)
        assert result is None


# ---------------------------------------------------------------------------
# TestFindActiveWindow
# ---------------------------------------------------------------------------


class TestFindActiveWindow:
    """Tests for find_active_window()."""

    def _tue_schedule(self) -> WeeklySchedule:
        """Create a TUE 8:30-10AM schedule."""
        return WeeklySchedule(
            windows=(_tw(ASPDay.TUESDAY, 8, 30, 10, 0),)
        )

    def test_inside_window_returns_cleaning_window(self) -> None:
        """Tuesday 9AM inside TUE 8:30-10AM -> returns active CleaningWindow."""
        schedule = self._tue_schedule()
        # 2026-02-24 is Tuesday
        now = datetime(2026, 2, 24, 9, 0, tzinfo=NYC_TZ)
        result = find_active_window(schedule, now)
        assert result is not None
        assert isinstance(result, CleaningWindow)
        assert result.day == ASPDay.TUESDAY

    def test_before_window_returns_none(self) -> None:
        """Tuesday 7AM, TUE 8:30-10AM -> returns None."""
        schedule = self._tue_schedule()
        now = datetime(2026, 2, 24, 7, 0, tzinfo=NYC_TZ)
        result = find_active_window(schedule, now)
        assert result is None

    def test_different_day_returns_none(self) -> None:
        """Monday 9AM, TUE 8:30-10AM -> returns None."""
        schedule = self._tue_schedule()
        # 2026-02-23 is Monday
        now = datetime(2026, 2, 23, 9, 0, tzinfo=NYC_TZ)
        result = find_active_window(schedule, now)
        assert result is None

    def test_exactly_at_start_is_active(self) -> None:
        """Exactly at start_time -> returns active (start is inclusive)."""
        schedule = self._tue_schedule()
        now = datetime(2026, 2, 24, 8, 30, tzinfo=NYC_TZ)
        result = find_active_window(schedule, now)
        assert result is not None
        assert result.day == ASPDay.TUESDAY

    def test_exactly_at_end_returns_none(self) -> None:
        """Exactly at end_time -> returns None (end is exclusive)."""
        schedule = self._tue_schedule()
        now = datetime(2026, 2, 24, 10, 0, tzinfo=NYC_TZ)
        result = find_active_window(schedule, now)
        assert result is None

    def test_active_window_datetimes_timezone_aware(self) -> None:
        """Active window datetimes are timezone-aware."""
        schedule = self._tue_schedule()
        now = datetime(2026, 2, 24, 9, 0, tzinfo=NYC_TZ)
        result = find_active_window(schedule, now)
        assert result is not None
        assert result.start_datetime.tzinfo is not None
        assert result.end_datetime.tzinfo is not None


# ---------------------------------------------------------------------------
# TestFormatSummary
# ---------------------------------------------------------------------------


class TestFormatSummary:
    """Tests for format_summary()."""

    def test_two_day_schedule(self) -> None:
        """Two-day schedule produces 'TUE & FRI' format."""
        schedule = WeeklySchedule(
            windows=(
                _tw(ASPDay.TUESDAY, 11, 30, 13, 0),
                _tw(ASPDay.FRIDAY, 11, 30, 13, 0),
            )
        )
        result = format_summary(schedule)
        assert "TUE" in result
        assert "FRI" in result
        assert "11:30" in result

    def test_single_day(self) -> None:
        """Single day just shows day name + time."""
        schedule = WeeklySchedule(
            windows=(_tw(ASPDay.TUESDAY, 11, 30, 13, 0),)
        )
        result = format_summary(schedule)
        assert "TUE" in result
        assert "11:30" in result

    def test_monday_through_friday_range(self) -> None:
        """MONDAY-FRIDAY uses dash notation."""
        schedule = WeeklySchedule(
            windows=(
                _tw(ASPDay.MONDAY, 8, 0, 9, 0),
                _tw(ASPDay.TUESDAY, 8, 0, 9, 0),
                _tw(ASPDay.WEDNESDAY, 8, 0, 9, 0),
                _tw(ASPDay.THURSDAY, 8, 0, 9, 0),
                _tw(ASPDay.FRIDAY, 8, 0, 9, 0),
            )
        )
        result = format_summary(schedule)
        assert "MON-FRI" in result

    def test_empty_schedule(self) -> None:
        """Empty schedule returns 'No schedule'."""
        schedule = WeeklySchedule(windows=())
        result = format_summary(schedule)
        assert result == "No schedule"

    def test_same_meridiem_simplification(self) -> None:
        """Same-meridiem times simplify: '8 - 9:30 AM' not '8 AM - 9:30 AM'."""
        schedule = WeeklySchedule(
            windows=(_tw(ASPDay.TUESDAY, 8, 0, 9, 30),)
        )
        result = format_summary(schedule)
        # Should NOT have "AM" twice.
        assert result.count("AM") == 1

    def test_cross_meridiem_both_shown(self) -> None:
        """Cross-meridiem shows both: '11:30 AM - 1 PM'."""
        schedule = WeeklySchedule(
            windows=(_tw(ASPDay.TUESDAY, 11, 30, 13, 0),)
        )
        result = format_summary(schedule)
        assert "AM" in result
        assert "PM" in result


# ---------------------------------------------------------------------------
# TestComputeSchedule (integration)
# ---------------------------------------------------------------------------


class TestComputeSchedule:
    """Integration tests for compute_schedule()."""

    def test_no_asp_signs_returns_no_asp_schedule(self) -> None:
        """NoASPSigns -> NoASPSchedule."""
        result = compute_schedule(NoASPSigns())
        assert isinstance(result, NoASPSchedule)
        assert result.status == "no_asp"

    def test_no_match_found_returns_no_match_schedule(self) -> None:
        """NoMatchFound -> NoMatchSchedule."""
        result = compute_schedule(NoMatchFound())
        assert isinstance(result, NoMatchSchedule)
        assert result.status == "no_match"

    def test_one_standard_sign_returns_schedule_found(self) -> None:
        """One standard sign -> ScheduleFound with correct next_window."""
        sign_result = _make_sign_result(
            "NO PARKING (SANITATION BROOM SYMBOL) TUESDAY FRIDAY 11:30AM-1PM <->"
        )
        # Monday 3PM: next should be Tuesday
        now = datetime(2026, 2, 23, 15, 0, tzinfo=NYC_TZ)
        result = compute_schedule(sign_result, now=now)
        assert isinstance(result, ScheduleFound)
        assert result.status == "schedule_found"
        assert result.next_window is not None
        assert result.next_window.day == ASPDay.TUESDAY

    def test_two_overlapping_signs_merged(self) -> None:
        """Two signs with overlapping windows -> ScheduleFound with merged schedule."""
        sign_result = _make_sign_result(
            "NO PARKING (SANITATION BROOM SYMBOL) TUESDAY 8AM-9:30AM <->",
            "NO PARKING (SANITATION BROOM SYMBOL) TUESDAY 9AM-10:30AM <->",
        )
        now = datetime(2026, 2, 23, 15, 0, tzinfo=NYC_TZ)
        result = compute_schedule(sign_result, now=now)
        assert isinstance(result, ScheduleFound)
        # Should be merged into one Tuesday window.
        tue_windows = result.weekly_schedule.windows_for_day(ASPDay.TUESDAY)
        assert len(tue_windows) == 1
        assert tue_windows[0].start_time == time(8, 0)
        assert tue_windows[0].end_time == time(10, 30)

    def test_one_parseable_one_unparseable(self) -> None:
        """One parseable + one unparseable -> ScheduleFound with parse_failures."""
        sign_result = _make_sign_result(
            "NO PARKING (SANITATION BROOM SYMBOL) TUESDAY FRIDAY 11:30AM-1PM <->",
            "SOME RANDOM TEXT THAT CANNOT BE PARSED",
        )
        now = datetime(2026, 2, 23, 15, 0, tzinfo=NYC_TZ)
        result = compute_schedule(sign_result, now=now)
        assert isinstance(result, ScheduleFound)
        assert len(result.parse_failures) == 1
        assert result.parse_failures[0].raw == "SOME RANDOM TEXT THAT CANNOT BE PARSED"

    def test_all_unparseable_returns_all_unparseable(self) -> None:
        """All signs fail to parse -> AllUnparseable."""
        sign_result = _make_sign_result(
            "GARBAGE SIGN TEXT ONE",
            "GARBAGE SIGN TEXT TWO",
        )
        result = compute_schedule(sign_result)
        assert isinstance(result, AllUnparseable)
        assert result.status == "all_unparseable"
        assert len(result.parse_failures) == 2

    def test_active_now_returns_asp_active(self) -> None:
        """Sign active at current time -> ASPActiveNow."""
        sign_result = _make_sign_result(
            "NO PARKING (SANITATION BROOM SYMBOL) TUESDAY FRIDAY 11:30AM-1PM <->"
        )
        # Tuesday at noon -- inside 11:30AM-1PM window.
        # 2026-02-24 is Tuesday
        now = datetime(2026, 2, 24, 12, 0, tzinfo=NYC_TZ)
        result = compute_schedule(sign_result, now=now)
        assert isinstance(result, ASPActiveNow)
        assert result.status == "asp_active_now"
        assert result.active_window.day == ASPDay.TUESDAY

    def test_street_info_passthrough(self) -> None:
        """Street info passes through from input to output."""
        sign_result = _make_sign_result(
            "NO PARKING (SANITATION BROOM SYMBOL) TUESDAY FRIDAY 11:30AM-1PM <->",
            on_street="PROSPECT PL",
            from_street="VANDERBILT AVE",
            to_street="UNDERHILL AVE",
            side="N",
        )
        now = datetime(2026, 2, 23, 15, 0, tzinfo=NYC_TZ)
        result = compute_schedule(sign_result, now=now)
        assert isinstance(result, ScheduleFound)
        assert result.on_street == "PROSPECT PL"
        assert result.from_street == "VANDERBILT AVE"
        assert result.to_street == "UNDERHILL AVE"
        assert result.side_of_street == "N"

    def test_source_signs_populated(self) -> None:
        """source_signs list is populated from input signs."""
        desc = "NO PARKING (SANITATION BROOM SYMBOL) TUESDAY FRIDAY 11:30AM-1PM <->"
        sign_result = _make_sign_result(desc)
        now = datetime(2026, 2, 23, 15, 0, tzinfo=NYC_TZ)
        result = compute_schedule(sign_result, now=now)
        assert isinstance(result, ScheduleFound)
        assert desc in result.source_signs

    def test_summary_string_non_empty(self) -> None:
        """Summary string is non-empty for ScheduleFound."""
        sign_result = _make_sign_result(
            "NO PARKING (SANITATION BROOM SYMBOL) TUESDAY FRIDAY 11:30AM-1PM <->"
        )
        now = datetime(2026, 2, 23, 15, 0, tzinfo=NYC_TZ)
        result = compute_schedule(sign_result, now=now)
        assert isinstance(result, ScheduleFound)
        assert result.summary
        assert len(result.summary) > 0

    def test_asp_active_now_summary_non_empty(self) -> None:
        """Summary string is non-empty for ASPActiveNow."""
        sign_result = _make_sign_result(
            "NO PARKING (SANITATION BROOM SYMBOL) TUESDAY FRIDAY 11:30AM-1PM <->"
        )
        # Tuesday at noon -- inside window.
        now = datetime(2026, 2, 24, 12, 0, tzinfo=NYC_TZ)
        result = compute_schedule(sign_result, now=now)
        assert isinstance(result, ASPActiveNow)
        assert result.summary
        assert len(result.summary) > 0

    def test_next_window_datetimes_timezone_aware(self) -> None:
        """All datetimes in ScheduleFound.next_window are timezone-aware."""
        sign_result = _make_sign_result(
            "NO PARKING (SANITATION BROOM SYMBOL) TUESDAY FRIDAY 11:30AM-1PM <->"
        )
        now = datetime(2026, 2, 23, 15, 0, tzinfo=NYC_TZ)
        result = compute_schedule(sign_result, now=now)
        assert isinstance(result, ScheduleFound)
        assert result.next_window.start_datetime.tzinfo is not None
        assert result.next_window.end_datetime.tzinfo is not None
