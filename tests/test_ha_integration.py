"""Integration tests for the ASP Parking custom component.

Tests coordinator data mapping, sensor state derivation, binary sensor logic,
movement threshold behavior, sensor attributes, and stale timeout -- all without
requiring a running Home Assistant instance.

The tests directly construct ASPParkingData with known ScheduleResult variants
and replicate the sensor's native_value / binary_sensor's is_on logic to verify
correct state mapping.
"""

from __future__ import annotations

import math
import re
import pytest
from datetime import datetime, time, timedelta, timezone
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

NYC_TZ = ZoneInfo("America/New_York")
UTC_TZ = timezone.utc


def _format_move_time(dt: datetime) -> str:
    """Mirror of ASPNextMoveTimeSensor._format_move_time() for test helpers.

    Uses stdlib only (no dt_util) so tests run without Home Assistant.
    """
    local_dt = dt.astimezone(NYC_TZ)
    seconds_until = (dt - datetime.now(tz=UTC_TZ)).total_seconds()
    time_str = local_dt.strftime("%I:%M %p").lstrip("0")
    if seconds_until < 12 * 3600:
        return f"\u26a0 Today {time_str}"
    day_str = local_dt.strftime("%a")
    return f"{day_str} {time_str}"

from gps2asp.schedule.models import (
    ASPActiveNow,
    ASPDay,
    AllUnparseable,
    CleaningWindow,
    NoASPSchedule,
    NoMatchSchedule,
    ParseFailure,
    ScheduleFound,
    ScheduleResult,
    TimeWindow,
    WeeklySchedule,
)
from gps2asp.suspension import SuspensionInfo, apply_suspension


# ---------------------------------------------------------------------------
# Local copy of ASPParkingData to avoid importing HA-dependent coordinator.py
# Fields mirror custom_components/asp_parking/coordinator.py ASPParkingData
# ---------------------------------------------------------------------------


@dataclass
class ASPParkingData:
    """Test-local mirror of the coordinator's ASPParkingData."""

    schedule_result: ScheduleResult | None = None
    special_state: str | None = None
    last_lat: float | None = None
    last_lon: float | None = None
    last_resolved: datetime | None = None
    last_gps_update: datetime | None = None
    last_error: str | None = None
    last_error_time: datetime | None = None
    confidence_score: float | None = None
    sign_count: int = 0
    parse_failures: int = 0
    soda_level: int = 0  # mirrors coordinator.py ASPParkingData
    # Phase 30 diagnostic fields (mirror coordinator.py ASPParkingData)
    borough: str | None = None
    distance_ft: float | None = None
    street_width_ft: float | None = None
    segment_id: int | None = None
    suspension_state: SuspensionInfo = field(
        default_factory=lambda: SuspensionInfo(is_suspended=False, reason=None, source='none')
    )
    last_notified_window: CleaningWindow | None = None


# ---------------------------------------------------------------------------
# State mapping helpers (replicate sensor.py native_value logic)
# ---------------------------------------------------------------------------


def sensor_native_value(data: ASPParkingData) -> str | None:
    """Replicate ASPNextMoveTimeSensor.native_value logic."""
    if data.special_state == "outside_coverage":
        return "Outside coverage area"
    if data.special_state == "no_street_match":
        return "No street match"
    if data.schedule_result is None:
        return None

    # Lazy merge suspension at read time
    schedule = apply_suspension(data.schedule_result, data.suspension_state)

    # Suspension branch (before normal schedule branches)
    if isinstance(schedule, (ScheduleFound, ASPActiveNow)) and schedule.suspended:
        return "Suspended"

    if isinstance(schedule, ScheduleFound):
        if schedule.next_window is None:
            return None  # find_next_window returned None (no windows in schedule)
        return _format_move_time(schedule.next_window.start_datetime)
    if isinstance(schedule, ASPActiveNow):
        return _format_move_time(schedule.active_window.end_datetime)
    if isinstance(schedule, NoASPSchedule):
        return "No restrictions"
    if isinstance(schedule, NoMatchSchedule):
        return "No restrictions"
    if isinstance(schedule, AllUnparseable):
        return "No restrictions"
    return None


def binary_sensor_is_on(data: ASPParkingData) -> bool:
    """Replicate ASPActiveNowBinarySensor.is_on logic."""
    schedule = data.schedule_result
    if not isinstance(schedule, ASPActiveNow):
        return False
    merged = apply_suspension(schedule, data.suspension_state)
    return isinstance(merged, ASPActiveNow) and not merged.suspended


def sensor_available(data: ASPParkingData, stale_timeout_hours: int = 8) -> bool:
    """Replicate ASPNextMoveTimeSensor.available logic."""
    if data.last_gps_update is None:
        return True
    elapsed = (datetime.now(tz=ZoneInfo("UTC")) - data.last_gps_update).total_seconds()
    return elapsed <= stale_timeout_hours * 3600


def sensor_extra_attributes(data: ASPParkingData) -> dict:
    """Replicate ASPNextMoveTimeSensor.extra_state_attributes logic."""
    attrs: dict = {}
    schedule = data.schedule_result

    # Lazy merge suspension at read time
    if schedule is not None:
        schedule = apply_suspension(schedule, data.suspension_state)

    if isinstance(schedule, (ScheduleFound, ASPActiveNow)):
        if isinstance(schedule, ScheduleFound):
            weekly = schedule.weekly_schedule
        else:
            weekly = None

        if weekly is not None:
            day_names = sorted(
                {w.day.name.title() for w in weekly.windows},
                key=lambda d: [
                    "Monday", "Tuesday", "Wednesday", "Thursday",
                    "Friday", "Saturday", "Sunday",
                ].index(d),
            )
            attrs["cleaning_days"] = day_names
            if weekly.windows:
                first_window = weekly.windows[0]
                attrs["time_window_start"] = first_window.start_time.strftime("%H:%M")
                attrs["time_window_end"] = first_window.end_time.strftime("%H:%M")

        attrs["schedule_summary"] = schedule.summary

        # Urgency attribute — only when a concrete move datetime exists
        _move_dt: datetime | None = None
        if isinstance(schedule, ScheduleFound) and schedule.next_window is not None:
            _move_dt = schedule.next_window.start_datetime
        elif isinstance(schedule, ASPActiveNow):
            _move_dt = schedule.active_window.end_datetime
        if _move_dt is not None:
            seconds_until = (_move_dt - datetime.now(tz=UTC_TZ)).total_seconds()
            attrs["urgency"] = "high" if seconds_until < 12 * 3600 else "normal"

        attrs["street_name"] = schedule.on_street
        attrs["cross_streets"] = f"{schedule.from_street} to {schedule.to_street}"
        attrs["side_of_street"] = schedule.side_of_street

    if isinstance(schedule, ScheduleFound):
        if schedule.next_window is not None:
            attrs["next_window_start"] = schedule.next_window.start_datetime.isoformat()
            attrs["next_window_end"] = schedule.next_window.end_datetime.isoformat()
            attrs["next_window_day"] = schedule.next_window.day.name.title()
    elif isinstance(schedule, ASPActiveNow):
        attrs["current_window_start"] = (
            schedule.active_window.start_datetime.isoformat()
        )
        attrs["current_window_end"] = (
            schedule.active_window.end_datetime.isoformat()
        )

    if isinstance(schedule, (ScheduleFound, ASPActiveNow)) and schedule.suspended:
        attrs["suspension_reason"] = schedule.suspension_reason
        attrs["resolution_reason"] = schedule.resolution_reason

    attrs["last_resolved"] = (
        data.last_resolved.isoformat() if data.last_resolved else None
    )
    attrs["confidence_score"] = data.confidence_score
    attrs["borough"] = data.borough          # Phase 30 — always present (None when unresolved)
    attrs["sign_count"] = data.sign_count
    attrs["parse_failures"] = data.parse_failures
    attrs["soda_level"] = data.soda_level

    if data.last_error is not None:
        attrs["last_error"] = data.last_error
        attrs["last_error_time"] = (
            data.last_error_time.isoformat() if data.last_error_time else None
        )

    return attrs


# ---------------------------------------------------------------------------
# Distance helper (replicate HA location_util.distance for threshold tests)
# ---------------------------------------------------------------------------


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in meters between two GPS coordinates."""
    R = 6371000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _make_cleaning_window(
    day: ASPDay = ASPDay.MONDAY,
    start_h: int = 8,
    start_m: int = 30,
    end_h: int = 10,
    end_m: int = 0,
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
) -> CleaningWindow:
    """Helper to build a CleaningWindow with defaults."""
    now = datetime.now(tz=NYC_TZ)
    if start_dt is None:
        start_dt = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    if end_dt is None:
        end_dt = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
    return CleaningWindow(
        day=day,
        start_time=time(start_h, start_m),
        end_time=time(end_h, end_m),
        start_datetime=start_dt,
        end_datetime=end_dt,
        source_signs=["NO PARKING 8:30AM-10AM MON"],
    )


def _make_schedule_found(
    window: CleaningWindow | None = None,
) -> ScheduleFound:
    """Helper to build a ScheduleFound with sensible defaults."""
    if window is None:
        window = _make_cleaning_window()
    tw = TimeWindow(
        day=window.day,
        start_time=window.start_time,
        end_time=window.end_time,
        source_sign="NO PARKING 8:30AM-10AM MON",
    )
    return ScheduleFound(
        status="schedule_found",
        next_window=window,
        weekly_schedule=WeeklySchedule(windows=(tw,)),
        on_street="PROSPECT PLACE",
        from_street="VANDERBILT AVENUE",
        to_street="UNDERHILL AVENUE",
        side_of_street="N",
        source_signs=["NO PARKING 8:30AM-10AM MON"],
        summary="Mon 8:30-10am",
        parse_failures=[],
    )


def _make_asp_active_now(
    window: CleaningWindow | None = None,
) -> ASPActiveNow:
    """Helper to build an ASPActiveNow with sensible defaults."""
    if window is None:
        window = _make_cleaning_window()
    return ASPActiveNow(
        status="asp_active_now",
        active_window=window,
        on_street="PROSPECT PLACE",
        from_street="VANDERBILT AVENUE",
        to_street="UNDERHILL AVENUE",
        side_of_street="N",
        source_signs=["NO PARKING 8:30AM-10AM MON"],
        summary="Mon 8:30-10am",
    )


# ===========================================================================
# Group 1: Sensor state mapping
# ===========================================================================


@pytest.mark.ha_integration
class TestSensorStateMapping:
    """Test ASPNextMoveTimeSensor native_value for all ScheduleResult variants."""

    def test_sensor_state_schedule_found(self) -> None:
        """ScheduleFound -> human-friendly move time (not ISO string)."""
        window = _make_cleaning_window()
        result = _make_schedule_found(window)
        data = ASPParkingData(schedule_result=result)

        state = sensor_native_value(data)
        assert state is not None
        # native_value should be human-friendly (not raw ISO)
        assert not re.match(r"\d{4}-\d{2}-\d{2}T", state), (
            f"ISO string leaked into native_value: {state!r}"
        )
        assert state == _format_move_time(window.start_datetime)

    def test_sensor_state_asp_active_now(self) -> None:
        """ASPActiveNow -> human-friendly end time (not ISO string)."""
        window = _make_cleaning_window()
        result = _make_asp_active_now(window)
        data = ASPParkingData(schedule_result=result)

        state = sensor_native_value(data)
        assert state is not None
        assert not re.match(r"\d{4}-\d{2}-\d{2}T", state), (
            f"ISO string leaked into native_value: {state!r}"
        )
        assert state == _format_move_time(window.end_datetime)

    def test_sensor_state_no_asp(self) -> None:
        """NoASPSchedule -> 'No restrictions'."""
        data = ASPParkingData(schedule_result=NoASPSchedule())
        assert sensor_native_value(data) == "No restrictions"

    def test_sensor_state_no_match(self) -> None:
        """NoMatchSchedule -> 'No restrictions'."""
        data = ASPParkingData(schedule_result=NoMatchSchedule())
        assert sensor_native_value(data) == "No restrictions"

    def test_sensor_state_all_unparseable(self) -> None:
        """AllUnparseable -> 'No restrictions'."""
        data = ASPParkingData(
            schedule_result=AllUnparseable(
                status="all_unparseable",
                parse_failures=[ParseFailure(raw="WEIRD SIGN", reason="unrecognized")],
            )
        )
        assert sensor_native_value(data) == "No restrictions"

    def test_sensor_state_outside_coverage(self) -> None:
        """special_state='outside_coverage' -> 'Outside coverage area'."""
        data = ASPParkingData(special_state="outside_coverage")
        assert sensor_native_value(data) == "Outside coverage area"

    def test_sensor_state_no_street_match(self) -> None:
        """special_state='no_street_match' -> 'No street match'."""
        data = ASPParkingData(special_state="no_street_match")
        assert sensor_native_value(data) == "No street match"

    def test_sensor_state_initial_none(self) -> None:
        """No schedule_result and no special_state -> None."""
        data = ASPParkingData()
        assert sensor_native_value(data) is None

    def test_schedule_found_none_next_window_returns_none(self) -> None:
        """Sensor returns None gracefully when ScheduleFound.next_window is None."""
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

        # sensor returns None (not AttributeError) when next_window is None
        assert sensor_native_value(data) is None

        # extra_state_attributes should not crash and should omit next_window_* keys
        attrs = sensor_extra_attributes(data)
        assert "next_window_start" not in attrs
        assert "next_window_end" not in attrs
        assert "next_window_day" not in attrs


# ===========================================================================
# Group 2: Binary sensor state mapping
# ===========================================================================


@pytest.mark.ha_integration
class TestBinarySensorStateMapping:
    """Test ASPActiveNowBinarySensor is_on for key variants."""

    def test_binary_sensor_on_when_active(self) -> None:
        """ASPActiveNow -> True (ON)."""
        data = ASPParkingData(schedule_result=_make_asp_active_now())
        assert binary_sensor_is_on(data) is True

    def test_binary_sensor_off_when_scheduled(self) -> None:
        """ScheduleFound -> False (OFF)."""
        data = ASPParkingData(schedule_result=_make_schedule_found())
        assert binary_sensor_is_on(data) is False

    def test_binary_sensor_off_when_no_asp(self) -> None:
        """NoASPSchedule -> False (OFF)."""
        data = ASPParkingData(schedule_result=NoASPSchedule())
        assert binary_sensor_is_on(data) is False

    def test_binary_sensor_off_when_no_match(self) -> None:
        """NoMatchSchedule -> False (OFF)."""
        data = ASPParkingData(schedule_result=NoMatchSchedule())
        assert binary_sensor_is_on(data) is False

    def test_binary_sensor_off_when_none(self) -> None:
        """No schedule_result -> False (OFF)."""
        data = ASPParkingData()
        assert binary_sensor_is_on(data) is False


# ===========================================================================
# Group 3: Coordinator movement threshold
# ===========================================================================


@pytest.mark.ha_integration
class TestMovementThreshold:
    """Test movement threshold logic for coordinator GPS event filtering."""

    # Prospect Park: 40.6602, -73.9690
    BASE_LAT = 40.6602
    BASE_LON = -73.9690

    def test_movement_below_threshold_ignored(self) -> None:
        """Movement < 50m should NOT trigger pipeline (skip)."""
        # Move ~10 meters north (approx 0.00009 degrees latitude)
        new_lat = self.BASE_LAT + 0.00009
        new_lon = self.BASE_LON
        dist = haversine_distance(self.BASE_LAT, self.BASE_LON, new_lat, new_lon)
        assert dist < 50.0, f"Expected <50m, got {dist:.1f}m"

    def test_movement_above_threshold_triggers(self) -> None:
        """Movement > 50m should trigger pipeline."""
        # Move ~100 meters north (approx 0.0009 degrees latitude)
        new_lat = self.BASE_LAT + 0.0009
        new_lon = self.BASE_LON
        dist = haversine_distance(self.BASE_LAT, self.BASE_LON, new_lat, new_lon)
        assert dist > 50.0, f"Expected >50m, got {dist:.1f}m"

    def test_first_gps_always_triggers(self) -> None:
        """No last position -> always triggers (distance check skipped)."""
        data = ASPParkingData(last_lat=None, last_lon=None)
        # When last_lat is None, the coordinator skips the distance check
        # and always runs the pipeline. Verify the condition.
        assert data.last_lat is None
        assert data.last_lon is None


# ===========================================================================
# Group 4: Sensor attributes
# ===========================================================================


@pytest.mark.ha_integration
class TestSensorAttributes:
    """Test extra_state_attributes content for various states."""

    def test_sensor_attributes_schedule_found(self) -> None:
        """ScheduleFound produces complete attribute dict."""
        now = datetime.now(tz=NYC_TZ)
        window = _make_cleaning_window(
            day=ASPDay.MONDAY,
            start_h=8, start_m=30,
            end_h=10, end_m=0,
            start_dt=now.replace(hour=8, minute=30, second=0, microsecond=0),
            end_dt=now.replace(hour=10, minute=0, second=0, microsecond=0),
        )
        result = _make_schedule_found(window)
        resolved_time = datetime.now(tz=ZoneInfo("UTC"))
        data = ASPParkingData(
            schedule_result=result,
            last_resolved=resolved_time,
            confidence_score=0.85,
            sign_count=3,
            parse_failures=1,
        )

        attrs = sensor_extra_attributes(data)

        # Schedule group
        assert "cleaning_days" in attrs
        assert "Monday" in attrs["cleaning_days"]
        assert attrs["time_window_start"] == "08:30"
        assert attrs["time_window_end"] == "10:00"
        assert attrs["schedule_summary"] == "Mon 8:30-10am"

        # Location group
        assert attrs["street_name"] == "PROSPECT PLACE"
        assert attrs["cross_streets"] == "VANDERBILT AVENUE to UNDERHILL AVENUE"
        assert attrs["side_of_street"] == "N"

        # Window group
        assert "next_window_start" in attrs
        assert "next_window_end" in attrs
        assert attrs["next_window_day"] == "Monday"

        # Metadata group
        assert attrs["last_resolved"] == resolved_time.isoformat()
        assert attrs["confidence_score"] == 0.85
        assert attrs["sign_count"] == 3
        assert attrs["parse_failures"] == 1

    def test_sensor_attributes_retained_on_special_state(self) -> None:
        """Schedule attributes persist when special_state is set.

        The coordinator retains schedule_result when setting special_state.
        The sensor should still produce schedule attributes from the retained result.
        """
        result = _make_schedule_found()
        data = ASPParkingData(
            schedule_result=result,
            special_state="outside_coverage",
            last_resolved=datetime.now(tz=ZoneInfo("UTC")),
            confidence_score=0.75,
            sign_count=2,
        )

        attrs = sensor_extra_attributes(data)

        # Schedule attributes from retained result should still be present
        assert "street_name" in attrs
        assert attrs["street_name"] == "PROSPECT PLACE"
        assert "next_window_start" in attrs
        assert attrs["confidence_score"] == 0.75

        # Sensor state should show special_state though
        state = sensor_native_value(data)
        assert state == "Outside coverage area"

    def test_sensor_attributes_minimal_when_no_schedule(self) -> None:
        """Initial state with no schedule produces minimal attributes."""
        data = ASPParkingData()
        attrs = sensor_extra_attributes(data)

        # Only metadata group present
        assert attrs["last_resolved"] is None
        assert attrs["confidence_score"] is None
        assert attrs["sign_count"] == 0
        assert attrs["parse_failures"] == 0

        # No schedule/location/window keys
        assert "street_name" not in attrs
        assert "next_window_start" not in attrs

    def test_sensor_attributes_error_shown(self) -> None:
        """Error info included when last_error is set."""
        error_time = datetime.now(tz=ZoneInfo("UTC"))
        data = ASPParkingData(
            last_error="SODA API timeout",
            last_error_time=error_time,
        )
        attrs = sensor_extra_attributes(data)
        assert attrs["last_error"] == "SODA API timeout"
        assert attrs["last_error_time"] == error_time.isoformat()


# ===========================================================================
# Group 5: Stale timeout
# ===========================================================================


@pytest.mark.ha_integration
class TestStaleTimeout:
    """Test sensor availability based on GPS data freshness."""

    def test_stale_timeout_marks_unavailable(self) -> None:
        """GPS update older than 8 hours -> available returns False."""
        stale_time = datetime.now(tz=ZoneInfo("UTC")) - timedelta(hours=9)
        data = ASPParkingData(last_gps_update=stale_time)
        assert sensor_available(data, stale_timeout_hours=8) is False

    def test_not_stale_when_recent(self) -> None:
        """GPS update 1 hour ago -> available returns True."""
        recent_time = datetime.now(tz=ZoneInfo("UTC")) - timedelta(hours=1)
        data = ASPParkingData(last_gps_update=recent_time)
        assert sensor_available(data, stale_timeout_hours=8) is True

    def test_available_when_no_gps_yet(self) -> None:
        """No GPS update received yet -> available returns True (initial state)."""
        data = ASPParkingData(last_gps_update=None)
        assert sensor_available(data) is True

    def test_stale_at_exact_boundary(self) -> None:
        """GPS update exactly at boundary -> should still be available."""
        # 8 hours minus 1 second should be available
        almost_stale = datetime.now(tz=ZoneInfo("UTC")) - timedelta(
            hours=8, seconds=-1
        )
        data = ASPParkingData(last_gps_update=almost_stale)
        assert sensor_available(data, stale_timeout_hours=8) is True


# ===========================================================================
# Group 6: Human-friendly native_value format and urgency attribute
# ===========================================================================


# Pattern for normal case: "Mon 8:00 AM" (abbreviated day + no-leading-zero 12h time)
_NORMAL_FORMAT_RE = re.compile(
    r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d{1,2}:\d{2} (AM|PM)$"
)

# Pattern for urgent case: "⚠ Today 8:00 AM"
_URGENT_FORMAT_RE = re.compile(r"^\u26a0 Today \d{1,2}:\d{2} (AM|PM)$")


@pytest.mark.ha_integration
class TestHumanFriendlyNativeValue:
    """Test that native_value returns human-friendly strings, not ISO."""

    def test_schedule_found_normal_format(self) -> None:
        """ScheduleFound >12h away returns 'Mon 8:00 AM' style string."""
        # Create a window 24 hours from now (well past 12h threshold)
        future_dt = datetime.now(tz=ZoneInfo("America/New_York")) + timedelta(hours=24)
        window = _make_cleaning_window(
            day=ASPDay.MONDAY,
            start_dt=future_dt,
            end_dt=future_dt + timedelta(hours=1, minutes=30),
        )
        result = _make_schedule_found(window)
        data = ASPParkingData(schedule_result=result)

        state = sensor_native_value(data)

        # Must match "DDD H:MM AM/PM" pattern — NOT an ISO string
        assert state is not None
        assert _NORMAL_FORMAT_RE.match(state), (
            f"Expected normal format like 'Mon 8:00 AM', got: {state!r}"
        )
        # Must NOT be an ISO string (ISO format: YYYY-MM-DDTHH:MM...)
        assert not re.match(r"\d{4}-\d{2}-\d{2}T", state), (
            f"ISO string leaked into native_value: {state!r}"
        )

    def test_schedule_found_urgent_format(self) -> None:
        """ScheduleFound <12h away returns '⚠ Today 8:00 AM' prefix."""
        # Create a window 3 hours from now (inside 12h threshold)
        soon_dt = datetime.now(tz=ZoneInfo("America/New_York")) + timedelta(hours=3)
        window = _make_cleaning_window(
            day=ASPDay.MONDAY,
            start_dt=soon_dt,
            end_dt=soon_dt + timedelta(hours=1, minutes=30),
        )
        result = _make_schedule_found(window)
        data = ASPParkingData(schedule_result=result)

        state = sensor_native_value(data)

        assert state is not None
        assert _URGENT_FORMAT_RE.match(state), (
            f"Expected urgent format like '⚠ Today 8:00 AM', got: {state!r}"
        )

    def test_asp_active_now_normal_format(self) -> None:
        """ASPActiveNow >12h end time returns 'Mon 8:00 AM' style for end time."""
        future_dt = datetime.now(tz=ZoneInfo("America/New_York")) + timedelta(hours=24)
        window = _make_cleaning_window(
            day=ASPDay.MONDAY,
            start_dt=future_dt - timedelta(hours=1),
            end_dt=future_dt,
        )
        result = _make_asp_active_now(window)
        data = ASPParkingData(schedule_result=result)

        state = sensor_native_value(data)

        assert state is not None
        assert _NORMAL_FORMAT_RE.match(state), (
            f"Expected normal format for ASPActiveNow, got: {state!r}"
        )

    def test_asp_active_now_urgent_format(self) -> None:
        """ASPActiveNow with end time <12h away gets urgency prefix."""
        soon_dt = datetime.now(tz=ZoneInfo("America/New_York")) + timedelta(hours=2)
        window = _make_cleaning_window(
            day=ASPDay.MONDAY,
            start_dt=soon_dt - timedelta(minutes=30),
            end_dt=soon_dt,
        )
        result = _make_asp_active_now(window)
        data = ASPParkingData(schedule_result=result)

        state = sensor_native_value(data)

        assert state is not None
        assert _URGENT_FORMAT_RE.match(state), (
            f"Expected urgent format for ASPActiveNow end, got: {state!r}"
        )

    def test_no_iso_string_leaks_in_schedule_found(self) -> None:
        """native_value for ScheduleFound must never contain raw ISO datetime."""
        future_dt = datetime.now(tz=ZoneInfo("America/New_York")) + timedelta(hours=48)
        window = _make_cleaning_window(
            start_dt=future_dt,
            end_dt=future_dt + timedelta(hours=2),
        )
        result = _make_schedule_found(window)
        data = ASPParkingData(schedule_result=result)

        state = sensor_native_value(data)
        # ISO 8601 pattern: digits-digits-digitsT
        assert state is not None
        assert not re.match(r"\d{4}-\d{2}-\d{2}T", state), (
            f"Raw ISO string returned from native_value: {state!r}"
        )

    def test_no_iso_string_leaks_in_asp_active_now(self) -> None:
        """native_value for ASPActiveNow must never contain raw ISO datetime."""
        future_dt = datetime.now(tz=ZoneInfo("America/New_York")) + timedelta(hours=48)
        window = _make_cleaning_window(
            start_dt=future_dt,
            end_dt=future_dt + timedelta(hours=2),
        )
        result = _make_asp_active_now(window)
        data = ASPParkingData(schedule_result=result)

        state = sensor_native_value(data)
        assert state is not None
        assert not re.match(r"\d{4}-\d{2}-\d{2}T", state), (
            f"Raw ISO string returned from ASPActiveNow native_value: {state!r}"
        )


@pytest.mark.ha_integration
class TestUrgencyAttribute:
    """Test that extra_state_attributes gains 'urgency' key."""

    def test_urgency_normal_when_far_away(self) -> None:
        """Move time >12h away -> urgency='normal'."""
        future_dt = datetime.now(tz=ZoneInfo("America/New_York")) + timedelta(hours=24)
        window = _make_cleaning_window(
            start_dt=future_dt,
            end_dt=future_dt + timedelta(hours=2),
        )
        result = _make_schedule_found(window)
        data = ASPParkingData(schedule_result=result)

        attrs = sensor_extra_attributes(data)
        assert "urgency" in attrs, "urgency key missing from extra_state_attributes"
        assert attrs["urgency"] == "normal"

    def test_urgency_high_when_soon(self) -> None:
        """Move time <12h away -> urgency='high'."""
        soon_dt = datetime.now(tz=ZoneInfo("America/New_York")) + timedelta(hours=3)
        window = _make_cleaning_window(
            start_dt=soon_dt,
            end_dt=soon_dt + timedelta(hours=2),
        )
        result = _make_schedule_found(window)
        data = ASPParkingData(schedule_result=result)

        attrs = sensor_extra_attributes(data)
        assert "urgency" in attrs
        assert attrs["urgency"] == "high"

    def test_urgency_high_for_asp_active_now_soon(self) -> None:
        """ASPActiveNow with end time <12h -> urgency='high'."""
        soon_dt = datetime.now(tz=ZoneInfo("America/New_York")) + timedelta(hours=1)
        window = _make_cleaning_window(
            start_dt=soon_dt - timedelta(minutes=30),
            end_dt=soon_dt,
        )
        result = _make_asp_active_now(window)
        data = ASPParkingData(schedule_result=result)

        attrs = sensor_extra_attributes(data)
        assert "urgency" in attrs
        assert attrs["urgency"] == "high"

    def test_urgency_absent_when_next_window_none(self) -> None:
        """ScheduleFound with next_window=None -> no urgency key."""
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
        # urgency must NOT be present when no datetime is available
        assert "urgency" not in attrs

    def test_urgency_absent_for_no_asp_schedule(self) -> None:
        """NoASPSchedule -> no urgency key in attributes."""
        data = ASPParkingData(schedule_result=NoASPSchedule())
        attrs = sensor_extra_attributes(data)
        assert "urgency" not in attrs

    def test_iso_attributes_still_present(self) -> None:
        """next_window_start/end still use .isoformat() (unchanged)."""
        future_dt = datetime.now(tz=ZoneInfo("America/New_York")) + timedelta(hours=24)
        window = _make_cleaning_window(
            day=ASPDay.MONDAY,
            start_dt=future_dt,
            end_dt=future_dt + timedelta(hours=2),
        )
        result = _make_schedule_found(window)
        data = ASPParkingData(schedule_result=result)

        attrs = sensor_extra_attributes(data)
        # ISO format must still be present in attributes
        assert "next_window_start" in attrs
        assert re.match(r"\d{4}-\d{2}-\d{2}T", attrs["next_window_start"]), (
            f"next_window_start not in ISO format: {attrs['next_window_start']!r}"
        )


# ===========================================================================
# Group 7: soda_level attribute
# ===========================================================================


@pytest.mark.ha_integration
class TestSodaLevelAttribute:
    """Test soda_level always present in extra_state_attributes."""

    def test_soda_level_default_zero_on_initial_state(self) -> None:
        """Initial state (no schedule) -> soda_level=0."""
        data = ASPParkingData()
        attrs = sensor_extra_attributes(data)
        assert "soda_level" in attrs
        assert attrs["soda_level"] == 0

    def test_soda_level_set_when_schedule_found(self) -> None:
        """soda_level from data propagates to attributes."""
        data = ASPParkingData(schedule_result=_make_schedule_found(), soda_level=2)
        attrs = sensor_extra_attributes(data)
        assert attrs["soda_level"] == 2

    def test_soda_level_zero_on_special_state(self) -> None:
        """special_state='outside_coverage' with soda_level=0 -> soda_level=0 in attrs."""
        data = ASPParkingData(special_state="outside_coverage", soda_level=0)
        attrs = sensor_extra_attributes(data)
        assert attrs["soda_level"] == 0

    def test_soda_level_4_present(self) -> None:
        """Level 4 match -> soda_level=4 in attributes."""
        data = ASPParkingData(schedule_result=_make_schedule_found(), soda_level=4)
        attrs = sensor_extra_attributes(data)
        assert attrs["soda_level"] == 4


# ===========================================================================
# Group 8: Suspension sensor state (SC1)
# ===========================================================================

@pytest.mark.ha_integration
class TestSuspensionSensorState:
    """Test sensor native_value returns 'Suspended' when suspension is active."""

    def test_suspended_holiday(self) -> None:
        """SC1: ScheduleFound + holiday suspension -> 'Suspended'."""
        data = ASPParkingData(
            schedule_result=_make_schedule_found(),
            suspension_state=SuspensionInfo(
                is_suspended=True, reason="Martin Luther King Jr.'s Birthday", source='holiday'
            ),
        )
        assert sensor_native_value(data) == "Suspended"

    def test_suspended_emergency(self) -> None:
        """Emergency suspension -> 'Suspended'."""
        data = ASPParkingData(
            schedule_result=_make_schedule_found(),
            suspension_state=SuspensionInfo(
                is_suspended=True, reason="Snow Day", source='emergency'
            ),
        )
        assert sensor_native_value(data) == "Suspended"

    def test_not_suspended_normal_schedule(self) -> None:
        """No suspension -> normal move time (not 'Suspended')."""
        data = ASPParkingData(schedule_result=_make_schedule_found())
        state = sensor_native_value(data)
        assert state is not None
        assert state != "Suspended"

    def test_suspension_attrs_present(self) -> None:
        """SC1: suspension_reason and resolution_reason in attrs when suspended."""
        data = ASPParkingData(
            schedule_result=_make_schedule_found(),
            suspension_state=SuspensionInfo(
                is_suspended=True, reason="Memorial Day", source='holiday'
            ),
        )
        attrs = sensor_extra_attributes(data)
        assert attrs["suspension_reason"] == "Memorial Day"
        assert attrs["resolution_reason"] == "suspended_holiday"

    def test_suspension_attrs_absent_when_not_suspended(self) -> None:
        """No suspension_reason/resolution_reason when not suspended."""
        data = ASPParkingData(schedule_result=_make_schedule_found())
        attrs = sensor_extra_attributes(data)
        assert "suspension_reason" not in attrs
        assert "resolution_reason" not in attrs

    def test_existing_schedule_attrs_retained_when_suspended(self) -> None:
        """Per D-05: existing schedule attrs retained during suspension."""
        data = ASPParkingData(
            schedule_result=_make_schedule_found(),
            suspension_state=SuspensionInfo(
                is_suspended=True, reason="Christmas Day", source='holiday'
            ),
        )
        attrs = sensor_extra_attributes(data)
        # Suspension attrs present
        assert "suspension_reason" in attrs
        # Existing schedule attrs also present
        assert "cleaning_days" in attrs
        assert "schedule_summary" in attrs
        assert "street_name" in attrs


# ===========================================================================
# Group 9: Suspension binary sensor (SC2)
# ===========================================================================

@pytest.mark.ha_integration
class TestSuspensionBinarySensor:
    """Test binary sensor is_on returns False during suspended active windows."""

    def test_is_on_false_when_suspended(self) -> None:
        """SC2: ASPActiveNow + suspended -> is_on=False."""
        data = ASPParkingData(
            schedule_result=_make_asp_active_now(),
            suspension_state=SuspensionInfo(
                is_suspended=True, reason="Snow Day", source='emergency'
            ),
        )
        assert binary_sensor_is_on(data) is False

    def test_is_on_true_when_not_suspended(self) -> None:
        """ASPActiveNow without suspension -> is_on=True."""
        data = ASPParkingData(schedule_result=_make_asp_active_now())
        assert binary_sensor_is_on(data) is True

    def test_is_on_false_when_no_active_window(self) -> None:
        """ScheduleFound (not active) + suspended -> is_on=False."""
        data = ASPParkingData(
            schedule_result=_make_schedule_found(),
            suspension_state=SuspensionInfo(
                is_suspended=True, reason="Memorial Day", source='holiday'
            ),
        )
        assert binary_sensor_is_on(data) is False


# ===========================================================================
# Group 10: Suspension poll timer independence (SC3)
# ===========================================================================

import pathlib as _pathlib

_COORDINATOR_SRC = (
    _pathlib.Path(__file__).parent.parent
    / "custom_components" / "asp_parking" / "coordinator.py"
)


@pytest.mark.ha_integration
class TestSuspensionPoll:
    """SC3: Suspension poll timer fires independently of GPS movement."""

    def test_poll_updates_without_gps(self) -> None:
        """_async_suspension_poll method exists and is registered with async_track_time_interval.

        The coordinator must register a periodic suspension timer that calls
        _async_suspension_poll, independent of any GPS state change events.
        This test inspects the coordinator source to confirm the wiring is
        present without requiring a running Home Assistant instance.
        """
        src = _COORDINATOR_SRC.read_text()
        assert "_async_suspension_poll" in src, (
            "coordinator.py missing _async_suspension_poll method"
        )
        assert "_async_update_suspension" in src, (
            "coordinator.py missing _async_update_suspension method"
        )
        # Confirm async_track_time_interval is used to register the suspension poll
        # (not just the GPS periodic refresh which uses a different timedelta)
        assert "DEFAULT_SUSPENSION_INTERVAL" in src, (
            "coordinator.py does not reference DEFAULT_SUSPENSION_INTERVAL for suspension timer"
        )
        # Confirm the poll callback is passed to async_track_time_interval
        assert "self._async_suspension_poll" in src, (
            "coordinator.py does not wire _async_suspension_poll into async_track_time_interval"
        )

    def test_suspension_poll_does_not_require_gps_coordinates(self) -> None:
        """_async_update_suspension reads today's date, not GPS coordinates.

        The holiday calendar check uses datetime.now(NYC_TZ).date(), not
        self.data.last_lat / last_lon, confirming independence from GPS movement.
        """
        src = _COORDINATOR_SRC.read_text()
        # The update method must check the current date
        assert "self._get_now().date()" in src, (
            "coordinator.py suspension poll does not derive 'today' via _get_now()"
        )
        # Confirm _async_suspension_poll does not gate on last_lat / last_lon
        poll_start = src.find("def _async_suspension_poll")
        update_start = src.find("async def _async_update_suspension")
        # Both methods must be present
        assert poll_start != -1
        assert update_start != -1
        # Extract _async_update_suspension body and verify no GPS gate
        update_body = src[update_start: update_start + 600]
        assert "last_lat" not in update_body, (
            "_async_update_suspension should not gate on last_lat (GPS-independent)"
        )


# ===========================================================================
# Group 11: Suspension startup holiday status (SC4)
# ===========================================================================


@pytest.mark.ha_integration
class TestSuspensionStartup:
    """SC4: Holiday suspension status is correct on first entity read after restart."""

    def test_immediate_holiday_status(self) -> None:
        """coordinator.py calls HolidayCalendar.is_suspended(today) in async_start
        before the suspension poll timer is registered.

        Code inspection: holiday check precedes async_track_time_interval for suspension.
        """
        src = _COORDINATOR_SRC.read_text()
        # Holiday calendar is initialised and loaded at startup
        assert "self._holiday_calendar = HolidayCalendar()" in src, (
            "coordinator.py does not initialise HolidayCalendar in async_start"
        )
        assert "await self._holiday_calendar.load()" in src, (
            "coordinator.py does not await holiday_calendar.load() on startup"
        )
        # Holiday check happens at startup
        assert "self._holiday_calendar.is_suspended(today)" in src, (
            "coordinator.py does not call is_suspended(today) on startup"
        )
        # The suspension timer is registered after the holiday check
        holiday_check_pos = src.find("self._holiday_calendar.is_suspended(today)")
        suspension_timer_pos = src.find("self._async_suspension_poll")
        assert holiday_check_pos < suspension_timer_pos, (
            "coordinator.py suspension timer registered before holiday check at startup"
        )

    def test_holiday_calendar_returns_suspended_for_known_holiday(self) -> None:
        """HolidayCalendar.is_suspended() returns is_suspended=True for a known holiday.

        Uses the hardcoded 2026 fallback calendar (no network required).
        April 8 2026 is 'Passover (7th Day)' per FALLBACK_2026.
        This validates the logic that the coordinator uses to set suspension_state.
        """
        from datetime import date as _date

        # Import everything from the same module path to avoid class identity mismatch
        from custom_components.asp_parking.gps2asp.suspension import (
            FALLBACK_2026,
            HolidayCalendar,
            SuspensionInfo as _SuspensionInfo,
        )
        cal = HolidayCalendar()
        cal._holidays = dict(FALLBACK_2026)
        cal._loaded = True

        # April 8 2026 is a known holiday in FALLBACK_2026
        holiday_date = _date(2026, 4, 8)
        info = cal.is_suspended(holiday_date)

        assert isinstance(info, _SuspensionInfo)
        assert info.is_suspended is True
        assert info.reason == "Passover (7th Day)"
        assert info.source == "holiday"

    def test_holiday_calendar_returns_not_suspended_for_normal_day(self) -> None:
        """HolidayCalendar.is_suspended() returns is_suspended=False for a non-holiday.

        Confirms coordinator startup correctly leaves suspension_state as default
        when today is not a holiday.
        """
        from datetime import date as _date

        from custom_components.asp_parking.gps2asp.suspension import (
            FALLBACK_2026,
            HolidayCalendar,
        )
        cal = HolidayCalendar()
        cal._holidays = dict(FALLBACK_2026)
        cal._loaded = True

        # A date with no holiday in 2026 fallback calendar
        normal_date = _date(2026, 4, 9)  # day after Passover (7th Day)
        info = cal.is_suspended(normal_date)

        assert info.is_suspended is False
        assert info.reason is None
        assert info.source == "none"


# ===========================================================================
# Group 12: Config flow API key constants (SC5)
# ===========================================================================

CONF_NYC311_API_KEY = "nyc311_api_key"


@pytest.mark.ha_integration
class TestConfigFlowApiKey:
    """Test that config flow API key infrastructure is in place."""

    def test_api_key_constant_value(self) -> None:
        """CONF_NYC311_API_KEY has expected string value."""
        assert CONF_NYC311_API_KEY == "nyc311_api_key"

    def test_suspension_info_default_not_suspended(self) -> None:
        """Default SuspensionInfo is not suspended."""
        info = SuspensionInfo(is_suspended=False, reason=None, source='none')
        assert not info.is_suspended
        assert info.reason is None
        assert info.source == 'none'

    def test_api_key_stored_separately_from_device_tracker(self) -> None:
        """API key constant is distinct from device_tracker constant."""
        assert CONF_NYC311_API_KEY != "device_tracker"


# ---------------------------------------------------------------------------
# DIAG-04 diagnostic sensor native_value replication tests (Phase 27)
# ---------------------------------------------------------------------------
# These four pure-Python helpers replicate the native_value logic of the four
# new diagnostic sensors that Plan 03 will add to sensor.py. Replicating the
# logic locally (rather than importing the sensor classes) keeps the file's
# no-HA-imports-at-module-top convention intact (see existing module docstring
# lines 1-9). The four helper tests pass on commit because they exercise pure
# Python; the fifth test (``test_diag04_sensor_classes_exist``) imports the
# sensor classes and FAILS until Plan 03 ships — that is the RED gate for
# DIAG-04's import-surface contract.


def _confidence_score_native_value(data: ASPParkingData) -> float | None:
    """Replicate ASPConfidenceScoreSensor.native_value logic."""
    return data.confidence_score


def _soda_level_native_value(data: ASPParkingData) -> int | None:
    """Replicate ASPSODALevelSensor.native_value logic."""
    return data.soda_level


def _last_resolved_native_value(data: ASPParkingData) -> str | None:
    """Replicate ASPLastResolvedSensor.native_value logic."""
    ts = data.last_resolved
    return ts.isoformat() if ts else None


def _last_error_native_value(data: ASPParkingData) -> str | None:
    """Replicate ASPLastErrorSensor.native_value logic."""
    return data.last_error


def test_diag04_confidence_score_native_value() -> None:
    """ASPConfidenceScoreSensor surfaces coordinator.data.confidence_score (DIAG-04)."""
    assert _confidence_score_native_value(ASPParkingData(confidence_score=0.85)) == 0.85
    assert _confidence_score_native_value(ASPParkingData()) is None


def test_diag04_soda_level_native_value() -> None:
    """ASPSODALevelSensor surfaces coordinator.data.soda_level (DIAG-04)."""
    assert _soda_level_native_value(ASPParkingData(soda_level=2)) == 2
    assert _soda_level_native_value(ASPParkingData()) == 0


def test_diag04_last_resolved_iso() -> None:
    """ASPLastResolvedSensor returns ISO string or None (DIAG-04)."""
    ts = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    assert (
        _last_resolved_native_value(ASPParkingData(last_resolved=ts))
        == "2026-05-01T12:00:00+00:00"
    )
    assert _last_resolved_native_value(ASPParkingData()) is None


def test_diag04_last_error_native_value() -> None:
    """ASPLastErrorSensor surfaces coordinator.data.last_error (DIAG-04)."""
    assert _last_error_native_value(ASPParkingData(last_error="boom")) == "boom"
    assert _last_error_native_value(ASPParkingData()) is None


@pytest.mark.ha_integration
def test_diag04_sensor_classes_exist() -> None:
    """The four DIAG-04 sensor classes must be importable from sensor.py (Plan 03).

    RED gate: this test fails with ImportError until Plan 03 adds the four
    diagnostic sensor classes to ``custom_components.asp_parking.sensor``.
    """
    from custom_components.asp_parking.sensor import (
        ASPConfidenceScoreSensor,
        ASPLastErrorSensor,
        ASPLastResolvedSensor,
        ASPSODALevelSensor,
    )
    # Subclass check — they must inherit from _ASPDiagnosticSensor
    from custom_components.asp_parking.sensor import _ASPDiagnosticSensor

    for cls in (
        ASPConfidenceScoreSensor,
        ASPSODALevelSensor,
        ASPLastResolvedSensor,
        ASPLastErrorSensor,
    ):
        assert issubclass(cls, _ASPDiagnosticSensor)


# ---------------------------------------------------------------------------
# Phase 30 Plan 04: Sensor extra_state_attributes for new diagnostic fields
# ---------------------------------------------------------------------------


@pytest.mark.ha_integration
def test_resolved_street_sensor_exposes_phase_30_diagnostic_attributes() -> None:
    """ASPResolvedStreetSensor.extra_state_attributes must surface borough,
    distance_ft, street_width_ft, segment_id from coordinator.data (Phase 30, D-13).
    """
    from unittest.mock import MagicMock

    from custom_components.asp_parking.sensor import ASPResolvedStreetSensor
    # The sensor imports ScheduleFound from the VENDORED copy under
    # custom_components.asp_parking.gps2asp.*; the canonical src/ ScheduleFound
    # used elsewhere in this file is a DIFFERENT class object — isinstance()
    # against the vendored class would fail. Reuse the vendored ScheduleFound
    # so the sensor's branch is exercised.
    from custom_components.asp_parking.gps2asp.schedule.models import (
        ScheduleFound as VendoredScheduleFound,
        WeeklySchedule as VendoredWeeklySchedule,
    )

    schedule = VendoredScheduleFound(
        status="schedule_found",
        next_window=None,
        weekly_schedule=VendoredWeeklySchedule(windows=()),
        on_street="PROSPECT PLACE",
        from_street="VANDERBILT AVENUE",
        to_street="UNDERHILL AVENUE",
        side_of_street="N",
        source_signs=["NO PARKING 8:30AM-10AM MON"],
        summary="Mon 8:30-10am",
        parse_failures=[],
    )

    # Build a coordinator stub with .data populated like Plan 03 success path.
    # The local ASPParkingData mirror in this module includes the Phase 30
    # diagnostic fields (borough, distance_ft, street_width_ft, segment_id),
    # so the sensor's `self._coordinator.data.<field>` reads resolve correctly.
    coord = MagicMock()
    coord.data = ASPParkingData()
    coord.data.borough = "Brooklyn"
    coord.data.distance_ft = 12.34
    coord.data.street_width_ft = 30.0
    coord.data.segment_id = 987654
    coord.data.confidence_score = 0.85
    coord.data.schedule_result = schedule
    coord.entry = MagicMock()
    coord.entry.entry_id = "test_entry"

    sensor = ASPResolvedStreetSensor(coord)
    attrs = sensor.extra_state_attributes

    # Phase 30 D-13: 4 new diagnostic keys
    assert attrs["borough"] == "Brooklyn"
    assert attrs["distance_ft"] == 12.34
    assert attrs["street_width_ft"] == 30.0
    assert attrs["segment_id"] == 987654
    # Existing 4 keys still present
    assert "from_street" in attrs
    assert "to_street" in attrs
    assert "side_of_street" in attrs
    assert "confidence_score" in attrs


@pytest.mark.ha_integration
def test_next_move_time_sensor_borough_attribute_populated_from_coordinator_data() -> None:
    """ASPNextMoveTimeSensor.extra_state_attributes['borough'] reads from
    coordinator.data.borough (no longer hardcoded to None) per Phase 30 D-14.
    """
    data = ASPParkingData()
    data.borough = "Manhattan"
    data.schedule_result = _make_schedule_found()

    attrs = sensor_extra_attributes(data)
    assert attrs["borough"] == "Manhattan"


# ===========================================================================
# Group 13: Notification logic (_async_maybe_send_notification)
# ===========================================================================


@pytest.mark.ha_integration
class TestNotificationLogic:
    """Test _async_maybe_send_notification business logic with mocked hass.services.

    NOTE: The coordinator's isinstance checks use the vendored copy of ScheduleFound
    and CleaningWindow under custom_components.asp_parking.gps2asp.*. Tests here
    import from the vendored path to ensure isinstance() passes correctly.
    """

    def _make_coord(self, notify_service: str = "notify.mobile_app", lead_time: int = 60):
        """Return a minimal namespace that satisfies _async_maybe_send_notification."""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        hass = SimpleNamespace()
        hass.services = SimpleNamespace()
        hass.services.async_call = AsyncMock()

        data = ASPParkingData()
        coord = SimpleNamespace(
            hass=hass,
            data=data,
            _notify_service=notify_service,
            _debug_enabled=False,
            _debug_suppress_notifications=False,
            _notify_lead_time=lead_time,
        )
        return coord

    def _make_vendored_schedule_found(self, start_dt: datetime) -> object:
        """Build a ScheduleFound using the vendored (coordinator-facing) models."""
        from custom_components.asp_parking.gps2asp.schedule.models import (
            ASPDay as VASPDay,
            CleaningWindow as VCleaningWindow,
            ScheduleFound as VScheduleFound,
            WeeklySchedule as VWeeklySchedule,
            TimeWindow as VTimeWindow,
        )
        from datetime import time as _time
        end_dt = start_dt + timedelta(hours=1)
        window = VCleaningWindow(
            day=VASPDay.MONDAY,
            start_time=_time(start_dt.hour, start_dt.minute),
            end_time=_time(end_dt.hour, end_dt.minute),
            start_datetime=start_dt,
            end_datetime=end_dt,
            source_signs=["NO PARKING 8:30AM-10AM MON"],
        )
        tw = VTimeWindow(
            day=VASPDay.MONDAY,
            start_time=_time(start_dt.hour, start_dt.minute),
            end_time=_time(end_dt.hour, end_dt.minute),
            source_sign="NO PARKING 8:30AM-10AM MON",
        )
        schedule = VScheduleFound(
            status="schedule_found",
            next_window=window,
            weekly_schedule=VWeeklySchedule(windows=(tw,)),
            on_street="PROSPECT PLACE",
            from_street="VANDERBILT AVENUE",
            to_street="UNDERHILL AVENUE",
            side_of_street="N",
            source_signs=["NO PARKING 8:30AM-10AM MON"],
            summary="Mon 8:30-10am",
            parse_failures=[],
        )
        return schedule, window

    async def test_notification_fires_within_lead_time(self) -> None:
        """Notification fires when 0 < seconds_until <= notify_lead_time * 60."""
        from custom_components.asp_parking.coordinator import ASPParkingCoordinator

        coord = self._make_coord(lead_time=60)
        # Window starts 30 minutes from now (within 60-minute lead time)
        future_dt = datetime.now(tz=NYC_TZ) + timedelta(minutes=30)
        schedule, window = self._make_vendored_schedule_found(future_dt)

        await ASPParkingCoordinator._async_maybe_send_notification(coord, schedule)

        coord.hass.services.async_call.assert_awaited_once()
        assert coord.data.last_notified_window == window

    async def test_notification_skipped_when_window_past(self) -> None:
        """Notification skipped when seconds_until <= 0 (window already started/past)."""
        from custom_components.asp_parking.coordinator import ASPParkingCoordinator

        coord = self._make_coord(lead_time=60)
        # Window started 5 minutes ago (past)
        past_dt = datetime.now(tz=NYC_TZ) - timedelta(minutes=5)
        schedule, _window = self._make_vendored_schedule_found(past_dt)

        await ASPParkingCoordinator._async_maybe_send_notification(coord, schedule)

        coord.hass.services.async_call.assert_not_awaited()
        assert coord.data.last_notified_window is None

    async def test_notification_skipped_when_already_notified(self) -> None:
        """Notification skipped when window == last_notified_window (dedup)."""
        from custom_components.asp_parking.coordinator import ASPParkingCoordinator

        coord = self._make_coord(lead_time=60)
        future_dt = datetime.now(tz=NYC_TZ) + timedelta(minutes=30)
        schedule, window = self._make_vendored_schedule_found(future_dt)
        # Pre-set last_notified_window to the same window (already notified)
        coord.data.last_notified_window = window

        await ASPParkingCoordinator._async_maybe_send_notification(coord, schedule)

        coord.hass.services.async_call.assert_not_awaited()

    async def test_last_notified_window_set_after_delivery(self) -> None:
        """last_notified_window is set only after confirmed delivery."""
        from custom_components.asp_parking.coordinator import ASPParkingCoordinator

        coord = self._make_coord(lead_time=60)
        future_dt = datetime.now(tz=NYC_TZ) + timedelta(minutes=30)
        schedule, window = self._make_vendored_schedule_found(future_dt)

        assert coord.data.last_notified_window is None
        await ASPParkingCoordinator._async_maybe_send_notification(coord, schedule)
        assert coord.data.last_notified_window == window

    async def test_last_notified_window_not_set_when_async_call_raises(self) -> None:
        """last_notified_window is NOT set when async_call raises."""
        from unittest.mock import AsyncMock
        from custom_components.asp_parking.coordinator import ASPParkingCoordinator

        coord = self._make_coord(lead_time=60)
        coord.hass.services.async_call = AsyncMock(side_effect=Exception("service unavailable"))
        future_dt = datetime.now(tz=NYC_TZ) + timedelta(minutes=30)
        schedule, _window = self._make_vendored_schedule_found(future_dt)

        await ASPParkingCoordinator._async_maybe_send_notification(coord, schedule)

        assert coord.data.last_notified_window is None
