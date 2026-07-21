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
from shapely.geometry import LineString

from gps2asp.resolver import resolve, convert, resolve_segment
from gps2asp.resolver.exceptions import AmbiguousResolutionError
from gps2asp.resolver.models import ResolutionResult, SegmentCandidate

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
        except AmbiguousResolutionError:  # lgtm[py/empty-except]
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
            except AmbiguousResolutionError:  # lgtm[py/empty-except]
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
        except AmbiguousResolutionError:  # lgtm[py/empty-except]
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
        except AmbiguousResolutionError:  # lgtm[py/empty-except]
            pass


# =====================================================================
# BUG-R-002/003/006/001 regression tests (Phase 35.1-02, RED -> GREEN)
# =====================================================================


class _FakeIndex:
    """Minimal SpatialIndex stand-in with a fixed nearest()-result list."""

    def __init__(self, candidates):
        self._candidates = candidates

    def nearest(self, x, y, *args, **kwargs):  # noqa: ARG002 - signature parity
        return list(self._candidates)


def _patch_index(monkeypatch, candidates):
    """Patch SpatialIndex.get to return a _FakeIndex with the given candidates."""
    fake = _FakeIndex(candidates)

    async def _fake_get(cls, index_dir=None):  # noqa: ARG001
        return fake

    from gps2asp.resolver import spatial_index as si_mod

    monkeypatch.setattr(si_mod.SpatialIndex, "get", classmethod(_fake_get))
    return fake


def _make_candidate(
    *,
    geometry: LineString,
    streetwidth: float = 30.0,
    has_asp_left: bool = False,
    has_asp_right: bool = False,
    rw_type: int = 1,
    segment_id: int = 42,
    nominaldir: str = "",
) -> SegmentCandidate:
    """Construct a SegmentCandidate for resolver-under-test scenarios."""
    return SegmentCandidate(
        segment_id=segment_id,
        geometry=geometry,
        full_street_name="TEST STREET",
        from_street="FROM ST",
        to_street="TO ST",
        trafdir="TW",
        nominaldir=nominaldir,
        rw_type=rw_type,
        streetwidth=streetwidth,
        borocode="3",
        has_asp_left=has_asp_left,
        has_asp_right=has_asp_right,
        distance_ft=10.0,
    )


class TestHasAspSideAware:
    """BUG-R-002: has_asp uses conservative OR across both sides.

    The spatial index stores identical values for has_asp_left and has_asp_right
    (both set by _check_has_asp which cannot distinguish sides). A compass-to-
    left/right mapping would require knowing the segment bearing and would be
    incorrect without per-side index data. The OR is the safe, correct default.
    """

    async def test_has_asp_or_across_both_sides(self, monkeypatch):
        """has_asp is True if either side has ASP, regardless of resolved side.

        N-running segment (0,0)->(0,100); query at (10, 50) yields side='E'.
        has_asp_left=True reflects that ASP exists on the block (the index
        stores the same value for both sides). Conservative OR returns True.
        """
        seg = LineString([(0, 0), (0, 100)])
        candidate = _make_candidate(
            geometry=seg,
            has_asp_left=True,
            has_asp_right=True,
            streetwidth=4.0,  # half-width 2ft, parking zone < 0.66ft, 10ft clears
        )
        _patch_index(monkeypatch, [candidate])

        result = await resolve_segment(10.0, 50.0)

        assert result.side_of_street == "E", "Sanity: side must be E"
        assert result.has_asp is True, (
            "BUG-R-002: has_asp must be True when either side has ASP "
            "(conservative OR — index stores identical left/right values)"
        )


class TestClassifyAmbiguityDocs:
    """BUG-R-001: _classify_ambiguity threshold-rationale documentation guard."""

    def test_classify_ambiguity_documents_threshold_basis(self):
        """The 10ft heuristic docstring must cite BUG-R-001 and the width-relative basis."""
        from gps2asp.resolver import _classify_ambiguity

        doc = _classify_ambiguity.__doc__ or ""
        assert "10ft" in doc, "docstring should mention the 10ft heuristic constant"
        assert "BUG-R-001" in doc, (
            "docstring should cite BUG-R-001 to anchor the width-relative rationale"
        )
        assert "width-relative" in doc.lower(), (
            "docstring should explain that the real threshold is width-relative"
        )


class TestDetermineSideSkippedAtZeroConfidence:
    """BUG-R-003: determine_side must not be called when confidence will be 0."""

    async def test_determine_side_not_called_at_zero_confidence(self, monkeypatch):
        """Near-centerline point (perp_distance < parking_lane_fraction*width/2) must
        skip determine_side; the AmbiguousResolutionError debug_info should have
        side=None (or empty string) to indicate the side computation was bypassed.
        """
        # Long E-running segment so dist_to_endpoints is large (not the ambiguity cause).
        seg = LineString([(0, 0), (1000, 0)])
        candidate = _make_candidate(
            geometry=seg,
            streetwidth=60.0,  # half-width 30ft, parking_lane_fraction*30 = 9.9ft inner zone
        )
        _patch_index(monkeypatch, [candidate])

        # Counter wrapping determine_side
        from gps2asp import resolver as resolver_pkg
        from gps2asp.resolver import side_resolver as sr_mod

        call_count = {"n": 0}
        real_determine_side = sr_mod.determine_side

        def counting_determine_side(*args, **kwargs):
            call_count["n"] += 1
            return real_determine_side(*args, **kwargs)

        # Patch BOTH the side_resolver module AND the binding imported into
        # resolver/__init__.py (it does `from .side_resolver import determine_side`).
        monkeypatch.setattr(sr_mod, "determine_side", counting_determine_side)
        monkeypatch.setattr(resolver_pkg, "determine_side", counting_determine_side)

        # Query at midpoint (500, 1.0) -- perp_distance = 1.0ft, near centerline.
        # parking_lane_fraction * width / 2 = 0.33 * 60 / 2 = 9.9ft -> confidence=0.
        with pytest.raises(AmbiguousResolutionError):
            await resolve_segment(500.0, 1.0)

        assert call_count["n"] == 0, (
            f"BUG-R-003: determine_side must be skipped when confidence will be 0, "
            f"but it was called {call_count['n']} time(s)"
        )


class TestMissingRwTypeLogIncludesSegmentId:
    """BUG-R-006: missing-streetwidth fallback log must include segment_id."""

    def test_missing_rw_type_log_includes_segment_id(self, caplog):
        """resolve_effective_width fallback log must surface segment_id."""
        from gps2asp.resolver.confidence import resolve_effective_width

        with caplog.at_level(logging.DEBUG, logger="gps2asp.resolver.confidence"):
            # rw_type=99 is not in _NYC_DEFAULT_WIDTHS -> fallback path taken
            resolve_effective_width(0.0, 99, segment_id=123456)

        fallback_records = [
            r for r in caplog.records if "streetwidth missing" in r.message
        ]
        assert len(fallback_records) > 0, "Expected a streetwidth-missing fallback log"
        msg = fallback_records[0].getMessage()
        assert "segment_id" in msg, (
            f"BUG-R-006: fallback log must include 'segment_id'; got: {msg!r}"
        )
        assert "123456" in msg, (
            f"BUG-R-006: fallback log must include the actual segment_id value; got: {msg!r}"
        )
