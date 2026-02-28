"""GPS2ASP resolver public API.

Provides three entry points for GPS-to-street resolution:

- resolve(lat, lon): High-level async API. Takes WGS84 GPS coordinates,
  returns a ResolutionResult with street segment and side.
- convert(lat, lon): Synchronous coordinate conversion. WGS84 to State Plane.
- resolve_segment(x, y): Low-level async API. Takes State Plane coordinates
  directly (skip conversion step).

Usage:
    from gps2asp.resolver import resolve, convert, resolve_segment

    # High-level (most common)
    result = await resolve(40.6778, -73.9690)
    print(result.on_street, result.side_of_street)

    # Two-step pipeline (for advanced use / testing)
    x, y = convert(40.6778, -73.9690)
    result = await resolve_segment(x, y)
"""

from __future__ import annotations

from gps2asp.resolver.confidence import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    compute_confidence,
    is_confident,
    resolve_effective_width,
)
from gps2asp.resolver.converter import convert
from gps2asp.resolver.exceptions import (
    AmbiguousResolutionError,
    NoSegmentFoundError,
    OutsideNYCError,
    ResolutionError,
)
from gps2asp.resolver.logging import log_resolution
from gps2asp.resolver.models import (
    ResolutionDebugInfo,
    ResolutionResult,
    SegmentCandidate,
)
from gps2asp.resolver.side_resolver import (
    compute_distance_to_endpoints,
    compute_perpendicular_distance,
    determine_side,
)
from gps2asp.resolver.spatial_index import SpatialIndex

__all__ = [
    "resolve",
    "convert",
    "resolve_segment",
    "ResolutionResult",
    "ResolutionError",
    "OutsideNYCError",
    "NoSegmentFoundError",
    "AmbiguousResolutionError",
]


async def resolve(
    lat: float,
    lon: float,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    index_dir: str | None = None,
    parking_lane_fraction: float = 0.33,
) -> ResolutionResult:
    """Resolve GPS coordinates to a street segment and side of street.

    This is the high-level API that runs the full pipeline:
    1. Convert WGS84 (lat, lon) to NY State Plane (x, y)
    2. Query the spatial index for nearest street segments
    3. Determine which side of the street (N/S/E/W)
    4. Compute confidence score
    5. Return result or raise if ambiguous

    Every resolution attempt is logged as JSON at DEBUG level, regardless
    of outcome, for threshold calibration.

    Args:
        lat: Latitude in WGS84 (e.g., 40.6778).
        lon: Longitude in WGS84 (e.g., -73.9690).
        confidence_threshold: Minimum confidence to accept (default 0.33).
        index_dir: Optional path to the spatial index directory.
        parking_lane_fraction: Fraction of street width considered the
            near-centerline ambiguous zone (default 0.33). Points within
            (effective_width * parking_lane_fraction / 2) feet of center
            return confidence=0.0.

    Returns:
        ResolutionResult with on_street, from_street, to_street,
        side_of_street, confidence, and has_asp.

    Raises:
        OutsideNYCError: Coordinates outside NYC bounding box.
        NoSegmentFoundError: No street segment within 164ft (~50m).
        AmbiguousResolutionError: Confidence below threshold (near
            centerline, intersection, etc.).
        IndexNotFoundError: Spatial index files not found on disk.
    """
    # Step 1: Convert coordinates
    x, y = convert(lat, lon)

    # Step 2-5: Delegate to resolve_segment
    return await resolve_segment(
        x, y,
        confidence_threshold=confidence_threshold,
        index_dir=index_dir,
        parking_lane_fraction=parking_lane_fraction,
        _input_lat=lat,
        _input_lon=lon,
    )


async def resolve_segment(
    x: float,
    y: float,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    index_dir: str | None = None,
    parking_lane_fraction: float = 0.33,
    _input_lat: float | None = None,
    _input_lon: float | None = None,
) -> ResolutionResult:
    """Resolve State Plane coordinates to a street segment and side.

    Same as resolve() but takes State Plane coordinates directly,
    skipping the WGS84-to-State-Plane conversion step. For advanced
    users who already have State Plane coordinates.

    Args:
        x: State Plane X coordinate (US survey feet).
        y: State Plane Y coordinate (US survey feet).
        confidence_threshold: Minimum confidence to accept (default 0.33).
        index_dir: Optional path to the spatial index directory.
        parking_lane_fraction: Fraction of street width considered the
            near-centerline ambiguous zone (default 0.33). Passed through
            to compute_confidence().
        _input_lat: Original latitude (for debug logging, internal use).
        _input_lon: Original longitude (for debug logging, internal use).

    Returns:
        ResolutionResult with street segment and side information.

    Raises:
        NoSegmentFoundError: No street segment within 164ft (~50m).
        AmbiguousResolutionError: Confidence below threshold.
        IndexNotFoundError: Spatial index files not found on disk.
    """
    input_lat = _input_lat if _input_lat is not None else 0.0
    input_lon = _input_lon if _input_lon is not None else 0.0

    # Initialize debug info for logging
    debug_info = ResolutionDebugInfo(
        input_lat=input_lat,
        input_lon=input_lon,
        state_plane_x=x,
        state_plane_y=y,
    )

    try:
        # Step 2: Query spatial index for nearest segments
        idx = await SpatialIndex.get(index_dir=index_dir)
        candidates = idx.nearest(x, y)

        # Build candidate list for debug info
        candidate_summaries = [
            {
                "segment_id": c.segment_id,
                "street": c.full_street_name,
                "distance_ft": round(c.distance_ft, 2),
            }
            for c in candidates
        ]

        # Select the best candidate (closest)
        best = candidates[0]

        # Step 3: Compute geometry metrics
        perp_distance = compute_perpendicular_distance(x, y, best.geometry)
        dist_to_endpoints = compute_distance_to_endpoints(x, y, best.geometry)

        # Step 4: Determine side of street
        side = determine_side(x, y, best.geometry, best.nominaldir)

        # Step 5: Compute effective width (post-fallback) and confidence
        effective_width = resolve_effective_width(best.streetwidth, best.rw_type)
        confidence = compute_confidence(
            perp_distance_ft=perp_distance,
            street_width_ft=best.streetwidth,
            distance_to_nearest_intersection_ft=dist_to_endpoints,
            rw_type=best.rw_type,
            parking_lane_fraction=parking_lane_fraction,
        )

        # Update debug info with results
        debug_info = ResolutionDebugInfo(
            input_lat=input_lat,
            input_lon=input_lon,
            state_plane_x=x,
            state_plane_y=y,
            candidates=candidate_summaries,
            selected_segment_id=best.segment_id,
            perpendicular_distance_ft=round(perp_distance, 2),
            confidence=round(confidence, 4),
            side=side,
            outcome=(
                "resolved" if is_confident(confidence, confidence_threshold)
                else _classify_ambiguity(perp_distance, dist_to_endpoints)
            ),
            street_width_ft=effective_width,
        )

        # Log every attempt
        log_resolution(debug_info)

        # Check confidence threshold
        if not is_confident(confidence, confidence_threshold):
            raise AmbiguousResolutionError(
                message=(
                    f"Resolution confidence {confidence:.2f} is below "
                    f"threshold {confidence_threshold:.2f} for segment "
                    f"{best.full_street_name} "
                    f"(street_width={effective_width:.0f}ft, "
                    f"perp_dist={perp_distance:.1f}ft, "
                    f"endpoint_dist={dist_to_endpoints:.1f}ft)"
                ),
                debug_info=debug_info,
                confidence=confidence,
            )

        # Determine has_asp based on side. Both left/right are flagged
        # conservatively (if any ASP sign exists on the segment, both are True).
        has_asp = best.has_asp_left or best.has_asp_right

        return ResolutionResult(
            on_street=best.full_street_name,
            from_street=best.from_street,
            to_street=best.to_street,
            side_of_street=side,
            confidence=round(confidence, 4),
            has_asp=has_asp,
        )

    except (NoSegmentFoundError, AmbiguousResolutionError):
        # Re-raise known resolution errors after logging
        raise

    except Exception as e:
        # Log unexpected errors and re-raise
        debug_info = ResolutionDebugInfo(
            input_lat=input_lat,
            input_lon=input_lon,
            state_plane_x=x,
            state_plane_y=y,
            outcome=f"error: {type(e).__name__}: {e}",
        )
        log_resolution(debug_info)
        raise


def _classify_ambiguity(perp_distance: float, dist_to_endpoints: float) -> str:
    """Classify the type of ambiguity for debug logging.

    The 10ft check here is a rough heuristic for log classification only —
    it is NOT the confidence algorithm threshold (which is width-relative).
    Width-relative classification would require passing effective_width; a
    static 10ft approximation is sufficient for debug log labels.

    Args:
        perp_distance: Perpendicular distance to centerline in feet.
        dist_to_endpoints: Distance to nearest endpoint in feet.

    Returns:
        String describing the ambiguity type.
    """
    if perp_distance < 10.0:
        return "ambiguous_centerline"
    if dist_to_endpoints < 30.0:
        return "ambiguous_intersection"
    return "ambiguous_low_confidence"
