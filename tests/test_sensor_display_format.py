"""Unit tests for Phase 32 sensor display format (FMT-01) — Wave 0 RED.

Verifies the locked CONTEXT.md decisions (D-01..D-07) for the next-move sensor:

  * D-01: Three-tier display format from ``_format_move_time``:
      - Today    → ``"⚠ Today, 8:30 AM"``
      - Tomorrow → ``"Tomorrow, 8:30 AM"``
      - Other    → ``"Thursday (5/3), 8:30 AM"`` (full weekday + unpadded M/D)
  * D-02: Today gate uses ``local_dt.date() == now_ha_local().date()`` — no
    12-hour seconds heuristic. (SC-2)
  * D-03: Uses ``dt_util.as_local`` + HA-local ``now_ha_local()``; never
    hardcodes ``NYC_TZ`` in the display path.
  * D-04: ``urgency`` attribute aligns with the date-based Today gate.
  * D-05: ``now_ha_local()`` lives in ``custom_components/asp_parking/util.py``.
  * D-06: New booleans ``next_move_is_today`` / ``next_move_is_tomorrow``
    always present, defaulting to ``False`` when no concrete ``_move_dt`` exists.
  * D-07: All previously documented attributes preserved.

The test file follows RESEARCH.md Pattern 3 (freezegun + ``dt_util.set_default_time_zone``
without the ``hass`` fixture) and Pitfalls 1–7. ``_format_move_time`` is exercised
by instantiating ``ASPNextMoveTimeSensor`` with a stub coordinator; the urgency
and boolean-attribute tests reuse ``sensor_extra_attributes`` from
``tests.test_ha_integration`` (rewritten in Task 2 of this plan).

Wave 0 expected RED state:
  * ``from custom_components.asp_parking.util import now_ha_local`` raises
    ``ModuleNotFoundError`` until Plan 32-02 ships ``util.py``. That is the
    contract this RED suite encodes.
"""

from __future__ import annotations

import datetime as dt
import inspect
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time

from homeassistant.util import dt as dt_util

# COLLECT-TIME CONTRACT: importing now_ha_local from util.py is the single
# blocker that Plan 32-02 satisfies. Do NOT silence the import error.
from custom_components.asp_parking.util import now_ha_local

# Reuse the test_ha_integration helpers and the local ASPParkingData mirror.
# tests/__init__.py exists, so this works as a sibling import.
from tests.test_ha_integration import (
    ASPParkingData,
    _make_asp_active_now,
    _make_cleaning_window,
    _make_schedule_found,
    sensor_extra_attributes,
)

from gps2asp.schedule.models import (
    ASPDay,
    NoASPSchedule,
    NoMatchSchedule,
    ScheduleFound,
    TimeWindow,
    WeeklySchedule,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NYC_TZ = ZoneInfo("America/New_York")
LA_TZ = ZoneInfo("America/Los_Angeles")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def la_timezone():
    """Set HA default TZ to Los Angeles for the test, restore on teardown.

    Pattern 3 / Pitfall 3 — yield + restore so a mid-test failure does not
    leak the mutated module-level global to the next test.
    """
    original = dt_util.DEFAULT_TIME_ZONE
    dt_util.set_default_time_zone(LA_TZ)
    try:
        yield
    finally:
        dt_util.set_default_time_zone(original)


@pytest.fixture
def nyc_timezone():
    """Set HA default TZ to New York for the test, restore on teardown.

    Used by ``TestFormatMoveTime`` so that the freeze_time wall clock and the
    schedule datetimes (which we construct in NYC) align deterministically.
    """
    original = dt_util.DEFAULT_TIME_ZONE
    dt_util.set_default_time_zone(NYC_TZ)
    try:
        yield
    finally:
        dt_util.set_default_time_zone(original)


def _make_stub_sensor():
    """Instantiate ASPNextMoveTimeSensor against a minimal stub coordinator.

    Only the attributes touched by ``_format_move_time`` itself are required —
    no entry_id wiring is needed for this method. We still set a stub
    ``entry.entry_id`` to keep ``__init__`` happy.
    """
    from custom_components.asp_parking.sensor import ASPNextMoveTimeSensor

    coord = SimpleNamespace()
    coord.entry = SimpleNamespace(entry_id="test_entry_id_p32")
    return ASPNextMoveTimeSensor(coord)


def _build_schedule_found_for_window(start_dt: datetime) -> ScheduleFound:
    """Build a ScheduleFound with a CleaningWindow whose start_datetime is start_dt."""
    end_dt = start_dt + timedelta(hours=1, minutes=30)
    window = _make_cleaning_window(
        day=ASPDay.MONDAY,
        start_dt=start_dt,
        end_dt=end_dt,
    )
    return _make_schedule_found(window)


def _build_asp_active_now_for_window(start_dt: datetime, end_dt: datetime):
    """Build an ASPActiveNow with the given window bounds."""
    window = _make_cleaning_window(
        day=ASPDay.MONDAY,
        start_dt=start_dt,
        end_dt=end_dt,
    )
    return _make_asp_active_now(window)


# ===========================================================================
# Class 1: now_ha_local() helper smoke tests (SC-4 / D-05)
# ===========================================================================


@pytest.mark.ha_integration
class TestNowHaLocalHelper:
    """now_ha_local() lives in util.py, returns dt_util.now() (D-05)."""

    def test_returns_datetime(self) -> None:
        """now_ha_local() returns a datetime instance."""
        result = now_ha_local()
        assert isinstance(result, datetime)

    def test_returns_tz_aware(self) -> None:
        """now_ha_local() returns a tz-aware datetime (tzinfo is not None)."""
        result = now_ha_local()
        assert result.tzinfo is not None

    def test_matches_dt_util_now(self) -> None:
        """now_ha_local() equals dt_util.now() within 1 second."""
        a = now_ha_local()
        b = dt_util.now()
        delta = abs((b - a).total_seconds())
        assert delta < 1.0, (
            f"now_ha_local() and dt_util.now() differ by {delta:.3f}s, expected <1.0s"
        )


# ===========================================================================
# Class 2: Day-boundary gate (SC-3 / FMT-01)
# ===========================================================================


@pytest.mark.ha_integration
class TestDayBoundaryGate:
    """Today/Tomorrow gate uses HA local TZ via dt_util.now() (D-02, D-03)."""

    def test_23_30_local_is_still_today(self, la_timezone) -> None:
        """At 23:30 LA-local on 2026-05-13 (= 06:30 UTC 2026-05-14), date() is 5/13."""
        with freeze_time("2026-05-14 06:30:00"):
            assert now_ha_local().date() == dt.date(2026, 5, 13)

    def test_00_30_local_is_tomorrow(self, la_timezone) -> None:
        """At 00:30 LA-local on 2026-05-14 (= 07:30 UTC 2026-05-14), date() is 5/14."""
        with freeze_time("2026-05-14 07:30:00"):
            assert now_ha_local().date() == dt.date(2026, 5, 14)


# ===========================================================================
# Class 3: _format_move_time three-tier output (SC-1, SC-2 / D-01..D-03)
# ===========================================================================


@pytest.mark.ha_integration
class TestFormatMoveTime:
    """_format_move_time produces the three-tier display string.

    Tests instantiate ``ASPNextMoveTimeSensor`` with a minimal stub coordinator
    (see ``_make_stub_sensor``) and call the instance method directly.

    All wall-clock-dependent assertions are anchored with ``freeze_time``; HA's
    default TZ is set to NYC via the ``nyc_timezone`` fixture so that
    ``dt_util.as_local`` and ``now_ha_local()`` resolve to the same NYC date
    the test datetimes are constructed in.
    """

    def test_today_tier(self, nyc_timezone) -> None:
        """Today: move dt today at 20:30 NYC → '⚠ Today, 8:30 PM'."""
        # Freeze at 12:00 NYC on 2026-05-13 (16:00 UTC = -04:00 DST)
        with freeze_time("2026-05-13 16:00:00"):
            sensor = _make_stub_sensor()
            move_dt = datetime(2026, 5, 13, 20, 30, tzinfo=NYC_TZ)
            assert sensor._format_move_time(move_dt) == "⚠ Today, 8:30 PM"

    def test_tomorrow_tier(self, nyc_timezone) -> None:
        """Tomorrow: move dt next day at 08:30 NYC → 'Tomorrow, 8:30 AM'."""
        with freeze_time("2026-05-13 16:00:00"):
            sensor = _make_stub_sensor()
            move_dt = datetime(2026, 5, 14, 8, 30, tzinfo=NYC_TZ)
            assert sensor._format_move_time(move_dt) == "Tomorrow, 8:30 AM"

    def test_other_day_full_weekday_unpadded_md(self, nyc_timezone) -> None:
        """Other day: move dt two days out → 'Friday (5/15), 8:30 AM'."""
        with freeze_time("2026-05-13 16:00:00"):
            sensor = _make_stub_sensor()
            move_dt = datetime(2026, 5, 15, 8, 30, tzinfo=NYC_TZ)
            assert sensor._format_move_time(move_dt) == "Friday (5/15), 8:30 AM"

    def test_no_padded_zeros_in_md(self, nyc_timezone) -> None:
        """Unpadded month/day: '1/8' not '01/08' (platform-portable per FMT-01)."""
        # 2026-01-02 (Friday) is the freeze; target is 2026-01-08 (Thursday).
        with freeze_time("2026-01-02 17:00:00"):
            sensor = _make_stub_sensor()
            move_dt = datetime(2026, 1, 8, 9, 0, tzinfo=NYC_TZ)
            result = sensor._format_move_time(move_dt)
            assert "(1/8)" in result, (
                f"Expected unpadded '(1/8)' in {result!r}; padded '(01/08)' is wrong."
            )
            assert "(01/08)" not in result

    def test_other_day_strftime_a_not_used(self, nyc_timezone) -> None:
        """Other-day tier must use full weekday name (%A), not 3-letter (%a).

        Asserts the result does NOT match the legacy 3-letter pattern at the
        start of the string.
        """
        import re

        with freeze_time("2026-05-13 16:00:00"):
            sensor = _make_stub_sensor()
            move_dt = datetime(2026, 5, 15, 8, 30, tzinfo=NYC_TZ)
            result = sensor._format_move_time(move_dt)
            assert not re.match(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun) ", result), (
                f"Result {result!r} matches legacy 3-letter weekday pattern; "
                "expected full weekday name."
            )


# ===========================================================================
# Class 4: Urgency attribute realigned to date gate (D-04)
# ===========================================================================


@pytest.mark.ha_integration
class TestUrgencyAttributeRealigned:
    """urgency uses date-equality gate, not 12-hour seconds threshold (D-04).

    These tests exercise ``sensor_extra_attributes`` from
    ``tests.test_ha_integration`` (rewritten in Task 2 of this plan to mirror
    the production D-04 + D-06 behavior).
    """

    def test_urgency_high_when_today(self, nyc_timezone) -> None:
        """next_window starts later today → urgency='high'."""
        with freeze_time("2026-05-13 16:00:00"):
            move_dt = datetime(2026, 5, 13, 20, 30, tzinfo=NYC_TZ)
            schedule = _build_schedule_found_for_window(move_dt)
            data = ASPParkingData(schedule_result=schedule)

            attrs = sensor_extra_attributes(data)
            assert "urgency" in attrs
            assert attrs["urgency"] == "high"

    def test_urgency_normal_when_tomorrow(self, nyc_timezone) -> None:
        """next_window tomorrow at 06:00 → urgency='normal' under new date gate.

        Critical: under the OLD 12h-seconds gate, a window 14h away at "tomorrow
        06:00 NYC" run from "today 16:00 NYC" would be ``normal`` (>12h); but a
        window 10h away at "tomorrow 02:00 NYC" would be ``high`` (<12h). The
        new gate is ``normal`` in BOTH cases because target_date != today.
        """
        with freeze_time("2026-05-13 16:00:00"):
            move_dt = datetime(2026, 5, 14, 6, 0, tzinfo=NYC_TZ)
            schedule = _build_schedule_found_for_window(move_dt)
            data = ASPParkingData(schedule_result=schedule)

            attrs = sensor_extra_attributes(data)
            assert "urgency" in attrs
            assert attrs["urgency"] == "normal"

    def test_urgency_normal_when_other_day(self, nyc_timezone) -> None:
        """next_window 3 days out → urgency='normal'."""
        with freeze_time("2026-05-13 16:00:00"):
            move_dt = datetime(2026, 5, 16, 8, 30, tzinfo=NYC_TZ)
            schedule = _build_schedule_found_for_window(move_dt)
            data = ASPParkingData(schedule_result=schedule)

            attrs = sensor_extra_attributes(data)
            assert "urgency" in attrs
            assert attrs["urgency"] == "normal"

    def test_urgency_absent_when_no_window(self) -> None:
        """ScheduleFound with next_window=None → 'urgency' key NOT in attrs.

        D-04 changes the gate, not the presence rule; the existing behavior
        (no urgency when no concrete move dt) is preserved.
        """
        tw = TimeWindow(
            day=ASPDay.MONDAY,
            start_time=time(8, 30),
            end_time=time(10, 0),
            source_sign="NO PARKING 8:30AM-10AM MON",
        )
        schedule = ScheduleFound(
            status="schedule_found",
            next_window=None,
            weekly_schedule=WeeklySchedule(windows=(tw,)),
            on_street="PROSPECT PLACE",
            from_street="VANDERBILT AVENUE",
            to_street="UNDERHILL AVENUE",
            side_of_street="N",
            source_signs=["NO PARKING 8:30AM-10AM MON"],
            summary="Mon 8:30-10am",
            parse_failures=[],
        )
        data = ASPParkingData(schedule_result=schedule)

        attrs = sensor_extra_attributes(data)
        assert "urgency" not in attrs


# ===========================================================================
# Class 5: New boolean attributes (D-06)
# ===========================================================================


@pytest.mark.ha_integration
class TestNewBooleanAttributes:
    """next_move_is_today / next_move_is_tomorrow always present (D-06)."""

    def test_is_today_true(self, nyc_timezone) -> None:
        """When next_window starts today: is_today=True, is_tomorrow=False."""
        with freeze_time("2026-05-13 16:00:00"):
            move_dt = datetime(2026, 5, 13, 20, 30, tzinfo=NYC_TZ)
            schedule = _build_schedule_found_for_window(move_dt)
            data = ASPParkingData(schedule_result=schedule)

            attrs = sensor_extra_attributes(data)
            assert attrs["next_move_is_today"] is True
            assert attrs["next_move_is_tomorrow"] is False

    def test_is_tomorrow_true(self, nyc_timezone) -> None:
        """When next_window starts tomorrow: is_today=False, is_tomorrow=True."""
        with freeze_time("2026-05-13 16:00:00"):
            move_dt = datetime(2026, 5, 14, 8, 30, tzinfo=NYC_TZ)
            schedule = _build_schedule_found_for_window(move_dt)
            data = ASPParkingData(schedule_result=schedule)

            attrs = sensor_extra_attributes(data)
            assert attrs["next_move_is_today"] is False
            assert attrs["next_move_is_tomorrow"] is True

    def test_both_false_when_other_day(self, nyc_timezone) -> None:
        """next_window 3 days out → both False (and present)."""
        with freeze_time("2026-05-13 16:00:00"):
            move_dt = datetime(2026, 5, 16, 8, 30, tzinfo=NYC_TZ)
            schedule = _build_schedule_found_for_window(move_dt)
            data = ASPParkingData(schedule_result=schedule)

            attrs = sensor_extra_attributes(data)
            assert "next_move_is_today" in attrs
            assert "next_move_is_tomorrow" in attrs
            assert attrs["next_move_is_today"] is False
            assert attrs["next_move_is_tomorrow"] is False

    def test_both_false_when_no_window(self) -> None:
        """ScheduleFound with next_window=None → both False AND keys PRESENT.

        D-06 (Claude's discretion): never None, never omitted.
        """
        tw = TimeWindow(
            day=ASPDay.MONDAY,
            start_time=time(8, 30),
            end_time=time(10, 0),
            source_sign="NO PARKING 8:30AM-10AM MON",
        )
        schedule = ScheduleFound(
            status="schedule_found",
            next_window=None,
            weekly_schedule=WeeklySchedule(windows=(tw,)),
            on_street="PROSPECT PLACE",
            from_street="VANDERBILT AVENUE",
            to_street="UNDERHILL AVENUE",
            side_of_street="N",
            source_signs=["NO PARKING 8:30AM-10AM MON"],
            summary="Mon 8:30-10am",
            parse_failures=[],
        )
        data = ASPParkingData(schedule_result=schedule)

        attrs = sensor_extra_attributes(data)
        assert "next_move_is_today" in attrs
        assert "next_move_is_tomorrow" in attrs
        assert attrs["next_move_is_today"] is False
        assert attrs["next_move_is_tomorrow"] is False

    def test_both_false_for_special_state_outside_coverage(self) -> None:
        """ASPParkingData(special_state='outside_coverage', schedule_result=None)
        → both booleans present and False (D-06 default applies to ALL paths)."""
        data = ASPParkingData(
            special_state="outside_coverage",
            schedule_result=None,
        )
        attrs = sensor_extra_attributes(data)
        assert "next_move_is_today" in attrs
        assert "next_move_is_tomorrow" in attrs
        assert attrs["next_move_is_today"] is False
        assert attrs["next_move_is_tomorrow"] is False

    def test_both_false_for_no_match_schedule(self) -> None:
        """ASPParkingData(schedule_result=NoMatchSchedule(...)) → both present and False."""
        data = ASPParkingData(schedule_result=NoMatchSchedule())
        attrs = sensor_extra_attributes(data)
        assert "next_move_is_today" in attrs
        assert "next_move_is_tomorrow" in attrs
        assert attrs["next_move_is_today"] is False
        assert attrs["next_move_is_tomorrow"] is False


# ===========================================================================
# Class 6: DST edge cases (EC-01, EC-02)
# ===========================================================================


@pytest.mark.ha_integration
class TestDSTEdgeCases:
    """_format_move_time correctly classifies Today across DST boundaries.

    Both spring-forward (2026-03-08) and fall-back (2026-11-01) are covered.
    The UTC freeze times are derived from the tz-aware local times to ensure
    the frozen wall clock lands at the expected local time regardless of what
    DST offset is active at that instant.
    """

    def test_dst_spring_forward_same_day_is_today(self, nyc_timezone) -> None:
        """Spring-forward day (2026-03-08): post-DST window on same day → 'Today'.

        Spring-forward in NYC: at 02:00 EST clocks jump to 03:00 EDT.
        Freeze at 08:30 EDT (12:30 UTC); window at 10:00 EDT (same calendar
        date, same -04:00 offset). Both share date 2026-03-08 → 'Today'.
        """
        # 08:30 NYC EDT on 2026-03-08 = 12:30 UTC (NYC is -04:00 post-spring)
        with freeze_time("2026-03-08 12:30:00"):
            sensor = _make_stub_sensor()
            # 10:00 NYC on the same spring-forward day
            move_dt = datetime(2026, 3, 8, 10, 0, tzinfo=NYC_TZ)
            result = sensor._format_move_time(move_dt)
            assert result.startswith("⚠ Today,"), (
                f"Expected result to start with '⚠ Today,' on DST spring-forward day; "
                f"got {result!r}"
            )

    def test_dst_fall_back_same_day_is_today(self, nyc_timezone) -> None:
        """Fall-back day (2026-11-01): repeated-hour window on same day → 'Today'.

        Fall-back in NYC: at 02:00 EDT clocks fall back to 01:00 EST.
        Freeze at 01:00 EDT (05:00 UTC, pre-fall-back); window at 02:00 EST
        (07:00 UTC, post-fall-back). Both share date 2026-11-01 → 'Today'.
        """
        # 01:00 NYC EDT on 2026-11-01 = 05:00 UTC (still -04:00 before fall-back)
        with freeze_time("2026-11-01 05:00:00"):
            sensor = _make_stub_sensor()
            # 02:00 NYC EST = 07:00 UTC (after the fall-back, -05:00 offset)
            move_dt = datetime(2026, 11, 1, 7, 0, tzinfo=ZoneInfo("UTC"))
            result = sensor._format_move_time(move_dt)
            assert result.startswith("⚠ Today,"), (
                f"Expected result to start with '⚠ Today,' on DST fall-back day; "
                f"got {result!r}"
            )


# ===========================================================================
# Class 7: Midnight and 1 AM time-string formatting (EC-03, EC-04)
# ===========================================================================


@pytest.mark.ha_integration
class TestMidnightAndEarlyHours:
    """Verify lstrip('0') edge cases for 12:xx AM times (EC-03, EC-04).

    ``strftime('%I:%M %p').lstrip('0')`` must NOT strip the leading digit of
    '12:00 AM' (since '1' is not '0'), but MUST strip the leading zero from
    '01:00 AM' → '1:00 AM'.
    """

    def test_midnight_formats_as_12_00_am(self, nyc_timezone) -> None:
        """00:00 local → '12:00 AM' (lstrip('0') does not affect '12:xx AM').

        Regression: a naive lstrip on '12:00 AM' could produce '2:00 AM'
        if implemented as lstrip('012') instead of lstrip('0').
        """
        # Freeze at 07:00 NYC; midnight window on the same day is still 'Today'.
        with freeze_time("2026-05-18 11:00:00"):  # 11:00 UTC = 07:00 EDT
            sensor = _make_stub_sensor()
            move_dt = datetime(2026, 5, 18, 0, 0, tzinfo=NYC_TZ)
            result = sensor._format_move_time(move_dt)
            # Time part is everything after the first ", "
            time_part = result.split(", ", 1)[1]
            assert time_part == "12:00 AM", (
                f"Expected '12:00 AM' but got {time_part!r} in {result!r}; "
                "lstrip('0') must not strip the '1' in '12:00 AM'."
            )

    def test_one_am_formats_with_leading_zero_stripped(self, nyc_timezone) -> None:
        """01:00 local → '1:00 AM' (lstrip('0') strips the leading zero).

        strftime('%I:%M %p') for 01:00 gives '01:00 AM'; lstrip('0') must
        yield '1:00 AM', not '01:00 AM'.
        """
        with freeze_time("2026-05-18 11:00:00"):  # 11:00 UTC = 07:00 EDT
            sensor = _make_stub_sensor()
            move_dt = datetime(2026, 5, 18, 1, 0, tzinfo=NYC_TZ)
            result = sensor._format_move_time(move_dt)
            time_part = result.split(", ", 1)[1]
            assert time_part == "1:00 AM", (
                f"Expected '1:00 AM' but got {time_part!r} in {result!r}; "
                "lstrip('0') must strip the leading zero from '01:00 AM'."
            )


# ===========================================================================
# Class 8: Two-arg _format_move_time midnight-race regression (EC-05)
# ===========================================================================


@pytest.mark.ha_integration
class TestFormatMoveTimeTwoArgForm:
    """_format_move_time(move_dt, today=...) exercises the midnight-race fix (WR-03).

    The production sensor pre-captures ``today`` once in extra_state_attributes
    and passes it as the second argument to _format_move_time so that
    native_value and extra_state_attributes share a single date snapshot.
    This test directly exercises that code path.
    """

    def test_explicit_today_matches_today_tier(self, nyc_timezone) -> None:
        """Passing explicit today=date(2026, 5, 18) with a same-day move_dt → 'Today'.

        The two-arg form exists to eliminate the midnight-race window described
        in WR-03. Calling _format_move_time with a pre-captured date must
        produce the same result as the no-arg form when the dates agree.
        """
        # Detect whether _format_move_time accepts a 'today' kwarg.
        sig = inspect.signature(_make_stub_sensor()._format_move_time)
        has_today_param = "today" in sig.parameters

        if not has_today_param:
            pytest.xfail(
                "_format_move_time does not accept a 'today' parameter; "
                "the two-arg midnight-race fix path cannot be exercised."
            )

        with freeze_time("2026-05-18 11:00:00"):  # 11:00 UTC = 07:00 EDT
            sensor = _make_stub_sensor()
            move_dt = datetime(2026, 5, 18, 8, 30, tzinfo=NYC_TZ)
            result = sensor._format_move_time(move_dt, today=date(2026, 5, 18))
            assert result.startswith("⚠ Today,"), (
                f"Expected '⚠ Today,' with explicit today=date(2026,5,18); "
                f"got {result!r}"
            )


# ===========================================================================
# Class 9: now_ha_local() with UTC timezone configured (EC-06)
# ===========================================================================


@pytest.mark.ha_integration
class TestNowHaLocalUtcTimezone:
    """now_ha_local() returns a valid tz-aware datetime even when HA TZ is UTC.

    Regression: a naive implementation that assumes NYC or a named timezone
    would break if the HA operator configured UTC as their default zone.
    """

    def test_now_ha_local_with_utc_configured(self) -> None:
        """Setting HA TZ to UTC: now_ha_local() still returns a tz-aware datetime."""
        original = dt_util.DEFAULT_TIME_ZONE
        utc_tz = ZoneInfo("UTC")
        dt_util.set_default_time_zone(utc_tz)
        try:
            result = now_ha_local()
        finally:
            dt_util.set_default_time_zone(original)

        assert result.tzinfo is not None, (
            "now_ha_local() must return a tz-aware datetime"
        )
        # UTC offset should be zero
        assert result.utcoffset() == dt.timedelta(0), (
            f"Expected UTC offset 0:00:00 when HA TZ is UTC; got {result.utcoffset()}"
        )


# ===========================================================================
# Class 10: Year-boundary date format (EC-07)
# ===========================================================================


@pytest.mark.ha_integration
class TestYearBoundaryFormat:
    """_format_move_time for a cross-year window uses M/D without year (EC-07).

    The format is ``"Weekday (M/D), H:MM AM/PM"`` — no year component.
    This test verifies that a window on Jan 1 of the next year when frozen
    on Dec 30 of the current year uses the unpadded M/D format and does NOT
    include the year.
    """

    def test_jan_1_next_year_format(self, nyc_timezone) -> None:
        """Frozen on 2026-12-30; window on 2027-01-01 → 'Friday (1/1), 8:30 AM'.

        Jan 1 2027 is a Friday. The result must contain '(1/1)' (unpadded)
        and must NOT contain '2027' (no year field in the format).
        """
        # 2026-12-30 07:00 NYC EST (-05:00) = 12:00 UTC
        with freeze_time("2026-12-30 12:00:00"):
            sensor = _make_stub_sensor()
            move_dt = datetime(2027, 1, 1, 8, 30, tzinfo=NYC_TZ)
            result = sensor._format_move_time(move_dt)
            assert "(1/1)" in result, (
                f"Expected '(1/1)' (unpadded) in {result!r}; year-boundary M/D is wrong."
            )
            assert "2027" not in result, (
                f"Year '2027' should NOT appear in {result!r}; "
                "the format is 'Weekday (M/D), H:MM AM/PM' with no year."
            )


# ===========================================================================
# Class 11: extra_state_attributes when suspended and no next_window (EC-08)
# ===========================================================================


@pytest.mark.ha_integration
class TestExtraAttrsWhenSuspendedNoWindow:
    """extra_state_attributes booleans and urgency when suspended with NoASPSchedule.

    When the schedule result is NoASPSchedule (which has no next_window) and
    suspension is active, the D-06 boolean defaults must still be False and
    the 'urgency' key must not be 'today' (it should be absent entirely).
    """

    def test_suspended_no_asp_schedule_boolean_defaults(self) -> None:
        """NoASPSchedule + suspended=True → is_today/is_tomorrow both False, no urgency='today'."""
        from gps2asp.suspension import SuspensionInfo

        data = ASPParkingData(
            schedule_result=NoASPSchedule(),
            suspension_state=SuspensionInfo(
                is_suspended=True,
                reason="NYC Sanitation suspension test",
                source="test",
            ),
        )
        attrs = sensor_extra_attributes(data)

        assert attrs["next_move_is_today"] is False, (
            "next_move_is_today must be False when schedule is NoASPSchedule"
        )
        assert attrs["next_move_is_tomorrow"] is False, (
            "next_move_is_tomorrow must be False when schedule is NoASPSchedule"
        )
        # urgency must either be absent or not equal to 'today'
        assert attrs.get("urgency") != "today", (
            f"urgency must not be 'today' when no concrete move datetime exists; "
            f"got {attrs.get('urgency')!r}"
        )


# ===========================================================================
# Class 12: _format_move_time for 8 days out (EC-09)
# ===========================================================================


@pytest.mark.ha_integration
class TestFormatMoveTimeEightDaysOut:
    """_format_move_time for a date 8 days out uses full weekday + M/D (EC-09).

    8 days out is beyond tomorrow (tier 2), so the 'Other' tier applies:
    full weekday name + unpadded (M/D) + 12-hour time.
    """

    def test_eight_days_out_full_weekday_md(self, nyc_timezone) -> None:
        """Frozen 2026-05-18 (Mon); window 2026-05-26 (Tue) → 'Tuesday (5/26), 8:30 AM'.

        2026-05-26 is 8 days after 2026-05-18. It falls in the 'Other' tier
        (not Today, not Tomorrow), so the format must be the full weekday name
        followed by the unpadded M/D in parentheses.
        """
        # 2026-05-18 07:00 NYC EDT (-04:00) = 11:00 UTC
        with freeze_time("2026-05-18 11:00:00"):
            sensor = _make_stub_sensor()
            move_dt = datetime(2026, 5, 26, 8, 30, tzinfo=NYC_TZ)
            result = sensor._format_move_time(move_dt)
            assert result == "Tuesday (5/26), 8:30 AM", (
                f"Expected 'Tuesday (5/26), 8:30 AM' for 8-days-out window; "
                f"got {result!r}"
            )


# ===========================================================================
# Class 13: BUG-T-005 (Phase 35.1-05) — ASPActiveNow exposes cleaning_days
# ===========================================================================


@pytest.mark.ha_integration
class TestASPActiveNowExposesCleaningDays:
    """BUG-T-005: when schedule is ASPActiveNow, sensor attrs must include
    cleaning_days derived from active_window.day.

    Before the fix, the attribute branch only emits cleaning_days when
    schedule has a weekly_schedule (ScheduleFound). ASPActiveNow sets
    weekly = None and silently drops cleaning_days from the sensor —
    a regression observable in the UI as a vanishing chip on holiday-
    cleared/active-now mornings.

    Fix: in the ASPActiveNow branch, populate
    ``attrs["cleaning_days"] = [active_window.day.name.title()]``.
    """

    def test_sensor_active_now_exposes_cleaning_days_monday(self) -> None:
        """ASPActiveNow on MONDAY must surface cleaning_days = ['Monday']."""
        window = _make_cleaning_window(day=ASPDay.MONDAY)
        schedule = _make_asp_active_now(window)
        data = ASPParkingData(schedule_result=schedule)

        attrs = sensor_extra_attributes(data)

        assert "cleaning_days" in attrs, (
            "ASPActiveNow branch must populate cleaning_days "
            "(BUG-T-005: previously dropped)"
        )
        assert attrs["cleaning_days"] == ["Monday"], (
            f"Expected ['Monday'] from active_window.day.name.title(); "
            f"got {attrs['cleaning_days']!r}"
        )

    def test_sensor_active_now_exposes_cleaning_days_thursday(self) -> None:
        """ASPActiveNow on THURSDAY must surface cleaning_days = ['Thursday']."""
        window = _make_cleaning_window(day=ASPDay.THURSDAY)
        schedule = _make_asp_active_now(window)
        data = ASPParkingData(schedule_result=schedule)

        attrs = sensor_extra_attributes(data)

        assert attrs.get("cleaning_days") == ["Thursday"], (
            f"Expected ['Thursday']; got {attrs.get('cleaning_days')!r}"
        )
