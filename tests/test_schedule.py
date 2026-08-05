"""Comprehensive unit tests for schedule merge, next-move, summary, and compute_schedule.

Tests the complete schedule computation pipeline: window merging, timezone-aware
next-occurrence computation, human-readable summary generation, and the
compute_schedule() public API entry point.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
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
from gps2asp.schedule.models import TimeWindow, WeeklySchedule
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

    def test_holiday_on_next_day_is_skipped(self) -> None:
        """Monday 3PM: next window is Wednesday, but Wednesday is a holiday -> skips to Friday."""
        # 2026-02-23 is Monday; 2026-02-25 is Wednesday, 2026-02-27 is Friday
        schedule = WeeklySchedule(
            windows=(
                _tw(ASPDay.WEDNESDAY, 8, 30, 10, 0),
                _tw(ASPDay.FRIDAY, 8, 30, 10, 0),
            )
        )
        now = datetime(2026, 2, 23, 15, 0, tzinfo=NYC_TZ)
        suspended = frozenset({now.date() + timedelta(days=2)})  # Wednesday
        result = find_next_window(schedule, now, suspended_dates=suspended)
        assert result is not None
        assert result.day == ASPDay.FRIDAY
        assert result.start_datetime.date().isoformat() == "2026-02-27"

    def test_holiday_skipping_without_suspended_dates_unchanged(self) -> None:
        """No suspended_dates -> behaviour is unchanged (backward compat)."""
        schedule = self._tue_fri_schedule()
        now = datetime(2026, 2, 23, 15, 0, tzinfo=NYC_TZ)
        result = find_next_window(schedule, now, suspended_dates=None)
        assert result is not None
        assert result.day == ASPDay.TUESDAY

    def test_all_candidates_suspended_returns_none(self) -> None:
        """If all 8 lookahead days are suspended, returns None."""
        schedule = self._tue_fri_schedule()
        now = datetime(2026, 2, 23, 15, 0, tzinfo=NYC_TZ)
        suspended = frozenset({now.date() + timedelta(days=i) for i in range(8)})
        result = find_next_window(schedule, now, suspended_dates=suspended)
        assert result is None


# ---------------------------------------------------------------------------
# TestFindActiveWindow
# ---------------------------------------------------------------------------


class TestFindActiveWindow:
    """Tests for find_active_window()."""

    def _tue_schedule(self) -> WeeklySchedule:
        """Create a TUE 8:30-10AM schedule."""
        return WeeklySchedule(windows=(_tw(ASPDay.TUESDAY, 8, 30, 10, 0),))

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
        schedule = WeeklySchedule(windows=(_tw(ASPDay.TUESDAY, 11, 30, 13, 0),))
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
        schedule = WeeklySchedule(windows=(_tw(ASPDay.TUESDAY, 8, 0, 9, 30),))
        result = format_summary(schedule)
        # Should NOT have "AM" twice.
        assert result.count("AM") == 1

    def test_cross_meridiem_both_shown(self) -> None:
        """Cross-meridiem shows both: '11:30 AM - 1 PM'."""
        schedule = WeeklySchedule(windows=(_tw(ASPDay.TUESDAY, 11, 30, 13, 0),))
        result = format_summary(schedule)
        assert "AM" in result
        assert "PM" in result

    def test_cross_midnight_truncated_window_human_readable(self) -> None:
        """A 23:00-23:59:59 cross-midnight window (BUG-T-004) renders as 11 - 11:59 PM."""
        # Phase 35.1 BUG-T-004: parser truncates cross-midnight windows at
        # 23:59:59 so they remain same-day. The summary output must remain
        # human-readable for Night Regulation signs like "11PM-MIDNIGHT".
        schedule = WeeklySchedule(
            windows=(
                TimeWindow(
                    day=ASPDay.MONDAY,
                    start_time=time(23, 0),
                    end_time=time(23, 59, 59),
                    source_sign="cross-midnight",
                ),
            )
        )
        result = format_summary(schedule)
        assert "MON" in result
        assert "11" in result
        assert "PM" in result
        # Must not be empty/None or some other degenerate output.
        assert len(result) > 5


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

    def test_active_now_preserves_full_weekly_schedule(self) -> None:
        """ASPActiveNow carries the FULL merged weekly schedule (all cleaning
        days), not just the single in-progress window (BUG-ASPActiveNow-full-weekly).
        """
        sign_result = _make_sign_result(
            "NO PARKING (SANITATION BROOM SYMBOL) TUESDAY FRIDAY 11:30AM-1PM <->"
        )
        # Tuesday at noon -- inside 11:30AM-1PM window; 2026-02-24 is a Tuesday.
        now = datetime(2026, 2, 24, 12, 0, tzinfo=NYC_TZ)
        result = compute_schedule(sign_result, now=now)
        assert isinstance(result, ASPActiveNow)
        # The in-progress window still points at the active day.
        assert result.active_window.day == ASPDay.TUESDAY
        # But the full weekly schedule preserves EVERY cleaning day.
        assert {w.day for w in result.weekly_schedule.windows} == {
            ASPDay.TUESDAY,
            ASPDay.FRIDAY,
        }

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

    def test_suspended_dates_skips_holiday_in_next_window(self) -> None:
        """compute_schedule skips Tuesday when Tuesday is a holiday -> lands on Friday."""
        sign_result = _make_sign_result(
            "NO PARKING (SANITATION BROOM SYMBOL) TUESDAY FRIDAY 11:30AM-1PM <->"
        )
        # Monday 3PM; next cleaning is Tuesday but Tuesday is a holiday
        # 2026-02-23 is Monday, 2026-02-24 is Tuesday, 2026-02-27 is Friday
        now = datetime(2026, 2, 23, 15, 0, tzinfo=NYC_TZ)
        tuesday = date(2026, 2, 24)
        result = compute_schedule(
            sign_result, now=now, suspended_dates=frozenset({tuesday})
        )
        assert isinstance(result, ScheduleFound)
        assert result.next_window is not None
        assert result.next_window.day == ASPDay.FRIDAY
        assert result.next_window.start_datetime.date() == date(2026, 2, 27)


# ---------------------------------------------------------------------------
# Phase 35.1 regression tests: find_next_window suspended_dates contract
#
# These tests guard BUG-H-003 (vendored copy lacked the suspended_dates
# parameter on find_next_window, so HA's Stage-3 call passing the kwarg
# raised AttributeError, which was silently swallowed by the coordinator's
# `except Exception`). Plan 35.1-01 Task 2 syncs the kwarg-aware signature
# into the vendored copy; these tests document the contract.
# ---------------------------------------------------------------------------

from gps2asp.schedule.next_move import NYC_TZ as _NEXT_MOVE_NYC_TZ  # noqa: E402


def test_find_next_window_skips_holiday_dates() -> None:
    """find_next_window with suspended_dates skips matching candidate dates."""
    # 2026-01-12 is a Monday; 2026-01-19 is the following Monday.
    schedule = WeeklySchedule(
        windows=(
            TimeWindow(
                day=ASPDay.MONDAY,
                start_time=time(9, 0),
                end_time=time(10, 30),
                source_sign="test",
            ),
        )
    )
    now = datetime(2026, 1, 12, 8, 0, tzinfo=_NEXT_MOVE_NYC_TZ)
    result = find_next_window(
        schedule,
        now=now,
        suspended_dates=frozenset({date(2026, 1, 12)}),
    )
    assert result is not None
    assert result.start_datetime.date() == date(2026, 1, 19)


def test_find_next_window_no_suspended_dates_returns_today() -> None:
    """Without suspended_dates, the same Monday-9AM window returns today's 9AM occurrence."""
    schedule = WeeklySchedule(
        windows=(
            TimeWindow(
                day=ASPDay.MONDAY,
                start_time=time(9, 0),
                end_time=time(10, 30),
                source_sign="test",
            ),
        )
    )
    now = datetime(2026, 1, 12, 8, 0, tzinfo=_NEXT_MOVE_NYC_TZ)
    result = find_next_window(schedule, now=now)
    assert result is not None
    assert result.start_datetime.date() == date(2026, 1, 12)
    assert result.start_time == time(9, 0)


# ---------------------------------------------------------------------------
# Phase 35.1 BUG-T-003: find_active_window two-layer contract
#
# Per RESEARCH.md Open Question 2, the chosen disposition is "keep the
# late-merge pattern": find_active_window intentionally does NOT consult
# suspended_dates. Suspension annotation is the responsibility of the
# apply_suspension merge layer. This test pins the contract so it cannot
# silently regress.
# ---------------------------------------------------------------------------

from gps2asp.suspension import SuspensionInfo  # noqa: E402
from gps2asp.suspension.merge import apply_suspension  # noqa: E402


def test_find_active_window_holiday_two_layer_contract() -> None:
    """find_active_window returns the window unconditionally; apply_suspension flips suspended."""
    # 2026-01-19 is Martin Luther King Jr. Day (Monday), a NYC ASP holiday.
    schedule = WeeklySchedule(
        windows=(
            TimeWindow(
                day=ASPDay.MONDAY,
                start_time=time(9, 0),
                end_time=time(10, 30),
                source_sign="test-mlk",
            ),
        )
    )
    now = datetime(2026, 1, 19, 9, 30, tzinfo=NYC_TZ)

    # Layer 1: find_active_window is suspension-unaware.
    active = find_active_window(schedule, now)
    assert active is not None
    assert active.day == ASPDay.MONDAY

    # Layer 2: apply_suspension annotates the result.
    asp_active_now = ASPActiveNow(
        status="asp_active_now",
        active_window=active,
        weekly_schedule=schedule,
        on_street="TEST ST",
        from_street="1ST AVE",
        to_street="2ND AVE",
        side_of_street="N",
        source_signs=["test-mlk"],
        summary="MON 9 - 10:30 AM",
    )
    info = SuspensionInfo(is_suspended=True, reason="MLK Day", source="holiday")
    merged = apply_suspension(asp_active_now, info)
    assert isinstance(merged, ASPActiveNow)
    assert merged.suspended is True
    assert merged.suspension_reason == "MLK Day"
    assert merged.resolution_reason == "suspended_holiday"


# ---------------------------------------------------------------------------
# Phase 35.1 BUG-T-002: find_next_window distinguishes failure causes
#
# Pre-fix, find_next_window logged a single generic warning regardless of
# why no next window was found. Operators could not distinguish "schedule
# is empty" from "all candidate days fell on a holiday". The fix
# differentiates by setting a `had_any_windows` flag inside the loop and
# emitting a cause-specific warning when no match is found.
# ---------------------------------------------------------------------------


import logging  # noqa: E402


def test_find_next_window_distinguishes_empty_schedule(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Empty WeeklySchedule logs 'no windows in schedule' and returns None."""
    schedule = WeeklySchedule(windows=())
    now = datetime(2026, 2, 23, 15, 0, tzinfo=NYC_TZ)

    with caplog.at_level(logging.WARNING, logger="gps2asp.schedule.next_move"):
        result = find_next_window(schedule, now=now)

    assert result is None
    assert any("no windows in schedule" in r.message.lower() for r in caplog.records), (
        f"Expected 'no windows in schedule' warning, got: {[r.message for r in caplog.records]}"
    )


def test_find_next_window_distinguishes_all_suspended(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """All candidate dates suspended logs the cause-specific warning and returns None."""
    # Monday-only schedule; suspended_dates covers every date in the 8-day window.
    schedule = WeeklySchedule(
        windows=(
            TimeWindow(
                day=ASPDay.MONDAY,
                start_time=time(9, 0),
                end_time=time(10, 30),
                source_sign="test",
            ),
        )
    )
    now = datetime(2026, 2, 23, 15, 0, tzinfo=NYC_TZ)
    suspended = frozenset({now.date() + timedelta(days=i) for i in range(8)})

    with caplog.at_level(logging.WARNING, logger="gps2asp.schedule.next_move"):
        result = find_next_window(schedule, now=now, suspended_dates=suspended)

    assert result is None
    assert any(
        "suspended" in r.message.lower() and "candidate" in r.message.lower()
        for r in caplog.records
    ), (
        f"Expected 'all candidate ... suspended' warning, got: {[r.message for r in caplog.records]}"
    )
