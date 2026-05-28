"""Tests for side-of-street determination."""

import pytest
from shapely.geometry import LineString

from gps2asp.resolver.side_resolver import (
    compute_distance_to_endpoints,
    compute_perpendicular_distance,
    determine_side,
)


class TestDetermineSide:
    """Test cross-product based side-of-street determination."""

    def test_east_west_segment_point_north(self):
        """Point above an East-West segment should return 'N'."""
        segment = LineString([(0, 0), (100, 0)])
        result = determine_side(50, 10, segment, nominaldir="E")
        assert result == "N"

    def test_east_west_segment_point_south(self):
        """Point below an East-West segment should return 'S'."""
        segment = LineString([(0, 0), (100, 0)])
        result = determine_side(50, -10, segment, nominaldir="E")
        assert result == "S"

    def test_north_south_segment_point_east(self):
        """Point to the right of a North-South segment should return 'E'."""
        segment = LineString([(0, 0), (0, 100)])
        result = determine_side(10, 50, segment, nominaldir="N")
        assert result == "E"

    def test_north_south_segment_point_west(self):
        """Point to the left of a North-South segment should return 'W'."""
        segment = LineString([(0, 0), (0, 100)])
        result = determine_side(-10, 50, segment, nominaldir="N")
        assert result == "W"

    def test_diagonal_segment_ne(self):
        """Test with a ~45-degree NE diagonal segment.
        A segment from (0,0) to (100,100) runs at 45 degrees (NE).
        45 degrees falls in the North-running quadrant (45-135),
        so left=W, right=E.
        Point at (-10, 50) is to the left (west) -> 'W'.
        Point at (60, 50) is to the right (east) -> 'E'."""
        segment = LineString([(0, 0), (100, 100)])
        # Point northwest of the midpoint (to the left of NE direction)
        result_left = determine_side(40, 60, segment, nominaldir="NE")
        assert result_left == "W"
        # Point southeast of the midpoint (to the right of NE direction)
        result_right = determine_side(60, 40, segment, nominaldir="NE")
        assert result_right == "E"

    def test_west_running_segment(self):
        """West-running segment: left=S, right=N."""
        segment = LineString([(100, 0), (0, 0)])
        # Point above (which is to the RIGHT of west direction)
        result = determine_side(50, 10, segment, nominaldir="W")
        assert result == "N"
        # Point below (which is to the LEFT of west direction)
        result = determine_side(50, -10, segment, nominaldir="W")
        assert result == "S"

    def test_south_running_segment(self):
        """South-running segment: left=E, right=W."""
        segment = LineString([(0, 100), (0, 0)])
        # Point to the right (which is to the LEFT of south direction)
        result = determine_side(10, 50, segment, nominaldir="S")
        assert result == "E"
        # Point to the left (which is to the RIGHT of south direction)
        result = determine_side(-10, 50, segment, nominaldir="S")
        assert result == "W"

    def test_curved_segment(self):
        """Test with a curved segment to verify local direction vector is used."""
        # A segment that curves: starts going east, then turns north
        segment = LineString([(0, 0), (50, 0), (50, 50)])
        # Point near the east-running part, above the line -> N
        result = determine_side(25, 10, segment, nominaldir="E")
        assert result == "N"
        # Point near the north-running part, to the right -> E
        result = determine_side(60, 25, segment, nominaldir="N")
        assert result == "E"


class TestPerpendicularDistance:
    """Test perpendicular distance computation."""

    def test_perpendicular_to_ew_segment(self):
        """Point at (50, 15) from E-W segment (0,0)-(100,0) should be 15.0 feet."""
        segment = LineString([(0, 0), (100, 0)])
        dist = compute_perpendicular_distance(50, 15, segment)
        assert abs(dist - 15.0) < 0.001

    def test_point_on_segment(self):
        """Point on the segment should have distance 0."""
        segment = LineString([(0, 0), (100, 0)])
        dist = compute_perpendicular_distance(50, 0, segment)
        assert abs(dist) < 0.001

    def test_perpendicular_to_ns_segment(self):
        """Point at (20, 50) from N-S segment (0,0)-(0,100) should be 20.0 feet."""
        segment = LineString([(0, 0), (0, 100)])
        dist = compute_perpendicular_distance(20, 50, segment)
        assert abs(dist - 20.0) < 0.001

    def test_diagonal_distance(self):
        """Point at (10, 10) from E-W segment at y=0 should be 10.0 feet
        (closest point is at (10, 0))."""
        segment = LineString([(0, 0), (100, 0)])
        dist = compute_perpendicular_distance(10, 10, segment)
        assert abs(dist - 10.0) < 0.001


class TestDistanceToEndpoints:
    """Test distance to segment endpoints (for intersection proximity)."""

    def test_near_start_point(self):
        """Point at (5, 0) near segment (0,0)-(100,0) should return ~5.0 feet."""
        segment = LineString([(0, 0), (100, 0)])
        dist = compute_distance_to_endpoints(5, 0, segment)
        assert abs(dist - 5.0) < 0.001

    def test_near_end_point(self):
        """Point at (95, 0) near segment (0,0)-(100,0) should return ~5.0 feet."""
        segment = LineString([(0, 0), (100, 0)])
        dist = compute_distance_to_endpoints(95, 0, segment)
        assert abs(dist - 5.0) < 0.001

    def test_midpoint(self):
        """Point at midpoint should be equidistant to both endpoints."""
        segment = LineString([(0, 0), (100, 0)])
        dist = compute_distance_to_endpoints(50, 0, segment)
        assert abs(dist - 50.0) < 0.001

    def test_offset_near_start(self):
        """Point at (3, 4) near start (0,0) should return 5.0 feet (3-4-5 triangle)."""
        segment = LineString([(0, 0), (100, 0)])
        dist = compute_distance_to_endpoints(3, 4, segment)
        assert abs(dist - 5.0) < 0.001


# =====================================================================
# BUG-R-004 regression test (Phase 35.1-02, RED -> GREEN)
# =====================================================================


class TestZeroLengthSegment:
    """BUG-R-004: zero-length segments must raise, not silently return 'S'."""

    def test_zero_length_segment_raises_value_error(self):
        """Degenerate zero-length LineString must raise ValueError, not return 'S'."""
        seg = LineString([(100, 200), (100, 200)])

        with pytest.raises(ValueError, match="zero-length"):
            determine_side(100.0, 200.0, seg, "NS")

    def test_normal_segment_still_returns_side(self):
        """Sanity: the happy path must continue to work after the zero-length guard."""
        seg = LineString([(100, 200), (200, 200)])
        result = determine_side(150.0, 210.0, seg, "EW")
        assert result in ("N", "S", "E", "W")
