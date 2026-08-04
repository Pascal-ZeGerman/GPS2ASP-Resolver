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
from datetime import datetime
from pathlib import Path

from shapely import wkt

from gps2asp.schedule import (
    ASPActiveNow,
    ScheduleFound,
    ScheduleResult,
    compute_schedule,
)
from gps2asp.dataset_common import (
    BOROUGH_NAMES,
    TO_WGS84,
    bounded_gather,
    load_segment_records_with_raw_count,
)
from gps2asp.resolver.confidence import DEFAULT_CONFIDENCE_THRESHOLD
from gps2asp.schedule.next_move import NYC_TZ
from gps2asp.signs import _normalize_street, materialize_cached_records
from gps2asp.signs.client import SODAClient
from gps2asp.signs.normalize import name_variants, normalize_to_soda

logger = logging.getLogger("build_coverage_dataset")

# Fixed build-time reference instant fed to compute_schedule. The committed
# dataset stores only the WEEKLY pattern (never an absolute next-move date —
# Pitfall 3), so this instant does not leak into the output; it exists solely to
# make the run deterministic. 04:00 on a weekday sits outside every realistic ASP
# cleaning window, so no block spuriously resolves to "asp_active_now" at build
# time (the "resting" status is schedule_found). It is naive; the schedule layer
# attaches America/New_York.
_BUILD_REFERENCE_TIME = datetime(2025, 1, 1, 4, 0)

# Bound on concurrent group RESOLUTIONS (R1's whole-index resolve dedups to one
# in-flight resolve_group call per distinct (street, side) group — low
# thousands for the full index; each resolve_group call issues 1-2 SODA
# queries, one per name_variants form). Unbounded asyncio.gather would fire
# them all at once; this caps in-flight requests so the build stays a good
# citizen of the SODA rate limit.
_GROUP_CONCURRENCY = 10

# SODA fallback level -> confidence (D-18). Level 0 (street absent from SODA)
# and level 3 (street present but no record matches this block's cross streets)
# both represent a true no-match for THIS block — resolve_side's materialized
# schedule is NoMatchFound either way — so both map to 0.00 and land in the
# "unresolved" tier. Any unexpected level also maps to 0.00 via the .get
# default. These are geometry-independent proxies: they express "how directly
# did the block match a SODA sign", NOT the GPS-point-relative resolver
# confidence (which needs a live fix — Pitfall 2).
CONFIDENCE_BY_LEVEL: dict[int, float] = {1: 0.90, 2: 0.66, 3: 0.00, 0: 0.00}

# The ONE half-open partition rule of the closed interval [0, 1]. Each tier owns
# [lower, upper): lower-inclusive, upper-exclusive — EXCEPT the top tier, which is
# inclusive of 1.0 so a perfect score is never orphaned. DEFAULT_CONFIDENCE_THRESHOLD
# is anchored to the resolver's "resolved" floor, so it lands in "low", never
# "unresolved". The tier NAME (not just a color) is the downstream channel: legend
# labels + per-tier marker radius (42-03/42-04), giving a non-hue signal for
# colorblind accessibility (T-42-05). Ordered high -> low so the first matching
# lower bound wins.
TIER_BOUNDS: tuple[tuple[float, str], ...] = (
    (0.75, "high"),
    (0.50, "medium"),
    (DEFAULT_CONFIDENCE_THRESHOLD, "low"),
    (0.00, "unresolved"),
)

def segment_midpoint_wgs84(line) -> tuple[float, float]:
    """Reproject a segment's midpoint to WGS84 ``(lat, lon)`` rounded to 6 dp.

    Emitting a single midpoint per segment (rather than the full polyline) keeps
    coverage.json small (RESEARCH Pitfall 5). The 0.5 interpolation happens in
    EPSG:2263 (equal-area feet) BEFORE reprojection, so it is the true geometric
    midpoint, not a lon/lat average.

    Args:
        line: The segment's already-parsed ``LINESTRING`` geometry (a
            ``shapely`` geometry, EPSG:2263 / NY State Plane, US feet).
            Callers that already parsed the WKT for another purpose (e.g.
            ``_sides_from_line``) pass that same geometry object instead of
            re-parsing the WKT string.

    Returns:
        ``(lat, lon)`` in WGS84, each rounded to 6 decimal places.
    """
    midpoint = line.interpolate(0.5, normalized=True)
    lon, lat = TO_WGS84.transform(midpoint.x, midpoint.y)
    return (round(lat, 6), round(lon, 6))


def _sides_from_line(line) -> tuple[str, str]:
    """Bearing-based side derivation (D-02) from an already-parsed geometry.

    The two sides are derived from the segment's run direction (first -> last
    coordinate), NEVER from ``has_asp_left``/``has_asp_right`` (which are always
    identical in the source data — D-02). An E-W street (bearing near 0/180 deg)
    has North and South curbs; an N-S street (bearing near 90/270 deg) has East
    and West curbs.

    Args:
        line: An already-parsed ``LINESTRING`` geometry (``shapely``).

    Returns:
        ``("N", "S")`` for an E-W segment, ``("E", "W")`` for an N-S segment.
    """
    coords = list(line.coords)
    x0, y0 = coords[0][0], coords[0][1]
    x1, y1 = coords[-1][0], coords[-1][1]
    angle = math.degrees(math.atan2(y1 - y0, x1 - x0)) % 360
    # E-W run (bearing within +-45 deg of the E-W axis) -> North/South curbs.
    if 315 <= angle or angle < 45 or 135 <= angle < 225:
        return ("N", "S")
    # Otherwise the segment runs N-S -> East/West curbs.
    return ("E", "W")


def derive_segment_sides(geometry_wkt: str) -> tuple[str, str]:
    """Return a segment's two candidate parking sides from its geometry bearing.

    WKT-string entrypoint used by callers that have not already parsed the
    geometry. ``build_coverage``'s whole-index loop parses the WKT once per
    segment and calls ``_sides_from_line`` directly instead, reusing that same
    parsed geometry for the segment's midpoint too.

    Args:
        geometry_wkt: A ``LINESTRING`` in EPSG:2263 (NY State Plane, US feet).

    Returns:
        ``("N", "S")`` for an E-W segment, ``("E", "W")`` for an N-S segment.
    """
    return _sides_from_line(wkt.loads(geometry_wkt))


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

    Levels 1/2 -> 0.90/0.66; level 3 (street present but no record matches this
    block), level 0 (street absent from SODA), and any unexpected value all
    -> 0.00. This is NOT the GPS-point resolver confidence (Pitfall 2).
    """
    return CONFIDENCE_BY_LEVEL.get(level, 0.0)


def confidence_for_result(level: int, schedule: ScheduleResult) -> float:
    """Confidence for one resolved side, accounting for unparseable signs.

    ``confidence_for_level`` alone only reflects match precision (whether a
    cross-street match was found), not whether the matched sign(s) actually
    parsed into a usable schedule. An ``all_unparseable`` schedule (sign(s)
    matched but their text failed to parse) is a genuine coverage gap and must
    never surface at high/medium confidence just because the street matched
    (Prohibition 2 / T-42-04 — never let a gap read as well-resolved).
    """
    if schedule.status == "all_unparseable":
        return 0.0
    return confidence_for_level(level)


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


async def resolve_group(
    client: SODAClient,
    on_streets: str | list[str],
    side: str,
) -> tuple[list[dict], int]:
    """Issue broad SODA queries for a whole ``(street, side)`` group.

    This is the R1 dedup primitive: instead of one exact block query per segment
    (~105K calls), the build fetches every broom sign on a street+side ONCE per
    name variant, then recovers per-block precision client-side via the
    cross-street filter. Tries every ``name_variants`` form of EVERY distinct raw
    spelling observed for the group (the canonical SODA-expanded name, then each
    raw CSCL form that differs from it) and merges the results — mirroring
    production's ``retrieve_signs`` Level 3 fallback loop, which iterates the same
    variants instead of querying only one canonical form. Without this, a street
    whose live SODA ``on_street`` field is stored in a raw CSCL form that only
    ONE sibling segment happens to use would return zero records here even
    though the live resolver would find it for that segment.

    Fail-soft (Pitfall 4): a failed variant query logs a WARNING and
    contributes no records rather than aborting the whole group — every
    segment in the group still degrades to an explicit no-match entry at
    worst, never a silent omission.

    Args:
        client: SODAClient (or a stub exposing the same two methods).
        on_streets: The group's raw on-street name(s) (CSCL form). A single
            string is accepted for the common one-spelling case; a list covers
            a group whose segments carry more than one distinct raw spelling
            of the same normalized street — every spelling's variants are
            queried so no sibling segment's SODA form is skipped.
        side: Compass side letter ("N", "S", "E", or "W").

    Returns:
        ``(records, query_count)`` — raw SODA record dicts merged across every
        variant query (``[]`` if every variant query failed or returned
        nothing), and the number of HTTP queries actually issued (one per
        distinct ``name_variants`` form across all ``on_streets``).
    """
    if isinstance(on_streets, str):
        on_streets = [on_streets]
    records: list[dict] = []
    variants: list[str] = []
    seen_variants: set[str] = set()
    for on_street in on_streets:
        try:
            street_variants = name_variants(on_street)
        except Exception as exc:  # noqa: BLE001 — fail-soft per street (Pitfall 4)
            logger.warning(
                "resolve_group: failed to derive name variants for street=%r "
                "side=%r: %s — skipping this spelling",
                on_street,
                side,
                exc,
            )
            continue
        for variant in street_variants:
            if variant not in seen_variants:
                seen_variants.add(variant)
                variants.append(variant)
    async def _fetch_variant(variant: str) -> list[dict]:
        try:
            query = client.build_on_street_query(variant, side)
            return await client.fetch_signs(query)
        except Exception as exc:  # noqa: BLE001 — fail-soft per variant (Pitfall 4)
            logger.warning(
                "resolve_group: SODA query failed for streets=%r (variant=%r) "
                "side=%r: %s — treating variant as empty",
                on_streets,
                variant,
                side,
                exc,
            )
            return []

    query_count = len(variants)
    variant_results = await asyncio.gather(*(_fetch_variant(v) for v in variants))
    for variant_records in variant_results:
        records.extend(variant_records)
    return records, query_count


def _exact_cross_match(record: dict, from_street: str, to_street: str) -> bool:
    """Whether a record's cross streets match EXACTLY (no abbreviation variants).

    Used to separate soda_level 1 (exact from/to or exact swap) from level 2
    (matched only via an abbreviation variant). Compares the RAW (upper/
    stripped, but NOT ``normalize_to_soda``-expanded) forms directly. A
    record only ever reaches this check by already having matched via
    ``index_group_records``, which keys on the ``normalize_to_soda`` form —
    so comparing normalized forms here would always be true and level 2
    could never be reached; comparing the raw literal forms instead lets a
    record whose spelling only matched through abbreviation normalization
    (e.g. "E 100 ST" vs "EAST  100 STREET") correctly fall through to level 2.
    """
    record_from = record.get("from_street", "")
    record_to = record.get("to_street", "")
    if not record_from or not record_to or not from_street or not to_street:
        return False
    rf = record_from.upper().strip()
    rt = record_to.upper().strip()
    ff = from_street.upper().strip()
    tt = to_street.upper().strip()
    return (rf == ff and rt == tt) or (rf == tt and rt == ff)


def _street_key(raw: str) -> str | None:
    """Canonical normalized-street key for cross-street indexing, or ``None``.

    Reuses the resolver's own ``_normalize_street`` so this dumper's
    soda_level classification can never silently drift from what the live
    resolver would return for the same record, plus an empty-field guard
    (BUG-S-003): an empty raw field never produces an indexable key, so it
    can never spuriously match.
    """
    if not raw:
        return None
    return _normalize_street(raw)


def index_group_records(group_records: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """Pre-index a group's records by normalized ``(from, to)`` cross-street pair.

    Built ONCE per group (the R1 dedup group), turning the per-segment
    cross-street lookup from an O(group_size) linear scan into O(1)-ish dict
    probes. A popular street (e.g. BROADWAY) can pool 100+ records into one
    group; without this index, every one of that street's many segments
    re-scanned the WHOLE group list in ``_cross_street_candidates``.

    Args:
        group_records: Raw SODA record dicts for one ``(street, side)`` group.

    Returns:
        ``(normalized_from, normalized_to) -> [matching records]``.
    """
    index: dict[tuple[str, str], list[dict]] = {}
    for record in group_records:
        from_key = _street_key(record.get("from_street", ""))
        to_key = _street_key(record.get("to_street", ""))
        if from_key is None or to_key is None:
            continue  # BUG-S-003 guard: never index an empty cross-street field
        index.setdefault((from_key, to_key), []).append(record)
    return index


def _street_variants(street: str) -> set[str]:
    """Upper/stripped ``name_variants`` set for one street, or empty if blank."""
    if not street:
        return set()
    return {v.upper().strip() for v in name_variants(street)}


def _cross_street_candidates(
    group_index: dict[tuple[str, str], list[dict]],
    from_variants: set[str],
    to_variants: set[str],
) -> list[dict]:
    """Records whose cross streets match ``(from_variants, to_variants)``, either order.

    Reproduces the resolver's ``_cross_streets_match`` direct-OR-swapped,
    variant-expanded semantics (same guard, same ``name_variants`` expansion)
    via bounded dict probes against a pre-built ``index_group_records`` index
    instead of a linear scan of every record in the group.

    Args:
        group_index: Output of ``index_group_records`` for this block's group.
        from_variants: This block's from_street, expanded via ``_street_variants``
            — precomputed once per segment (perf: a segment's two sides share
            identical from/to streets, so the caller derives this ONCE rather
            than re-running ``name_variants`` per side).
        to_variants: This block's to_street, expanded via ``_street_variants``.

    Returns:
        Matching records (no particular order; never contains duplicates).
    """
    if not from_variants or not to_variants:
        return []

    seen_ids: set[int] = set()
    matches: list[dict] = []
    for fv in from_variants:
        for tv in to_variants:
            for bucket_key in ((fv, tv), (tv, fv)):
                for record in group_index.get(bucket_key, ()):
                    if id(record) not in seen_ids:
                        seen_ids.add(id(record))
                        matches.append(record)
    return matches


def resolve_side(
    group_records: list[dict],
    group_index: dict[tuple[str, str], list[dict]],
    on_street: str,
    from_street: str,
    to_street: str,
    from_variants: set[str],
    to_variants: set[str],
    side: str,
    now: datetime,
) -> tuple[int, ScheduleResult]:
    """Resolve ONE side of a block from its group's pre-fetched, pre-indexed records.

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

    Args:
        group_records: The group's raw records — used only to detect the
            street-absent-from-SODA case (level 0); the actual cross-street
            match runs against ``group_index``.
        group_index: ``index_group_records(group_records)``, built once per
            group and reused across every segment on that group (perf).
        from_variants: ``_street_variants(from_street)``, precomputed once per
            segment by the caller (perf: both of a segment's sides share the
            same from/to streets, so name_variants shouldn't re-run per side).
        to_variants: ``_street_variants(to_street)``, precomputed likewise.

    Returns:
        ``(soda_level, schedule_result)``.
    """
    filtered = _cross_street_candidates(group_index, from_variants, to_variants)
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
    if isinstance(schedule, (ScheduleFound, ASPActiveNow)):
        # Emit the FULL merged weekly_schedule (every cleaning day), not just the
        # single in-progress active_window (for ASPActiveNow) — otherwise wk[]
        # silently drops days the summary text lists (BUG-ASPActiveNow-full-weekly).
        weekly = [
            {
                "d": window.day.value,
                "s": window.start_time.strftime("%H:%M"),
                "e": window.end_time.strftime("%H:%M"),
            }
            for window in schedule.weekly_schedule.windows
        ]
        return schedule.summary, weekly
    return None, []


def build_segment_entry(
    segment_id: str,
    seg_record: dict,
    line,
    side: str,
    soda_level: int,
    schedule: ScheduleResult,
    confidence: float,
) -> dict:
    """Assemble ONE canonical compact coverage.json segment entry (42-01 schema).

    Emits EXACTLY the locked short keys and no others:
    ``id, lat, lon, st, fr, to, sd, bc, lv, cf, status, sm, wk``. No credential
    field, no raw sign text, no absolute date.

    Args:
        segment_id: The segment id (dataset ``id``).
        seg_record: The raw segments.json record (street identity).
        line: The segment's already-parsed geometry (same object used to
            derive its sides in pass 1 — avoids re-parsing the WKT).
        side: The worst-case side chosen for this segment (D-13).
        soda_level: Match-precision level for the chosen side.
        schedule: The chosen side's schedule result.
        confidence: The chosen side's confidence score — the same
            ``confidence_for_result(soda_level, schedule)`` value the caller
            already computed to pick this side as the worst case (D-13), so
            the picked winner and the serialized ``cf`` can never disagree.
    """
    lat, lon = segment_midpoint_wgs84(line)
    summary, weekly = _summary_and_weekly(schedule)
    return {
        "id": segment_id,
        "lat": lat,
        "lon": lon,
        "st": seg_record.get("full_street_name"),
        "fr": seg_record.get("from_street"),
        "to": seg_record.get("to_street"),
        "sd": side,
        "bc": None if (bc := seg_record.get("borocode")) is None else str(bc),
        "lv": soda_level,
        "cf": confidence,
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
      1. For each segment, parse its geometry ONCE and derive its two
         geometry-based sides and their two ``group_key``s from that same
         parsed geometry; collect the DISTINCT set of ``(normalized street,
         side)`` groups, keyed to one representative original street name.
      2. Resolve every distinct group CONCURRENTLY (bounded by
         ``_GROUP_CONCURRENCY``), caching records in memory — this is the
         dedup: SODA group count == distinct-group count, far below the
         segment count.
      3. Pre-index each group's records once (``index_group_records``) so
         pass 2's per-segment cross-street lookup is O(1)-ish instead of an
         O(group_size) rescan.
      4. For each segment, resolve BOTH sides against their group's index and
         pick the WORST-CASE side (lower confidence; D-13). A segment is only
         high-tier when both sides resolve well. Reuses the SAME parsed
         geometry from step 1 for the segment's midpoint (no re-parse).
      5. Build one compact entry per segment — never omit a segment.

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

    # ---- pass 1: parse geometry once, derive sides, collect distinct groups ----
    # seg_plan[sid] = (on_street, from_street, to_street, line, [(side, group_key), ...])
    seg_plan: dict[
        str, tuple[str, str, str, object, list[tuple[str, tuple[str, str]]]]
    ] = {}
    # distinct_groups[group_key] = every distinct raw (CSCL-form) street
    # spelling observed for that group, used to seed resolve_group's
    # name_variants fallback. name_variants() only emits the raw/abbreviated
    # form when it differs from the canonical SODA form (see name_variants
    # docstring), so collecting a SINGLE "first/best" representative spelling
    # can silently drop the abbreviated-form fallback query for a sibling
    # segment whose raw spelling differs from the chosen representative's.
    # Collecting every distinct spelling (deduped in resolve_group) queries
    # the full superset of variants any segment in the group could need.
    distinct_groups: dict[tuple[str, str], list[str]] = {}
    for sid, rec in items:
        on_street = rec["full_street_name"]
        from_street = rec["from_street"]
        to_street = rec["to_street"]
        line = wkt.loads(rec["geometry_wkt"])
        sides = _sides_from_line(line)
        side_keys: list[tuple[str, tuple[str, str]]] = []
        for side in sides:
            gk = group_key(on_street, side)
            streets = distinct_groups.setdefault(gk, [])
            if on_street not in streets:
                streets.append(on_street)
            side_keys.append((side, gk))
        seg_plan[sid] = (on_street, from_street, to_street, line, side_keys)

    # ---- resolve every distinct group concurrently (the R1 dedup) ----
    async def _resolve_one(
        item: tuple[tuple[str, str], list[str]],
    ) -> tuple[tuple[str, str], list[dict], int]:
        gk, group_streets = item
        _, side = gk
        records, count = await resolve_group(client, group_streets, side)
        return gk, records, count

    resolved = await bounded_gather(
        distinct_groups.items(), _resolve_one, _GROUP_CONCURRENCY
    )
    group_records: dict[tuple[str, str], list[dict]] = {}
    query_count = 0
    for gk, records, count in resolved:
        group_records[gk] = records
        query_count += count

    # ---- pre-index each group's records once (perf: O(1)-ish per-segment lookup) ----
    group_indexes: dict[tuple[str, str], dict[tuple[str, str], list[dict]]] = {
        gk: index_group_records(records) for gk, records in group_records.items()
    }

    # ---- pass 2: worst-case side per segment -> one entry each ----
    segment_entries: list[dict] = []
    for sid, rec in items:
        on_street, from_street, to_street, line, side_keys = seg_plan[sid]
        # Both of a segment's sides share the same from/to streets — derive
        # variants ONCE per segment rather than once per side (perf).
        from_variants = _street_variants(from_street)
        to_variants = _street_variants(to_street)
        best: tuple[float, int, str, ScheduleResult] | None = None
        for side, gk in side_keys:
            soda_level, schedule = resolve_side(
                group_records[gk],
                group_indexes[gk],
                on_street,
                from_street,
                to_street,
                from_variants,
                to_variants,
                side,
                now,
            )
            cf = confidence_for_result(soda_level, schedule)
            # Worst-case = LOWER confidence (D-13); ties keep the first side.
            if best is None or cf < best[0]:
                best = (cf, soda_level, side, schedule)
        assert best is not None  # every segment has at least one side
        worst_cf, worst_level, worst_side, worst_schedule = best
        segment_entries.append(
            build_segment_entry(
                sid, rec, line, worst_side, worst_level, worst_schedule, worst_cf
            )
        )

    return {
        "generation_date": datetime.now(NYC_TZ).date().isoformat(),
        "boroughs": BOROUGH_NAMES,
        # Emitted so the client (docs/explorer/app.js tierForConfidence) can
        # read the tier partition from the dataset instead of hand-maintaining
        # a "vendored mirror" of TIER_BOUNDS that can silently drift from it.
        "tier_bounds": [[lower, name] for lower, name in TIER_BOUNDS],
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

    # With no --limit, compared against the RAW pre-filter count (not
    # len(segments)) so this self-check can actually catch a segment that
    # load_segment_records itself silently dropped, not just one
    # build_coverage dropped. With --limit, build_coverage() slices --limit
    # off the already-FILTERED segments dict (see build_coverage's `items =
    # list(segments.items())`), so the expectation must be based on the
    # filtered count — comparing against raw_count there would false-positive
    # whenever any raw record was filtered out.
    segments, raw_count = load_segment_records_with_raw_count(args.segments)
    expected_count = (
        raw_count if args.limit is None else min(args.limit, len(segments))
    )

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
    # Compact separators (no indent): this dataset has ~105K segments, and
    # every docs/explorer visitor's browser fetches the whole file — pretty
    # printing would inflate it by ~13MB of pure whitespace for no benefit
    # (no one reads coverage.json by hand).
    out_path.write_text(json.dumps(dataset, separators=(",", ":")) + "\n")

    # R1 verifiability: the low-thousands query claim must be readable from the
    # run output.
    print(
        f"build_coverage_dataset: issued {dataset['query_count']} SODA group "
        f"queries for {actual} segments -> {out_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
