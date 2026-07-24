"""Wave-2 integration regressions for calibrated side-of-street resolution (Plan 40-06).

These tests prove the calibrated pipeline is LIVE in ``resolve_segment``: the N/S
boundary splits at the fitted centre ``c`` (SC-2), confidence has an upper
plausibility bound relative to ``c`` (SC-3), the SC-4 fallback chain
(curb ``c`` -> learned ``c`` -> 0) is wired, and genuine side alternation is
preserved (SC-6, no hysteresis).

Two of these are non-inferable regressions anchored to spike ground truth:

- **Prospect Pl -> South (accepted).** The only user-confirmed ground-truth label
  in the phase (fix 40.677770, -73.969472 with ``c=-2.38``) must resolve to South
  and be ACCEPTED (no ``AmbiguousResolutionError``).
- **89 ft -> refused.** A fix 89 ft off a 40 ft street, far from an intersection,
  must be REFUSED — the legacy ``confidence-1.0-at-89ft`` defect is gone
  end-to-end.

The candidate is injected by monkeypatching ``SpatialIndex.get`` to return a
fake index (reusing the harness pattern already used by ``test_resolver.py``),
so these tests do not require a built spatial index on disk.
"""

from __future__ import annotations

import pytest
from shapely import wkt
from shapely.geometry import LineString

from gps2asp.resolver import convert, resolve_segment
from gps2asp.resolver.confidence import DEFAULT_CONFIDENCE_THRESHOLD
from gps2asp.resolver.exceptions import AmbiguousResolutionError
from gps2asp.resolver.models import SegmentCandidate

# Real geometry for CSCL physical segment 39224 = PROSPECT PL (Carlton Ave ->
# Vanderbilt Ave), copied verbatim from src/gps2asp/data/index/segments.json.
# Runs roughly East (x increases, y decreases): left=N, right=S.
PROSPECT_PL_WKT = (
    "LINESTRING (992008.6222559249 186413.7267719634, "
    "992887.2230225515 186172.44116602992)"
)

# Confirmed ground truth (spike 001 / side-calibration-algorithm.md): this fix is
# a South park; the fitted curb centre offset for the segment is c = -2.38 ft.
PROSPECT_PL_FIX_LAT = 40.677770
PROSPECT_PL_FIX_LON = -73.969472
PROSPECT_PL_C = -2.38
PROSPECT_PL_CURB_WIDTH = 32.0


class _FakeIndex:
    """Minimal SpatialIndex stand-in returning a fixed nearest()-result list."""

    def __init__(self, candidates: list[SegmentCandidate]):
        self._candidates = candidates

    def nearest(self, x, y, *args, **kwargs):  # noqa: ARG002 - signature parity
        return list(self._candidates)


def _patch_index(monkeypatch, candidates: list[SegmentCandidate]) -> _FakeIndex:
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
    center_offset_c: float = 0.0,
    curb_width_ft: float | None = None,
    calibrated: bool = False,
    streetwidth: float = 30.0,
    rw_type: int = 1,
    segment_id: int = 39224,
    full_street_name: str = "PROSPECT PL",
) -> SegmentCandidate:
    """Construct a SegmentCandidate with explicit calibration fields."""
    return SegmentCandidate(
        segment_id=segment_id,
        geometry=geometry,
        full_street_name=full_street_name,
        from_street="FROM ST",
        to_street="TO ST",
        trafdir="TW",
        nominaldir="",
        rw_type=rw_type,
        streetwidth=streetwidth,
        borocode="3",
        has_asp_left=True,
        has_asp_right=True,
        distance_ft=10.0,
        center_offset_c=center_offset_c,
        curb_width_ft=curb_width_ft,
        calibrated=calibrated,
    )


class TestProspectPlaceSouthRegression:
    """SC-2: the confirmed Prospect Pl fix resolves to South and is ACCEPTED."""

    async def test_prospect_place_resolves_south_accepted(self, monkeypatch):
        """Fix (40.677770, -73.969472) with c=-2.38 -> side 'S', no raise.

        This is the phase's only user-confirmed ground truth. It MUST resolve to
        South AND be accepted (confidence >= threshold; no AmbiguousResolutionError).
        """
        seg = wkt.loads(PROSPECT_PL_WKT)
        candidate = _make_candidate(
            geometry=seg,
            center_offset_c=PROSPECT_PL_C,
            curb_width_ft=PROSPECT_PL_CURB_WIDTH,
            calibrated=True,
            streetwidth=30.0,
        )
        _patch_index(monkeypatch, [candidate])

        x, y = convert(PROSPECT_PL_FIX_LAT, PROSPECT_PL_FIX_LON)

        # Must NOT raise AmbiguousResolutionError (accepted).
        result = await resolve_segment(x, y)

        assert result.side_of_street == "S", (
            f"Prospect Pl fix must resolve to South with c={PROSPECT_PL_C}; "
            f"got {result.side_of_street}"
        )
        assert result.confidence >= DEFAULT_CONFIDENCE_THRESHOLD, (
            f"Prospect Pl fix must be accepted (confidence "
            f"{result.confidence} >= {DEFAULT_CONFIDENCE_THRESHOLD})"
        )
        assert result.on_street == "PROSPECT PL"


class TestNinetyFootRefusalRegression:
    """SC-3: a fix 89 ft off a 40 ft street is REFUSED (upper plausibility bound)."""

    async def test_89ft_fix_is_refused(self, monkeypatch):
        """89 ft off a 40 ft street, far from an intersection -> AmbiguousResolutionError.

        The legacy compute_confidence scored this same fix at 1.0. The lane-snap
        model's upper bound (d_near > p) makes it 0.0 < threshold, so
        resolve_segment refuses rather than emitting a confident-wrong side.
        """
        # E-running segment along x-axis: signed_offset of (500, y) equals y.
        seg = LineString([(0, 0), (1000, 0)])
        candidate = _make_candidate(
            geometry=seg,
            center_offset_c=-2.0,
            curb_width_ft=40.0,  # p = 40/2 - 3 = 17 ft
            calibrated=True,
        )
        _patch_index(monkeypatch, [candidate])

        # Query 89 ft off the centerline, mid-segment (far from either endpoint).
        with pytest.raises(AmbiguousResolutionError) as excinfo:
            await resolve_segment(500.0, 89.0)

        assert excinfo.value.confidence < DEFAULT_CONFIDENCE_THRESHOLD, (
            "89ft fix must score below threshold (upper plausibility bound); "
            f"got confidence {excinfo.value.confidence}"
        )


class TestFallbackChain:
    """SC-4: curb c -> learned c -> 0, gated on the `calibrated` flag."""

    async def test_non_calibrated_uses_c_zero(self, monkeypatch):
        """A non-calibrated candidate resolves with c=0 (plain-CSCL / pre-fix side).

        Point 9.7 ft LEFT of an E-running segment -> North with c=0.
        """
        seg = LineString([(0, 0), (1000, 0)])
        candidate = _make_candidate(geometry=seg, calibrated=False)
        _patch_index(monkeypatch, [candidate])

        result = await resolve_segment(500.0, 9.7)

        assert result.side_of_street == "N", (
            "Non-calibrated candidate must split at c=0 (pre-fix behaviour)"
        )

    async def test_learned_offset_shifts_boundary_when_non_calibrated(
        self, monkeypatch
    ):
        """learned_center_offset is TIER 2: it shifts the boundary for a non-calibrated segment.

        The same point (9.7 ft left) that resolves North with c=0 resolves South
        once a learned c=19.4 (> the point's offset) is supplied.
        """
        seg = LineString([(0, 0), (1000, 0)])
        candidate = _make_candidate(geometry=seg, calibrated=False)
        _patch_index(monkeypatch, [candidate])

        result = await resolve_segment(500.0, 9.7, learned_center_offset=19.4)

        assert result.side_of_street == "S", (
            "Supplying learned_center_offset must shift the N/S boundary for a "
            "non-calibrated candidate (fallback TIER 2)"
        )

    async def test_calibrated_candidate_ignores_learned_offset(self, monkeypatch):
        """Curb c (TIER 1) wins: a calibrated candidate ignores learned_center_offset.

        The calibrated candidate has center_offset_c=0.0, so the point resolves
        North; supplying learned=19.4 must NOT flip it to South (learned is only
        consulted when the candidate is non-calibrated).
        """
        seg = LineString([(0, 0), (1000, 0)])
        candidate = _make_candidate(
            geometry=seg,
            center_offset_c=0.0,
            curb_width_ft=25.4,  # p = 25.4/2 - 3 = 9.7 ft
            calibrated=True,
        )
        _patch_index(monkeypatch, [candidate])

        result = await resolve_segment(500.0, 9.7, learned_center_offset=19.4)

        assert result.side_of_street == "N", (
            "A calibrated candidate must use its own curb c and ignore "
            "learned_center_offset (TIER 1 precedence)"
        )


class TestAlternationPreserved:
    """SC-6: genuine side alternation is preserved (no hysteresis / stickiness)."""

    async def test_opposite_side_points_resolve_to_opposite_sides(self, monkeypatch):
        """Two points on opposite sides of the SAME calibrated segment flip side.

        No stickiness suppresses the flip — the car legitimately alternates sides
        across street-cleaning days and the resolver must report that faithfully.
        """
        seg = LineString([(0, 0), (1000, 0)])
        candidate = _make_candidate(
            geometry=seg,
            center_offset_c=0.0,
            curb_width_ft=25.4,
            calibrated=True,
        )
        _patch_index(monkeypatch, [candidate])

        north = await resolve_segment(500.0, 9.7)
        south = await resolve_segment(500.0, -9.7)

        assert north.side_of_street == "N"
        assert south.side_of_street == "S"
        assert north.side_of_street != south.side_of_street, (
            "Opposite-side points must resolve to opposite sides — alternation "
            "must not be suppressed by any hysteresis"
        )
