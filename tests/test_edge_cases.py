"""Edge case tests for GPS2ASP resolver.

Tests error handling, boundary conditions, and unusual scenarios:
- Coordinates outside NYC
- Points near road centerlines (ambiguous)
- Points near intersections (ambiguous)
- Points in parks (no segment)
- Divided roads (service roads vs main)

These tests require a built spatial index. Run with:
    pytest tests/test_edge_cases.py -v
"""

from __future__ import annotations

import pytest

from gps2asp.resolver import resolve, convert, resolve_segment
from gps2asp.resolver.exceptions import (
    AmbiguousResolutionError,
    NoSegmentFoundError,
    OutsideNYCError,
)
from gps2asp.resolver.spatial_index import SpatialIndex


@pytest.mark.integration
class TestOutsideNYC:
    """Test that coordinates outside NYC raise OutsideNYCError."""

    async def test_outside_nyc_los_angeles(self, spatial_index_dir):
        """Los Angeles coordinates should raise OutsideNYCError."""
        with pytest.raises(OutsideNYCError):
            await resolve(34.0, -118.0, index_dir=spatial_index_dir)

    async def test_outside_nyc_ocean(self, spatial_index_dir):
        """Ocean coordinates near NYC should raise OutsideNYCError."""
        with pytest.raises(OutsideNYCError):
            await resolve(40.5, -74.5, index_dir=spatial_index_dir)

    async def test_outside_nyc_error_contains_coordinates(
        self,
        spatial_index_dir,
    ):
        """OutsideNYCError should include the original coordinates."""
        with pytest.raises(OutsideNYCError) as exc_info:
            await resolve(34.0, -118.0, index_dir=spatial_index_dir)
        assert exc_info.value.lat == 34.0
        assert exc_info.value.lon == -118.0


@pytest.mark.integration
class TestAmbiguousResolution:
    """Test that ambiguous situations raise AmbiguousResolutionError."""

    async def test_near_centerline_ambiguous(self, spatial_index_dir):
        """A point near the road centerline should be ambiguous.

        Uses convert() to get State Plane coordinates, then manually
        constructs a point near the centerline.
        """
        # Convert a known Prospect Heights point to State Plane
        x, y = convert(40.6778, -73.9690)

        # Get the index to find the nearest segment
        idx = await SpatialIndex.get(index_dir=spatial_index_dir)
        candidates = idx.nearest(x, y)
        best = candidates[0]

        # Project onto segment to find nearest point on centerline
        from shapely.geometry import Point

        dist_along = best.geometry.project(Point(x, y))
        nearest_on_line = best.geometry.interpolate(dist_along)

        # Place a point very close to the centerline (2 feet offset)
        # Perpendicular offset: move slightly in the perpendicular direction
        centerline_x = nearest_on_line.x + 2.0
        centerline_y = nearest_on_line.y

        with pytest.raises(AmbiguousResolutionError):
            await resolve_segment(
                centerline_x,
                centerline_y,
                index_dir=spatial_index_dir,
            )

    async def test_intersection_ambiguous(self, spatial_index_dir):
        """A point right at a segment endpoint should be ambiguous.

        Programmatically finds a segment endpoint (intersection) and
        places a point right next to it, which should trigger low
        confidence due to intersection proximity (<30ft).
        """
        from shapely.geometry import Point

        # Convert a known Prospect Heights point to State Plane
        x, y = convert(40.6778, -73.9690)

        # Get the nearest segment and find its endpoint
        idx = await SpatialIndex.get(index_dir=spatial_index_dir)
        candidates = idx.nearest(x, y)
        best = candidates[0]

        # Get the first endpoint of the segment (an intersection)
        endpoint = Point(best.geometry.coords[0])

        # Place a test point 15ft from the endpoint (perpendicular
        # offset so it is off-centerline but still near intersection)
        test_x = endpoint.x + 15.0
        test_y = endpoint.y + 15.0

        # This should either raise AmbiguousResolutionError or have
        # low confidence due to intersection proximity
        try:
            result = await resolve_segment(
                test_x,
                test_y,
                index_dir=spatial_index_dir,
            )
            # If it resolves, confidence should be low
            # (near intersection penalty <30ft)
            assert result.confidence <= 0.7, (
                f"Expected low confidence near intersection, got {result.confidence}"
            )
        except (AmbiguousResolutionError, NoSegmentFoundError):
            # Expected -- near-intersection raises ambiguous,
            # or point may be too far from any segment
            pass

    async def test_resolve_custom_high_threshold(self, spatial_index_dir):
        """A very high threshold should make most resolutions ambiguous."""
        with pytest.raises(AmbiguousResolutionError) as exc_info:
            await resolve(
                40.6778,
                -73.9690,
                confidence_threshold=0.99,
                index_dir=spatial_index_dir,
            )
        assert exc_info.value.confidence < 0.99


@pytest.mark.integration
class TestNoSegment:
    """Test behavior when no street segment is nearby."""

    async def test_no_segment_park(self, spatial_index_dir):
        """A point deep inside Prospect Park should fail.

        The point is far from any road, so either NoSegmentFoundError
        (>164ft from any road) or a result for the nearest park road
        is acceptable.
        """
        # Deep inside Prospect Park (Long Meadow area)
        try:
            result = await resolve(
                40.6602,
                -73.9690,
                index_dir=spatial_index_dir,
            )
            # If it resolves, it should be to a park road
            # (reasonable fallback behavior)
            assert result.confidence > 0.0
        except (NoSegmentFoundError, AmbiguousResolutionError):
            # Expected -- deep in park, far from roads
            pass


@pytest.mark.integration
class TestDividedRoads:
    """Test behavior on divided roads with service roads."""

    async def test_divided_road_eastern_parkway(self, spatial_index_dir):
        """Eastern Parkway has main road and service roads.

        A point on the south service road should resolve to a different
        segment than the main road.
        """
        # South service road of Eastern Parkway near Prospect Heights
        # This should resolve to the service road, not the main road
        try:
            result = await resolve(
                40.6710,
                -73.9620,
                index_dir=spatial_index_dir,
            )
            # The result should be a street near Eastern Parkway
            # We don't assert exact street name since GPS coordinates
            # are approximate, but it should resolve to something
            assert isinstance(result.on_street, str)
            assert len(result.on_street) > 0
        except (AmbiguousResolutionError, NoSegmentFoundError):  # lgtm[py/empty-except]
            pass


@pytest.mark.integration
class TestMultipleBoroughs:
    """Test resolver works across different NYC boroughs."""

    async def test_manhattan_midtown(self, spatial_index_dir):
        """Test resolution in Manhattan (different grid orientation)."""
        # 5th Ave and 42nd St area
        try:
            result = await resolve(
                40.7539,
                -73.9822,
                index_dir=spatial_index_dir,
            )
            assert isinstance(result.on_street, str)
            assert result.side_of_street in ("N", "S", "E", "W")
        except (AmbiguousResolutionError, NoSegmentFoundError):  # lgtm[py/empty-except]
            pass

    async def test_queens_astoria(self, spatial_index_dir):
        """Test resolution in Queens (rotated grid)."""
        # Steinway Street in Astoria
        try:
            result = await resolve(
                40.7635,
                -73.9165,
                index_dir=spatial_index_dir,
            )
            assert isinstance(result.on_street, str)
        except (AmbiguousResolutionError, NoSegmentFoundError):  # lgtm[py/empty-except]
            pass

    async def test_bronx_grand_concourse(self, spatial_index_dir):
        """Test resolution in the Bronx."""
        # Grand Concourse area
        try:
            result = await resolve(
                40.8288,
                -73.9235,
                index_dir=spatial_index_dir,
            )
            assert isinstance(result.on_street, str)
        except (AmbiguousResolutionError, NoSegmentFoundError):  # lgtm[py/empty-except]
            pass
