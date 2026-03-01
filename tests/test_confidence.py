"""Tests for confidence scoring."""

import pytest

from gps2asp.resolver.confidence import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    compute_confidence,
    is_confident,
    resolve_effective_width,
)


class TestComputeConfidence:
    """Test confidence scoring for side-of-street determination."""

    def test_near_centerline_below_threshold(self):
        """Point at 5ft on 30ft street: threshold=4.95ft; guard does NOT fire.

        5ft > new 4.95ft threshold (width-relative), so confidence is computed.
        offset_ratio = 5/15 = 0.333; confidence = 0.333 — low but non-zero.
        """
        result = compute_confidence(
            perp_distance_ft=5.0,
            effective_width_ft=30.0,
            distance_to_nearest_intersection_ft=200.0,
        )
        assert result > 0.0
        assert result < 0.4  # 0.333... is low confidence (close to parking-lane threshold)

    def test_near_intersection_returns_zero(self):
        """Point near intersection (20ft < 30ft threshold) -> 0.0.
        At intersection, block face is ambiguous."""
        result = compute_confidence(
            perp_distance_ft=15.0,
            effective_width_ft=30.0,
            distance_to_nearest_intersection_ft=20.0,
        )
        assert result == 0.0

    def test_high_confidence(self):
        """Point well off-center and far from intersection -> high confidence.
        18ft perp on 30ft street (offset_ratio = 18/15 = 1.2, capped to 1.0)
        200ft from intersection (200/100 = 2.0, capped to 1.0)
        confidence = 1.0 * 1.0 = 1.0"""
        result = compute_confidence(
            perp_distance_ft=18.0,
            effective_width_ft=30.0,
            distance_to_nearest_intersection_ft=200.0,
        )
        assert result > 0.8

    def test_medium_confidence(self):
        """Point moderately off-center, somewhat near intersection.
        12ft perp on 30ft street (offset_ratio = 12/15 = 0.8)
        80ft from intersection (80/100 = 0.8)
        confidence = 0.8 * 0.8 = 0.64"""
        result = compute_confidence(
            perp_distance_ft=12.0,
            effective_width_ft=30.0,
            distance_to_nearest_intersection_ft=80.0,
        )
        assert 0.4 < result < 0.8

    def test_exact_centerline_threshold(self):
        """Point at 10ft on a 30ft street: well above width-relative threshold=4.95ft.

        With the new width-relative guard: threshold = 30*0.33/2 = 4.95ft.
        10ft > 4.95ft, so the guard does NOT fire.
        offset_ratio = 10/15 = 0.667; confidence = 0.667 >= 0.6 -> confidently in parking lane.
        """
        result = compute_confidence(
            perp_distance_ft=10.0,
            effective_width_ft=30.0,
            distance_to_nearest_intersection_ft=200.0,
        )
        # 10ft on 30ft street is confidently in the parking lane (above 0.6 threshold)
        assert result > DEFAULT_CONFIDENCE_THRESHOLD

    def test_exact_intersection_threshold(self):
        """Point at exactly 30ft intersection distance (boundary) -> 0.0.
        The threshold is < 30, so 30ft exactly should NOT be zero."""
        result = compute_confidence(
            perp_distance_ft=15.0,
            effective_width_ft=30.0,
            distance_to_nearest_intersection_ft=30.0,
        )
        # 30ft is not < 30ft, so this should NOT be 0.0
        assert result > 0.0

    def test_zero_street_width_uses_fallback(self):
        """Edge case: zero street width — caller resolves via resolve_effective_width first.

        resolve_effective_width(0.0, rw_type=1) -> 30ft fallback.
        With effective_width=30ft: half_width=15ft, threshold=4.95ft.
        15ft > 4.95ft -> passes guard. offset_ratio = 15/15 = 1.0 -> confidence=1.0.
        """
        effective_width = resolve_effective_width(0.0, rw_type=1)
        result = compute_confidence(
            perp_distance_ft=15.0,
            effective_width_ft=effective_width,
            distance_to_nearest_intersection_ft=200.0,
        )
        # 15/15 = 1.0 offset, 200/100 = 2.0 capped to 1.0 -> 1.0
        assert result == 1.0

    def test_confidence_range(self):
        """Confidence should always be between 0.0 and 1.0."""
        # Test various inputs
        test_cases = [
            (5.0, 30.0, 200.0),   # above width-relative guard, below confidence threshold
            (15.0, 30.0, 20.0),   # near intersection
            (18.0, 30.0, 200.0),  # high confidence
            (12.0, 30.0, 80.0),   # medium confidence
            (50.0, 60.0, 500.0),  # very confident
            (11.0, 30.0, 31.0),   # just above both thresholds
        ]
        for perp, width, intersection in test_cases:
            result = compute_confidence(perp, width, intersection)
            assert 0.0 <= result <= 1.0, (
                f"confidence={result} out of range for "
                f"perp={perp}, width={width}, intersection={intersection}"
            )

    def test_near_centerline_within_fraction_returns_zero(self):
        """Point within parking_lane_fraction threshold returns 0.0.

        new threshold = 30 * 0.33 / 2 = 4.95ft
        3.0ft < 4.95ft -> returns 0.0
        """
        result = compute_confidence(
            perp_distance_ft=3.0,
            effective_width_ft=30.0,
            distance_to_nearest_intersection_ft=200.0,
        )
        assert result == 0.0

    def test_regression_prospect_pl_9ft(self):
        """Regression: 9.2ft from centerline on 30ft street passes 0.6 threshold.

        This is the failing E2E case from 2026-02-27 (lat=40.677629, lng=-73.968527).
        Before fix: 9.2 < 10.0 (absolute guard) -> confidence = 0.0
        After fix:  9.2 > 4.95ft (width-relative) -> confidence ~= 0.6133 -> resolved
        """
        result = compute_confidence(
            perp_distance_ft=9.2,
            effective_width_ft=30.0,
            distance_to_nearest_intersection_ft=200.0,
            parking_lane_fraction=0.33,
        )
        assert result >= DEFAULT_CONFIDENCE_THRESHOLD, (
            f"Expected >= {DEFAULT_CONFIDENCE_THRESHOLD}, got {result:.4f} — "
            f"PROSPECT PL regression"
        )

    def test_nan_streetwidth_uses_rw_type_fallback(self):
        """NaN streetwidth falls back to _NYC_DEFAULT_WIDTHS[rw_type=1] = 30ft.

        resolve_effective_width resolves the fallback; result matches explicit 30ft.
        """
        width_from_nan = resolve_effective_width(float('nan'), rw_type=1)
        result_nan = compute_confidence(
            perp_distance_ft=9.2,
            effective_width_ft=width_from_nan,
            distance_to_nearest_intersection_ft=200.0,
        )
        result_explicit = compute_confidence(
            perp_distance_ft=9.2,
            effective_width_ft=30.0,
            distance_to_nearest_intersection_ft=200.0,
        )
        assert result_nan == result_explicit

    def test_highway_width_fallback(self):
        """rw_type=2 (highway) falls back to 60ft when streetwidth=0.

        threshold = 60*0.33/2 = 9.9ft; 20ft > 9.9ft -> passes guard
        half_width = 30ft; offset_ratio = 20/30 = 0.667; confidence ~= 0.667
        """
        effective_width = resolve_effective_width(0.0, rw_type=2)
        result = compute_confidence(
            perp_distance_ft=20.0,
            effective_width_ft=effective_width,
            distance_to_nearest_intersection_ft=200.0,
        )
        assert result > 0.6

    def test_custom_parking_lane_fraction(self):
        """Custom parking_lane_fraction changes the near-centerline threshold.

        With fraction=0.5: threshold = 30*0.5/2 = 7.5ft; 9.2ft > 7.5ft -> passes
        With fraction=0.7: threshold = 30*0.7/2 = 10.5ft; 9.2ft < 10.5ft -> 0.0
        """
        result_passes = compute_confidence(
            perp_distance_ft=9.2,
            effective_width_ft=30.0,
            distance_to_nearest_intersection_ft=200.0,
            parking_lane_fraction=0.5,
        )
        result_zero = compute_confidence(
            perp_distance_ft=9.2,
            effective_width_ft=30.0,
            distance_to_nearest_intersection_ft=200.0,
            parking_lane_fraction=0.7,
        )
        assert result_passes > 0.0
        assert result_zero == 0.0


class TestIsConfident:
    """Test the is_confident helper."""

    def test_above_default_threshold(self):
        """Confidence above default threshold (0.6) should return True."""
        assert is_confident(0.8) is True

    def test_below_default_threshold(self):
        """Confidence below default threshold (0.6) should return False."""
        assert is_confident(0.3) is False

    def test_at_default_threshold(self):
        """Confidence exactly at threshold should return True (>=)."""
        assert is_confident(DEFAULT_CONFIDENCE_THRESHOLD) is True

    def test_custom_threshold(self):
        """Custom threshold should be respected."""
        assert is_confident(0.5, threshold=0.4) is True
        assert is_confident(0.5, threshold=0.6) is False

    def test_zero_confidence(self):
        """Zero confidence should return False."""
        assert is_confident(0.0) is False

    def test_default_threshold_value(self):
        """Default threshold should be 0.33."""
        assert DEFAULT_CONFIDENCE_THRESHOLD == 0.33
