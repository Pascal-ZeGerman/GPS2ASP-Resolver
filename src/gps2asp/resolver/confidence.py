"""Confidence scoring for side-of-street determination.

Computes a confidence score (0.0 to 1.0) indicating how reliable the
side-of-street determination is. The score is based on:

1. Perpendicular distance from the street centerline relative to street width:
   The near-centerline guard is width-relative (parking_lane_fraction * width / 2).
   This ensures narrow streets (~30ft residential) are not penalised the same as
   wide avenues (~60ft) — a point 9ft from the centerline on a 30ft street is
   well within the parking lane, not ambiguous.

2. Distance to the nearest intersection: Points near intersections are
   ambiguous because they could belong to either cross street.

Per user decisions (see CONTEXT.md for rationale):
- Near centerline (< effective_width * parking_lane_fraction / 2): confidence = 0.0
- Near intersection (< 30ft, ~10m): confidence = 0.0 (ambiguous)
- Otherwise: combine offset ratio and intersection proximity

Width fallback: When CSCL streetwidth is missing (0 or NaN), the rw_type is used
to look up a NYC-informed default via _NYC_DEFAULT_WIDTHS. Fallback is logged at
DEBUG level only — not surfaced to users.
"""

from __future__ import annotations

import logging
import math

# Named constant for intersection proximity threshold (single source of truth;
# imported by resolver/__init__.py for _classify_ambiguity())
_NEAR_INTERSECTION_THRESHOLD_FT: float = 30.0  # ~10m: block-face ambiguity zone

# Default confidence threshold: 0.33 (lowered for testing — permits PROSPECT PL score of 0.57)
# Rationale: GPS accuracy ~10-16ft, half street width ~15-20ft.
# An offset_ratio > 0.5 means the point is clearly off-center.
# Combined with intersection distance, 0.33 permits scores >= 0.33 while still
# rejecting near-centerline (0.0) and near-intersection (0.0) ambiguous cases.
DEFAULT_CONFIDENCE_THRESHOLD = 0.33

# --- Lane-snap geometry (spike 004a) ------------------------------------------
# Two lane centres sit at c +/- p, where p is the lane half-width. When true curb
# width is unknown, p defaults to ~9.7 ft: half a typical NYC curb-to-curb width
# (~25 ft) minus roughly half a car width. See side-calibration-algorithm.md §3.
DEFAULT_LANE_HALF_P: float = 9.7  # default lane half-width when curb width unknown
HALF_CAR_WIDTH_FT: float = 3.0  # ~half a car width, subtracted from curb-to-curb/2
MIN_LANE_HALF_P: float = 6.0  # floor for p on very narrow streets

# CSCL rw_type -> approximate paved width in feet
# NYC-informed estimates; code constant (not runtime-configurable) per user decision.
# rw_type meanings from CSCL data dictionary (VEHICULAR_RW_TYPES = {1,2,3,4,5})
_NYC_DEFAULT_WIDTHS: dict[int, float] = {
    0: 30.0,  # rw_type missing from CSCL (legacy / under-coded segments) — IN-04
    1: 30.0,  # Street — typical NYC residential/commercial block (~30ft curb-to-curb)
    2: 60.0,  # Highway / expressway (~60ft, multiple lanes)
    3: 60.0,  # Bridge — conservative wide estimate (~60ft deck width)
    4: 30.0,  # Tunnel — conservative fallback (rarely parked on; width uncertain)
    5: 30.0,  # Boardwalk / service road — treated conservatively as street width
}
_DEFAULT_WIDTH_FALLBACK = 30.0  # catch-all for unrecognized rw_types


def resolve_effective_width(
    streetwidth_ft: float,
    rw_type: int,
    segment_id: int | str | None = None,
) -> float:
    """Return effective street width, falling back to rw_type table when CSCL data is missing.

    Logs at DEBUG level when a fallback is used (not surfaced to the user per CONTEXT.md).

    Args:
        streetwidth_ft: Width from CSCL data. May be 0.0 (missing) or NaN (corrupt).
        rw_type: CSCL road type code. Used for fallback width lookup.
        segment_id: Optional CSCL physical segment ID for the candidate. When
            provided, it is included in the fallback debug log so operators
            can trace missing-width records back to the source segment
            (BUG-R-006). Default None preserves the legacy call signature.

    Returns:
        Positive float representing effective street width in feet.
    """
    if streetwidth_ft > 0 and not math.isnan(streetwidth_ft):
        return streetwidth_ft
    fallback = _NYC_DEFAULT_WIDTHS.get(rw_type, _DEFAULT_WIDTH_FALLBACK)
    logging.getLogger(__name__).debug(
        "streetwidth missing (got %s) for rw_type=%d; using fallback=%.0fft (segment_id=%s)",
        streetwidth_ft,
        rw_type,
        fallback,
        segment_id,
    )
    return fallback


def lane_half_from_width(curb_width_ft: float | None) -> float:
    """Derive the lane half-width `p` (feet) from the true curb-to-curb width.

    Two lane centres are placed at `c +/- p` by the lane-snap model
    (spike 004a). `p` is half the curb-to-curb width minus roughly half a car
    width, floored at MIN_LANE_HALF_P so very narrow streets keep a usable band.

    Args:
        curb_width_ft: True curb-to-curb width in feet. When None, <= 0, or NaN
            (curb data missing/complex), the default DEFAULT_LANE_HALF_P is used.

    Returns:
        Lane half-width `p` in feet.
    """
    if curb_width_ft is None or curb_width_ft <= 0 or math.isnan(curb_width_ft):
        return DEFAULT_LANE_HALF_P
    return max(curb_width_ft / 2.0 - HALF_CAR_WIDTH_FT, MIN_LANE_HALF_P)


def compute_confidence(
    perp_distance_ft: float,
    effective_width_ft: float,
    distance_to_nearest_intersection_ft: float,
    parking_lane_fraction: float = 0.33,
) -> float:
    """Compute confidence score for side-of-street determination.

    The confidence is a product of two factors:
    - Distance-based: How far off-center the point is (offset_ratio)
    - Intersection proximity: How far from the nearest intersection

    The near-centerline guard is width-relative: points within
    (effective_width_ft * parking_lane_fraction / 2) feet of the centerline
    are considered ambiguous (could be either lane or the center of the road).

    Returns 0.0 for clearly ambiguous cases (near centerline or intersection).

    Args:
        perp_distance_ft: Perpendicular distance from the point to the
            street centerline in feet.
        effective_width_ft: Effective street width in feet, already resolved
            by the caller via resolve_effective_width(). Typical NYC values:
            25-60 feet.
        distance_to_nearest_intersection_ft: Distance from the point to the
            nearest segment endpoint (intersection) in feet.
        parking_lane_fraction: Fraction of street width considered the
            near-centerline ambiguous zone. Default 0.33 means the inner 33%
            of the road (between the travel lanes) returns confidence=0.0.
            Threshold = effective_width_ft * parking_lane_fraction / 2.

    Returns:
        Confidence score from 0.0 (ambiguous) to 1.0 (certain).
    """
    effective_width = effective_width_ft

    # Near centerline: within the central travel-lane zone, could be either side
    near_center_threshold = effective_width * parking_lane_fraction / 2.0
    if perp_distance_ft < near_center_threshold:
        return 0.0

    # Near intersection: within ~10m = ~30ft, block face is ambiguous
    if distance_to_nearest_intersection_ft < _NEAR_INTERSECTION_THRESHOLD_FT:
        return 0.0

    # Distance-based confidence: how far off-center as fraction of half-width
    half_width = effective_width / 2.0
    offset_ratio = perp_distance_ft / half_width
    distance_conf = min(1.0, offset_ratio)

    # Intersection proximity factor: scales from 0.3 at _NEAR_INTERSECTION_THRESHOLD_FT (30ft) to 1.0 at 100ft
    intersection_conf = min(1.0, distance_to_nearest_intersection_ft / 100.0)

    return distance_conf * intersection_conf


def is_confident(
    confidence: float,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> bool:
    """Check if a confidence score exceeds the threshold.

    Args:
        confidence: The computed confidence score (0.0 to 1.0).
        threshold: The minimum acceptable confidence (default 0.33).

    Returns:
        True if confidence >= threshold, False otherwise.
    """
    return confidence >= threshold
