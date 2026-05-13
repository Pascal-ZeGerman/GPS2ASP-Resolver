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
from datetime import datetime, time, timedelta
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
            assert not re.match(
                r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun) ", result
            ), (
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
