#!/usr/bin/env python3
"""Offline, build-time coverage dataset dumper for the static coverage explorer.

Walks the committed spatial-index segments, resolves each block's ASP schedule
against the SODA API (network wiring lands in plan 42-02), and serialises a
single small committed dataset (``docs/explorer/data/coverage.json``) that the
static explorer page (``docs/explorer/``) renders with no server.

This is a PRESENTATION-LAYER SNAPSHOT DUMPER — it re-implements no resolver
logic. It reuses ``normalize_to_soda`` for the canonical grouping key and derives
each segment's candidate parking sides from geometry alone; it does NOT recompute
the GPS-point-relative confidence (that needs a live GPS fix — RESEARCH Pitfall 2).

Two decay traps are deliberately avoided:

  * Date decay (Pitfall 3): the emitted dataset stores the WEEKLY PATTERN
    (day-of-week + start/end times) per block, NEVER an absolute next-move
    datetime. The client recomputes the next occurrence at page load.
  * Feet-vs-degrees (Pitfall 5): segment geometry (EPSG:2263 US survey feet) is
    reprojected to WGS84 before it can be drawn on a Leaflet map. Only ONE
    midpoint per segment is emitted to keep coverage.json small.

Security (T-42-01): the NYC SODA app token is a BUILD-TIME env var consumed only
inside the resolver's SODA client. The pure functions in this module never read
or touch any credential, and no token is ever serialised into coverage.json. The
serialization guard test lands in plan 42-02.

Canonical coverage.json schema is documented in 42-01-PLAN.md's <objective>; this
plan (42-01) locks the deterministic core (grouping key + tier partition). The
network resolve pipeline + main() land in 42-02.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from pyproj import Transformer
from shapely import wkt

from gps2asp.signs.normalize import normalize_to_soda

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

# SODA fallback level -> confidence (D-18). Level 0 (no match) and any unexpected
# level both map to 0.00 via the .get default. These are geometry-independent
# proxies: they express "how directly did the block match a SODA sign", NOT the
# GPS-point-relative resolver confidence (which needs a live fix — Pitfall 2).
CONFIDENCE_BY_LEVEL: dict[int, float] = {1: 0.90, 2: 0.66, 3: 0.40, 0: 0.00}

# The ONE half-open partition rule of the closed interval [0, 1]. Each tier owns
# [lower, upper): lower-inclusive, upper-exclusive — EXCEPT the top tier, which is
# inclusive of 1.0 so a perfect score is never orphaned. 0.33 is anchored to the
# resolver's DEFAULT_CONFIDENCE_THRESHOLD ("resolved" floor), so 0.33 lands in
# "low", never "unresolved". The tier NAME (not just a color) is the downstream
# channel: legend labels + per-tier marker radius (42-03/42-04), giving a
# non-hue signal for colorblind accessibility (T-42-05). Ordered high -> low so
# the first matching lower bound wins.
TIER_BOUNDS: tuple[tuple[float, str], ...] = (
    (0.75, "high"),
    (0.50, "medium"),
    (0.33, "low"),
    (0.00, "unresolved"),
)

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


def reproject_wkt_to_wgs84(geometry_wkt: str) -> list[list[float]]:
    """Reproject an EPSG:2263 LINESTRING WKT to WGS84 ``[[lon, lat], ...]``.

    Args:
        geometry_wkt: A ``LINESTRING`` in EPSG:2263 (NY State Plane, US feet).

    Returns:
        List of ``[lon, lat]`` coordinate pairs in GeoJSON order (WGS84).
    """
    line = wkt.loads(geometry_wkt)
    return [list(_TO_WGS84.transform(x, y)) for (x, y) in line.coords]


def segment_midpoint_wgs84(geometry_wkt: str) -> tuple[float, float]:
    """Reproject a segment's midpoint to WGS84 ``(lat, lon)`` rounded to 6 dp.

    Emitting a single midpoint per segment (rather than the full polyline) keeps
    coverage.json small (RESEARCH Pitfall 5). The 0.5 interpolation happens in
    EPSG:2263 (equal-area feet) BEFORE reprojection, so it is the true geometric
    midpoint, not a lon/lat average.

    Args:
        geometry_wkt: A ``LINESTRING`` in EPSG:2263 (NY State Plane, US feet).

    Returns:
        ``(lat, lon)`` in WGS84, each rounded to 6 decimal places.
    """
    line = wkt.loads(geometry_wkt)
    midpoint = line.interpolate(0.5, normalized=True)
    lon, lat = _TO_WGS84.transform(midpoint.x, midpoint.y)
    return (round(lat, 6), round(lon, 6))


def _borough_name(borocode: str | None) -> str | None:
    """Map a CSCL borough code to its human name, or None when unknown."""
    if borocode is None:
        return None
    return _BOROUGH_NAMES.get(str(borocode))


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


def derive_segment_sides(geometry_wkt: str) -> tuple[str, str]:
    """Return a segment's two candidate parking sides from its geometry bearing.

    The two sides are derived from the segment's run direction (first -> last
    coordinate), NEVER from ``has_asp_left``/``has_asp_right`` (which are always
    identical in the source data — D-02). An E-W street (bearing near 0/180 deg)
    has North and South curbs; an N-S street (bearing near 90/270 deg) has East
    and West curbs.

    Args:
        geometry_wkt: A ``LINESTRING`` in EPSG:2263 (NY State Plane, US feet).

    Returns:
        ``("N", "S")`` for an E-W segment, ``("E", "W")`` for an N-S segment.
    """
    line = wkt.loads(geometry_wkt)
    coords = list(line.coords)
    x0, y0 = coords[0][0], coords[0][1]
    x1, y1 = coords[-1][0], coords[-1][1]
    angle = math.degrees(math.atan2(y1 - y0, x1 - x0)) % 360
    # E-W run (bearing within +-45 deg of the E-W axis) -> North/South curbs.
    if 315 <= angle or angle < 45 or 135 <= angle < 225:
        return ("N", "S")
    # Otherwise the segment runs N-S -> East/West curbs.
    return ("E", "W")


def group_key(full_street_name: str, side: str) -> tuple[str, str]:
    """Canonical dedup key ``(normalized_street, side)`` for a block face.

    ``normalize_to_soda`` collapses casing / internal whitespace / abbreviation
    variants of the same street to ONE canonical form (D-01), so BROADWAY /
    Broadway / "W  THAMES ST" all fold onto a single street key. Pairing it with
    the derived ``side`` gives two recoverable keys per segment (one per curb),
    guaranteeing no segment is double-counted or dropped across group boundaries.

    Args:
        full_street_name: The block's on-street / full street name (CSCL form).
        side: One compass side letter ("N", "S", "E", or "W").

    Returns:
        ``(canonical_street, side)``.
    """
    return (normalize_to_soda(full_street_name), side)


def confidence_for_level(level: int) -> float:
    """Map a SODA fallback level to its geometry-independent confidence (D-18).

    Levels 1/2/3 -> 0.90/0.66/0.40; level 0 (no match) and any unexpected value
    -> 0.00. This is NOT the GPS-point resolver confidence (Pitfall 2).
    """
    return CONFIDENCE_BY_LEVEL.get(level, 0.0)


def tier_for_confidence(v: float) -> str:
    """Partition a confidence in [0, 1] into exactly one named tier.

    Applies the single half-open rule documented on ``TIER_BOUNDS``:
    ``[0.00, 0.33) unresolved | [0.33, 0.50) low | [0.50, 0.75) medium |
    [0.75, 1.00] high`` (top tier inclusive of 1.0). Returns a NAMED tier string
    usable as a text/shape channel downstream, not merely a color (T-42-05).

    Args:
        v: A confidence value, expected in the closed interval [0, 1].

    Returns:
        One of ``"high"``, ``"medium"``, ``"low"``, ``"unresolved"``.
    """
    for lower, name in TIER_BOUNDS:
        if v >= lower:
            return name
    # Values below 0.0 are not expected; treat them as unresolved defensively.
    return "unresolved"


def main(argv: list[str] | None = None) -> int:
    """Network resolve pipeline + serialisation — implemented in plan 42-02.

    This 42-01 plan locks only the deterministic, network-free core (grouping key
    + tier partition) behind tests. The SODA-backed resolve/write path lands next.
    """
    raise NotImplementedError(
        "build_coverage_dataset.main() is implemented in plan 42-02 "
        "(SODA resolve pipeline + coverage.json writer)."
    )


if __name__ == "__main__":
    import sys

    sys.exit(main())
