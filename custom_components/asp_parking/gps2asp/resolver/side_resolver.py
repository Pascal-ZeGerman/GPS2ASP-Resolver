"""Side-of-street determination using cross-product geometry.

Determines which compass side (N/S/E/W) of a street centerline a GPS point
falls on. Uses the 2D cross product of the segment direction vector and the
point-to-segment vector to determine left/right, then maps to compass
direction based on the segment's actual geometric angle.

This approach handles curved blocks correctly by computing the local direction
vector at the projection point (using a small epsilon), rather than using
the segment endpoints.
"""

from __future__ import annotations

import math
from typing import Literal

from shapely.geometry import LineString, Point


def determine_side(
    point_x: float,
    point_y: float,
    segment: LineString,
    nominaldir: str,
) -> Literal["N", "S", "E", "W"]:
    """Determine the compass side (N/S/E/W) of a point relative to a street segment.

    Algorithm:
    1. Project the point onto the segment to find the nearest point on the line.
    2. Compute the local direction vector at the projection point using a small
       epsilon (handles curved blocks correctly).
    3. Compute the 2D cross product of (direction vector) x (point vector).
       Positive = point is to the LEFT of the directed segment.
       Negative = point is to the RIGHT.
    4. Map left/right to compass direction based on the segment's actual angle:
       - East-running (315-45 deg): left=N, right=S
       - North-running (45-135 deg): left=W, right=E
       - West-running (135-225 deg): left=S, right=N
       - South-running (225-315 deg): left=E, right=W

    Args:
        point_x: State Plane X coordinate of the GPS point (feet).
        point_y: State Plane Y coordinate of the GPS point (feet).
        segment: Shapely LineString of the street centerline (State Plane).
        nominaldir: Nominal compass direction from CSCL data (used as hint,
            but geometry is authoritative for angle computation).

    Returns:
        Compass direction side: "N", "S", "E", or "W".
    """
    point = Point(point_x, point_y)

    # Project point onto segment to find the closest point on the line
    dist_along = segment.project(point)
    nearest_pt = segment.interpolate(dist_along)

    # Compute local direction vector using small epsilon around projection point.
    # This handles curved segments correctly -- we use the local tangent direction,
    # not the endpoint-to-endpoint direction.
    length = segment.length
    eps = min(1.0, length * 0.01)  # 1% of length or 1 foot, whichever is smaller
    p1 = segment.interpolate(max(0.0, dist_along - eps))
    p2 = segment.interpolate(min(length, dist_along + eps))

    # Direction vector of the segment at this point
    dx = p2.x - p1.x
    dy = p2.y - p1.y

    # Vector from nearest point on segment to the GPS point
    px = point_x - nearest_pt.x
    py = point_y - nearest_pt.y

    # 2D cross product: positive = left of direction, negative = right
    cross = dx * py - dy * px

    # Compute segment angle in degrees (0=East, 90=North, 180=West, 270=South)
    angle = math.degrees(math.atan2(dy, dx)) % 360

    # Map cross product sign to compass direction based on segment orientation
    if 315 <= angle or angle < 45:
        # Segment runs roughly East: left=N, right=S
        return "N" if cross > 0 else "S"
    elif angle < 135:
        # Segment runs roughly North: left=W, right=E
        return "W" if cross > 0 else "E"
    elif angle < 225:
        # Segment runs roughly West: left=S, right=N
        return "S" if cross > 0 else "N"
    else:  # 225 <= angle < 315
        # Segment runs roughly South: left=E, right=W
        return "E" if cross > 0 else "W"


def compute_perpendicular_distance(
    point_x: float,
    point_y: float,
    segment: LineString,
) -> float:
    """Compute the perpendicular distance from a point to a segment centerline.

    Uses Shapely's distance computation which handles curved linestrings
    correctly (finds the true closest point, not just the distance to a
    straight line between endpoints).

    Args:
        point_x: State Plane X coordinate (feet).
        point_y: State Plane Y coordinate (feet).
        segment: Shapely LineString of the street centerline.

    Returns:
        Distance in feet from the point to the nearest point on the segment.
    """
    point = Point(point_x, point_y)
    return point.distance(segment)


def compute_distance_to_endpoints(
    point_x: float,
    point_y: float,
    segment: LineString,
) -> float:
    """Compute the minimum distance from a point to either endpoint of a segment.

    Used for intersection proximity detection: if the point is near an endpoint,
    it's likely near an intersection and the resolution is ambiguous.

    Args:
        point_x: State Plane X coordinate (feet).
        point_y: State Plane Y coordinate (feet).
        segment: Shapely LineString of the street centerline.

    Returns:
        Minimum distance in feet to either the start or end point of the segment.
    """
    point = Point(point_x, point_y)
    coords = list(segment.coords)
    start = Point(coords[0])
    end = Point(coords[-1])
    return min(point.distance(start), point.distance(end))
