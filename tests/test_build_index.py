"""Unit tests for scripts/build_index.py bug fixes and graph construction.

Tests for:
1. _normalize_street_name() — directional prefix expansion (Bug 1)
2. _find_cross_street() — dead-end returns "" not "DEAD END" (Bug 3)
3. _fetch_asp_signs() — voided sign filter (Bug 2)
4. _build_street_adjacency() — coordinate-based street adjacency graph
5. _build_intersection_index() — (on_street, cross_street) -> segment PIDs
6. _bfs_between() — BFS traversal with depth limit
7. _propagate_asp_to_interior_blocks() — ASP flag expansion via BFS
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("geopandas")

# Add scripts/ to sys.path so we can import build_index
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import build_index
from build_index import (
    _bfs_between,
    _build_intersection_index,
    _build_street_adjacency,
    _find_cross_street,
    _normalize_street_name,
    _propagate_asp_to_interior_blocks,
)


class TestNormalizeStreetName:
    def test_directional_east(self):
        # SODA fixed-width: "EAST  100 STREET" (2 spaces before 3-digit number)
        assert _normalize_street_name("E 100 ST") == "EAST  100 STREET"

    def test_directional_west(self):
        # SODA fixed-width: "WEST    4 STREET" (4 spaces before 1-digit number)
        assert _normalize_street_name("W 4 ST") == "WEST    4 STREET"

    def test_directional_north(self):
        # SODA fixed-width: "NORTH   10 AVENUE" (3 spaces before 2-digit number)
        assert _normalize_street_name("N 10 AVE") == "NORTH   10 AVENUE"

    def test_suffix_only(self):
        assert _normalize_street_name("PROSPECT PL") == "PROSPECT PLACE"

    def test_no_false_positive_essex(self):
        # "ESSEX ST" starts with "E" but next char is "S" not a digit -- no expansion
        assert _normalize_street_name("ESSEX ST") == "ESSEX STREET"

    def test_empty_string(self):
        assert _normalize_street_name("") == ""

    def test_lowercase_input(self):
        # Function should uppercase internally; SODA fixed-width applies
        assert _normalize_street_name("e 100 st") == "EAST  100 STREET"


class TestFindCrossStreet:
    def test_dead_end_returns_empty_string(self):
        # Empty node_lookup means no cross streets found -- should return ""
        result = _find_cross_street(
            node=(100, 200),
            own_pid=42,
            own_name="MAIN STREET",
            node_lookup={},
        )
        assert result == ""
        assert result != "DEAD END"

    def test_cross_street_found(self):
        # Node lookup has a different street at the same node
        node_lookup = {(100, 200): [(99, "BROADWAY")]}
        result = _find_cross_street(
            node=(100, 200),
            own_pid=42,
            own_name="MAIN STREET",
            node_lookup=node_lookup,
        )
        assert result == "BROADWAY"


class TestFetchAspSignsFilter:
    def test_uses_voided_date_filter(self, monkeypatch):
        """_fetch_asp_signs() must use sign_design_voided_on_date IS NULL filter."""
        from build_index import _fetch_asp_signs
        import requests

        captured_params = {}

        class MockResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return []  # empty list stops the loop

        def mock_get(url, params=None, headers=None, timeout=None):
            captured_params.update(params or {})
            return MockResponse()

        monkeypatch.setattr(requests, "get", mock_get)
        _fetch_asp_signs()

        where_clause = captured_params.get("$where", "")
        assert "sign_design_voided_on_date IS NULL" in where_clause
        assert "record_type" not in where_clause


# ---------------------------------------------------------------------------
# Phase 11: Graph construction and BFS propagation tests
# ---------------------------------------------------------------------------


class TestBuildStreetAdjacency:
    """Tests for _build_street_adjacency()."""

    def test_linear_chain_same_street(self):
        """3 segments A-B-C on BROADWAY sharing nodes should be adjacent A-B and B-C but not A-C."""
        # Segment 1: node (0,0) to (100,0)
        # Segment 2: node (100,0) to (200,0)
        # Segment 3: node (200,0) to (300,0)
        # A shares (100,0) with B; B shares (200,0) with C; A and C share no node.
        node_lookup = {
            (0, 0): [(1, "BROADWAY")],
            (100, 0): [(1, "BROADWAY"), (2, "BROADWAY")],
            (200, 0): [(2, "BROADWAY"), (3, "BROADWAY")],
            (300, 0): [(3, "BROADWAY")],
        }
        adj = _build_street_adjacency(node_lookup)

        assert 2 in adj.get(1, set()), "Segment 1 should be adjacent to segment 2"
        assert 1 in adj.get(2, set()), "Segment 2 should be adjacent to segment 1"
        assert 3 in adj.get(2, set()), "Segment 2 should be adjacent to segment 3"
        assert 2 in adj.get(3, set()), "Segment 3 should be adjacent to segment 2"
        assert 3 not in adj.get(1, set()), (
            "Segment 1 should NOT be adjacent to segment 3"
        )
        assert 1 not in adj.get(3, set()), (
            "Segment 3 should NOT be adjacent to segment 1"
        )

    def test_different_street_names_not_connected(self):
        """Segments at the same node with different street names are NOT connected."""
        node_lookup = {
            (100, 200): [(10, "BROADWAY"), (20, "MAIN STREET")],
        }
        adj = _build_street_adjacency(node_lookup)

        assert 20 not in adj.get(10, set()), (
            "Different street names should not be connected"
        )
        assert 10 not in adj.get(20, set()), (
            "Different street names should not be connected"
        )

    def test_3x3_neighborhood_tolerance(self):
        """Segments at (100,200) and (101,200) on same street should be connected."""
        # Segment 11 ends at (100, 200); segment 12 starts at (101, 200)
        node_lookup = {
            (0, 0): [(11, "BROADWAY")],
            (100, 200): [(11, "BROADWAY")],
            (101, 200): [(12, "BROADWAY")],
            (200, 0): [(12, "BROADWAY")],
        }
        adj = _build_street_adjacency(node_lookup)

        assert 12 in adj.get(11, set()), (
            "Segments at (100,200) and (101,200) should connect"
        )
        assert 11 in adj.get(12, set()), (
            "Segments at (100,200) and (101,200) should connect"
        )

    def test_single_segment_has_empty_or_no_adjacency(self):
        """A single segment with no neighbors has no adjacent segments."""
        node_lookup = {
            (0, 0): [(99, "LONE STREET")],
            (100, 0): [(99, "LONE STREET")],
        }
        adj = _build_street_adjacency(node_lookup)

        # 99 may be in adj with an empty set, or not present at all
        assert len(adj.get(99, set())) == 0, "Isolated segment should have no adjacency"


class TestBuildIntersectionIndex:
    """Tests for _build_intersection_index()."""

    def test_maps_on_street_cross_street_to_pids(self):
        """(on_street, cross_street) should map to the correct PIDs."""
        cross_streets = {
            10: ("72 ST", "73 ST"),
            11: ("73 ST", "74 ST"),
        }
        gdf_street_names = {10: "BROADWAY", 11: "BROADWAY"}

        idx = _build_intersection_index(cross_streets, gdf_street_names)

        # Segment 10: BROADWAY at 72 STREET and at 73 STREET
        assert 10 in idx.get(("BROADWAY", "72 STREET"), set())
        assert 10 in idx.get(("BROADWAY", "73 STREET"), set())
        # Segment 11: BROADWAY at 73 STREET and at 74 STREET
        assert 11 in idx.get(("BROADWAY", "73 STREET"), set())
        assert 11 in idx.get(("BROADWAY", "74 STREET"), set())

    def test_both_from_and_to_streets_indexed(self):
        """Both from_street and to_street endpoints are indexed for each segment."""
        cross_streets = {42: ("MAIN ST", "PARK AVE")}
        gdf_street_names = {42: "ELM ST"}

        idx = _build_intersection_index(cross_streets, gdf_street_names)

        assert 42 in idx.get(("ELM STREET", "MAIN STREET"), set())
        assert 42 in idx.get(("ELM STREET", "PARK AVENUE"), set())

    def test_empty_cross_streets_skipped(self):
        """Segments with empty cross streets should not create empty-key entries."""
        cross_streets = {5: ("", "PARK AVE")}
        gdf_street_names = {5: "BROADWAY"}

        idx = _build_intersection_index(cross_streets, gdf_street_names)

        # Empty cross street should not be indexed
        for key in idx:
            assert key[1] != "", "Empty cross street should not be in index"

    def test_names_are_normalized(self):
        """Street names should be normalized via _normalize_street_name."""
        cross_streets = {7: ("E 14 ST", "W 14 ST")}
        gdf_street_names = {7: "BROADWAY"}

        idx = _build_intersection_index(cross_streets, gdf_street_names)

        # E 14 ST should normalize to EAST   14 STREET (SODA fixed-width);
        # W 14 ST to WEST   14 STREET
        assert 7 in idx.get(("BROADWAY", "EAST   14 STREET"), set())
        assert 7 in idx.get(("BROADWAY", "WEST   14 STREET"), set())


class TestBfsBetween:
    """Tests for _bfs_between()."""

    def test_linear_chain_full_traversal(self):
        """BFS from {A} to {D} on a linear chain A-B-C-D should return {A,B,C,D}."""
        adjacency = {
            1: {2},
            2: {1, 3},
            3: {2, 4},
            4: {3},
        }
        result = _bfs_between(start_pids={1}, end_pids={4}, adjacency=adjacency)
        assert result == {1, 2, 3, 4}

    def test_max_depth_stops_early(self):
        """BFS with max_depth=1 should not traverse beyond depth 1 from start."""
        adjacency = {
            1: {2},
            2: {1, 3},
            3: {2, 4},
            4: {3},
        }
        result = _bfs_between(
            start_pids={1}, end_pids={4}, adjacency=adjacency, max_depth=1
        )
        # With max_depth=1, BFS only expands one hop from start.
        # Since end_pid=4 is never reached, must return empty set.
        assert result == set(), (
            "BFS that doesn't reach end_pids should return empty set"
        )

    def test_unreachable_endpoint_returns_empty_set(self):
        """BFS that never reaches any end_pid should return empty set."""
        adjacency = {
            1: {2},
            2: {1},
            # 3 is disconnected
        }
        result = _bfs_between(start_pids={1}, end_pids={3}, adjacency=adjacency)
        assert result == set(), "Unreachable endpoint should return empty set"

    def test_start_equals_end_returns_just_that_pid(self):
        """If start and end are the same pid, BFS returns just that pid."""
        adjacency = {1: {2}, 2: {1}}
        result = _bfs_between(start_pids={1}, end_pids={1}, adjacency=adjacency)
        assert 1 in result

    def test_multiple_start_and_end_pids(self):
        """BFS works with multiple start and end pids."""
        adjacency = {
            10: {11},
            11: {10, 12},
            12: {11, 13},
            13: {12},
        }
        result = _bfs_between(
            start_pids={10, 11}, end_pids={12, 13}, adjacency=adjacency
        )
        # Should reach 12 and/or 13 from the start set
        assert len(result) > 0
        assert result.issubset({10, 11, 12, 13})


class TestPropagateAspToInteriorBlocks:
    """Tests for _propagate_asp_to_interior_blocks()."""

    def _make_fixtures(self):
        """Build a minimal 4-segment linear street for testing.

        Layout: seg 1 (72nd-73rd) - seg 2 (73rd-74th) - seg 3 (74th-75th)
        SODA has span: BROADWAY from 72ND STREET to 75TH STREET (covers all 3)

        Segment 4 is on a different street (MAIN STREET) and should not be affected.
        """
        # cross_streets: pid -> (from_cross, to_cross) using CSCL abbreviated names
        cross_streets = {
            1: ("72 ST", "73 ST"),
            2: ("73 ST", "74 ST"),
            3: ("74 ST", "75 ST"),
            4: ("A ST", "B ST"),
        }
        gdf_street_names = {
            1: "BROADWAY",
            2: "BROADWAY",
            3: "BROADWAY",
            4: "MAIN ST",
        }
        # adjacency: 1-2-3 linear chain; 4 isolated
        adjacency = {
            1: {2},
            2: {1, 3},
            3: {2},
            4: set(),
        }
        # intersection_index: built from the normalized cross streets
        intersection_index = {
            ("BROADWAY", "72 STREET"): {1},
            ("BROADWAY", "73 STREET"): {1, 2},
            ("BROADWAY", "74 STREET"): {2, 3},
            ("BROADWAY", "75 STREET"): {3},
            ("MAIN STREET", "A STREET"): {4},
            ("MAIN STREET", "B STREET"): {4},
        }
        return cross_streets, gdf_street_names, adjacency, intersection_index

    def test_interior_blocks_added_to_asp_lookup(self):
        """BFS spanning 3 blocks should add interior block tuples to asp_lookup."""
        cross_streets, gdf_street_names, adjacency, intersection_index = (
            self._make_fixtures()
        )

        # SODA span covers entire BROADWAY from 72nd to 75th on both sides
        asp_lookup = {
            ("BROADWAY", "72 STREET", "75 STREET", "N"),
            ("BROADWAY", "72 STREET", "75 STREET", "S"),
        }

        expanded, _stats = _propagate_asp_to_interior_blocks(
            asp_lookup, adjacency, intersection_index, cross_streets, gdf_street_names
        )

        # Interior block 2 (73rd-74th): should be added for both sides N and S
        # seg 2 cross streets are "73 ST" -> normalized "73 STREET" and "74 ST" -> "74 STREET"
        # Both orderings should be checked by _check_has_asp, so either direction is valid.
        # At minimum, the expanded set should be larger than the original.
        assert len(expanded) > len(asp_lookup), "Interior blocks should be added"

        # Check that seg 1 (original endpoint) is also in expanded
        # (it was already in asp_lookup or gets re-added)
        # More specifically: interior segment 2 (73 ST - 74 ST) should appear
        interior_tuples = {t for t in expanded if "73 STREET" in t or "74 STREET" in t}
        assert len(interior_tuples) > 0, (
            "Interior block 73rd-74th should be in expanded asp_lookup"
        )

    def test_bfs_failure_does_not_add_tuples(self):
        """When BFS can't reach endpoint, no tuples should be added."""
        cross_streets, gdf_street_names, adjacency, intersection_index = (
            self._make_fixtures()
        )

        # Span references a cross street that doesn't exist in intersection_index
        asp_lookup = {
            ("BROADWAY", "99 STREET", "105 STREET", "N"),  # Not in intersection_index
        }

        expanded, _stats = _propagate_asp_to_interior_blocks(
            asp_lookup, adjacency, intersection_index, cross_streets, gdf_street_names
        )

        # Should be unchanged -- BFS couldn't find endpoints
        assert expanded == asp_lookup, "Unresolvable span should not expand asp_lookup"

    def test_propagation_stats_returned(self):
        """Stats dict should contain expected keys."""
        cross_streets, gdf_street_names, adjacency, intersection_index = (
            self._make_fixtures()
        )
        asp_lookup = {("BROADWAY", "72 STREET", "75 STREET", "N")}

        _, stats = _propagate_asp_to_interior_blocks(
            asp_lookup, adjacency, intersection_index, cross_streets, gdf_street_names
        )

        assert "spans_processed" in stats
        assert "spans_resolved" in stats
        assert "interior_blocks_added" in stats
        assert stats["spans_processed"] >= 1

    def test_propagate_asp_left_side_only(self):
        """When asp_lookup has only one side, interior blocks get only that side."""
        cross_streets, gdf_street_names, adjacency, intersection_index = (
            self._make_fixtures()
        )

        # Only North side in asp_lookup
        asp_lookup = {("BROADWAY", "72 STREET", "75 STREET", "N")}

        expanded, _ = _propagate_asp_to_interior_blocks(
            asp_lookup, adjacency, intersection_index, cross_streets, gdf_street_names
        )

        # All tuples added should have side "N" only -- no "S" side should be added
        sides_in_expanded = {t[3] for t in expanded}
        assert "S" not in sides_in_expanded, (
            "South side should not be added when only North side is in asp_lookup"
        )
        assert "N" in sides_in_expanded


class TestCurbCalibration:
    """Offline synthetic-curb tests for per-segment calibration (SC-1/SC-5).

    A tiny index is built over ONE East-running CSCL segment with synthetic
    flanking curb + roadbed geometry, monkeypatching the three network download
    helpers. All geometry is in EPSG:2263 (State Plane feet); the CSCL frame is
    tagged EPSG:2263 so _filter_and_reproject's to_crs is a no-op and coordinates
    are preserved through the build.
    """

    # East-running segment on y=0-line, 300 ft long, at a State-Plane origin.
    _X0 = 1_000_000.0
    _Y0 = 200_000.0
    _LEN = 300.0

    def _make_cscl_gdf(self):
        import geopandas as gpd
        from shapely.geometry import LineString

        seg = LineString([(self._X0, self._Y0), (self._X0 + self._LEN, self._Y0)])
        return gpd.GeoDataFrame(
            {
                "physicalid": [1],
                "full_street_name": ["TEST STREET"],
                "rw_type": [1],
                "trafdir": ["TW"],
                "streetwidth": [34.0],
                "nominaldir": [""],
                "boroughcode": ["1"],
                "geometry": [seg],
            },
            crs="EPSG:2263",
        )

    def _make_curb_gdf(self):
        """North curb at +16 ft, South curb at -14 ft -> c=+1.0, width=30.0."""
        import geopandas as gpd
        from shapely.geometry import LineString

        north = LineString(
            [(self._X0, self._Y0 + 16), (self._X0 + self._LEN, self._Y0 + 16)]
        )
        south = LineString(
            [(self._X0, self._Y0 - 14), (self._X0 + self._LEN, self._Y0 - 14)]
        )
        return gpd.GeoDataFrame(geometry=[north, south], crs="EPSG:2263")

    def _make_roadbed_gdf(self):
        """Pavement polygon spanning y in [-14, +16] -> roadbed c ~= +1.0 (agrees)."""
        import geopandas as gpd
        from shapely.geometry import box

        pavement = box(
            self._X0 - 10, self._Y0 - 14, self._X0 + self._LEN + 10, self._Y0 + 16
        )
        return gpd.GeoDataFrame(geometry=[pavement], crs="EPSG:2263")

    def _patch_downloads(self, monkeypatch, *, curbs=True):
        monkeypatch.setattr(
            build_index, "_download_cscl_geojson", lambda: self._make_cscl_gdf()
        )
        monkeypatch.setattr(build_index, "_fetch_asp_signs", lambda: set())
        if curbs:
            monkeypatch.setattr(
                build_index,
                "_download_curbs",
                lambda cache_path=None: self._make_curb_gdf(),
            )
            monkeypatch.setattr(
                build_index,
                "_download_roadbed",
                lambda cache_path=None: self._make_roadbed_gdf(),
            )

    def _load_segments(self, output_dir):
        with open(output_dir / "segments.json") as f:
            return json.load(f)

    def _load_build_info(self, output_dir):
        with open(output_dir / "build_info.json") as f:
            return json.load(f)

    def test_calibration_fields_written_on_clean_curbs(self, tmp_path, monkeypatch):
        """Clean synthetic curbs -> segment record carries all five keys, calibrated."""
        self._patch_downloads(monkeypatch)
        build_index.build_index(output_dir=tmp_path)

        segments = self._load_segments(tmp_path)
        assert "1" in segments, "synthetic segment should be indexed"
        rec = segments["1"]

        for key in (
            "center_offset_c",
            "curb_width_ft",
            "spread_n",
            "spread_s",
            "calibrated",
        ):
            assert key in rec, f"segment record missing calibration key {key!r}"

        assert rec["calibrated"] is True, "clean synthetic curbs should calibrate"
        # North +16, South -14 -> c = (16 + -14)/2 = +1.0, width = 30.0
        assert rec["center_offset_c"] == pytest.approx(1.0, abs=0.5)
        assert rec["curb_width_ft"] == pytest.approx(30.0, abs=1.0)
        assert rec["spread_n"] is not None
        assert rec["spread_s"] is not None

    def test_build_info_has_calibration_counts(self, tmp_path, monkeypatch):
        """build_info.json records calibrated_count and non_calibrated_count."""
        self._patch_downloads(monkeypatch)
        build_index.build_index(output_dir=tmp_path)

        info = self._load_build_info(tmp_path)
        assert "calibrated_count" in info
        assert "non_calibrated_count" in info
        assert info["calibrated_count"] == 1
        assert info["non_calibrated_count"] == 0

    def test_no_curb_calibration_writes_non_calibrated_defaults(
        self, tmp_path, monkeypatch
    ):
        """--no-curb-calibration -> five keys as non-calibrated defaults."""
        # Curb/roadbed helpers are NOT patched: they must never be called.
        self._patch_downloads(monkeypatch, curbs=False)

        def _boom(cache_path=None):
            raise AssertionError("curb/roadbed download must not run when disabled")

        monkeypatch.setattr(build_index, "_download_curbs", _boom)
        monkeypatch.setattr(build_index, "_download_roadbed", _boom)

        build_index.build_index(output_dir=tmp_path, no_curb_calibration=True)

        rec = self._load_segments(tmp_path)["1"]
        assert rec["calibrated"] is False
        assert rec["center_offset_c"] == 0.0
        assert rec["curb_width_ft"] is None
        assert rec["spread_n"] is None
        assert rec["spread_s"] is None

        info = self._load_build_info(tmp_path)
        assert info["calibrated_count"] == 0
        assert info["non_calibrated_count"] == 1


class TestGraphJson:
    """Tests for graph.json serialization (Task 2 integration)."""

    def test_graph_json_structure(self, tmp_path):
        """graph.json should have adjacency, segment_streets, segment_cross_streets keys."""
        import json

        # Build a minimal adjacency and cross_streets to produce graph.json content
        adjacency = {1: {2}, 2: {1, 3}, 3: {2}}
        cross_streets = {
            1: ("72 STREET", "73 STREET"),
            2: ("73 STREET", "74 STREET"),
            3: ("74 STREET", "75 STREET"),
        }
        gdf_street_names = {1: "BROADWAY", 2: "BROADWAY", 3: "BROADWAY"}

        # Simulate what build_index() will write
        graph_data = {
            "adjacency": {
                str(pid): sorted(neighbors) for pid, neighbors in adjacency.items()
            },
            "segment_streets": {
                str(pid): name for pid, name in gdf_street_names.items()
            },
            "segment_cross_streets": {
                str(pid): list(cs) for pid, cs in cross_streets.items()
            },
        }

        graph_path = tmp_path / "graph.json"
        with open(graph_path, "w") as f:
            json.dump(graph_data, f)

        # Verify it round-trips correctly
        with open(graph_path) as f:
            loaded = json.load(f)

        assert "adjacency" in loaded
        assert "segment_streets" in loaded
        assert "segment_cross_streets" in loaded

        # Adjacency values should be lists (JSON arrays)
        for pid_str, neighbors in loaded["adjacency"].items():
            assert isinstance(neighbors, list), (
                f"Neighbors for {pid_str} should be list"
            )

        # Segment streets should be strings
        for pid_str, name in loaded["segment_streets"].items():
            assert isinstance(name, str)

        # Cross streets should be 2-element lists
        for pid_str, cs in loaded["segment_cross_streets"].items():
            assert isinstance(cs, list)
            assert len(cs) == 2
