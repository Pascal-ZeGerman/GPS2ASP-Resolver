"""Offline Wave-0 unit tests for scripts/build_demo_dataset.py.

The demo dumper is a presentation-layer snapshot producer: it calls the
existing ``resolve_asp(debug=True)`` entrypoint and serialises the result into
a small JSON shape the static demo page consumes. These tests exercise the
*pure* functions of the dumper (reprojection + dict assembly) WITHOUT any
network or the 39 MB spatial index — resolver results are fabricated in-test
using the real frozen dataclasses.

Guardrails proven here (plan 41-01):
  - test_reprojection_bounds: geometry reprojects EPSG:2263 -> WGS84 in [lon, lat]
    order, inside the NYC bbox (Pitfall 5 / feet-vs-degrees).
  - test_no_absolute_nextmove: the entry stores a WEEKLY pattern, never an
    absolute next-move datetime (Pitfall 1 / date decay).
  - test_sensor_shape: mock-sensor attribute keys are a subset of the real
    ASPNextMoveTimeSensor / ASPResolvedStreetSensor key sets (no invented keys).
  - test_dataset_completeness_and_status: lat/lon/status always present and the
    status literal is correct across schedule_found / resolution_failed / no_match.

This module is intentionally offline (no ``@pytest.mark.integration``) so CI's
``-m "not integration"`` selection runs it.
"""

from __future__ import annotations

import importlib.util
import re
from datetime import datetime, time
from pathlib import Path

from gps2asp.api_models import ASPDebugResult
from gps2asp.schedule.models import (
    ASPActiveNow,
    ASPDay,
    CleaningWindow,
    NoMatchSchedule,
    ScheduleFound,
    TimeWindow,
    WeeklySchedule,
)

_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_demo_dataset.py"


def _load_dumper():
    spec = importlib.util.spec_from_file_location("build_demo_dataset", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Loaded at import time — collection FAILS (RED) until the script exists.
dumper = _load_dumper()


# The canonical real HA sensor attribute key sets, transcribed from
# custom_components/asp_parking/sensor.py (source of truth). The demo mock may
# emit a SUBSET of these; it must never invent a key outside them.
_ALLOWED_NEXT_MOVE_KEYS = {
    "next_move_is_today",
    "next_move_is_tomorrow",
    "cleaning_days",
    "time_window_start",
    "time_window_end",
    "schedule_summary",
    "urgency",
    "street_name",
    "cross_streets",
    "side_of_street",
    "side_label",
    "confidence_score",
    "borough",
    "soda_level",
}
_ALLOWED_RESOLVED_STREET_KEYS = {
    "from_street",
    "to_street",
    "side_of_street",
    "confidence_score",
    "borough",
    "distance_ft",
    "street_width_ft",
    "segment_id",
    "side_label",
}

# ISO-8601 datetime detector (date + 'T' + time). Used to prove the entry never
# carries an absolute next-move timestamp anywhere in its values.
_ISO_DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def _make_weekly() -> WeeklySchedule:
    return WeeklySchedule(
        windows=(
            TimeWindow(
                day=ASPDay.TUESDAY,
                start_time=time(11, 30),
                end_time=time(13, 0),
                source_sign="NO PARKING TUE 11:30AM-1PM STREET CLEANING",
            ),
            TimeWindow(
                day=ASPDay.FRIDAY,
                start_time=time(11, 30),
                end_time=time(13, 0),
                source_sign="NO PARKING FRI 11:30AM-1PM STREET CLEANING",
            ),
        )
    )


def _make_schedule_found() -> ScheduleFound:
    return ScheduleFound(
        status="schedule_found",
        next_window=None,  # deliberately no absolute datetime
        weekly_schedule=_make_weekly(),
        on_street="PROSPECT PL",
        from_street="VANDERBILT AVE",
        to_street="CARLTON AVE",
        side_of_street="N",
        source_signs=["NO PARKING TUE 11:30AM-1PM STREET CLEANING"],
        summary="TUE & FRI 11:30 AM - 1:00 PM",
        parse_failures=[],
    )


def _make_asp_active_now() -> ASPActiveNow:
    return ASPActiveNow(
        status="asp_active_now",
        active_window=CleaningWindow(
            day=ASPDay.THURSDAY,
            start_time=time(11, 0),
            end_time=time(14, 0),
            start_datetime=datetime(2026, 7, 30, 11, 0),
            end_datetime=datetime(2026, 7, 30, 14, 0),
            source_signs=["NO PARKING THU 11AM-2PM STREET CLEANING"],
        ),
        on_street="ORIENTAL BLVD",
        from_street="",
        to_street="DECATUR AVE",
        side_of_street="N",
        source_signs=["NO PARKING THU 11AM-2PM STREET CLEANING"],
        summary="MON & THU 11 AM - 2 PM",
    )


def _make_debug_result(schedule) -> ASPDebugResult:
    """Fabricate a resolved ASPDebugResult (resolution/sign_result unused by dumper)."""
    return ASPDebugResult(
        schedule=schedule,
        resolution_failed=False,
        resolution_error=None,
        on_street="PROSPECT PL",
        from_street="VANDERBILT AVE",
        to_street="CARLTON AVE",
        side_of_street="N",
        resolution=None,
        sign_result=None,
        confidence=0.87,
        state_plane_x=992700.0,
        state_plane_y=186200.0,
        soda_level=1,
        borocode="3",
        perpendicular_distance_ft=12.5,
        street_width_ft=34.0,
        segment_id=123456,
    )


def _iter_str_values(obj):
    """Yield every string scalar reachable in a nested dict/list structure."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from _iter_str_values(value)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            yield from _iter_str_values(value)


# --- test_reprojection_bounds -----------------------------------------------


def test_reprojection_bounds():
    coords = dumper.reproject_wkt_to_wgs84(
        "LINESTRING (979278.28 196558.53, 979500 196700)"
    )
    assert isinstance(coords, list) and len(coords) == 2
    for pair in coords:
        assert isinstance(pair, list) and len(pair) == 2
        lon, lat = pair
        # [lon, lat] order (GeoJSON), inside the NYC bbox.
        assert -74.3 <= lon <= -73.6, f"lon {lon} outside NYC bbox (wrong axis order?)"
        assert 40.4 <= lat <= 41.0, f"lat {lat} outside NYC bbox (wrong axis order?)"


# --- test_no_absolute_nextmove ----------------------------------------------


def test_no_absolute_nextmove():
    entry = dumper.build_point_entry(
        _make_debug_result(_make_schedule_found()), 40.677629, -73.968527
    )

    # Weekly pattern present and shaped correctly.
    assert isinstance(entry["weekly"], list) and entry["weekly"]
    for window in entry["weekly"]:
        assert isinstance(window["day"], int)
        assert re.fullmatch(r"\d{2}:\d{2}", window["start"])
        assert re.fullmatch(r"\d{2}:\d{2}", window["end"])
        assert isinstance(window["sign"], str)

    # No absolute next-move keys anywhere (top-level or nested sensor attrs).
    def _assert_no_key(node):
        if isinstance(node, dict):
            for banned in ("next_window_start", "next_window_end", "next_window_day"):
                assert banned not in node, f"absolute next-move key leaked: {banned}"
            for value in node.values():
                _assert_no_key(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                _assert_no_key(value)

    _assert_no_key(entry)

    # No ISO-8601 datetime value appears anywhere in the entry.
    for value in _iter_str_values(entry):
        assert not _ISO_DATETIME_RE.search(value), (
            f"absolute ISO datetime leaked into entry: {value!r}"
        )


# --- test_sensor_shape ------------------------------------------------------


def test_sensor_shape():
    entry = dumper.build_point_entry(
        _make_debug_result(_make_schedule_found()), 40.677629, -73.968527
    )

    next_move_attrs = entry["sensors"]["next_move"]["attributes"]
    resolved_attrs = entry["sensors"]["resolved_street"]["attributes"]

    assert set(next_move_attrs).issubset(_ALLOWED_NEXT_MOVE_KEYS), (
        f"invented next_move keys: {set(next_move_attrs) - _ALLOWED_NEXT_MOVE_KEYS}"
    )
    assert set(resolved_attrs).issubset(_ALLOWED_RESOLVED_STREET_KEYS), (
        f"invented resolved_street keys: "
        f"{set(resolved_attrs) - _ALLOWED_RESOLVED_STREET_KEYS}"
    )
    # Entities must be shaped as HA entities (entity_id present).
    assert entry["sensors"]["next_move"]["entity_id"].startswith("sensor.")
    assert entry["sensors"]["resolved_street"]["entity_id"].startswith("sensor.")


# --- test_dataset_completeness_and_status -----------------------------------


def test_dataset_completeness_and_status():
    found = dumper.build_point_entry(
        _make_debug_result(_make_schedule_found()), 40.677629, -73.968527
    )
    failed = dumper.build_point_entry(
        ASPDebugResult.from_error("ambiguous", 992700.0, 186200.0),
        40.5,
        -74.0,
    )
    no_match = dumper.build_point_entry(
        _make_debug_result(NoMatchSchedule()), 40.71, -73.99
    )

    assert found["status"] == "schedule_found"
    assert failed["status"] == "resolution_failed"
    assert no_match["status"] == "no_match"

    for entry in (found, failed, no_match):
        assert "lat" in entry
        assert "lon" in entry
        assert "status" in entry


# --- test_asp_active_now_populates_weekly ------------------------------------


def test_asp_active_now_populates_weekly():
    """Regression test: ASPActiveNow must populate weekly/summary like ScheduleFound.

    app.js's hasSchedule() treats 'asp_active_now' as a schedule-bearing status
    and renders the calendar from `weekly` — an empty weekly array here would
    have shipped a broken calendar for any point currently mid-cleaning-window
    (found via code review on the committed dataset, see 41-02-SUMMARY.md).
    """
    entry = dumper.build_point_entry(
        _make_debug_result(_make_asp_active_now()), 40.578552, -73.934903
    )

    assert entry["status"] == "asp_active_now"
    assert entry["summary"] == "MON & THU 11 AM - 2 PM"
    assert isinstance(entry["weekly"], list) and entry["weekly"]
    window = entry["weekly"][0]
    assert window["day"] == ASPDay.THURSDAY.value
    assert window["start"] == "11:00"
    assert window["end"] == "14:00"
    assert "NO PARKING" in window["sign"]

    # build_sensor_shapes()/_cleaning_day_names() had the identical ScheduleFound-
    # only gap — cleaning_days/schedule_summary must also populate for asp_active_now.
    next_move_attrs = entry["sensors"]["next_move"]["attributes"]
    assert next_move_attrs["cleaning_days"] == ["Thursday"]
    assert next_move_attrs["schedule_summary"] == "MON & THU 11 AM - 2 PM"
