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

import argparse
import asyncio
import json
import logging
import math
import sys
from datetime import date, datetime
from pathlib import Path

from pyproj import Transformer
from shapely import wkt

from gps2asp.schedule import (
    ASPActiveNow,
    ScheduleFound,
    ScheduleResult,
    compute_schedule,
)
from gps2asp.signs import _cross_streets_match, materialize_cached_records
from gps2asp.signs.client import SODAClient
from gps2asp.signs.normalize import normalize_to_soda

logger = logging.getLogger("build_coverage_dataset")

# Fixed build-time reference instant fed to compute_schedule. The committed
# dataset stores only the WEEKLY pattern (never an absolute next-move date —
# Pitfall 3), so this instant does not leak into the output; it exists solely to
# make the run deterministic. 04:00 on a weekday sits outside every realistic ASP
# cleaning window, so no block spuriously resolves to "asp_active_now" at build
# time (the "resting" status is schedule_found). It is naive; the schedule layer
# attaches America/New_York.
_BUILD_REFERENCE_TIME = datetime(2025, 1, 1, 4, 0)

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


def _load_segment_records() -> dict[str, dict]:
    """Load ``segments.json`` into a ``segment_id -> full record`` map.

    Unlike ``_load_segments`` (which keeps only the geometry for reprojection),
    the whole-index resolve needs each block's street identity too:
    ``full_street_name``/``from_street``/``to_street``/``borocode`` plus the
    ``geometry_wkt`` used for the map midpoint and the geometry-derived sides.
    """
    raw = json.loads(_SEGMENTS_PATH.read_text())
    return {
        str(seg_id): rec
        for seg_id, rec in raw.items()
        if isinstance(rec, dict) and "geometry_wkt" in rec
    }


async def resolve_group(
    client: SODAClient,
    normalized_street: str,
    side: str,
) -> list[dict]:
    """Issue ONE broad SODA query for a whole ``(normalized street, side)`` group.

    This is the R1 dedup primitive: instead of one exact block query per segment
    (~105K calls), the build fetches every broom sign on a street+side ONCE, then
    recovers per-block precision client-side via the cross-street filter. Mirrors
    ``audit_queens_coverage.py``'s ``build_on_street_query`` + ``fetch_signs``
    pattern.

    Fail-soft (Pitfall 4): a failed group logs a WARNING and returns ``[]`` rather
    than aborting the whole-index run — every segment in the group then degrades
    to an explicit no-match entry (never a silent omission).

    Args:
        client: SODAClient (or a stub exposing the same two methods).
        normalized_street: Canonical street key (already ``normalize_to_soda``d).
        side: Compass side letter ("N", "S", "E", or "W").

    Returns:
        Raw SODA record dicts for the group, or ``[]`` on any query failure.
    """
    query = client.build_on_street_query(normalized_street, side)
    try:
        return await client.fetch_signs(query)
    except Exception as exc:  # noqa: BLE001 — fail-soft per group (Pitfall 4)
        logger.warning(
            "resolve_group: SODA query failed for street=%r side=%r: %s — "
            "treating group as empty",
            normalized_street,
            side,
            exc,
        )
        return []


def cross_streets_match(record: dict, from_street: str, to_street: str) -> bool:
    """Whether a SODA record covers this block's cross streets.

    Thin wrapper over the resolver's ``signs._cross_streets_match`` so the build
    reuses its variant + swap + empty-field guard (BUG-S-003) instead of a naive
    string compare (RESEARCH "Don't Hand-Roll").
    """
    return _cross_streets_match(record, from_street, to_street)


def _exact_cross_match(record: dict, from_street: str, to_street: str) -> bool:
    """Whether a record's cross streets match EXACTLY (no abbreviation variants).

    Used to separate soda_level 1 (exact from/to or exact swap) from level 2
    (matched only via an abbreviation variant). Compares the canonical
    ``normalize_to_soda`` forms directly, without expanding ``name_variants``.
    """
    record_from = record.get("from_street", "")
    record_to = record.get("to_street", "")
    if not record_from or not record_to or not from_street or not to_street:
        return False
    rf = normalize_to_soda(record_from.upper().strip())
    rt = normalize_to_soda(record_to.upper().strip())
    ff = normalize_to_soda(from_street.upper().strip())
    tt = normalize_to_soda(to_street.upper().strip())
    return (rf == ff and rt == tt) or (rf == tt and rt == ff)


def resolve_side(
    group_records: list[dict],
    on_street: str,
    from_street: str,
    to_street: str,
    side: str,
    now: datetime,
) -> tuple[int, ScheduleResult]:
    """Resolve ONE side of a block from its group's pre-fetched records.

    Assigns ``soda_level`` by match precision (D-18 confidence follows):
      * group empty (street absent from SODA) -> 0 (no-match)
      * an exact from/to (or exact swap) match exists -> 1
      * only abbreviation-variant matches exist -> 2
      * the group has records but NONE match this block's cross streets -> 3

    The filtered records are materialised into the resolver's ``SignRetrievalResult``
    shape and run through ``compute_schedule`` (fixed ``now``) so status/summary/
    weekly come from the SAME pipeline the live resolver uses. For levels 0 and 3
    the filter is empty, so ``materialize_cached_records`` yields ``NoMatchFound``
    -> a ``no_match`` schedule (still an explicit entry).

    Returns:
        ``(soda_level, schedule_result)``.
    """
    filtered = [
        r for r in group_records if cross_streets_match(r, from_street, to_street)
    ]
    if not group_records:
        soda_level = 0
    elif any(_exact_cross_match(r, from_street, to_street) for r in filtered):
        soda_level = 1
    elif filtered:
        soda_level = 2
    else:
        soda_level = 3

    sign_result = materialize_cached_records(
        filtered,
        on_street,
        from_street,
        to_street,
        side,
        # For empty `filtered` this marker is unused (NoMatchFound short-circuits);
        # clamp to a valid level>=1 for the success shape when records are present.
        soda_level if soda_level >= 1 else 1,
    )
    schedule = compute_schedule(sign_result, now=now)
    return soda_level, schedule


def _summary_and_weekly(
    schedule: ScheduleResult,
) -> tuple[str | None, list[dict]]:
    """Extract ``(summary, weekly_pattern)`` from a schedule result.

    The weekly pattern stores ``{d, s, e}`` = day value + start/end ``%H:%M``
    ONLY — never an absolute date (Pitfall 3) and never the raw sign text (D-04,
    unlike ``build_demo_dataset`` which keeps ``sign``). Non-schedule variants
    (no_asp / no_match / all_unparseable) yield ``(None, [])``.
    """
    if isinstance(schedule, ScheduleFound):
        weekly = [
            {
                "d": window.day.value,
                "s": window.start_time.strftime("%H:%M"),
                "e": window.end_time.strftime("%H:%M"),
            }
            for window in schedule.weekly_schedule.windows
        ]
        return schedule.summary, weekly
    if isinstance(schedule, ASPActiveNow):
        # No weekly_schedule on the active variant — only the single active
        # window. Still surface it so the client renders a schedule (mirrors
        # build_demo_dataset's asp_active_now handling).
        window = schedule.active_window
        weekly = [
            {
                "d": window.day.value,
                "s": window.start_time.strftime("%H:%M"),
                "e": window.end_time.strftime("%H:%M"),
            }
        ]
        return schedule.summary, weekly
    return None, []


def build_segment_entry(
    segment_id: str,
    seg_record: dict,
    side: str,
    soda_level: int,
    schedule: ScheduleResult,
) -> dict:
    """Assemble ONE canonical compact coverage.json segment entry (42-01 schema).

    Emits EXACTLY the locked short keys and no others:
    ``id, lat, lon, st, fr, to, sd, bc, lv, cf, status, sm, wk``. No credential
    field, no raw sign text, no absolute date.

    Args:
        segment_id: The segment id (dataset ``id``).
        seg_record: The raw segments.json record (street identity + geometry).
        side: The worst-case side chosen for this segment (D-13).
        soda_level: Match-precision level for the chosen side.
        schedule: The chosen side's schedule result.
    """
    lat, lon = segment_midpoint_wgs84(seg_record["geometry_wkt"])
    summary, weekly = _summary_and_weekly(schedule)
    return {
        "id": segment_id,
        "lat": lat,
        "lon": lon,
        "st": seg_record.get("full_street_name"),
        "fr": seg_record.get("from_street"),
        "to": seg_record.get("to_street"),
        "sd": side,
        "bc": str(seg_record.get("borocode")),
        "lv": soda_level,
        "cf": confidence_for_level(soda_level),
        "status": schedule.status,
        "sm": summary,
        "wk": weekly,
    }


async def build_coverage(
    segments: dict[str, dict],
    client: SODAClient,
    *,
    now: datetime = _BUILD_REFERENCE_TIME,
    limit: int | None = None,
) -> dict:
    """Resolve the whole index deduped by ``(street, side)`` into the dataset dict.

    Steps (R1):
      1. For each segment, derive its two geometry-based sides and their two
         ``group_key``s; collect the DISTINCT set of ``(normalized street, side)``
         groups.
      2. Issue exactly ONE ``resolve_group`` per distinct group, caching records
         in memory — this is the dedup: SODA call count == distinct-group count,
         far below the segment count.
      3. For each segment, resolve BOTH sides against their group's records and
         pick the WORST-CASE side (lower confidence; D-13). A segment is only
         high-tier when both sides resolve well.
      4. Build one compact entry per segment — never omit a segment.

    Args:
        segments: ``segment_id -> raw segments.json record`` (in-memory; tests
            pass a tiny stub map, ``main`` passes the whole index).
        client: SODAClient (or a stub exposing build_on_street_query/fetch_signs).
        now: Fixed build-time instant for compute_schedule (determinism).
        limit: If set, resolve only the first N segments (local smoke runs).

    Returns:
        The full dataset dict (``generation_date, boroughs, query_count,
        segment_count, segments``).
    """
    items = list(segments.items())
    if limit is not None:
        items = items[:limit]

    # ---- pass 1: derive per-segment sides + collect the distinct group set ----
    # seg_plan[sid] = (on_street, from_street, to_street, [(side, group_key), ...])
    seg_plan: dict[str, tuple[str, str, str, list[tuple[str, tuple[str, str]]]]] = {}
    distinct_groups: dict[tuple[str, str], None] = {}
    for sid, rec in items:
        on_street = rec["full_street_name"]
        from_street = rec["from_street"]
        to_street = rec["to_street"]
        sides = derive_segment_sides(rec["geometry_wkt"])
        side_keys: list[tuple[str, tuple[str, str]]] = []
        for side in sides:
            gk = group_key(on_street, side)
            distinct_groups[gk] = None
            side_keys.append((side, gk))
        seg_plan[sid] = (on_street, from_street, to_street, side_keys)

    # ---- resolve each distinct group exactly once (the R1 dedup) ----
    group_records: dict[tuple[str, str], list[dict]] = {}
    for normalized_street, side in distinct_groups:
        group_records[(normalized_street, side)] = await resolve_group(
            client, normalized_street, side
        )
    query_count = len(distinct_groups)

    # ---- pass 2: worst-case side per segment -> one entry each ----
    segment_entries: list[dict] = []
    for sid, rec in items:
        on_street, from_street, to_street, side_keys = seg_plan[sid]
        best: tuple[float, int, str, ScheduleResult] | None = None
        for side, gk in side_keys:
            soda_level, schedule = resolve_side(
                group_records[gk], on_street, from_street, to_street, side, now
            )
            cf = confidence_for_level(soda_level)
            # Worst-case = LOWER confidence (D-13); ties keep the first side.
            if best is None or cf < best[0]:
                best = (cf, soda_level, side, schedule)
        assert best is not None  # every segment has at least one side
        _, worst_level, worst_side, worst_schedule = best
        segment_entries.append(
            build_segment_entry(sid, rec, worst_side, worst_level, worst_schedule)
        )

    return {
        "generation_date": date.today().isoformat(),
        "boroughs": _BOROUGH_NAMES,
        "query_count": query_count,
        "segment_count": len(segment_entries),
        "segments": segment_entries,
    }


def main(argv: list[str] | None = None) -> int:
    """Whole-index SODA resolve + coverage.json writer (R1).

    Reads the committed spatial-index segments (or a ``--segments`` override for
    tests/smoke runs), resolves every segment deduped by ``(street, side)``, and
    writes the canonical compact ``coverage.json``. The SODA app token is read
    ONLY inside ``SODAClient`` (from the environment); this script never reads it
    and never serialises any credential (T-42-01).
    """
    parser = argparse.ArgumentParser(
        description=(
            "Offline whole-index coverage dumper: grouped SODA resolve -> "
            "coverage.json for the static street-sign coverage explorer."
        ),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("docs/explorer/data"),
        help="Directory to write coverage.json into.",
    )
    parser.add_argument(
        "--segments",
        type=Path,
        default=None,
        help="Optional segments.json override (id -> record). Defaults to the "
        "committed spatial index.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Resolve only the first N segments (local smoke runs).",
    )
    args = parser.parse_args(argv)

    if args.segments is not None:
        segments = json.loads(args.segments.read_text())
    else:
        segments = _load_segment_records()

    expected_count = len(segments) if args.limit is None else min(args.limit, len(segments))

    client = SODAClient()
    dataset = asyncio.run(build_coverage(segments, client, limit=args.limit))

    # Build-time self-check: fail loud if any segment was dropped (R1: never an
    # omitted entry). The whole-index build has no per-point fallback, so a count
    # mismatch is a hard bug, not a soft-degrade.
    actual = len(dataset["segments"])
    if actual != expected_count:
        print(
            f"build_coverage_dataset: ERROR — expected {expected_count} segment "
            f"entries but produced {actual}; refusing to write a lossy dataset.",
            file=sys.stderr,
        )
        return 1

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "coverage.json"
    out_path.write_text(json.dumps(dataset, indent=2) + "\n")

    # R1 verifiability: the low-thousands query claim must be readable from the
    # run output.
    print(
        f"build_coverage_dataset: issued {dataset['query_count']} SODA group "
        f"queries for {actual} segments -> {out_path}"
    )
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
