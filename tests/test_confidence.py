"""Tests for confidence scoring."""

import pytest

from gps2asp.resolver.confidence import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    compute_confidence,
    is_confident,
)


class TestComputeConfidence:
    """Test confidence scoring for side-of-street determination."""

    def test_near_centerline_returns_zero(self):
        """Point very close to centerline (5ft < 10ft threshold) -> 0.0.
        Within GPS error, could be either side."""
        result = compute_confidence(
            perp_distance_ft=5.0,
            street_width_ft=30.0,
            distance_to_nearest_intersection_ft=200.0,
        )
        assert result == 0.0

    def test_near_intersection_returns_zero(self):
        """Point near intersection (20ft < 30ft threshold) -> 0.0.
        At intersection, block face is ambiguous."""
        result = compute_confidence(
            perp_distance_ft=15.0,
            street_width_ft=30.0,
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
            street_width_ft=30.0,
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
            street_width_ft=30.0,
            distance_to_nearest_intersection_ft=80.0,
        )
        assert 0.4 < result < 0.8

    def test_exact_centerline_threshold(self):
        """Point at exactly 10ft (threshold boundary) -> 0.0.
        The threshold is < 10, so 10ft exactly should NOT be zero."""
        result = compute_confidence(
            perp_distance_ft=10.0,
            street_width_ft=30.0,
            distance_to_nearest_intersection_ft=200.0,
        )
        # 10ft is not < 10ft, so this should NOT be 0.0
        assert result > 0.0

    def test_exact_intersection_threshold(self):
        """Point at exactly 30ft intersection distance (boundary) -> 0.0.
        The threshold is < 30, so 30ft exactly should NOT be zero."""
        result = compute_confidence(
            perp_distance_ft=15.0,
            street_width_ft=30.0,
            distance_to_nearest_intersection_ft=30.0,
        )
        # 30ft is not < 30ft, so this should NOT be 0.0
        assert result > 0.0

    def test_zero_street_width(self):
        """Edge case: zero street width should use default half-width of 15ft."""
        result = compute_confidence(
            perp_distance_ft=15.0,
            street_width_ft=0.0,
            distance_to_nearest_intersection_ft=200.0,
        )
        # 15/15 = 1.0 offset, 200/100 = 2.0 capped to 1.0 -> 1.0
        assert result == 1.0

    def test_confidence_range(self):
        """Confidence should always be between 0.0 and 1.0."""
        # Test various inputs
        test_cases = [
            (5.0, 30.0, 200.0),   # near centerline
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
        """Default threshold should be 0.6."""
        assert DEFAULT_CONFIDENCE_THRESHOLD == 0.6
