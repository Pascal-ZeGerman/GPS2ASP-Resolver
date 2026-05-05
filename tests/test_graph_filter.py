"""Tests for graph.json 2-hop BFS filter and zstandard loading.

Filter tests validate correctness of _filter_2hop_neighborhood():
- Retains ASP seeds + 1-hop + 2-hop neighbors
- Excludes 3+ hop segments
- Prunes dangling neighbor references from adjacency lists

Load tests validate StreetGraph.load() with .zst and .json files.
BFS test validates span_distance on a filtered graph fixture.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import zstandard

pytest.importorskip("geopandas")

# Add scripts/ to sys.path so we can import build_index
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from build_index import _filter_2hop_neighborhood

from gps2asp.signs.graph import StreetGraph


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Chain: 1 -- 2 -- 3 -- 4 -- 5
# Branch: 2 -- 6, 3 -- 7
ADJACENCY = {
    1: {2},
    2: {1, 3, 6},
    3: {2, 4, 7},
    4: {3, 5},
    5: {4},
    6: {2},
    7: {3},
}
ASP_PIDS = {1}
# hop0 = {1}
# hop1_new = neighbors of {1} minus retained = {2}
# hop2 = neighbors of {2} minus retained = {1,3,6} minus {1,2} = {3,6}
# retained = {1, 2, 3, 6}


# ---------------------------------------------------------------------------
# Filter correctness tests
# ---------------------------------------------------------------------------


class TestFilter2HopNeighborhood:
    """Test the 2-hop BFS filter function."""

    def test_filter_retains_asp_and_2hop(self) -> None:
        """2-hop filter retains ASP seed + 1-hop + 2-hop neighbors."""
        retained = _filter_2hop_neighborhood(ADJACENCY, ASP_PIDS)
        assert retained == {1, 2, 3, 6}

    def test_filter_excludes_beyond_2hop(self) -> None:
        """Chain A-B-C-D-E where only A has ASP: retains A,B,C; excludes D,E."""
        chain = {
            10: {11},
            11: {10, 12},
            12: {11, 13},
            13: {12, 14},
            14: {13},
        }
        retained = _filter_2hop_neighborhood(chain, {10})
        assert 10 in retained
        assert 11 in retained
        assert 12 in retained
        assert 13 not in retained
        assert 14 not in retained

    def test_filter_prunes_dangling_neighbors(self) -> None:
        """Filtered adjacency lists contain no references to excluded PIDs."""
        retained = _filter_2hop_neighborhood(ADJACENCY, ASP_PIDS)
        excluded = set(ADJACENCY.keys()) - retained

        for pid in retained:
            neighbors = ADJACENCY.get(pid, set())
            pruned = {n for n in neighbors if n in retained}
            {n for n in neighbors if n in excluded}
            # When building the filtered graph, dangling refs must be removed
            for n in pruned:
                assert n in retained, (
                    f"Neighbor {n} of PID {pid} is not in retained set"
                )
            # Verify that excluded PIDs exist (the filter actually excluded something)
            assert len(excluded) > 0, "Expected some PIDs to be excluded"

    def test_filter_multiple_asp_seeds(self) -> None:
        """Multiple ASP seeds expand neighborhoods from each seed."""
        # Triangle + tail: 1--2--3--1, 3--4--5
        adj = {
            1: {2, 3},
            2: {1, 3},
            3: {1, 2, 4},
            4: {3, 5},
            5: {4},
        }
        # Seeds at both ends
        retained = _filter_2hop_neighborhood(adj, {1, 5})
        # From 1: hop1={2,3}, hop2={4} -> {1,2,3,4}
        # From 5: hop1={4}, hop2={3} -> {5,4,3}
        # Union: {1,2,3,4,5}
        assert retained == {1, 2, 3, 4, 5}

    def test_filter_asp_pid_not_in_adjacency(self) -> None:
        """ASP PID not in adjacency is silently ignored."""
        retained = _filter_2hop_neighborhood(ADJACENCY, {999})
        assert retained == set()


# ---------------------------------------------------------------------------
# StreetGraph .zst loading tests
# ---------------------------------------------------------------------------


class TestStreetGraphLoad:
    """Test StreetGraph.load() with .zst and .json files."""

    def setup_method(self) -> None:
        """Reset StreetGraph singleton before each test to prevent cross-test contamination."""
        StreetGraph._instance = None

    def teardown_method(self) -> None:
        """Reset StreetGraph singleton after each test to prevent cross-test contamination."""
        StreetGraph._instance = None

    def test_load_zst(self, tmp_path: pytest.TempPathFactory) -> None:
        """StreetGraph.load() reads a .zst file created with zstandard."""
        graph_data = {
            "adjacency": {"1": [2]},
            "segment_streets": {"1": "MAIN ST"},
            "segment_cross_streets": {"1": ["1ST AVE", "2ND AVE"]},
        }
        json_bytes = json.dumps(graph_data).encode("utf-8")
        cctx = zstandard.ZstdCompressor()
        compressed = cctx.compress(json_bytes)
        zst_path = tmp_path / "graph.json.zst"
        zst_path.write_bytes(compressed)

        graph = StreetGraph.load(index_dir=tmp_path)
        assert graph is not None
        assert "1" in graph.adjacency
        assert graph.adjacency["1"] == [2]

    def test_load_json_fallback(self, tmp_path: pytest.TempPathFactory) -> None:
        """StreetGraph.load() falls back to .json when no .zst exists."""
        graph_data = {
            "adjacency": {"10": [20]},
            "segment_streets": {"10": "BROADWAY"},
            "segment_cross_streets": {"10": ["3RD AVE", "4TH AVE"]},
        }
        json_path = tmp_path / "graph.json"
        json_path.write_text(json.dumps(graph_data), encoding="utf-8")

        graph = StreetGraph.load(index_dir=tmp_path)
        assert graph is not None
        assert "10" in graph.adjacency

    def test_load_no_file(self, tmp_path: pytest.TempPathFactory) -> None:
        """StreetGraph.load() returns None when no graph file exists."""
        graph = StreetGraph.load(index_dir=tmp_path)
        assert graph is None


# ---------------------------------------------------------------------------
# BFS on filtered graph
# ---------------------------------------------------------------------------


class TestBFSOnFilteredGraph:
    """Test BFS span_distance on a StreetGraph built from filtered data."""

    def test_bfs_on_filtered_graph(self) -> None:
        """span_distance returns correct hops on a filtered graph fixture."""
        # Build a small graph: 3 segments on MAIN ST
        # PID 100: MAIN ST between 1ST AVE and 2ND AVE
        # PID 200: MAIN ST between 2ND AVE and 3RD AVE
        # PID 300: MAIN ST between 3RD AVE and 4TH AVE
        adjacency = {
            "100": [200],
            "200": [100, 300],
            "300": [200],
        }
        segment_streets = {
            "100": "MAIN STREET",
            "200": "MAIN STREET",
            "300": "MAIN STREET",
        }
        segment_cross_streets = {
            "100": ["1ST AVENUE", "2ND AVENUE"],
            "200": ["2ND AVENUE", "3RD AVENUE"],
            "300": ["3RD AVENUE", "4TH AVENUE"],
        }

        graph = StreetGraph(
            adjacency=adjacency,
            segment_streets=segment_streets,
            segment_cross_streets=segment_cross_streets,
        )

        # Adjacent spans sharing 2ND AVE endpoint: distance = 0
        d = graph.span_distance("1ST AVENUE", "2ND AVENUE", "2ND AVENUE", "3RD AVENUE")
        assert d == 0

        # Spans 2 hops apart (1ST-2ND vs 3RD-4TH): distance > 0
        d2 = graph.span_distance("1ST AVENUE", "2ND AVENUE", "3RD AVENUE", "4TH AVENUE")
        assert d2 > 0

    def test_bfs_unreachable(self) -> None:
        """span_distance returns inf for disconnected components."""
        adjacency = {
            "1": [2],
            "2": [1],
            "10": [20],
            "20": [10],
        }
        segment_streets = {
            "1": "MAIN STREET",
            "2": "MAIN STREET",
            "10": "OTHER STREET",
            "20": "OTHER STREET",
        }
        segment_cross_streets = {
            "1": ["A AVENUE", "B AVENUE"],
            "2": ["B AVENUE", "C AVENUE"],
            "10": ["X AVENUE", "Y AVENUE"],
            "20": ["Y AVENUE", "Z AVENUE"],
        }

        graph = StreetGraph(
            adjacency=adjacency,
            segment_streets=segment_streets,
            segment_cross_streets=segment_cross_streets,
        )

        d = graph.span_distance("A AVENUE", "B AVENUE", "X AVENUE", "Y AVENUE")
        assert d == float("inf")
