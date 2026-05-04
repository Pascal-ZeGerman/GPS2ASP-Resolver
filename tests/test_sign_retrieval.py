"""Tests for sign retrieval: unit tests for StreetGraph / Level 4, plus
integration tests against the live SODA API.

Integration tests require network access to data.cityofnewyork.us and are
skipped when the endpoint is unreachable. Marked with @pytest.mark.integration.

All tests are async (pytest-asyncio with asyncio_mode = auto).
"""

from __future__ import annotations

import json
import logging
import socket
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gps2asp.signs import (
    NoASPSigns,
    NoMatchFound,
    SignRetrievalSuccess,
    retrieve_signs,
)


def _soda_reachable() -> bool:
    """Check if the SODA API endpoint is reachable."""
    try:
        socket.create_connection(("data.cityofnewyork.us", 443), timeout=5)
        return True
    except OSError:
        return False


skip_no_network = pytest.mark.skipif(
    not _soda_reachable(),
    reason="SODA API unreachable (data.cityofnewyork.us:443)",
)

integration = pytest.mark.integration


# ── Known ASP block ──────────────────────────────────────────────────


@skip_no_network
@integration
async def test_retrieve_signs_known_asp_block() -> None:
    """Prospect Place between Carlton Ave and Vanderbilt Ave (North side).

    Known to have ASP broom signs. Validates SIGN-01 (query works).
    """
    result = await retrieve_signs(
        on_street="PROSPECT PLACE",
        from_street="CARLTON AVENUE",
        to_street="VANDERBILT AVENUE",
        side_of_street="N",
    )

    assert isinstance(result, SignRetrievalSuccess), (
        f"Expected SignRetrievalSuccess, got {type(result).__name__}"
    )
    assert result.status == "signs_found"
    assert len(result.signs) >= 1

    # Verify at least one sign mentions broom
    descriptions = [s.sign_description for s in result.signs]
    assert any(
        "BROOM" in desc.upper() for desc in descriptions
    ), f"No broom sign found in: {descriptions}"


# ── Name normalization fallback ──────────────────────────────────────


@skip_no_network
@integration
async def test_retrieve_signs_name_normalization() -> None:
    """Call with CSCL abbreviated names -- fallback should still find signs.

    Uses abbreviated forms (PL, AVE) instead of full SODA names.
    """
    result = await retrieve_signs(
        on_street="PROSPECT PL",
        from_street="CARLTON AVE",
        to_street="VANDERBILT AVE",
        side_of_street="N",
    )

    assert isinstance(result, SignRetrievalSuccess), (
        f"Expected SignRetrievalSuccess with abbreviated names, "
        f"got {type(result).__name__}"
    )
    assert len(result.signs) >= 1


# ── Deduplication ────────────────────────────────────────────────────


@skip_no_network
@integration
async def test_retrieve_signs_deduplication() -> None:
    """Block with multiple identical sign posts should be deduplicated.

    Research shows blocks can have up to 46 identical sign records.
    The deduplicated count should be small (typically 1-2 per block).
    """
    result = await retrieve_signs(
        on_street="PROSPECT PLACE",
        from_street="CARLTON AVENUE",
        to_street="VANDERBILT AVENUE",
        side_of_street="N",
    )

    assert isinstance(result, SignRetrievalSuccess)
    # Deduplicated: should have far fewer records than raw SODA output
    # Typically 1-2 unique sign descriptions per block-face
    assert len(result.signs) <= 5, (
        f"Expected <= 5 unique signs after dedup, got {len(result.signs)}"
    )


# ── No ASP street ───────────────────────────────────────────────────


@skip_no_network
@integration
async def test_retrieve_signs_no_asp_street() -> None:
    """A street name unlikely to have ASP signs should return NoASPSigns or NoMatchFound.

    Use a fabricated street name that should not exist in SODA.
    """
    result = await retrieve_signs(
        on_street="NONEXISTENT FAKE STREET ZZZZZ",
        from_street="ALSO FAKE AVENUE ZZZZZ",
        to_street="ANOTHER FAKE BLVD ZZZZZ",
        side_of_street="N",
    )

    assert not isinstance(result, SignRetrievalSuccess), (
        f"Expected NoASPSigns or NoMatchFound for fake street, "
        f"got SignRetrievalSuccess with {len(result.signs)} signs"
    )
    assert isinstance(result, (NoASPSigns, NoMatchFound))


# ── No voided signs ─────────────────────────────────────────────────


@skip_no_network
@integration
async def test_retrieve_signs_no_voided_signs() -> None:
    """Returned signs should not contain voided/superseded designs (SIGN-02).

    Check that no sign descriptions contain "SUPERSEDED BY" text.
    """
    result = await retrieve_signs(
        on_street="PROSPECT PLACE",
        from_street="CARLTON AVENUE",
        to_street="VANDERBILT AVENUE",
        side_of_street="N",
    )

    assert isinstance(result, SignRetrievalSuccess)
    for sign in result.signs:
        assert "SUPERSEDED" not in sign.sign_description.upper(), (
            f"Voided sign found: {sign.sign_description}"
        )


# ── Result uses input names ─────────────────────────────────────────


@skip_no_network
@integration
async def test_retrieve_signs_result_uses_input_names() -> None:
    """Result should use CSCL input names, not SODA-converted names.

    When calling with abbreviated CSCL names, the returned result
    should preserve those original input names.
    """
    result = await retrieve_signs(
        on_street="PROSPECT PL",
        from_street="CARLTON AVE",
        to_street="VANDERBILT AVE",
        side_of_street="N",
    )

    assert isinstance(result, SignRetrievalSuccess)
    # Result should reflect the input names, NOT the expanded SODA names
    assert result.on_street == "PROSPECT PL"
    assert result.from_street == "CARLTON AVE"
    assert result.to_street == "VANDERBILT AVE"
    assert result.side_of_street == "N"


# ── StreetGraph unit tests ───────────────────────────────────────────


# Synthetic graph for testing:
#
#   Segment layout (segment_id -> cross streets):
#     seg_10: [72 STREET, 73 STREET]   <- our block
#     seg_11: [73 STREET, 74 STREET]
#     seg_12: [74 STREET, 75 STREET]
#     seg_13: [71 STREET, 72 STREET]
#     seg_20: [ALPHA STREET, BETA STREET]  <- different sub-graph
#
#   Adjacency (by segment id as string):
#     "10": [11, 13]
#     "11": [10, 12]
#     "12": [11]
#     "13": [10]
#     "20": []
#
#   All segments are on "BROADWAY" street.

_SYNTHETIC_GRAPH = {
    "adjacency": {
        "10": [11, 13],
        "11": [10, 12],
        "12": [11],
        "13": [10],
        "20": [],
    },
    "segment_streets": {
        "10": "BROADWAY",
        "11": "BROADWAY",
        "12": "BROADWAY",
        "13": "BROADWAY",
        "20": "BROADWAY",
    },
    "segment_cross_streets": {
        "10": ["72 STREET", "73 STREET"],
        "11": ["73 STREET", "74 STREET"],
        "12": ["74 STREET", "75 STREET"],
        "13": ["71 STREET", "72 STREET"],
        "20": ["ALPHA STREET", "BETA STREET"],
    },
}


def _make_graph():
    """Return a StreetGraph loaded from _SYNTHETIC_GRAPH (no file I/O)."""
    from gps2asp.signs.graph import StreetGraph
    return StreetGraph(
        adjacency=_SYNTHETIC_GRAPH["adjacency"],
        segment_streets=_SYNTHETIC_GRAPH["segment_streets"],
        segment_cross_streets=_SYNTHETIC_GRAPH["segment_cross_streets"],
    )


# ── StreetGraph.load() ───────────────────────────────────────────────


def test_graph_load_reads_graph_json(tmp_path: Path) -> None:
    """StreetGraph.load() reads graph.json and populates all three dicts."""
    graph_file = tmp_path / "graph.json"
    graph_file.write_text(json.dumps(_SYNTHETIC_GRAPH))

    from gps2asp.signs.graph import StreetGraph
    graph = StreetGraph.load(index_dir=tmp_path)

    assert graph is not None
    assert "10" in graph.adjacency
    assert "10" in graph.segment_streets
    assert "10" in graph.segment_cross_streets


def test_graph_load_returns_none_when_missing(tmp_path: Path) -> None:
    """StreetGraph.load() returns None when graph.json does not exist."""
    from gps2asp.signs.graph import StreetGraph
    graph = StreetGraph.load(index_dir=tmp_path)
    assert graph is None


def test_graph_load_normalizes_street_names(tmp_path: Path) -> None:
    """StreetGraph.load() normalizes street names via normalize_to_soda."""
    data = {
        "adjacency": {"1": []},
        "segment_streets": {"1": "3 AVE"},
        "segment_cross_streets": {"1": ["72 ST", "73 ST"]},
    }
    (tmp_path / "graph.json").write_text(json.dumps(data))

    from gps2asp.signs.graph import StreetGraph
    graph = StreetGraph.load(index_dir=tmp_path)

    assert graph is not None
    # normalize_to_soda("3 AVE") == "3 AVENUE"
    assert graph.segment_streets["1"] == "3 AVENUE"
    # normalize_to_soda("72 ST") == "72 STREET"
    assert "72 STREET" in graph.segment_cross_streets["1"]
    assert "73 STREET" in graph.segment_cross_streets["1"]


# ── StreetGraph.get() lazy singleton ────────────────────────────────


def test_graph_get_is_singleton(tmp_path: Path) -> None:
    """StreetGraph.get() returns the same instance on repeated calls."""
    graph_file = tmp_path / "graph.json"
    graph_file.write_text(json.dumps(_SYNTHETIC_GRAPH))

    from gps2asp.signs import graph as graph_module
    from gps2asp.signs.graph import StreetGraph

    # Reset singleton state for test isolation
    StreetGraph._instance = None

    with patch.object(StreetGraph, "_index_dir", return_value=tmp_path, create=True):
        with patch("gps2asp.signs.graph._default_index_dir", return_value=tmp_path):
            g1 = StreetGraph.get()
            g2 = StreetGraph.get()

    assert g1 is g2, "StreetGraph.get() must return the same instance on repeated calls"

    # Reset after test
    StreetGraph._instance = None


# ── span_distance ────────────────────────────────────────────────────


def test_span_distance_exact_match() -> None:
    """span_distance returns 0 when span cross streets exactly match block."""
    graph = _make_graph()
    dist = graph.span_distance("72 STREET", "73 STREET", "72 STREET", "73 STREET")
    assert dist == 0


def test_span_distance_adjacent_span_sharing_endpoint() -> None:
    """span_distance for adjacent span sharing an endpoint cross street is finite.

    Span [73 STREET, 74 STREET] shares 73 STREET with our block
    [72 STREET, 73 STREET]. The BFS finds overlap at the shared endpoint,
    so the combined distance is low (0 or small int), not inf.
    """
    graph = _make_graph()
    # Our block: [72 STREET, 73 STREET] (seg 10)
    # Span:      [73 STREET, 74 STREET] (seg 11, adjacent to seg 10)
    dist = graph.span_distance("72 STREET", "73 STREET", "73 STREET", "74 STREET")
    assert dist < float("inf")


def test_span_distance_non_adjacent_span_farther_than_adjacent() -> None:
    """span_distance is larger for a non-adjacent span than an adjacent one."""
    graph = _make_graph()
    # Adjacent span (shares 73 STREET endpoint with our block)
    dist_adj = graph.span_distance("72 STREET", "73 STREET", "73 STREET", "74 STREET")
    # Further span: [74 STREET, 75 STREET] -- seg 12, 2 segments away from our block
    dist_far = graph.span_distance("72 STREET", "73 STREET", "74 STREET", "75 STREET")
    assert dist_far >= dist_adj


def test_span_distance_unreachable_returns_inf() -> None:
    """span_distance returns float('inf') for unreachable span endpoints."""
    graph = _make_graph()
    # ALPHA STREET and BETA STREET are in a disconnected sub-graph
    dist = graph.span_distance("72 STREET", "73 STREET", "ALPHA STREET", "BETA STREET")
    assert dist == float("inf")


def test_span_distance_symmetric() -> None:
    """span_distance handles both (from,to) and (to,from) orderings."""
    graph = _make_graph()
    # Reversed: span (74,73) should equal span (73,74) since we try both orderings
    dist_fwd = graph.span_distance("72 STREET", "73 STREET", "73 STREET", "74 STREET")
    dist_rev = graph.span_distance("72 STREET", "73 STREET", "74 STREET", "73 STREET")
    assert dist_fwd == dist_rev


# ── _find_best_covering_span ─────────────────────────────────────────


def test_find_best_covering_span_picks_lowest_distance() -> None:
    """_find_best_covering_span picks the span with lowest graph distance."""
    from gps2asp.signs.graph import _find_best_covering_span

    graph = _make_graph()

    # Two candidate spans: one exact match (seg 10), one 1 block away (seg 11)
    records = [
        # Exact match span
        {
            "from_street": "72 STREET",
            "to_street": "73 STREET",
            "sign_description": "SANITATION BROOM EXACT",
        },
        # One-hop span
        {
            "from_street": "73 STREET",
            "to_street": "74 STREET",
            "sign_description": "SANITATION BROOM NEARBY",
        },
    ]

    best = _find_best_covering_span(records, "72 STREET", "73 STREET", graph)
    assert best is not None
    # The exact match span should win
    assert best[0]["sign_description"] == "SANITATION BROOM EXACT"


def test_find_best_covering_span_empty_records() -> None:
    """_find_best_covering_span returns None when given an empty records list."""
    from gps2asp.signs.graph import _find_best_covering_span

    graph = _make_graph()
    result = _find_best_covering_span([], "72 STREET", "73 STREET", graph)
    assert result is None


def test_find_best_covering_span_returns_none_when_all_inf() -> None:
    """_find_best_covering_span returns None when all spans are unreachable."""
    from gps2asp.signs.graph import _find_best_covering_span

    graph = _make_graph()

    records = [
        {
            "from_street": "ALPHA STREET",
            "to_street": "BETA STREET",
            "sign_description": "SANITATION BROOM UNREACHABLE",
        },
    ]

    # Our block is at seg 10 (72/73 STREET) — disconnected from ALPHA/BETA sub-graph
    best = _find_best_covering_span(records, "72 STREET", "73 STREET", graph)
    assert best is None


def test_find_best_covering_span_groups_records_by_span() -> None:
    """_find_best_covering_span groups multiple records for the same span."""
    from gps2asp.signs.graph import _find_best_covering_span

    graph = _make_graph()

    # Same span, multiple sign records (simulating multi-sign posts on same block)
    records = [
        {"from_street": "72 STREET", "to_street": "73 STREET", "sign_description": "SIGN A"},
        {"from_street": "72 STREET", "to_street": "73 STREET", "sign_description": "SIGN B"},
        {"from_street": "73 STREET", "to_street": "74 STREET", "sign_description": "SIGN C"},
    ]

    best = _find_best_covering_span(records, "72 STREET", "73 STREET", graph)
    assert best is not None
    # Exact match wins; it has 2 records
    assert len(best) == 2
    descs = {r["sign_description"] for r in best}
    assert descs == {"SIGN A", "SIGN B"}


# ── _bfs_min_hops edge cases ─────────────────────────────────────────


def test_bfs_min_hops_empty_start_pids() -> None:
    """_bfs_min_hops returns inf when start_pids is empty."""
    graph = _make_graph()
    assert graph._bfs_min_hops(set(), {"10"}) == float("inf")


def test_bfs_min_hops_empty_target_pids() -> None:
    """_bfs_min_hops returns inf when target_pids is empty."""
    graph = _make_graph()
    assert graph._bfs_min_hops({"10"}, set()) == float("inf")


# ── Level 4 integration with retrieve_signs() ────────────────────────


_BROOM_SIGN_RECORD = {
    "from_street": "72 STREET",
    "to_street": "73 STREET",
    "sign_description": "SANITATION BROOM UP",
    "side_of_street": "N",
}


async def test_level_4_activates_when_levels_1_2_3_return_nothing() -> None:
    """Level 4 fires when Levels 1-3 produce no SODA results at all.

    Setup: SODAClient returns no records for exact/variant queries but
    returns records on the broad on_street query. StreetGraph.get() returns
    a graph that picks the best span, and _try_query returns SignRetrievalSuccess.
    """
    graph = _make_graph()

    # Build SODA broad-query records (on BROADWAY, side N)
    broad_records = [dict(_BROOM_SIGN_RECORD)]

    mock_client = MagicMock()
    mock_client.build_block_query.return_value = "mock_block_query"
    mock_client.build_on_street_query.return_value = "mock_broad_query"
    # fetch_signs: empty for block queries (Levels 1+2), records for broad query (Level 3+4)
    mock_client.fetch_signs = AsyncMock(side_effect=[
        [],          # Level 1 block query
        [],          # Level 3 broad query (Level 2 has no extra combos for single-variant names)
        broad_records,  # Level 4 broad query
    ])

    with (
        patch("gps2asp.signs.SODAClient", return_value=mock_client),
        patch("gps2asp.signs.graph.StreetGraph.get", return_value=graph),
    ):
        result = await retrieve_signs(
            on_street="BROADWAY",
            from_street="72 STREET",
            to_street="73 STREET",
            side_of_street="N",
        )

    assert isinstance(result, SignRetrievalSuccess), (
        f"Expected SignRetrievalSuccess from Level 4, got {type(result).__name__}"
    )
    assert result.soda_level == 4


async def test_level_4_does_not_activate_when_level_1_succeeds() -> None:
    """Level 4 is skipped when Level 1 already returns results."""
    graph = _make_graph()

    mock_client = MagicMock()
    mock_client.build_block_query.return_value = "mock_block_query"
    mock_client.build_on_street_query.return_value = "mock_broad_query"
    # Level 1 returns records directly
    mock_client.fetch_signs = AsyncMock(return_value=[_BROOM_SIGN_RECORD])

    with (
        patch("gps2asp.signs.SODAClient", return_value=mock_client),
        patch("gps2asp.signs.graph.StreetGraph.get", return_value=graph),
    ):
        result = await retrieve_signs(
            on_street="BROADWAY",
            from_street="72 STREET",
            to_street="73 STREET",
            side_of_street="N",
        )

    assert isinstance(result, SignRetrievalSuccess)
    assert result.soda_level == 1
    # StreetGraph.get should not have been called for Level 4 lookup
    # (Level 1 succeeded, so Level 4 was never reached)


async def test_level_4_gracefully_degrades_when_graph_missing() -> None:
    """Level 4 falls through to NoMatchFound when graph.json is absent."""
    mock_client = MagicMock()
    mock_client.build_block_query.return_value = "mock_block_query"
    mock_client.build_on_street_query.return_value = "mock_broad_query"
    # All queries return empty (simulates SODA having no records for this block)
    mock_client.fetch_signs = AsyncMock(return_value=[])

    with (
        patch("gps2asp.signs.SODAClient", return_value=mock_client),
        patch("gps2asp.signs.graph.StreetGraph.get", return_value=None),  # no graph
    ):
        result = await retrieve_signs(
            on_street="BROADWAY",
            from_street="72 STREET",
            to_street="73 STREET",
            side_of_street="N",
        )

    # No SODA results at all, no graph -> NoMatchFound
    assert isinstance(result, NoMatchFound)


async def test_level_4_returns_all_records_including_non_broom() -> None:
    """Level 4 returns SignRetrievalSuccess even for non-broom records.

    retrieve_signs() does not filter for SANITATION BROOM signs -- that
    filtering happens downstream in the schedule parser. When Level 4 finds a
    reachable best span, it returns all records from that span as-is.
    """
    graph = _make_graph()

    # Records at an exact-match span with a non-broom sign description
    non_broom_records = [
        {
            "from_street": "72 STREET",
            "to_street": "73 STREET",
            "sign_description": "NO PARKING",
            "side_of_street": "N",
        }
    ]

    mock_client = MagicMock()
    mock_client.build_block_query.return_value = "mock_block_query"
    mock_client.build_on_street_query.return_value = "mock_broad_query"
    mock_client.fetch_signs = AsyncMock(side_effect=[
        [],                 # Level 1 block query
        [],                 # Level 3 broad query
        non_broom_records,  # Level 4 broad query
    ])

    with (
        patch("gps2asp.signs.SODAClient", return_value=mock_client),
        patch("gps2asp.signs.graph.StreetGraph.get", return_value=graph),
    ):
        result = await retrieve_signs(
            on_street="BROADWAY",
            from_street="72 STREET",
            to_street="73 STREET",
            side_of_street="N",
        )

    # Level 4 found a reachable span: returns SignRetrievalSuccess with all records.
    # Broom-sign filtering is the caller's responsibility (schedule parser), not ours.
    assert isinstance(result, SignRetrievalSuccess)
    assert result.soda_level == 4
    assert len(result.signs) >= 1


async def test_level_4_returns_no_match_when_best_span_is_none() -> None:
    """Level 4 returns NoMatchFound when _find_best_covering_span returns None.

    This happens when the broad on_street query returns records but none
    of them are reachable from our block in the graph.
    """
    graph = _make_graph()

    # Records from a disconnected sub-graph (ALPHA/BETA streets)
    unreachable_records = [
        {
            "from_street": "ALPHA STREET",
            "to_street": "BETA STREET",
            "sign_description": "SANITATION BROOM UNREACHABLE",
        }
    ]

    mock_client = MagicMock()
    mock_client.build_block_query.return_value = "mock_block_query"
    mock_client.build_on_street_query.return_value = "mock_broad_query"
    mock_client.fetch_signs = AsyncMock(side_effect=[
        [],                # Level 1
        [],                # Level 3 broad
        unreachable_records,  # Level 4 broad
    ])

    with (
        patch("gps2asp.signs.SODAClient", return_value=mock_client),
        patch("gps2asp.signs.graph.StreetGraph.get", return_value=graph),
    ):
        result = await retrieve_signs(
            on_street="BROADWAY",
            from_street="72 STREET",
            to_street="73 STREET",
            side_of_street="N",
        )

    # best span is None (all distances inf) -> no Level 4 result
    # SODA had results (any_soda_results=True) -> NoASPSigns
    assert isinstance(result, (NoASPSigns, NoMatchFound))


# ── Structured Level 4 logging (l4_event) ───────────────────────────


async def test_l4_entry_logged_once_before_loop() -> None:
    """l4_event=l4_entry is emitted exactly once, before the on_variants loop.

    A single retrieve_signs() call that reaches Level 4 should produce
    exactly one l4_entry record, and it must appear before any l4_no_span
    or l4_no_records records.
    """
    graph = _make_graph()
    broad_records = [dict(_BROOM_SIGN_RECORD)]

    mock_client = MagicMock()
    mock_client.build_block_query.return_value = "mock_block_query"
    mock_client.build_on_street_query.return_value = "mock_broad_query"
    mock_client.fetch_signs = AsyncMock(side_effect=[
        [],            # Level 1 block query
        [],            # Level 3 broad query
        broad_records, # Level 4 broad query
    ])

    log_handler = _CapturingHandler()
    signs_logger = logging.getLogger("gps2asp.signs")
    signs_logger.addHandler(log_handler)
    original_level = signs_logger.level
    signs_logger.setLevel(logging.INFO)
    try:
        with (
            patch("gps2asp.signs.SODAClient", return_value=mock_client),
            patch("gps2asp.signs.graph.StreetGraph.get", return_value=graph),
        ):
            await retrieve_signs(
                on_street="BROADWAY",
                from_street="72 STREET",
                to_street="73 STREET",
                side_of_street="N",
            )
    finally:
        signs_logger.removeHandler(log_handler)
        signs_logger.setLevel(original_level)

    entry_records = [r for r in log_handler.records if "l4_event=l4_entry" in r.getMessage()]
    assert len(entry_records) == 1, (
        f"Expected exactly 1 l4_event=l4_entry record, got {len(entry_records)}: "
        f"{[r.getMessage() for r in log_handler.records]}"
    )


async def test_l4_match_log_includes_span_fields() -> None:
    """When Level 4 finds a covering span, the l4_match log contains span_from, span_to, and signs."""
    graph = _make_graph()
    broad_records = [dict(_BROOM_SIGN_RECORD)]

    mock_client = MagicMock()
    mock_client.build_block_query.return_value = "mock_block_query"
    mock_client.build_on_street_query.return_value = "mock_broad_query"
    mock_client.fetch_signs = AsyncMock(side_effect=[
        [],
        [],
        broad_records,
    ])

    log_handler = _CapturingHandler()
    signs_logger = logging.getLogger("gps2asp.signs")
    signs_logger.addHandler(log_handler)
    original_level = signs_logger.level
    signs_logger.setLevel(logging.INFO)
    try:
        with (
            patch("gps2asp.signs.SODAClient", return_value=mock_client),
            patch("gps2asp.signs.graph.StreetGraph.get", return_value=graph),
        ):
            await retrieve_signs(
                on_street="BROADWAY",
                from_street="72 STREET",
                to_street="73 STREET",
                side_of_street="N",
            )
    finally:
        signs_logger.removeHandler(log_handler)
        signs_logger.setLevel(original_level)

    match_records = [r for r in log_handler.records if "l4_event=l4_match" in r.getMessage()]
    assert len(match_records) == 1, (
        f"Expected 1 l4_event=l4_match record, got {len(match_records)}: "
        f"{[r.getMessage() for r in log_handler.records]}"
    )
    msg = match_records[0].getMessage()
    assert "span_from=" in msg, f"Missing span_from= in: {msg}"
    assert "span_to=" in msg, f"Missing span_to= in: {msg}"
    assert "signs=" in msg, f"Missing signs= in: {msg}"


async def test_l4_no_span_log_includes_span_candidates() -> None:
    """When broad query returns records but no reachable span, l4_no_span is logged with span_candidates."""
    graph = _make_graph()
    # Use records from a disconnected sub-graph so _find_best_covering_span returns None
    unreachable_records = [
        {
            "from_street": "ALPHA STREET",
            "to_street": "BETA STREET",
            "sign_description": "SANITATION BROOM UP",
            "side_of_street": "N",
        }
    ]

    mock_client = MagicMock()
    mock_client.build_block_query.return_value = "mock_block_query"
    mock_client.build_on_street_query.return_value = "mock_broad_query"
    mock_client.fetch_signs = AsyncMock(side_effect=[
        [],
        [],
        unreachable_records,
    ])

    log_handler = _CapturingHandler()
    signs_logger = logging.getLogger("gps2asp.signs")
    signs_logger.addHandler(log_handler)
    original_level = signs_logger.level
    signs_logger.setLevel(logging.INFO)
    try:
        with (
            patch("gps2asp.signs.SODAClient", return_value=mock_client),
            patch("gps2asp.signs.graph.StreetGraph.get", return_value=graph),
        ):
            await retrieve_signs(
                on_street="BROADWAY",
                from_street="72 STREET",
                to_street="73 STREET",
                side_of_street="N",
            )
    finally:
        signs_logger.removeHandler(log_handler)
        signs_logger.setLevel(original_level)

    no_span_records = [r for r in log_handler.records if "l4_event=l4_no_span" in r.getMessage()]
    assert len(no_span_records) >= 1, (
        f"Expected l4_event=l4_no_span record, got none: "
        f"{[r.getMessage() for r in log_handler.records]}"
    )
    msg = no_span_records[0].getMessage()
    assert "span_candidates=" in msg, f"Missing span_candidates= in: {msg}"


async def test_l4_no_records_logged_when_broad_query_empty() -> None:
    """When Level 4 broad query returns zero records, l4_no_records is logged (no span_candidates)."""
    graph = _make_graph()

    mock_client = MagicMock()
    mock_client.build_block_query.return_value = "mock_block_query"
    mock_client.build_on_street_query.return_value = "mock_broad_query"
    mock_client.fetch_signs = AsyncMock(side_effect=[
        [],  # Level 1 block query
        [],  # Level 3 broad query
        [],  # Level 4 broad query — empty
    ])

    log_handler = _CapturingHandler()
    signs_logger = logging.getLogger("gps2asp.signs")
    signs_logger.addHandler(log_handler)
    original_level = signs_logger.level
    signs_logger.setLevel(logging.INFO)
    try:
        with (
            patch("gps2asp.signs.SODAClient", return_value=mock_client),
            patch("gps2asp.signs.graph.StreetGraph.get", return_value=graph),
        ):
            await retrieve_signs(
                on_street="BROADWAY",
                from_street="72 STREET",
                to_street="73 STREET",
                side_of_street="N",
            )
    finally:
        signs_logger.removeHandler(log_handler)
        signs_logger.setLevel(original_level)

    no_rec_records = [r for r in log_handler.records if "l4_event=l4_no_records" in r.getMessage()]
    assert len(no_rec_records) >= 1, (
        f"Expected l4_event=l4_no_records record, got none: "
        f"{[r.getMessage() for r in log_handler.records]}"
    )
    msg = no_rec_records[0].getMessage()
    assert "span_candidates=" not in msg, f"l4_no_records should NOT contain span_candidates=: {msg}"


async def test_all_l4_events_share_common_prefix() -> None:
    """All four l4_event variants are accessible via a single 'l4_event=' grep.

    This test drives all four code paths and confirms the common prefix makes
    them all greppable together in HA logs.
    """
    graph = _make_graph()
    broad_records = [dict(_BROOM_SIGN_RECORD)]
    unreachable_records = [
        {"from_street": "ALPHA STREET", "to_street": "BETA STREET",
         "sign_description": "SANITATION BROOM UP", "side_of_street": "N"}
    ]

    log_handler = _CapturingHandler()
    signs_logger = logging.getLogger("gps2asp.signs")
    signs_logger.addHandler(log_handler)
    original_level = signs_logger.level
    signs_logger.setLevel(logging.INFO)
    try:
        # Path 1: l4_entry + l4_match (broad query has reachable records)
        mock_client = MagicMock()
        mock_client.build_block_query.return_value = "mock_block_query"
        mock_client.build_on_street_query.return_value = "mock_broad_query"
        mock_client.fetch_signs = AsyncMock(side_effect=[[], [], broad_records])
        with (
            patch("gps2asp.signs.SODAClient", return_value=mock_client),
            patch("gps2asp.signs.graph.StreetGraph.get", return_value=graph),
        ):
            await retrieve_signs("BROADWAY", "72 STREET", "73 STREET", "N")

        # Path 2: l4_entry + l4_no_span (broad query has unreachable records)
        mock_client2 = MagicMock()
        mock_client2.build_block_query.return_value = "mock_block_query"
        mock_client2.build_on_street_query.return_value = "mock_broad_query"
        mock_client2.fetch_signs = AsyncMock(side_effect=[[], [], unreachable_records])
        with (
            patch("gps2asp.signs.SODAClient", return_value=mock_client2),
            patch("gps2asp.signs.graph.StreetGraph.get", return_value=graph),
        ):
            await retrieve_signs("BROADWAY", "72 STREET", "73 STREET", "N")

        # Path 3: l4_entry + l4_no_records (broad query returns empty)
        mock_client3 = MagicMock()
        mock_client3.build_block_query.return_value = "mock_block_query"
        mock_client3.build_on_street_query.return_value = "mock_broad_query"
        mock_client3.fetch_signs = AsyncMock(side_effect=[[], [], []])
        with (
            patch("gps2asp.signs.SODAClient", return_value=mock_client3),
            patch("gps2asp.signs.graph.StreetGraph.get", return_value=graph),
        ):
            await retrieve_signs("BROADWAY", "72 STREET", "73 STREET", "N")
    finally:
        signs_logger.removeHandler(log_handler)
        signs_logger.setLevel(original_level)

    all_msgs = [r.getMessage() for r in log_handler.records]
    l4_event_msgs = [m for m in all_msgs if "l4_event=" in m]

    # Must find all four variants
    variants = {"l4_entry", "l4_match", "l4_no_span", "l4_no_records"}
    found_variants = {v for v in variants if any(f"l4_event={v}" in m for m in l4_event_msgs)}
    assert found_variants == variants, (
        f"Missing l4_event variants: {variants - found_variants}. "
        f"Found messages: {l4_event_msgs}"
    )


class _CapturingHandler(logging.Handler):
    """Simple in-memory log handler for test assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)
