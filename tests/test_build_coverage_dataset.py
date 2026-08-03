"""Offline Wave-1 unit tests for scripts/build_coverage_dataset.py.

The coverage dumper is a presentation-layer snapshot producer for the static
street-sign coverage explorer (docs/explorer/). This module exercises the two
hardest-to-get-right, purely-deterministic pieces of the dumper BEFORE any
SODA/network wiring (42-02) or client rendering (42-04) consumes them:

  1. The street+side GROUPING KEY (D-01/D-02) — decides dedup correctness. Each
     segment's two candidate parking sides are derived from its geometry bearing
     (E-W street -> {N,S}; N-S street -> {E,W}), and normalize_to_soda collapses
     casing/whitespace/abbreviation variants of the same street to ONE key.
  2. The TIER PARTITION — the single documented half-open boundary rule the whole
     UI depends on, shared by R2 (marker color), R3 (popup tier label) and R4
     (tier filter). tier_for_confidence maps a confidence in [0,1] to exactly one
     of {high, medium, low, unresolved}; confidence_for_level maps SODA level.

These tests are pure (no network, no SODAClient, no 39 MB spatial index) so CI's
``-m "not integration"`` selection runs them.
"""

from __future__ import annotations

import asyncio
import json

import scripts.build_coverage_dataset as bcd
from scripts.build_coverage_dataset import (
    build_coverage,
    confidence_for_level,
    derive_segment_sides,
    group_key,
    resolve_group,
    tier_for_confidence,
)

# Every canonical compact-schema key an entry must carry — and no others (42-01).
_CANONICAL_ENTRY_KEYS = {
    "id",
    "lat",
    "lon",
    "st",
    "fr",
    "to",
    "sd",
    "bc",
    "lv",
    "cf",
    "status",
    "sm",
    "wk",
}

# A real parseable ASP broom sign (verified against the schedule parser) so the
# resolve path can exercise a full ScheduleFound entry (summary + weekly windows).
_PARSEABLE_SIGN = "NO PARKING (SANITATION BROOM SYMBOL) MONDAY THURSDAY 11:30AM-1PM <->"

# EPSG:2263 (NY State Plane, US survey feet) test geometries. Exact coordinates
# are irrelevant to the bearing; only the run direction matters.
#   E-W segment: runs horizontally (delta-y == 0) -> bearing 0 deg   -> {N, S}
#   N-S segment: runs vertically   (delta-x == 0) -> bearing 90 deg  -> {E, W}
_EW_WKT = "LINESTRING (980000 200000, 980100 200000)"
_NS_WKT = "LINESTRING (980000 200000, 980000 200100)"


def _seg(
    street: str,
    from_street: str,
    to_street: str,
    *,
    wkt: str = _EW_WKT,
    boro: str = "1",
) -> dict:
    """Build a minimal in-memory segment record (whole-index build input shape)."""
    return {
        "full_street_name": street,
        "from_street": from_street,
        "to_street": to_street,
        "borocode": boro,
        "geometry_wkt": wkt,
    }


class _StubClient:
    """Records every SODA call so tests can assert the grouped query count.

    Mirrors the two SODAClient methods the build touches: the (sync) query
    builder and the (async) fetch. No network, no token. ``records_by_query``
    maps a built query string to canned records; ``default`` is returned for
    any unlisted query.
    """

    def __init__(
        self,
        records_by_query: dict[str, list[dict]] | None = None,
        default: list[dict] | None = None,
    ) -> None:
        self.calls: list[str] = []
        self._records = records_by_query or {}
        self._default = default if default is not None else []

    def build_on_street_query(self, on_street: str, side: str) -> str:
        return f"{on_street}|{side}"

    async def fetch_signs(self, query: str) -> list[dict]:
        self.calls.append(query)
        return self._records.get(query, self._default)


async def test_query_count_is_grouped():
    """One SODA fetch per distinct (normalized street, side) group, not per segment."""
    # 6 segments across 2 E-W streets (3 each) -> sides {N,S} per street ->
    # 2 streets x 2 sides = 4 distinct groups. A per-segment resolve would issue
    # up to 12 (6 segments x 2 sides); grouped resolve issues exactly 4.
    segments = {
        "1": _seg("BROADWAY", "1 ST", "2 ST"),
        "2": _seg("BROADWAY", "2 ST", "3 ST"),
        "3": _seg("BROADWAY", "3 ST", "4 ST"),
        "4": _seg("5 AVENUE", "10 ST", "11 ST"),
        "5": _seg("5 AVENUE", "11 ST", "12 ST"),
        "6": _seg("5 AVENUE", "12 ST", "13 ST"),
    }
    client = _StubClient()  # every group returns []
    dataset = await build_coverage(segments, client)

    assert dataset["query_count"] == 4
    assert len(client.calls) == 4
    assert dataset["query_count"] < len(segments)


async def test_every_segment_has_entry():
    """Exactly one entry per input segment_id — never an omitted segment."""
    segments = {
        "1": _seg("BROADWAY", "1 ST", "2 ST"),
        "2": _seg("BROADWAY", "2 ST", "3 ST"),
        "3": _seg("5 AVENUE", "10 ST", "11 ST", wkt=_NS_WKT),
        "42": _seg("W THAMES ST", "GREENWICH ST", "WASHINGTON ST"),
    }
    client = _StubClient()
    dataset = await build_coverage(segments, client)

    assert len(dataset["segments"]) == len(segments)
    assert {entry["id"] for entry in dataset["segments"]} == set(segments.keys())


async def test_zero_record_group_no_match():
    """A group whose broad query returns [] still yields an explicit no-match entry."""
    segments = {
        "1": _seg("BROADWAY", "1 ST", "2 ST"),
        "2": _seg("BROADWAY", "2 ST", "3 ST"),
    }
    client = _StubClient()  # all groups empty
    dataset = await build_coverage(segments, client)

    assert len(dataset["segments"]) == 2
    for entry in dataset["segments"]:
        assert entry["status"] == "no_match"
        assert entry["lv"] == 0
        assert entry["cf"] == 0.0


async def test_no_token_in_output(monkeypatch):
    """The serialized dataset never carries the SODA token or its env-var name."""
    monkeypatch.setenv("NYC_OPEN_DATA_APP_TOKEN", "secrettok_ABC123XYZ")
    segments = {"1": _seg("BROADWAY", "1 ST", "2 ST")}
    # A matching broom record so the entry resolves to a full schedule_found
    # (summary + weekly), exercising the richest serialization path.
    record = {
        "sign_description": _PARSEABLE_SIGN,
        "from_street": "1 ST",
        "to_street": "2 ST",
    }
    client = _StubClient(default=[record])
    dataset = await build_coverage(segments, client)

    serialized = json.dumps(dataset)
    assert "NYC_OPEN_DATA_APP_TOKEN" not in serialized
    assert "secrettok_ABC123XYZ" not in serialized
    for entry in dataset["segments"]:
        assert "token" not in entry
        assert "app_token" not in entry

    # The matching record produced a real schedule_found entry whose weekly
    # pattern stores day/start/end ONLY — no raw sign text field (D-04).
    entry = dataset["segments"][0]
    assert set(entry.keys()) == _CANONICAL_ENTRY_KEYS
    assert entry["status"] == "schedule_found"
    assert entry["lv"] == 1
    assert entry["wk"], "expected a weekly pattern"
    for window in entry["wk"]:
        assert set(window.keys()) == {"d", "s", "e"}


async def test_level_3_no_cross_street_match_is_unresolved():
    """Group has records, but none match this block's cross streets -> level 3,
    cf 0.0, tier 'unresolved' — NOT the misleading 'low' tier a nonzero
    confidence would produce for a block whose schedule is genuinely no_match."""
    segments = {"1": _seg("BROADWAY", "1 ST", "2 ST")}
    # A real broom record on BROADWAY, but for an unrelated block.
    record = {
        "sign_description": _PARSEABLE_SIGN,
        "from_street": "9 ST",
        "to_street": "10 ST",
    }
    client = _StubClient(default=[record])
    dataset = await build_coverage(segments, client)

    entry = dataset["segments"][0]
    assert entry["lv"] == 3
    assert entry["cf"] == 0.0
    assert entry["status"] == "no_match"
    assert tier_for_confidence(entry["cf"]) == "unresolved"


async def test_resolve_group_tries_both_name_variants():
    """resolve_group falls back to the raw CSCL form when the canonical SODA
    form returns nothing — mirrors production's retrieve_signs Level 3 loop,
    which tries every name_variants() form instead of only the normalized one."""
    record = {
        "sign_description": _PARSEABLE_SIGN,
        "from_street": "1 ST",
        "to_street": "2 ST",
    }
    # Only the RAW CSCL-form query ("3 AVE") has records; the canonical
    # SODA-expanded form ("3 AVENUE") returns nothing, simulating a street
    # whose live SODA on_street field is stored in the unexpanded form.
    client = _StubClient(records_by_query={"3 AVE|N": [record]})
    records, query_count = await resolve_group(client, "3 AVE", "N")

    assert records == [record]
    assert query_count == 2  # one query per name_variants() form
    assert "3 AVE|N" in client.calls
    assert "3 AVENUE|N" in client.calls  # canonical form tried too, even if empty


async def test_swapped_cross_streets_still_match_via_index():
    """cross_streets_match's swapped-order semantics still hold through the
    pre-built group index: a record's from/to can be in the opposite order
    from the block's own from/to and still count as a match (level 1)."""
    segments = {"1": _seg("BROADWAY", "1 ST", "2 ST")}
    record = {
        "sign_description": _PARSEABLE_SIGN,
        "from_street": "2 ST",  # swapped relative to the segment's from/to
        "to_street": "1 ST",
    }
    client = _StubClient(default=[record])
    dataset = await build_coverage(segments, client)

    entry = dataset["segments"][0]
    assert entry["status"] == "schedule_found"
    assert entry["lv"] == 1


def test_main_writes_canonical_coverage_json(tmp_path, monkeypatch):
    """main() writes coverage.json with the canonical top-level + entry schema."""
    seg_path = tmp_path / "segments.json"
    seg_path.write_text(
        json.dumps(
            {
                "1": _seg("BROADWAY", "1 ST", "2 ST"),
                "2": _seg("BROADWAY", "2 ST", "3 ST"),
            }
        )
    )
    out_dir = tmp_path / "out"
    # Patch the client so main() issues NO network calls (offline test).
    monkeypatch.setattr(bcd, "SODAClient", lambda *a, **k: _StubClient())

    try:
        rc = bcd.main(["--segments", str(seg_path), "--out-dir", str(out_dir)])
    finally:
        # main() runs asyncio.run(), which closes the loop and clears the
        # current-loop slot; restore one so pytest-asyncio (auto mode) can still
        # manage later sync tests on Python 3.13 (get_event_loop no longer
        # auto-creates a loop).
        asyncio.set_event_loop(asyncio.new_event_loop())
    assert rc == 0

    data = json.loads((out_dir / "coverage.json").read_text())
    assert set(data) == {
        "generation_date",
        "boroughs",
        "tier_bounds",
        "query_count",
        "segment_count",
        "segments",
    }
    assert data["tier_bounds"] == [[lower, name] for lower, name in bcd.TIER_BOUNDS]
    assert data["segment_count"] == 2
    assert len(data["segments"]) == 2
    # query_count is the distinct-group count, strictly below the segment count.
    assert data["query_count"] < data["segment_count"] * 2
    for entry in data["segments"]:
        assert set(entry.keys()) == _CANONICAL_ENTRY_KEYS


def test_grouping_key_and_side_derivation():
    """Sides come from geometry bearing; group_key canonicalizes the street."""
    # --- side derivation from bearing (D-02): NEVER from has_asp_left/right ---
    assert derive_segment_sides(_EW_WKT) == ("N", "S")
    assert derive_segment_sides(_NS_WKT) == ("E", "W")

    # --- normalize_to_soda collapses casing/whitespace/abbreviation variants ---
    # BROADWAY / Broadway / broadway all canonicalize to one grouping key.
    key_upper = group_key("BROADWAY", "N")
    key_title = group_key("Broadway", "N")
    key_lower = group_key("broadway", "N")
    assert key_upper == key_title == key_lower

    # Collapsed internal whitespace ("W  THAMES ST") maps to the same key as its
    # single-spaced form ("W THAMES ST").
    assert group_key("W  THAMES ST", "N") == group_key("W THAMES ST", "N")

    # --- property: no double-count, no drop across the group boundary ---
    # Two distinct segments on the same normalized street+side must produce an
    # IDENTICAL group_key (so they collapse into one group), and the two sides of
    # one street must produce DIFFERENT keys (so neither side is dropped).
    seg_a_side = group_key("BROADWAY", "N")
    seg_b_side = group_key("broadway", "N")
    assert seg_a_side == seg_b_side  # same street+side -> one group (no double-count)

    north_key = group_key("BROADWAY", "N")
    south_key = group_key("BROADWAY", "S")
    assert north_key != south_key  # both sides recoverable (no drop)

    # The key exposes the canonical street and side for downstream recovery.
    assert north_key[1] == "N"
    assert south_key[1] == "S"
    assert north_key[0] == south_key[0]  # same canonical street on both sides


def test_tier_boundary_partition():
    """One documented half-open rule partitions [0,1] into four named tiers."""
    tiers = {"high", "medium", "low", "unresolved"}

    # Fine grid over [0,1] plus the exact boundary values: every value maps to
    # exactly one of the four named tiers.
    grid = [i / 100 for i in range(0, 101)] + [0.33, 0.50, 0.75]
    for v in grid:
        tier = tier_for_confidence(v)
        assert tier in tiers, f"{v!r} produced non-tier {tier!r}"

    # The four named boundary landings (the single half-open rule):
    #   [0.00, 0.33) unresolved | [0.33, 0.50) low | [0.50, 0.75) medium |
    #   [0.75, 1.00] high  (top tier inclusive of 1.0)
    assert tier_for_confidence(0.0) == "unresolved"
    assert tier_for_confidence(0.33) == "low"  # boundary lands in low, NOT unresolved
    assert tier_for_confidence(0.50) == "medium"
    assert tier_for_confidence(0.75) == "high"
    assert tier_for_confidence(1.0) == "high"

    # --- confidence_for_level maps SODA level deterministically (D-18) ---
    assert confidence_for_level(1) == 0.90
    assert confidence_for_level(2) == 0.66
    # Level 3 (street present in SODA, but no record matches this block's
    # cross streets) always resolves to an empty filter -> NoMatchFound, the
    # same as level 0 -- so it carries the SAME 0.00 confidence, landing in
    # "unresolved" rather than the misleading "low" tier a nonzero value would
    # produce for a block with no schedule at all.
    assert confidence_for_level(3) == 0.00
    assert confidence_for_level(0) == 0.00

    # ...and each level's confidence lands in the expected tier.
    assert tier_for_confidence(confidence_for_level(1)) == "high"
    assert tier_for_confidence(confidence_for_level(2)) == "medium"
    assert tier_for_confidence(confidence_for_level(3)) == "unresolved"
    assert tier_for_confidence(confidence_for_level(0)) == "unresolved"


def test_summary_and_weekly_asp_active_now_keeps_all_days():
    """_summary_and_weekly() on a multi-day ASPActiveNow must emit EVERY cleaning
    day, not just the single in-progress window (BUG-ASPActiveNow-full-weekly).
    """
    from datetime import datetime, time

    from scripts.build_coverage_dataset import _summary_and_weekly
    from gps2asp.schedule.models import (
        ASPActiveNow,
        ASPDay,
        CleaningWindow,
        TimeWindow,
        WeeklySchedule,
    )

    schedule = ASPActiveNow(
        status="asp_active_now",
        active_window=CleaningWindow(
            day=ASPDay.THURSDAY,
            start_time=time(11, 0),
            end_time=time(14, 0),
            start_datetime=datetime(2026, 7, 30, 11, 0),
            end_datetime=datetime(2026, 7, 30, 14, 0),
            source_signs=["NO PARKING THU 11AM-2PM STREET CLEANING"],
        ),
        weekly_schedule=WeeklySchedule(
            windows=(
                TimeWindow(
                    day=ASPDay.MONDAY,
                    start_time=time(11, 0),
                    end_time=time(14, 0),
                    source_sign="NO PARKING MON 11AM-2PM STREET CLEANING",
                ),
                TimeWindow(
                    day=ASPDay.THURSDAY,
                    start_time=time(11, 0),
                    end_time=time(14, 0),
                    source_sign="NO PARKING THU 11AM-2PM STREET CLEANING",
                ),
            )
        ),
        on_street="ORIENTAL BLVD",
        from_street="",
        to_street="DECATUR AVE",
        side_of_street="N",
        source_signs=["NO PARKING THU 11AM-2PM STREET CLEANING"],
        summary="MON & THU 11 AM - 2 PM",
    )

    summary, wk = _summary_and_weekly(schedule)
    assert summary == "MON & THU 11 AM - 2 PM"
    assert len(wk) == 2
    assert {entry["d"] for entry in wk} == {ASPDay.MONDAY.value, ASPDay.THURSDAY.value}
    # Compact coverage schema: {d, s, e} only, never a sign text (D-04).
    for entry in wk:
        assert set(entry.keys()) == {"d", "s", "e"}
