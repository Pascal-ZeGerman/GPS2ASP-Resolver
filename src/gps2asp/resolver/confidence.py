"""Confidence scoring for side-of-street determination.

Computes a confidence score (0.0 to 1.0) indicating how reliable the
side-of-street determination is. The score is based on:

1. Perpendicular distance from the street centerline relative to street width:
   Further from center = more confident the GPS point is truly on one side.

2. Distance to the nearest intersection: Points near intersections are
   ambiguous because they could belong to either cross street.

Per user decisions:
- Near centerline (<10ft, within GPS error): confidence = 0.0 (ambiguous)
- Near intersection (<30ft, ~10m): confidence = 0.0 (ambiguous)
- Otherwise: combine offset ratio and intersection proximity
"""

from __future__ import annotations

# Default confidence threshold: 0.6
# Rationale: GPS accuracy ~10-16ft, half street width ~15-20ft.
# An offset_ratio > 0.5 means the point is clearly off-center.
# Combined with intersection distance, 0.6 provides good balance
# between false negatives (rejecting correct resolutions) and
# false positives (accepting incorrect side determinations).
DEFAULT_CONFIDENCE_THRESHOLD = 0.6


def compute_confidence(
    perp_distance_ft: float,
    street_width_ft: float,
    distance_to_nearest_intersection_ft: float,
) -> float:
    """Compute confidence score for side-of-street determination.

    The confidence is a product of two factors:
    - Distance-based: How far off-center the point is (offset_ratio)
    - Intersection proximity: How far from the nearest intersection

    Returns 0.0 for clearly ambiguous cases (near centerline or intersection).

    Args:
        perp_distance_ft: Perpendicular distance from the point to the
            street centerline in feet.
        street_width_ft: Total paved width of the street in feet (from CSCL
            streetwidth field). Typical NYC values: 25-60 feet.
        distance_to_nearest_intersection_ft: Distance from the point to the
            nearest segment endpoint (intersection) in feet.

    Returns:
        Confidence score from 0.0 (ambiguous) to 1.0 (certain).
    """
    # Near centerline: within GPS error (~3m = ~10ft), could be either side
    if perp_distance_ft < 10.0:
        return 0.0

    # Near intersection: within ~10m = ~30ft, block face is ambiguous
    if distance_to_nearest_intersection_ft < 30.0:
        return 0.0

    # Distance-based confidence: how far off-center as fraction of half-width
    half_width = street_width_ft / 2.0 if street_width_ft > 0 else 15.0
    offset_ratio = perp_distance_ft / half_width
    distance_conf = min(1.0, offset_ratio)

    # Intersection proximity factor: scales from 0 at 30ft to 1.0 at 100ft
    intersection_conf = min(1.0, distance_to_nearest_intersection_ft / 100.0)

    return distance_conf * intersection_conf


def is_confident(
    confidence: float,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> bool:
    """Check if a confidence score exceeds the threshold.

    Args:
        confidence: The computed confidence score (0.0 to 1.0).
        threshold: The minimum acceptable confidence (default 0.6).

    Returns:
        True if confidence >= threshold, False otherwise.
    """
    return confidence >= threshold
