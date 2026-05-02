"""Unit tests for SpatialIndex.query_radius() bounded-radius queries.

These tests require a built spatial index (skipped via spatial_index_dir
fixture if not built). Each test exercises the new query_radius() helper
introduced in Phase 26 for parking-area pre-seeding.
"""

from __future__ import annotations

import pytest

from gps2asp.resolver import convert
from gps2asp.resolver.spatial_index import SpatialIndex

PROSPECT_HEIGHTS_LAT = 40.6778
PROSPECT_HEIGHTS_LON = -73.9690


@pytest.mark.integration
class TestQueryRadius:
    """Bounded-radius enumeration via SpatialIndex.query_radius()."""

    async def test_query_radius_returns_segments_within_radius_ft(
        self, spatial_index_dir,
    ):
        """query_radius returns at least one segment with distance_ft <= radius_ft."""
        cx_ft, cy_ft = convert(PROSPECT_HEIGHTS_LAT, PROSPECT_HEIGHTS_LON)
        idx = await SpatialIndex.get(index_dir=spatial_index_dir)

        results = idx.query_radius(cx_ft, cy_ft, 500.0)

        assert len(results) > 0, "Prospect Heights with 500ft radius should return segments"
        assert all(c.distance_ft <= 500.0 for c in results), (
            "All returned segments must be within radius_ft"
        )

    async def test_query_radius_excludes_far_segments(self, spatial_index_dir):
        """Tight radius is a strict subset of looser radius (compare by segment_id)."""
        cx_ft, cy_ft = convert(PROSPECT_HEIGHTS_LAT, PROSPECT_HEIGHTS_LON)
        idx = await SpatialIndex.get(index_dir=spatial_index_dir)

        tight = idx.query_radius(cx_ft, cy_ft, 50.0)
        loose = idx.query_radius(cx_ft, cy_ft, 1000.0)

        assert len(tight) <= len(loose), (
            "Tight radius cannot return more segments than loose radius"
        )
        loose_ids = {c.segment_id for c in loose}
        tight_ids = {c.segment_id for c in tight}
        assert tight_ids.issubset(loose_ids), (
            "Every tight-radius segment must also appear in the loose-radius result"
        )

    async def test_query_radius_returns_empty_list_for_zero_radius(
        self, spatial_index_dir,
    ):
        """Zero radius returns [] (does NOT raise).

        Contract: query_radius() calls self._index.intersection((x, x, x, x)),
        a degenerate zero-area bounding box.  Even if libspatialindex returns a
        segment whose bounding box happens to include the exact point, the
        subsequent ``distance_ft <= 0.0`` exact-distance filter eliminates it,
        so the result list is always empty.  The behaviour is therefore
        guaranteed by the implementation filter, not solely by libspatialindex.
        """
        cx_ft, cy_ft = convert(PROSPECT_HEIGHTS_LAT, PROSPECT_HEIGHTS_LON)
        idx = await SpatialIndex.get(index_dir=spatial_index_dir)

        results = idx.query_radius(cx_ft, cy_ft, 0.0)

        assert results == [], "Zero-radius query must return [] (no raise)"

    async def test_query_radius_returns_empty_list_far_from_nyc(
        self, spatial_index_dir,
    ):
        """A point far from NYC (origin of State Plane) returns [] (no raise)."""
        idx = await SpatialIndex.get(index_dir=spatial_index_dir)

        results = idx.query_radius(0.0, 0.0, 500.0)

        assert results == [], "Origin-of-State-Plane query must return [] (no raise)"

    async def test_query_radius_results_sorted_closest_first(
        self, spatial_index_dir,
    ):
        """Results must be sorted by distance_ft ascending."""
        cx_ft, cy_ft = convert(PROSPECT_HEIGHTS_LAT, PROSPECT_HEIGHTS_LON)
        idx = await SpatialIndex.get(index_dir=spatial_index_dir)

        results = idx.query_radius(cx_ft, cy_ft, 500.0)

        distances = [c.distance_ft for c in results]
        assert distances == sorted(distances), (
            "query_radius results must be sorted closest-first"
        )

    async def test_query_radius_returns_segment_candidate_with_required_fields(
        self, spatial_index_dir,
    ):
        """Each returned candidate exposes the SegmentCandidate contract fields."""
        cx_ft, cy_ft = convert(PROSPECT_HEIGHTS_LAT, PROSPECT_HEIGHTS_LON)
        idx = await SpatialIndex.get(index_dir=spatial_index_dir)

        results = idx.query_radius(cx_ft, cy_ft, 500.0)

        assert len(results) > 0, "Need at least one result to assert field shape"
        for c in results:
            assert isinstance(c.segment_id, int)
            assert isinstance(c.distance_ft, float)
            assert isinstance(c.full_street_name, str)
            assert len(c.full_street_name) > 0, (
                "full_street_name must be non-empty for index-resident segments"
            )


def test_query_radius_raises_runtime_error_when_not_loaded():
    """query_radius() raises RuntimeError if the index has not been loaded."""
    idx = SpatialIndex(index_dir="/nonexistent")
    # Do NOT call _load(); _index and _segments stay None.

    with pytest.raises(RuntimeError, match="SpatialIndex not loaded"):
        idx.query_radius(0.0, 0.0, 100.0)
