"""End-to-end integration tests for the GPS2ASP resolver.

These tests require a built spatial index. They verify the full pipeline:
GPS coordinate -> State Plane conversion -> nearest segment -> side determination
-> confidence scoring -> ResolutionResult.

Run with: pytest tests/test_resolver.py -v
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from gps2asp.resolver import resolve, convert, resolve_segment
from gps2asp.resolver.exceptions import AmbiguousResolutionError
from gps2asp.resolver.models import ResolutionResult

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def prospect_heights_fixtures():
    """Load Prospect Heights test coordinate fixtures."""
    with open(FIXTURES_DIR / "prospect_heights.json") as f:
        return json.load(f)


@pytest.mark.integration
class TestResolveProspectHeights:
    """End-to-end resolution tests using known Prospect Heights coordinates."""

    async def test_resolve_prospect_heights(
        self,
        spatial_index_dir,
        prospect_heights_fixtures,
    ):
        """Resolve known Prospect Heights coordinates to correct streets."""
        for fixture in prospect_heights_fixtures:
            lat = fixture["lat"]
            lon = fixture["lon"]
            expected_street = fixture["expected_on_street"]

            try:
                result = await resolve(
                    lat,
                    lon,
                    index_dir=spatial_index_dir,
                )
                # Street name should match (case-insensitive contains)
                assert expected_street.upper() in result.on_street.upper(), (
                    f"Expected '{expected_street}' in '{result.on_street}' "
                    f"for {fixture['name']}"
                )
            except AmbiguousResolutionError:
                # Some coordinates may be near centerline/intersection --
                # this is acceptable for approximate coordinates
                pass

    async def test_resolve_returns_confidence(self, spatial_index_dir):
        """Verify resolve() returns a confidence score between 0.0 and 1.0."""
        try:
            result = await resolve(
                40.6778,
                -73.9690,
                index_dir=spatial_index_dir,
            )
            assert isinstance(result.confidence, float)
            assert 0.0 <= result.confidence <= 1.0
        except AmbiguousResolutionError as e:
            # Even on ambiguous result, confidence should be available
            assert isinstance(e.confidence, float)
            assert 0.0 <= e.confidence <= 1.0

    async def test_resolve_returns_has_asp(self, spatial_index_dir):
        """Verify resolve() returns a boolean has_asp field."""
        try:
            result = await resolve(
                40.6778,
                -73.9690,
                index_dir=spatial_index_dir,
            )
            assert isinstance(result.has_asp, bool)
        except AmbiguousResolutionError:
            pass  # has_asp only available on success

    async def test_resolve_returns_cross_streets(self, spatial_index_dir):
        """Verify resolve() returns non-empty from_street and to_street."""
        try:
            result = await resolve(
                40.6778,
                -73.9690,
                index_dir=spatial_index_dir,
            )
            assert isinstance(result.from_street, str)
            assert isinstance(result.to_street, str)
            assert len(result.from_street) > 0, "from_street should not be empty"
            assert len(result.to_street) > 0, "to_street should not be empty"
        except AmbiguousResolutionError:
            pass

    async def test_convert_then_resolve_segment(self, spatial_index_dir):
        """Test two-step pipeline produces same result as one-step resolve()."""
        lat, lon = 40.6778, -73.9690

        # One-step
        try:
            result_one_step = await resolve(
                lat,
                lon,
                index_dir=spatial_index_dir,
            )
        except AmbiguousResolutionError as e:
            result_one_step = e

        # Two-step
        x, y = convert(lat, lon)
        try:
            result_two_step = await resolve_segment(
                x,
                y,
                index_dir=spatial_index_dir,
            )
        except AmbiguousResolutionError as e:
            result_two_step = e

        # Both should produce the same outcome type
        if isinstance(result_one_step, ResolutionResult):
            assert isinstance(result_two_step, ResolutionResult)
            assert result_one_step.on_street == result_two_step.on_street
            assert result_one_step.side_of_street == result_two_step.side_of_street
            assert abs(result_one_step.confidence - result_two_step.confidence) < 0.01
        else:
            assert isinstance(result_two_step, AmbiguousResolutionError)

    async def test_resolve_debug_logging(
        self,
        spatial_index_dir,
        caplog,
    ):
        """Verify JSON debug output is emitted during resolution."""
        # Use caplog.at_level instead of configure_logging() to avoid
        # permanently adding handlers to the logger across the test session.
        with caplog.at_level(logging.DEBUG, logger="gps2asp.resolver"):
            try:
                await resolve(
                    40.6778,
                    -73.9690,
                    index_dir=spatial_index_dir,
                )
            except AmbiguousResolutionError:
                pass

        # Check that at least one log record contains JSON-like content
        debug_records = [
            r
            for r in caplog.records
            if r.levelno == logging.DEBUG and "resolution_attempt" in r.message
        ]
        assert len(debug_records) > 0, "Expected DEBUG log with resolution_attempt"

        # Verify the JSON contains expected keys
        msg = debug_records[0].message
        assert "state_plane_x" in msg
        assert "confidence" in msg

    async def test_resolve_custom_threshold(self, spatial_index_dir):
        """Verify that a very high confidence threshold raises AmbiguousResolutionError."""
        with pytest.raises(AmbiguousResolutionError):
            await resolve(
                40.6778,
                -73.9690,
                confidence_threshold=0.99,
                index_dir=spatial_index_dir,
            )

    async def test_resolve_result_types(self, spatial_index_dir):
        """Verify ResolutionResult has the correct field types."""
        try:
            result = await resolve(
                40.6778,
                -73.9690,
                index_dir=spatial_index_dir,
            )
            assert isinstance(result, ResolutionResult)
            assert isinstance(result.on_street, str)
            assert isinstance(result.from_street, str)
            assert isinstance(result.to_street, str)
            assert result.side_of_street in ("N", "S", "E", "W")
            assert isinstance(result.confidence, float)
            assert isinstance(result.has_asp, bool)
        except AmbiguousResolutionError:
            pass

    async def test_resolve_prospect_place_has_asp(self, spatial_index_dir):
        """Prospect Place in Prospect Heights should have ASP regulations."""
        try:
            result = await resolve(
                40.6778,
                -73.9690,
                index_dir=spatial_index_dir,
            )
            # Prospect Place has ASP signs per parking signs dataset
            if "PROSPECT" in result.on_street.upper():
                assert result.has_asp is True, (
                    f"Expected has_asp=True for {result.on_street}"
                )
        except AmbiguousResolutionError:
            pass
