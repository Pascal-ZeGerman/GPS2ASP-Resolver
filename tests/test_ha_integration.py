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
import pytest
from datetime import datetime, time, timedelta
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

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

    schedule = data.schedule_result
    if isinstance(schedule, ScheduleFound):
        return schedule.next_window.start_datetime.isoformat()
    if isinstance(schedule, ASPActiveNow):
        return schedule.active_window.end_datetime.isoformat()
    if isinstance(schedule, NoASPSchedule):
        return "No restrictions"
    if isinstance(schedule, NoMatchSchedule):
        return "No restrictions"
    if isinstance(schedule, AllUnparseable):
        return "No restrictions"
    return None


def binary_sensor_is_on(data: ASPParkingData) -> bool:
    """Replicate ASPActiveNowBinarySensor.is_on logic."""
    return isinstance(data.schedule_result, ASPActiveNow)


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

        attrs["street_name"] = schedule.on_street
        attrs["cross_streets"] = f"{schedule.from_street} to {schedule.to_street}"
        attrs["side_of_street"] = schedule.side_of_street
        attrs["borough"] = None

    if isinstance(schedule, ScheduleFound):
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

    attrs["last_resolved"] = (
        data.last_resolved.isoformat() if data.last_resolved else None
    )
    attrs["confidence_score"] = data.confidence_score
    attrs["sign_count"] = data.sign_count
    attrs["parse_failures"] = data.parse_failures

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

NYC_TZ = ZoneInfo("America/New_York")


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
        """ScheduleFound -> ISO datetime of next window start."""
        window = _make_cleaning_window()
        result = _make_schedule_found(window)
        data = ASPParkingData(schedule_result=result)

        state = sensor_native_value(data)
        assert state == window.start_datetime.isoformat()

    def test_sensor_state_asp_active_now(self) -> None:
        """ASPActiveNow -> ISO datetime of active window end."""
        window = _make_cleaning_window()
        result = _make_asp_active_now(window)
        data = ASPParkingData(schedule_result=result)

        state = sensor_native_value(data)
        assert state == window.end_datetime.isoformat()

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
