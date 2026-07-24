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

from .confidence import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    _NEAR_INTERSECTION_THRESHOLD_FT,
    compute_lane_snap_confidence,
    is_confident,
    lane_half_from_width,
    resolve_effective_width,
)
from .converter import convert
from .exceptions import (
    AmbiguousResolutionError,
    NoSegmentFoundError,
    OutsideNYCError,
    ResolutionError,
)
from .logging import log_resolution
from .models import (
    ResolutionDebugInfo,
    ResolutionResult,
    SegmentCandidate,
)
from .side_resolver import (
    compute_distance_to_endpoints,
    compute_perpendicular_distance,
    determine_side,
    signed_offset,
)
from .spatial_index import SpatialIndex

__all__ = [
    "resolve",
    "convert",
    "resolve_segment",
    "ResolutionResult",
    "ResolutionDebugInfo",
    "SegmentCandidate",
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
    learned_center_offset: float | None = None,
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
        parking_lane_fraction: Retained for backward-compatible API shape only.
            The lane-snap confidence model (40-06) judges plausibility relative
            to the fitted centre ``c`` and no longer uses a width-relative
            near-centerline zone, so this argument is now inert. Kept in the
            signature so existing callers do not break.
        learned_center_offset: Optional parking-history cluster-mean centre
            offset ``c`` (feet) used as fallback TIER 2 when the matched segment
            is NOT curb-calibrated. Ignored for calibrated segments (curb ``c``
            wins) and defaults to plain CSCL (``c=0``) when None. See the SC-4
            fallback chain in resolve_segment().

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
        x,
        y,
        confidence_threshold=confidence_threshold,
        index_dir=index_dir,
        parking_lane_fraction=parking_lane_fraction,
        input_lat=lat,
        input_lon=lon,
        learned_center_offset=learned_center_offset,
    )


async def resolve_segment(
    x: float,
    y: float,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    index_dir: str | None = None,
    parking_lane_fraction: float = 0.33,
    input_lat: float | None = None,
    input_lon: float | None = None,
    learned_center_offset: float | None = None,
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
        parking_lane_fraction: Retained for backward-compatible API shape only.
            The lane-snap confidence model (40-06) judges plausibility relative
            to the fitted centre ``c`` and no longer uses a width-relative
            near-centerline zone, so this argument is now inert. Kept in the
            signature so existing callers do not break.
        input_lat: Original latitude (for debug logging). Pass when calling
            from resolve() or the pipeline so logs contain GPS coordinates.
        input_lon: Original longitude (for debug logging).
        learned_center_offset: Optional parking-history cluster-mean centre
            offset ``c`` (feet), used as fallback TIER 2 of the SC-4 chain
            (curb ``c`` -> learned ``c`` -> 0). Consulted ONLY when the matched
            candidate is non-calibrated; ignored when the candidate is
            curb-calibrated (its own ``center_offset_c`` wins). None -> plain
            CSCL (``c=0``). Supplying it is a follow-on integration: the
            collection/persistence of per-segment settled offsets is out of
            scope for this plan (only the estimator unit exists, 40-03).

    Returns:
        ResolutionResult with street segment and side information.

    Raises:
        NoSegmentFoundError: No street segment within 164ft (~50m).
        AmbiguousResolutionError: Confidence below threshold.
        IndexNotFoundError: Spatial index files not found on disk.
    """
    input_lat = input_lat if input_lat is not None else 0.0
    input_lon = input_lon if input_lon is not None else 0.0

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
        # Signed perpendicular offset (+ve = LEFT/N of the directed segment).
        # Same primitive the N/S split and the lane-snap model both consume, so
        # the boundary and the confidence agree by construction.
        so = signed_offset(x, y, best.geometry)

        # Resolve the fitted road centre `c` via the SC-4 fallback chain:
        #   TIER 1  curb-calibrated segment -> its index-derived center_offset_c
        #   TIER 2  else a learned parking-history cluster-mean (when supplied)
        #   TIER 3  else plain CSCL (c=0) -- production-equivalent to today.
        # `calibrated` is the single authoritative gate (40-04): a non-calibrated
        # candidate is never silently miscalibrated.
        if best.calibrated:
            c = best.center_offset_c
        elif learned_center_offset is not None:
            c = learned_center_offset
        else:
            c = 0.0

        # Lane half-width `p`: derived from the true curb width only for a
        # calibrated candidate; otherwise the default lane half (via None).
        p = lane_half_from_width(best.curb_width_ft if best.calibrated else None)

        # Effective width is retained purely for the debug record /
        # ResolutionResult.street_width_ft (unchanged); the confidence model no
        # longer uses it.
        effective_width = resolve_effective_width(
            best.streetwidth, best.rw_type, segment_id=best.segment_id
        )

        # Step 4: Lane-snap confidence with an UPPER plausibility bound judged
        # relative to `c` (not 0). A fix more than one lane-width outside the
        # nearer lane centre scores 0.0 -- this is the SC-3 fix for the
        # confidence-1.0-at-89ft defect.
        # BUG-R-003: side determination is meaningless at zero confidence
        # (implausible or near-intersection). Defer determine_side until after
        # the confidence gate so we don't compute (and log) a misleading side.
        confidence = compute_lane_snap_confidence(
            signed_offset_ft=so,
            center_offset_c=c,
            lane_half_p=p,
            distance_to_nearest_intersection_ft=dist_to_endpoints,
        )

        # Step 5: Determine side of street only when confidence will be
        # accepted; otherwise leave side=None in the debug record (BUG-R-003).
        # The N/S boundary splits at the fitted centre `c` (SC-2), not 0.
        side: str | None
        if is_confident(confidence, confidence_threshold):
            side = determine_side(x, y, best.geometry, best.nominaldir, center_offset=c)
        else:
            side = None

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
                "resolved"
                if is_confident(confidence, confidence_threshold)
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

        # BUG-R-002: has_asp reflects either side (conservative OR).
        # The spatial index stores identical values for has_asp_left and
        # has_asp_right because _check_has_asp() sets both to the same
        # boolean; a compass→left/right mapping would require knowing the
        # segment bearing and is not reliable without per-side index data.
        assert (  # nosec B101
            side is not None
        )  # guaranteed: AmbiguousResolutionError raised above when not is_confident
        has_asp = best.has_asp_left or best.has_asp_right

        return ResolutionResult(
            on_street=best.full_street_name,
            from_street=best.from_street,
            to_street=best.to_street,
            side_of_street=side,
            confidence=round(confidence, 4),
            has_asp=has_asp,
            borocode=best.borocode,
            perpendicular_distance_ft=round(perp_distance, 2),
            street_width_ft=effective_width,
            segment_id=best.segment_id,
        )

    except (NoSegmentFoundError, AmbiguousResolutionError):
        # Re-raise known resolution errors after logging
        raise

    except Exception as e:
        # Log and re-raise unexpected errors (e.g., IndexNotFoundError, shapely errors).
        # NoSegmentFoundError and AmbiguousResolutionError are handled above.
        # Exception excludes BaseException subclasses (KeyboardInterrupt, SystemExit).
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

    BUG-R-001: The 10ft check here is a rough width-relative approximation,
    used purely for log classification — it is NOT the confidence algorithm
    threshold. The real threshold lives in compute_confidence() and is
    width-relative: ``effective_width * parking_lane_fraction / 2``. For a
    typical NYC 30ft residential street with parking_lane_fraction=0.33,
    that evaluates to ~4.95ft, while a 60ft avenue produces ~9.9ft — both
    approximated here by the static 10ft constant for log labelling.
    Width-relative classification at this call-site would require passing
    effective_width through the debug pipeline; the static approximation
    keeps the log-label boundary stable without coupling _classify_ambiguity
    to the confidence-scoring API.

    IN-01: the static 10ft threshold here is for **log classification only**;
    it does not match the width-relative algorithm threshold and may
    produce labels that diverge by up to ~1 ft at the boundary. For
    example, a 9.9ft perpendicular distance on a wide 60ft avenue is
    *not ambiguous* to the algorithm (algorithm threshold ~9.9ft) but
    is still classified ``ambiguous_low_confidence`` by this function
    because 9.9 > 10.0 is false. This off-by-one discrepancy is
    acceptable for log-labelling purposes — the algorithm's decision is
    authoritative, and the log label is a human-readable hint only.

    Args:
        perp_distance: Perpendicular distance to centerline in feet.
        dist_to_endpoints: Distance to nearest endpoint in feet.

    Returns:
        String describing the ambiguity type.
    """
    if perp_distance < 10.0:
        return "ambiguous_centerline"
    if dist_to_endpoints < _NEAR_INTERSECTION_THRESHOLD_FT:
        return "ambiguous_intersection"
    return "ambiguous_low_confidence"
