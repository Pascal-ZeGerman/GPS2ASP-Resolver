#!/usr/bin/env python3
"""Offline, build-time demo dataset dumper for the hosted demo page.

Runs the existing resolver (``resolve_asp(lat, lon, debug=True)``) over a small
set of hand-picked NYC coordinates and serialises a tiny committed dataset the
static demo page (``docs/demo/``) consumes without any server.

This is a PRESENTATION-LAYER SNAPSHOT DUMPER — it re-implements no resolver
logic. It calls the single public entrypoint and serialises the result into a
JSON shape the browser renders directly.

Two decay traps are deliberately avoided:

  * Pitfall 1 (date decay): the emitted dataset stores the WEEKLY PATTERN
    (day-of-week + start/end times + sign text), never an absolute next-move
    datetime. The client (app.js) recomputes the next occurrence at page load,
    pinned to America/New_York.
  * Pitfall 5 (feet vs degrees): matched segment geometry (``geometry_wkt`` in
    EPSG:2263 US survey feet) is reprojected to WGS84 ``[lon, lat]`` (GeoJSON
    order) via pyproj before it can be drawn on a Leaflet map.

Security (T-41-01): the NYC SODA app token is a BUILD-TIME env var consumed only
by the resolver's SODA client. It is never read or serialised into demo.json or
the GeoJSON. External NYC sign text is stored as-is (untrusted) and MUST be
rendered client-side via ``textContent`` (see 41-04), never ``innerHTML``.

The dataset FILES are produced by running this script (plan 41-02); this module
only defines the dumper and its offline-testable pure functions.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from shapely import wkt

from gps2asp import resolve_asp
from gps2asp.dataset_common import TO_WGS84, bounded_gather
from gps2asp.dataset_common import borough_name as _borough_name
from gps2asp.resolver.exceptions import (
    IndexNotFoundError,
    NoSegmentFoundError,
    OutsideNYCError,
)
from gps2asp.resolver.spatial_index import SpatialIndex
from gps2asp.schedule.models import ASPActiveNow, ScheduleFound
from gps2asp.schedule.next_move import NYC_TZ
from gps2asp.signs.exceptions import IncompleteResultsError, SODAAPIError

# side_of_street letter -> display label (mirrors sensor._SIDE_LABELS).
_SIDE_LABELS: dict[str, str] = {
    "N": "North side",
    "S": "South side",
    "E": "East side",
    "W": "West side",
}

# Hand-picked demo coordinates. Includes the canonical Prospect Pl regression
# case, a point expected to have no ASP restrictions, and one deliberately
# outside coverage to exercise the per-point failure path (Pitfall 4).
DEMO_POINTS: list[dict] = [
    {"key": "prospect_pl", "lat": 40.677629, "lon": -73.968527},
    {"key": "williamsburg", "lat": 40.714606, "lon": -73.961216},
    {"key": "astoria", "lat": 40.761897, "lon": -73.925232},
    {"key": "bronx_grand_concourse", "lat": 40.831258, "lon": -73.926617},
    {"key": "staten_island_no_match", "lat": 40.626511, "lon": -74.077902},
    {"key": "oriental_blvd", "lat": 40.578552, "lon": -73.934903},
    {"key": "outside_coverage", "lat": 40.912000, "lon": -73.700000},
]

# Sample car/profile assignments demonstrating results vary by location.
# NOTE: every point above (except outside_coverage, which is deliberately
# outside NYC bounds) was verified to actually resolve against the live index
# + SODA API before being committed here — see 41-02-SUMMARY.md's gap-closure
# note for the probe that replaced the original speculative coordinates, three
# of which (east_village, upper_west_side, central_park_no_restrictions) failed
# outright because they weren't actually close enough to an indexed segment.
DEMO_PROFILES: dict[str, dict] = {
    "A": {"point_key": "prospect_pl"},
    "B": {"point_key": "williamsburg"},
}


def reproject_wkt_to_wgs84(geometry_wkt: str) -> list[list[float]]:
    """Reproject an EPSG:2263 LINESTRING WKT to WGS84 ``[[lon, lat], ...]``.

    Args:
        geometry_wkt: A ``LINESTRING`` in EPSG:2263 (NY State Plane, US feet).

    Returns:
        List of ``[lon, lat]`` coordinate pairs in GeoJSON order (WGS84).
    """
    line = wkt.loads(geometry_wkt)
    return [list(TO_WGS84.transform(x, y)) for (x, y) in line.coords]


def _cleaning_day_names(result) -> list[str]:
    """Ordered unique cleaning-day names from a ScheduleFound/ASPActiveNow schedule."""
    schedule = result.schedule
    if isinstance(schedule, ScheduleFound):
        windows = schedule.weekly_schedule.windows
    elif isinstance(schedule, ASPActiveNow):
        windows = [schedule.active_window]
    else:
        return []
    seen: list[str] = []
    for window in windows:
        name = window.day.name.title()
        if name not in seen:
            seen.append(name)
    return seen


def build_sensor_shapes(result) -> dict:
    """Build the two mock HA sensor objects (next_move + resolved_street).

    Mirrors ``custom_components/asp_parking/sensor.py`` ``extra_state_attributes``
    but emits only STABLE attributes — no date-relative field (state string,
    ``next_window_*``, ``urgency``, ``next_move_is_today``/``_tomorrow``,
    ``time_window_*``); those are computed client-side by app.js from the weekly
    pattern (Pitfall 1). Keys are added only when their source value exists, so
    the emitted key set is always a subset of the real sensor key set.
    """
    borough = _borough_name(result.borocode)
    side = result.side_of_street
    side_label = _SIDE_LABELS.get(side) if side is not None else None
    has_schedule = isinstance(result.schedule, (ScheduleFound, ASPActiveNow))

    # --- Next Move Time sensor (primary, user-facing) ---
    # Location/schedule fields are gated behind has_schedule to mirror
    # sensor.py's ASPNextMoveTimeSensor.extra_state_attributes, which only
    # emits cleaning_days/schedule_summary/street_name/cross_streets/
    # side_of_street/side_label inside its own isinstance(schedule,
    # (ScheduleFound, ASPActiveNow)) branch.
    next_move_attrs: dict = {}
    if has_schedule:
        cleaning_days = _cleaning_day_names(result)
        if cleaning_days:
            next_move_attrs["cleaning_days"] = cleaning_days
        next_move_attrs["schedule_summary"] = result.schedule.summary
        if result.on_street is not None:
            next_move_attrs["street_name"] = result.on_street
        if result.from_street and result.to_street:
            next_move_attrs["cross_streets"] = (
                f"{result.from_street} to {result.to_street}"
            )
        if side is not None:
            next_move_attrs["side_of_street"] = side
        if side_label is not None:
            next_move_attrs["side_label"] = side_label
    next_move_attrs["confidence_score"] = result.confidence
    if borough is not None:
        next_move_attrs["borough"] = borough
    next_move_attrs["soda_level"] = result.soda_level

    # --- Resolved Street sensor (secondary) ---
    # Mirrors ASPResolvedStreetSensor.extra_state_attributes, which returns {}
    # entirely unless the schedule is ScheduleFound/ASPActiveNow.
    resolved_attrs: dict = {}
    if has_schedule:
        if result.from_street is not None:
            resolved_attrs["from_street"] = result.from_street
        if result.to_street is not None:
            resolved_attrs["to_street"] = result.to_street
        if side is not None:
            resolved_attrs["side_of_street"] = side
        resolved_attrs["confidence_score"] = result.confidence
        if borough is not None:
            resolved_attrs["borough"] = borough
        if result.perpendicular_distance_ft is not None:
            resolved_attrs["distance_ft"] = result.perpendicular_distance_ft
        if result.street_width_ft is not None:
            resolved_attrs["street_width_ft"] = result.street_width_ft
        if result.segment_id is not None:
            resolved_attrs["segment_id"] = result.segment_id
        if side_label is not None:
            resolved_attrs["side_label"] = side_label

    return {
        "next_move": {
            "entity_id": "sensor.asp_parking_monitor_next_move_time",
            "attributes": next_move_attrs,
        },
        "resolved_street": {
            "entity_id": "sensor.asp_parking_monitor_resolved_street",
            "attributes": resolved_attrs,
        },
    }


def build_point_entry(result, lat: float, lon: float) -> dict:
    """Assemble the serialisable demo entry for one resolved coordinate.

    Every field is built explicitly (never the dataclass auto-conversion helper
    — it chokes on datetime / IntEnum / shapely LineString, Pitfall 8). ``lat``,
    ``lon`` and ``status`` are always present, even on failure.
    """
    schedule = result.schedule
    if result.resolution_failed:
        status = "resolution_failed"
    elif schedule is not None:
        status = schedule.status
    else:
        status = "unknown"

    weekly: list[dict] = []
    summary: str | None = None
    if isinstance(schedule, ScheduleFound):
        summary = schedule.summary
        weekly = [
            {
                "day": window.day.value,
                "start": window.start_time.strftime("%H:%M"),
                "end": window.end_time.strftime("%H:%M"),
                "sign": window.source_sign,
            }
            for window in schedule.weekly_schedule.windows
        ]
    elif isinstance(schedule, ASPActiveNow):
        # The car is parked during an active cleaning window right now — there is
        # no weekly_schedule (only the single active_window), but app.js's
        # hasSchedule() treats "asp_active_now" as a schedule-bearing status, so
        # summary/weekly must still be populated or the calendar renders empty.
        summary = schedule.summary
        window = schedule.active_window
        weekly = [
            {
                "day": window.day.value,
                "start": window.start_time.strftime("%H:%M"),
                "end": window.end_time.strftime("%H:%M"),
                "sign": "; ".join(window.source_signs),
            }
        ]

    side = result.side_of_street
    return {
        "lat": lat,
        "lon": lon,
        "status": status,
        "on_street": result.on_street,
        "from_street": result.from_street,
        "to_street": result.to_street,
        "side_of_street": side,
        "side_label": _SIDE_LABELS.get(side) if side is not None else None,
        "confidence": result.confidence,
        "borocode": result.borocode,
        "borough": _borough_name(result.borocode),
        "segment_id": result.segment_id,
        "soda_level": result.soda_level,
        "summary": summary,
        "weekly": weekly,
        "sensors": build_sensor_shapes(result),
    }


async def _segment_coords(segment_id) -> list[list[float]] | None:
    """Reprojected WGS84 coords for a segment id, or None when unavailable.

    Reads geometry from the resolver's SpatialIndex singleton — already
    loaded by the resolve_asp() call in dump_point() — instead of a second,
    independent parse of segments.json.
    """
    if segment_id is None:
        return None
    index = await SpatialIndex.get()
    geometry_wkt = index.get_segment_geometry_wkt(segment_id)
    if geometry_wkt is None:
        return None
    return reproject_wkt_to_wgs84(geometry_wkt)


# Every infrastructural exception dump_point() can catch and degrade to a
# named-status entry. Shared with main()'s broken_profiles self-check so a
# future exception added here is automatically covered there too (finding:
# the self-check previously hardcoded only 3 of these 5+2 status strings).
_DUMP_POINT_FAILURE_EXCEPTIONS: tuple[type[Exception], ...] = (
    OutsideNYCError,
    NoSegmentFoundError,
    IndexNotFoundError,
    SODAAPIError,
    IncompleteResultsError,
)


async def dump_point(lat: float, lon: float) -> dict:
    """Resolve one coordinate, fail-soft per-point.

    Returns a dict ``{"entry": <demo entry>, "coords": <reprojected coords|None>}``.
    On any infrastructural resolver error the point degrades to a minimal entry
    with a status naming the error — the whole run is never aborted (Pitfall 4).
    """
    try:
        result = await resolve_asp(lat, lon, debug=True)
    except _DUMP_POINT_FAILURE_EXCEPTIONS as exc:
        print(
            f"build_demo_dataset: WARNING point ({lat}, {lon}) failed: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        entry = {
            "lat": lat,
            "lon": lon,
            "status": type(exc).__name__,
            "error": str(exc),
        }
        return {"entry": entry, "coords": None}

    entry = build_point_entry(result, lat, lon)
    coords = await _segment_coords(result.segment_id)
    return {"entry": entry, "coords": coords}


def _read_points(points_file: Path | None) -> list[dict]:
    """Return the point list from a JSON file, or the built-in DEMO_POINTS."""
    if points_file is None:
        return DEMO_POINTS
    data = json.loads(points_file.read_text())
    if not isinstance(data, list):
        raise SystemExit(
            f"--points file must be a JSON list, got {type(data).__name__}"
        )
    return data


def _profiles_for_points(points: list[dict], points_file: Path | None) -> dict[str, dict]:
    """Profile assignments (e.g. ``{"A": {"point_key": ...}}``) to ship and
    self-check.

    The built-in DEMO_POINTS list is paired with the module-level
    DEMO_PROFILES. A ``--points`` override supplies its own assignments via
    each point's optional ``profile`` field instead — DEMO_PROFILES' point
    keys ("prospect_pl"/"williamsburg") won't generally exist in an override
    file, so falling back to it would break main()'s broken_profiles
    self-check for the supplied points.
    """
    if points_file is None:
        return DEMO_PROFILES
    return {
        point["profile"]: {"point_key": point["key"]}
        for point in points
        if point.get("profile")
    }


# Bound on concurrent point resolves — each is an independent, I/O-bound
# resolve_asp() call (its own SODA queries). DEMO_POINTS is small (a handful
# of hand-picked coordinates), so this only needs to keep the build a good
# citizen of the SODA rate limit, not dedup work like the coverage dumper's
# per-group concurrency.
_POINT_CONCURRENCY = 5


async def _run(points: list[dict]) -> dict[str, dict]:
    """Resolve every point CONCURRENTLY (bounded), returning ``point_key -> {entry, coords}``."""

    async def _dump_one(point: dict) -> tuple[str, dict]:
        return point["key"], await dump_point(point["lat"], point["lon"])

    resolved = await bounded_gather(points, _dump_one, _POINT_CONCURRENCY)
    return dict(resolved)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Offline demo dataset dumper: resolve_asp -> demo.json + "
            "demo-segments.geojson for the static demo page."
        ),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("docs/demo/data"),
        help="Directory to write demo.json and demo-segments.geojson into.",
    )
    parser.add_argument(
        "--points",
        type=Path,
        default=None,
        help="Optional JSON file: [{key, lat, lon, profile?}]. Defaults to DEMO_POINTS.",
    )
    args = parser.parse_args(argv)

    points = _read_points(args.points)
    resolved = asyncio.run(_run(points))
    profiles = _profiles_for_points(points, args.points)

    # Build-time self-check: every DEMO_PROFILES target must have actually
    # resolved to a real, renderable status. Without this check a broken
    # profile point (e.g. a coordinate too far from any indexed segment, or a
    # transient SODA failure) silently ships and only surfaces as a dead
    # "Car B" toggle in the browser — this is exactly the class of bug this
    # check exists to catch. The failure set covers every exception
    # dump_point() can catch (_DUMP_POINT_FAILURE_EXCEPTIONS) plus the two
    # non-exception failure statuses build_point_entry() can emit.
    failure_statuses = {exc.__name__ for exc in _DUMP_POINT_FAILURE_EXCEPTIONS} | {
        "resolution_failed",
        "unknown",
    }
    broken_profiles = []
    for profile_key, profile in profiles.items():
        point_key = profile["point_key"]
        entry = resolved.get(point_key, {}).get("entry")
        if entry is None:
            broken_profiles.append(
                (profile_key, point_key, "point_key not in resolved set")
            )
            continue
        status = entry.get("status")
        if status in failure_statuses:
            broken_profiles.append((profile_key, point_key, f"status={status}"))
    if broken_profiles:
        details = "; ".join(
            f"{pk} ({key}): {reason}" for pk, key, reason in broken_profiles
        )
        print(
            f"build_demo_dataset: ERROR — {len(broken_profiles)} profile "
            f"target(s) failed to resolve: {details}",
            file=sys.stderr,
        )
        print(
            "  Fix: pick a different coordinate for the affected point_key(s) in "
            "DEMO_POINTS and re-run.",
            file=sys.stderr,
        )
        return 1

    # Assemble the committed demo.json (weekly patterns only; no absolute dates).
    # NYC-pinned "today" (not the build machine's local date — Pitfall 1): a
    # UTC-clocked CI runner can already be "tomorrow" while it is still
    # "today" in NYC for the evening hours this matters.
    dataset = {
        "generation_date": datetime.now(NYC_TZ).date().isoformat(),
        "profiles": profiles,
        "points": {key: payload["entry"] for key, payload in resolved.items()},
    }

    # One GeoJSON LineString feature per resolved segment (WGS84).
    features: list[dict] = []
    for key, payload in resolved.items():
        coords = payload["coords"]
        if not coords:
            continue
        entry = payload["entry"]
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "point_key": key,
                    "segment_id": entry.get("segment_id"),
                    "on_street": entry.get("on_street"),
                },
            }
        )
    geojson = {"type": "FeatureCollection", "features": features}

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "demo.json").write_text(json.dumps(dataset, indent=2) + "\n")
    (out_dir / "demo-segments.geojson").write_text(json.dumps(geojson, indent=2) + "\n")

    print(
        f"build_demo_dataset: wrote {out_dir / 'demo.json'} "
        f"({len(dataset['points'])} points) and "
        f"{out_dir / 'demo-segments.geojson'} ({len(features)} segments)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
