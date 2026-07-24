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


def signed_offset(
    point_x: float,
    point_y: float,
    segment: LineString,
) -> float:
    """Perpendicular signed distance (feet) from a point to a directed segment.

    Uses the SAME projection + local-tangent-epsilon logic as
    :func:`determine_side`, then normalises the cross product by the direction
    vector's magnitude so the result is an actual distance in feet rather than a
    raw (unnormalised) cross product.

    The sign convention matches ``determine_side``'s internal cross product:
    positive = the point lies to the LEFT of the directed segment (= North for
    an East-running block). This is the reusable geometry primitive shared by the
    confidence model (40-02/40-06) and the build-time curb core (40-05).

    Args:
        point_x: State Plane X coordinate of the point (feet).
        point_y: State Plane Y coordinate of the point (feet).
        segment: Shapely LineString of the street centerline (State Plane).

    Returns:
        Signed perpendicular distance in feet. ``+ve`` = LEFT/North of the
        directed segment, ``-ve`` = RIGHT/South.

    Raises:
        ValueError: If ``segment`` is a zero-length LineString (degenerate
            geometry); mirrors ``determine_side``'s BUG-R-004 hard-fail rather
            than silently returning 0.0.
    """
    point = Point(point_x, point_y)

    # Project point onto segment to find the closest point on the line.
    dist_along = segment.project(point)
    nearest_pt = segment.interpolate(dist_along)

    length = segment.length
    if length == 0.0:
        raise ValueError(
            f"signed_offset received zero-length segment at point "
            f"({point_x}, {point_y}); cannot determine offset without "
            f"direction vector (BUG-R-004)"
        )

    # Local direction vector using a small epsilon around the projection point
    # (handles curved segments -- local tangent, not endpoint-to-endpoint).
    eps = min(1.0, length * 0.01)  # 1% of length or 1 foot, whichever is smaller
    p1 = segment.interpolate(max(0.0, dist_along - eps))
    p2 = segment.interpolate(min(length, dist_along + eps))

    dx = p2.x - p1.x
    dy = p2.y - p1.y
    n = math.hypot(dx, dy) or 1.0

    # Normalised cross product: (dir_hat) x (point - nearest). +ve = LEFT.
    return (dx / n) * (point_y - nearest_pt.y) - (dy / n) * (point_x - nearest_pt.x)


def determine_side(
    point_x: float,
    point_y: float,
    segment: LineString,
    nominaldir: str,
    *,
    center_offset: float = 0.0,
) -> Literal["N", "S", "E", "W"]:
    """Determine the compass side (N/S/E/W) of a point relative to a street segment.

    Algorithm:
    1. Compute the perpendicular signed distance from the point to the directed
       segment via :func:`signed_offset` (+ve = LEFT of the directed segment).
    2. The point is on the LEFT of the *fitted road centre* when its signed
       offset exceeds ``center_offset`` (the fitted centre ``c``), rather than
       simply exceeding 0. This is the SC-2 boundary move: the CSCL centerline
       sits a median ~2 ft off the true road centre, so splitting at 0 mis-assigns
       one side; splitting at ``c`` restores the margin.
    3. Map left/right to compass direction based on the segment's actual angle:
       - East-running (315-45 deg): left=N, right=S
       - North-running (45-135 deg): left=W, right=E
       - West-running (135-225 deg): left=S, right=N
       - South-running (225-315 deg): left=E, right=W

    Args:
        point_x: State Plane X coordinate of the GPS point (feet).
        point_y: State Plane Y coordinate of the GPS point (feet).
        segment: Shapely LineString of the street centerline (State Plane).
        nominaldir: Nominal compass direction from CSCL data. Currently not used
            in the computation — the geometry offset is the sole determinant.
            The parameter is retained in the signature for future use as a tiebreaker.
        center_offset: Keyword-only. The fitted road centre ``c`` (signed feet,
            +ve = LEFT/N) that the N/S decision splits on. The default ``0.0``
            reproduces the CSCL-centerline behaviour exactly (a behavioural no-op
            for non-calibrated segments); calibrated segments pass their
            index-derived ``c`` here (wired in 40-06).

    Returns:
        Compass direction side: "N", "S", "E", or "W".

    Raises:
        ValueError: If ``segment`` is a zero-length LineString (degenerate
            geometry). Pre-fix code silently returned "S" because the cross
            product collapsed to zero (BUG-R-004). Callers must filter
            zero-length segments upstream or treat the raise as a hard
            data-integrity signal.
    """
    _ = nominaldir  # not currently used; geometry offset is sole determinant

    # Perpendicular signed distance (+ve = LEFT of the directed segment). This
    # raises ValueError on a zero-length segment (BUG-R-004 hard-fail preserved).
    offset = signed_offset(point_x, point_y, segment)

    # Local direction vector (for the compass-quadrant mapping only). Reuses the
    # same projection + local-tangent-epsilon logic as signed_offset.
    length = segment.length
    dist_along = segment.project(Point(point_x, point_y))
    eps = min(1.0, length * 0.01)  # 1% of length or 1 foot, whichever is smaller
    p1 = segment.interpolate(max(0.0, dist_along - eps))
    p2 = segment.interpolate(min(length, dist_along + eps))
    dx = p2.x - p1.x
    dy = p2.y - p1.y

    # Split at the fitted road centre `c` (center_offset), not at 0. With the
    # default center_offset=0.0 this is byte-identical to the legacy `cross > 0`.
    is_left = offset > center_offset

    # Compute segment angle in degrees (0=East, 90=North, 180=West, 270=South)
    angle = math.degrees(math.atan2(dy, dx)) % 360

    # Map left/right to compass direction based on segment orientation.
    # offset == center_offset: point is exactly on the fitted centre; side is
    # arbitrary here. The caller's confidence scoring returns 0.0 in this case
    # and raises AmbiguousResolutionError upstream, so this code path is not
    # reachable in normal operation.
    if 315 <= angle or angle < 45:
        # Segment runs roughly East: left=N, right=S
        return "N" if is_left else "S"
    elif angle < 135:
        # Segment runs roughly North: left=W, right=E
        return "W" if is_left else "E"
    elif angle < 225:
        # Segment runs roughly West: left=S, right=N
        return "S" if is_left else "N"
    else:  # 225 <= angle < 315
        # Segment runs roughly South: left=E, right=W
        return "E" if is_left else "W"


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
