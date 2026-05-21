"""Comprehensive unit tests for the ASP sign description parser.

Covers all format variations observed in the SODA dataset (447 unique
patterns): standard day+time, MOON & STARS night signs, EXCEPT SUNDAY,
dash ranges, NOON/MIDNIGHT, arrow/SUPERSEDES stripping, and template
sign rejection.
"""

from __future__ import annotations

from datetime import time

import pytest

from gps2asp.schedule.models import ASPDay
from gps2asp.schedule.parser import extract_days, parse_sign, parse_time_token


# ---------------------------------------------------------------------------
# TestParseTimeToken
# ---------------------------------------------------------------------------


class TestParseTimeToken:
    """Tests for parse_time_token()."""

    def test_standard_am(self) -> None:
        assert parse_time_token("8AM") == time(8, 0)

    def test_standard_am_with_minutes(self) -> None:
        assert parse_time_token("8:30AM") == time(8, 30)

    def test_standard_pm(self) -> None:
        assert parse_time_token("1PM") == time(13, 0)

    def test_standard_am_late_morning(self) -> None:
        assert parse_time_token("11:30AM") == time(11, 30)

    def test_12pm_is_noon(self) -> None:
        """12PM is noon (12:00), not midnight."""
        assert parse_time_token("12PM") == time(12, 0)

    def test_12am_is_midnight(self) -> None:
        """12AM is midnight (00:00), not noon."""
        assert parse_time_token("12AM") == time(0, 0)

    def test_12_30pm(self) -> None:
        assert parse_time_token("12:30PM") == time(12, 30)

    def test_noon_special_token(self) -> None:
        assert parse_time_token("NOON") == time(12, 0)

    def test_midnight_special_token(self) -> None:
        assert parse_time_token("MIDNIGHT") == time(0, 0)

    def test_case_insensitive_noon(self) -> None:
        assert parse_time_token("noon") == time(12, 0)

    def test_case_insensitive_midnight(self) -> None:
        assert parse_time_token("midnight") == time(0, 0)

    def test_case_insensitive_am(self) -> None:
        assert parse_time_token("8am") == time(8, 0)

    def test_garbage_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Cannot parse time token"):
            parse_time_token("GARBAGE")

    def test_3am(self) -> None:
        assert parse_time_token("3AM") == time(3, 0)

    def test_6am(self) -> None:
        assert parse_time_token("6AM") == time(6, 0)

    def test_9_30am(self) -> None:
        assert parse_time_token("9:30AM") == time(9, 30)

    def test_10am(self) -> None:
        assert parse_time_token("10AM") == time(10, 0)

    def test_1_30pm(self) -> None:
        assert parse_time_token("1:30PM") == time(13, 30)


# ---------------------------------------------------------------------------
# TestExtractDays
# ---------------------------------------------------------------------------


class TestExtractDays:
    """Tests for extract_days()."""

    def test_single_day(self) -> None:
        assert extract_days("TUESDAY") == [ASPDay.TUESDAY]

    def test_two_days_space_separated(self) -> None:
        assert extract_days("TUESDAY FRIDAY") == [
            ASPDay.TUESDAY,
            ASPDay.FRIDAY,
        ]

    def test_three_days(self) -> None:
        assert extract_days("MONDAY WEDNESDAY FRIDAY") == [
            ASPDay.MONDAY,
            ASPDay.WEDNESDAY,
            ASPDay.FRIDAY,
        ]

    def test_dash_range_monday_friday(self) -> None:
        """MONDAY-FRIDAY should expand to all 5 weekdays."""
        assert extract_days("MONDAY-FRIDAY") == [
            ASPDay.MONDAY,
            ASPDay.TUESDAY,
            ASPDay.WEDNESDAY,
            ASPDay.THURSDAY,
            ASPDay.FRIDAY,
        ]

    def test_except_sunday(self) -> None:
        """EXCEPT SUNDAY should return Mon through Sat (6 days)."""
        assert extract_days("EXCEPT SUNDAY") == [
            ASPDay.MONDAY,
            ASPDay.TUESDAY,
            ASPDay.WEDNESDAY,
            ASPDay.THURSDAY,
            ASPDay.FRIDAY,
            ASPDay.SATURDAY,
        ]

    def test_no_days_returns_empty(self) -> None:
        assert extract_days("") == []

    def test_no_days_in_random_text(self) -> None:
        assert extract_days("8:30AM-9AM") == []

    def test_case_insensitive(self) -> None:
        assert extract_days("tuesday friday") == [
            ASPDay.TUESDAY,
            ASPDay.FRIDAY,
        ]

    def test_four_days(self) -> None:
        assert extract_days("MONDAY TUESDAY THURSDAY FRIDAY") == [
            ASPDay.MONDAY,
            ASPDay.TUESDAY,
            ASPDay.THURSDAY,
            ASPDay.FRIDAY,
        ]

    def test_single_monday(self) -> None:
        assert extract_days("MONDAY") == [ASPDay.MONDAY]

    def test_wednesday_saturday(self) -> None:
        assert extract_days("WEDNESDAY SATURDAY") == [
            ASPDay.WEDNESDAY,
            ASPDay.SATURDAY,
        ]

    def test_tuesday_thursday_saturday(self) -> None:
        assert extract_days("TUESDAY THURSDAY SATURDAY") == [
            ASPDay.TUESDAY,
            ASPDay.THURSDAY,
            ASPDay.SATURDAY,
        ]


# ---------------------------------------------------------------------------
# TestParseSign
# ---------------------------------------------------------------------------


class TestParseSign:
    """Tests for parse_sign() -- the main entry point."""

    # --- Top 10 most common SODA patterns ---

    def test_top1_tuesday_friday_1130am_1pm(self) -> None:
        """Most common pattern (7,260 records)."""
        result = parse_sign(
            "NO PARKING (SANITATION BROOM SYMBOL) TUESDAY FRIDAY 11:30AM-1PM <->"
        )
        assert result is not None
        assert len(result) == 2
        assert result[0].day == ASPDay.TUESDAY
        assert result[1].day == ASPDay.FRIDAY
        assert result[0].start_time == time(11, 30)
        assert result[0].end_time == time(13, 0)

    def test_top2_monday_thursday_1130am_1pm(self) -> None:
        """Second most common pattern (7,172 records)."""
        result = parse_sign(
            "NO PARKING (SANITATION BROOM SYMBOL) MONDAY THURSDAY 11:30AM-1PM <->"
        )
        assert result is not None
        assert len(result) == 2
        assert result[0].day == ASPDay.MONDAY
        assert result[1].day == ASPDay.THURSDAY

    def test_top3_tuesday_1130am_1pm(self) -> None:
        """Single-day pattern (5,385 records)."""
        result = parse_sign(
            "NO PARKING (SANITATION BROOM SYMBOL) TUESDAY 11:30AM-1PM <->"
        )
        assert result is not None
        assert len(result) == 1
        assert result[0].day == ASPDay.TUESDAY
        assert result[0].start_time == time(11, 30)
        assert result[0].end_time == time(13, 0)

    def test_top6_tuesday_friday_11am_1230pm(self) -> None:
        """11AM-12:30PM pattern (5,086 records)."""
        result = parse_sign(
            "NO PARKING (SANITATION BROOM SYMBOL) TUESDAY FRIDAY 11AM-12:30PM <->"
        )
        assert result is not None
        assert len(result) == 2
        assert result[0].start_time == time(11, 0)
        assert result[0].end_time == time(12, 30)

    def test_top9_tuesday_friday_8am_930am(self) -> None:
        """8AM-9:30AM pattern (4,924 records)."""
        result = parse_sign(
            "NO PARKING (SANITATION BROOM SYMBOL) TUESDAY FRIDAY 8AM-9:30AM <->"
        )
        assert result is not None
        assert len(result) == 2
        assert result[0].start_time == time(8, 0)
        assert result[0].end_time == time(9, 30)

    def test_top10_tuesday_friday_930am_11am(self) -> None:
        """9:30AM-11AM pattern (4,866 records)."""
        result = parse_sign(
            "NO PARKING (SANITATION BROOM SYMBOL) TUESDAY FRIDAY 9:30AM-11AM <->"
        )
        assert result is not None
        assert len(result) == 2
        assert result[0].start_time == time(9, 30)
        assert result[0].end_time == time(11, 0)

    # --- Special format variations ---

    def test_moon_and_stars_night_sign(self) -> None:
        """MOON & STARS night cleaning sign."""
        result = parse_sign(
            "NO PARKING (SANITATION BROOM SYMBOL) MOON & STARS (SYMBOLS) "
            "MONDAY THURSDAY MIDNIGHT-3AM <->"
        )
        assert result is not None
        assert len(result) == 2
        assert result[0].day == ASPDay.MONDAY
        assert result[1].day == ASPDay.THURSDAY
        assert result[0].start_time == time(0, 0)
        assert result[0].end_time == time(3, 0)

    def test_except_sunday(self) -> None:
        """EXCEPT SUNDAY -- 6 days a week."""
        result = parse_sign(
            "NO PARKING (SANITATION BROOM SYMBOL) 8:30AM-9AM EXCEPT SUNDAY <->"
        )
        assert result is not None
        assert len(result) == 6
        days = [w.day for w in result]
        assert ASPDay.SUNDAY not in days
        assert ASPDay.MONDAY in days
        assert ASPDay.SATURDAY in days
        assert result[0].start_time == time(8, 30)
        assert result[0].end_time == time(9, 0)

    def test_monday_friday_dash_range(self) -> None:
        """MONDAY-FRIDAY dash range -- 5 weekdays."""
        result = parse_sign(
            "NO PARKING (SANITATION BROOM SYMBOL) MONDAY-FRIDAY 8AM-9AM <->"
        )
        assert result is not None
        assert len(result) == 5
        days = [w.day for w in result]
        assert days == [
            ASPDay.MONDAY,
            ASPDay.TUESDAY,
            ASPDay.WEDNESDAY,
            ASPDay.THURSDAY,
            ASPDay.FRIDAY,
        ]

    def test_night_regulation_prefix(self) -> None:
        """NIGHT REGULATION prefix before standard prefix."""
        result = parse_sign(
            "NIGHT REGULATION (MOON & STAR SYMBOLS) "
            "NO PARKING (SANITATION BROOM SYMBOL) MOON & STARS (SYMBOLS) "
            "MONDAY THURSDAY 2AM-6AM <->"
        )
        assert result is not None
        assert len(result) == 2
        assert result[0].day == ASPDay.MONDAY
        assert result[1].day == ASPDay.THURSDAY
        assert result[0].start_time == time(2, 0)
        assert result[0].end_time == time(6, 0)

    def test_supersedes_suffix(self) -> None:
        """SUPERSEDES suffix stripped correctly."""
        result = parse_sign(
            "NO PARKING (SANITATION BROOM SYMBOL) TUESDAY FRIDAY "
            "8AM-9:30AM <-> (SUPERSEDES SP-361C)"
        )
        assert result is not None
        assert len(result) == 2
        assert result[0].start_time == time(8, 0)
        assert result[0].end_time == time(9, 30)

    def test_noon_time_token(self) -> None:
        """NOON as end time."""
        result = parse_sign(
            "NO PARKING (SANITATION BROOM SYMBOL) TUESDAY FRIDAY 10:30AM-NOON <->"
        )
        assert result is not None
        assert len(result) == 2
        assert result[0].start_time == time(10, 30)
        assert result[0].end_time == time(12, 0)

    def test_unidirectional_arrow(self) -> None:
        """Unidirectional arrow (-->) stripped correctly."""
        result = parse_sign("NO PARKING (SANITATION BROOM SYMBOL) TUESDAY 8AM-9AM -->")
        assert result is not None
        assert len(result) == 1
        assert result[0].day == ASPDay.TUESDAY

    # --- Failure cases ---

    def test_template_sign_returns_none(self) -> None:
        """Template/placeholder sign must return None."""
        result = parse_sign(
            "NO PARKING <----> SANITATION BROOM (SYMBOL) XYY-XYY "
            '"DAY" THRU "DAY" (TIMES & DAYS TO BE SPECIFIED) '
            "(FOR CIRCULAR BUS SIGNS)"
        )
        assert result is None

    def test_non_standard_prefix_returns_none(self) -> None:
        """Sign without the standard prefix must return None."""
        result = parse_sign("SOME RANDOM TEXT TUESDAY 8AM-9AM")
        assert result is None

    def test_garbled_time_returns_none(self) -> None:
        """Garbled/missing time must return None."""
        result = parse_sign(
            "NO PARKING (SANITATION BROOM SYMBOL) TUESDAY FRIDAY GARBLED <->"
        )
        assert result is None

    def test_days_but_no_time_returns_none(self) -> None:
        """Days present but no time window must return None."""
        result = parse_sign("NO PARKING (SANITATION BROOM SYMBOL) TUESDAY FRIDAY <->")
        assert result is None

    def test_time_but_no_days_returns_none(self) -> None:
        """Time present but no days and no EXCEPT clause must return None."""
        result = parse_sign("NO PARKING (SANITATION BROOM SYMBOL) 8AM-9AM <->")
        assert result is None

    # --- Source tracking and structural verification ---

    def test_source_sign_tracking(self) -> None:
        """Returned TimeWindow objects track the original sign text."""
        original = "NO PARKING (SANITATION BROOM SYMBOL) TUESDAY FRIDAY 11:30AM-1PM <->"
        result = parse_sign(original)
        assert result is not None
        for window in result:
            assert window.source_sign == original

    def test_day_count_two_days(self) -> None:
        """Two days in sign produces exactly 2 TimeWindow objects."""
        result = parse_sign(
            "NO PARKING (SANITATION BROOM SYMBOL) TUESDAY FRIDAY 11:30AM-1PM <->"
        )
        assert result is not None
        assert len(result) == 2

    def test_three_day_sign(self) -> None:
        """Three-day sign produces 3 TimeWindow objects."""
        result = parse_sign(
            "NO PARKING (SANITATION BROOM SYMBOL) MONDAY WEDNESDAY FRIDAY "
            "8AM-9:30AM <->"
        )
        assert result is not None
        assert len(result) == 3
        assert result[0].day == ASPDay.MONDAY
        assert result[1].day == ASPDay.WEDNESDAY
        assert result[2].day == ASPDay.FRIDAY

    def test_all_windows_share_same_times(self) -> None:
        """All windows from a single sign have the same time range."""
        result = parse_sign(
            "NO PARKING (SANITATION BROOM SYMBOL) MONDAY THURSDAY 11:30AM-1PM <->"
        )
        assert result is not None
        for window in result:
            assert window.start_time == time(11, 30)
            assert window.end_time == time(13, 0)

    def test_except_sunday_30min_windows(self) -> None:
        """EXCEPT SUNDAY with short (30min) window."""
        result = parse_sign(
            "NO PARKING (SANITATION BROOM SYMBOL) 7:30AM-8AM EXCEPT SUNDAY <->"
        )
        assert result is not None
        assert len(result) == 6
        assert result[0].start_time == time(7, 30)
        assert result[0].end_time == time(8, 0)

    def test_moon_stars_singular_symbol(self) -> None:
        """MOON & STAR (SYMBOL) singular variant."""
        result = parse_sign(
            "NO PARKING (SANITATION BROOM SYMBOL) MOON & STAR (SYMBOL) "
            "TUESDAY FRIDAY MIDNIGHT-3AM <->"
        )
        assert result is not None
        assert len(result) == 2

    def test_supersedes_with_ampersand(self) -> None:
        """SUPERSEDES with multiple codes joined by &."""
        result = parse_sign(
            "NO PARKING (SANITATION BROOM SYMBOL) TUESDAY FRIDAY "
            "8AM-9:30AM <-> (SUPERSEDES SP-379C & SP-454C)"
        )
        assert result is not None
        assert len(result) == 2

    def test_saturday_single_day(self) -> None:
        """Saturday single-day pattern."""
        result = parse_sign(
            "NO PARKING (SANITATION BROOM SYMBOL) SATURDAY 8AM-9:30AM <->"
        )
        assert result is not None
        assert len(result) == 1
        assert result[0].day == ASPDay.SATURDAY


# ---------------------------------------------------------------------------
# Phase 35.1 BUG-T-004: Cross-midnight parser regression tests
#
# These tests guard the cross-midnight window admission contract documented
# in RESEARCH.md Pitfall 3. Pre-fix, parse_sign() returned None for any sign
# whose end time was MIDNIGHT (00:00) because end_time <= start_time was True
# for any non-midnight start. Night Regulation signs like
# "MONDAY 11PM-MIDNIGHT" were therefore wholly unparseable in production.
#
# Fix scheme (Pitfall 3 option a): truncate the end at time(23, 59, 59) so
# the window lives entirely within a single day, leaving downstream callers
# (merge, summary, find_active_window, find_next_window) unchanged.
# ---------------------------------------------------------------------------


class TestCrossMidnightWindow:
    """BUG-T-004 regression: parse_sign accepts cross-midnight windows."""

    def test_parse_cross_midnight_11pm_to_midnight(self) -> None:
        """11PM-MIDNIGHT must produce a single Monday 23:00-23:59:59 window."""
        sign = (
            "NIGHT REGULATION (MOON & STARS SYMBOLS) "
            "NO PARKING (SANITATION BROOM SYMBOL) "
            "MONDAY 11PM-MIDNIGHT <->"
        )
        result = parse_sign(sign)
        assert result is not None, (
            "Cross-midnight Night Regulation sign must parse (BUG-T-004)"
        )
        assert len(result) == 1
        assert result[0].day == ASPDay.MONDAY
        assert result[0].start_time == time(23, 0)
        assert result[0].end_time == time(23, 59, 59)

    def test_parse_cross_midnight_with_minutes(self) -> None:
        """10:30PM-MIDNIGHT must produce a Tuesday 22:30-23:59:59 window."""
        sign = (
            "NO PARKING (SANITATION BROOM SYMBOL) "
            "TUESDAY 10:30PM-MIDNIGHT <->"
        )
        result = parse_sign(sign)
        assert result is not None
        assert len(result) == 1
        assert result[0].day == ASPDay.TUESDAY
        assert result[0].start_time == time(22, 30)
        assert result[0].end_time == time(23, 59, 59)

    def test_parse_midnight_to_3am_still_works(self) -> None:
        """Existing MIDNIGHT-3AM pattern remains a normal same-day window (regression guard)."""
        result = parse_sign(
            "NO PARKING (SANITATION BROOM SYMBOL) MOON & STARS (SYMBOLS) "
            "MONDAY MIDNIGHT-3AM <->"
        )
        assert result is not None
        assert len(result) == 1
        assert result[0].start_time == time(0, 0)
        assert result[0].end_time == time(3, 0)

    def test_parse_reverse_non_midnight_window_still_rejected(self) -> None:
        """Degenerate non-midnight reversal like 9AM-8AM is still rejected."""
        result = parse_sign(
            "NO PARKING (SANITATION BROOM SYMBOL) MONDAY 9AM-8AM <->"
        )
        assert result is None

    def test_parse_midnight_to_midnight_is_rejected(self) -> None:
        """MIDNIGHT-MIDNIGHT is zero-length and is still rejected."""
        result = parse_sign(
            "NO PARKING (SANITATION BROOM SYMBOL) MONDAY MIDNIGHT-MIDNIGHT <->"
        )
        assert result is None
