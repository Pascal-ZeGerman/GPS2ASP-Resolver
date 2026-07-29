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
from datetime import date
from pathlib import Path

from pyproj import Transformer
from shapely import wkt

from gps2asp import resolve_asp
from gps2asp.resolver.exceptions import (
    IndexNotFoundError,
    NoSegmentFoundError,
    OutsideNYCError,
)
from gps2asp.schedule.models import ScheduleFound
from gps2asp.signs.exceptions import IncompleteResultsError, SODAAPIError

# Reverse of resolver/converter.py's forward transform: EPSG:2263 -> WGS84.
# always_xy=True yields (lon, lat) — exactly GeoJSON coordinate order.
_TO_WGS84 = Transformer.from_crs("EPSG:2263", "EPSG:4326", always_xy=True)

# CSCL borough code -> human name (mirrors coordinator._BOROUGH_NAMES).
_BOROUGH_NAMES: dict[str, str] = {
    "1": "Manhattan",
    "2": "Bronx",
    "3": "Brooklyn",
    "4": "Queens",
    "5": "Staten Island",
}

# side_of_street letter -> display label (mirrors sensor._SIDE_LABELS).
_SIDE_LABELS: dict[str, str] = {
    "N": "North side",
    "S": "South side",
    "E": "East side",
    "W": "West side",
}

# Lazily-loaded segment geometry cache: str(segment_id) -> geometry_wkt.
_SEGMENTS_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "gps2asp"
    / "data"
    / "index"
    / "segments.json"
)
_segments_cache: dict[str, str] | None = None


# Hand-picked demo coordinates. Includes the canonical Prospect Pl regression
# case, a point expected to have no ASP restrictions, and one deliberately
# outside coverage to exercise the per-point failure path (Pitfall 4).
DEMO_POINTS: list[dict] = [
    {"key": "prospect_pl", "lat": 40.677629, "lon": -73.968527},
    {"key": "east_village", "lat": 40.726379, "lon": -73.981583},
    {"key": "upper_west_side", "lat": 40.785091, "lon": -73.975502},
    {"key": "astoria", "lat": 40.762130, "lon": -73.923462},
    {"key": "bronx_grand_concourse", "lat": 40.830990, "lon": -73.918030},
    {"key": "central_park_no_restrictions", "lat": 40.782864, "lon": -73.965355},
    {"key": "outside_coverage", "lat": 40.912000, "lon": -73.700000},
]

# Sample car/profile assignments demonstrating results vary by location.
DEMO_PROFILES: dict[str, dict] = {
    "A": {"label": "Car A", "point_key": "prospect_pl"},
    "B": {"label": "Car B", "point_key": "east_village"},
}


def reproject_wkt_to_wgs84(geometry_wkt: str) -> list[list[float]]:
    """Reproject an EPSG:2263 LINESTRING WKT to WGS84 ``[[lon, lat], ...]``.

    Args:
        geometry_wkt: A ``LINESTRING`` in EPSG:2263 (NY State Plane, US feet).

    Returns:
        List of ``[lon, lat]`` coordinate pairs in GeoJSON order (WGS84).
    """
    line = wkt.loads(geometry_wkt)
    return [list(_TO_WGS84.transform(x, y)) for (x, y) in line.coords]


def _borough_name(borocode: str | None) -> str | None:
    """Map a CSCL borough code to its human name, or None when unknown."""
    if borocode is None:
        return None
    return _BOROUGH_NAMES.get(str(borocode))


def _cleaning_day_names(result) -> list[str]:
    """Ordered unique cleaning-day names from a ScheduleFound weekly pattern."""
    schedule = result.schedule
    if not isinstance(schedule, ScheduleFound):
        return []
    seen: list[str] = []
    for window in schedule.weekly_schedule.windows:
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

    # --- Next Move Time sensor (primary, user-facing) ---
    next_move_attrs: dict = {}
    cleaning_days = _cleaning_day_names(result)
    if cleaning_days:
        next_move_attrs["cleaning_days"] = cleaning_days
    if isinstance(result.schedule, ScheduleFound):
        next_move_attrs["schedule_summary"] = result.schedule.summary
    if result.on_street is not None:
        next_move_attrs["street_name"] = result.on_street
    if result.from_street is not None and result.to_street is not None:
        next_move_attrs["cross_streets"] = f"{result.from_street} to {result.to_street}"
    if side is not None:
        next_move_attrs["side_of_street"] = side
    if side_label is not None:
        next_move_attrs["side_label"] = side_label
    next_move_attrs["confidence_score"] = result.confidence
    if borough is not None:
        next_move_attrs["borough"] = borough
    next_move_attrs["soda_level"] = result.soda_level

    # --- Resolved Street sensor (secondary) ---
    resolved_attrs: dict = {}
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


def _load_segments() -> dict[str, str]:
    """Lazily load ``segments.json`` into a ``segment_id -> geometry_wkt`` map."""
    global _segments_cache
    if _segments_cache is None:
        raw = json.loads(_SEGMENTS_PATH.read_text())
        _segments_cache = {
            str(seg_id): rec["geometry_wkt"]
            for seg_id, rec in raw.items()
            if isinstance(rec, dict) and "geometry_wkt" in rec
        }
    return _segments_cache


def _segment_coords(segment_id) -> list[list[float]] | None:
    """Reprojected WGS84 coords for a segment id, or None when unavailable."""
    if segment_id is None:
        return None
    geometry_wkt = _load_segments().get(str(segment_id))
    if geometry_wkt is None:
        return None
    return reproject_wkt_to_wgs84(geometry_wkt)


async def dump_point(lat: float, lon: float) -> dict:
    """Resolve one coordinate, fail-soft per-point.

    Returns a dict ``{"entry": <demo entry>, "coords": <reprojected coords|None>}``.
    On any infrastructural resolver error the point degrades to a minimal entry
    with a status naming the error — the whole run is never aborted (Pitfall 4).
    """
    try:
        result = await resolve_asp(lat, lon, debug=True)
    except (
        OutsideNYCError,
        NoSegmentFoundError,
        IndexNotFoundError,
        SODAAPIError,
        IncompleteResultsError,
    ) as exc:
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
    coords = _segment_coords(result.segment_id)
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


async def _run(points: list[dict]) -> dict[str, dict]:
    """Resolve every point, returning ``point_key -> {entry, coords}``."""
    results: dict[str, dict] = {}
    for point in points:
        key = point["key"]
        results[key] = await dump_point(point["lat"], point["lon"])
    return results


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

    # Assemble the committed demo.json (weekly patterns only; no absolute dates).
    dataset = {
        "generation_date": date.today().isoformat(),
        "profiles": DEMO_PROFILES,
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
