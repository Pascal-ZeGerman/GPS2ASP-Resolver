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
from gps2asp.resolver.confidence import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_LANE_HALF_P,
    compute_lane_snap_confidence,
    lane_half_from_width,
)
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


class TestNonCalibratedLaneHalfWidth:
    """Spike 010: `p` scales with the CSCL effective width on NON-calibrated segments.

    A non-calibrated candidate used to receive a fixed
    ``DEFAULT_LANE_HALF_P = 9.7`` ft lane half-width regardless of how wide the
    street is, so a car parked in the lane of a 58 ft avenue fell outside the
    plausible band and was refused (the user's Aug 30 Vanderbilt park). 46% of
    the index is non-calibrated. The fix derives ``p`` from the effective width
    and FLOORS it at 9.7 ft — the margin score is not monotone in ``p``, so the
    floor is what makes the change strictly non-regressive on narrow streets.
    """

    async def test_wide_non_calibrated_street_resolves(self, monkeypatch):
        """58 ft non-calibrated street, fix 21 ft off the centre -> resolves at ~0.81.

        The Aug 30 Vanderbilt defect. With width-informed ``p`` the effective
        width 58.0 gives ``p = max(9.7, 58/2 - 3) = 26.0``, so the fix sits 5 ft
        from the North lane centre and scores ``(47 - 5) / 52 = 0.8077``.
        """
        seg = LineString([(0, 0), (1000, 0)])
        candidate = _make_candidate(
            geometry=seg,
            calibrated=False,
            streetwidth=58.0,
        )
        _patch_index(monkeypatch, [candidate])

        # Must NOT raise: this is the fix that used to be refused at 0.0.
        result = await resolve_segment(500.0, 21.0)

        assert result.side_of_street == "N", (
            "A fix 21 ft LEFT of an E-running segment is the North curb"
        )
        assert result.confidence == pytest.approx(0.8077, abs=1e-4), (
            "58 ft non-calibrated street with p = 26.0 must score (47-5)/52; "
            f"got {result.confidence}"
        )
        assert result.confidence > DEFAULT_CONFIDENCE_THRESHOLD
        assert result.street_width_ft == 58.0

        # Prove the defect is real so this test cannot pass vacuously: with the
        # OLD fixed p = 9.7 the very same fix scores exactly 0.0 (d_near = 11.3
        # exceeds the plausible band) and resolve_segment would refuse it.
        assert (
            compute_lane_snap_confidence(
                signed_offset_ft=21.0,
                center_offset_c=0.0,
                lane_half_p=DEFAULT_LANE_HALF_P,
                distance_to_nearest_intersection_ft=500.0,
            )
            == 0.0
        ), (
            "Pre-fix model (p = 9.7) must score this fix 0.0 — otherwise the test is vacuous"
        )

    async def test_narrow_non_calibrated_street_keeps_default_floor(self, monkeypatch):
        """20 ft non-calibrated street keeps p = 9.7 exactly (the floor is load-bearing).

        ``lane_half_from_width(20.0) = 7.0`` is BELOW the default, and the margin
        score is not monotone in ``p``: a 7 ft band would refuse a fix that
        resolves today. The floor makes spike 010 strictly non-regressive.
        """
        seg = LineString([(0, 0), (1000, 0)])
        candidate = _make_candidate(
            geometry=seg,
            calibrated=False,
            streetwidth=20.0,
        )
        _patch_index(monkeypatch, [candidate])

        result = await resolve_segment(500.0, 15.0)

        assert result.confidence == pytest.approx(0.6467, abs=1e-4), (
            "Narrow non-calibrated street must score identically to pre-fix "
            f"behaviour ((24.7-5.3)/30.0); got {result.confidence}"
        )
        assert result.confidence > DEFAULT_CONFIDENCE_THRESHOLD

        # Without the floor, p would be 7.0 and d_near = 8.0 > 7.0 -> refused.
        assert (
            compute_lane_snap_confidence(
                signed_offset_ft=15.0,
                center_offset_c=0.0,
                lane_half_p=lane_half_from_width(20.0),
                distance_to_nearest_intersection_ft=500.0,
            )
            == 0.0
        ), (
            "Dropping the 9.7 ft floor must refuse this fix — that is why the floor exists"
        )

        # Pin p exactly: the fix lands on the lane centre (margin 1.0) only when
        # p is precisely DEFAULT_LANE_HALF_P.
        on_lane_centre = await resolve_segment(500.0, 9.7)
        assert on_lane_centre.confidence == pytest.approx(1.0), (
            "A fix at 9.7 ft must sit exactly on the lane centre, proving "
            f"p == {DEFAULT_LANE_HALF_P}; got {on_lane_centre.confidence}"
        )

    async def test_calibrated_candidate_still_uses_curb_width(self, monkeypatch):
        """A calibrated candidate derives p from curb_width_ft ONLY — no width leak.

        ``curb_width_ft = 25.4`` gives ``p = 9.7`` while the CSCL
        ``streetwidth = 58.0`` would give ``p = 26.0``. If the effective width
        leaked into the calibrated branch this fix would score 0.373, not 1.0.
        """
        seg = LineString([(0, 0), (1000, 0)])
        candidate = _make_candidate(
            geometry=seg,
            center_offset_c=0.0,
            curb_width_ft=25.4,  # p = 25.4/2 - 3 = 9.7 ft
            calibrated=True,
            streetwidth=58.0,  # would give p = 26.0 if it leaked in
        )
        _patch_index(monkeypatch, [candidate])

        result = await resolve_segment(500.0, 9.7)

        assert result.confidence == pytest.approx(1.0), (
            "Calibrated p must come from curb_width_ft alone; a 0.373 score "
            f"means the CSCL effective width leaked in. Got {result.confidence}"
        )

    async def test_centre_of_road_fix_still_refused(self, monkeypatch):
        """A fix 1.1 ft from the centre of a 58 ft street stays REFUSED.

        The user's Aug 28 park. No choice of ``p`` may turn a centre-of-road fix
        into a side answer — with p = 26.0 the margin is (27.1-24.9)/52 = 0.0423,
        far below the 0.33 threshold. This belongs to refusal handling (spike
        011), not to ``p``.
        """
        seg = LineString([(0, 0), (1000, 0)])
        candidate = _make_candidate(
            geometry=seg,
            calibrated=False,
            streetwidth=58.0,
        )
        _patch_index(monkeypatch, [candidate])

        with pytest.raises(AmbiguousResolutionError) as excinfo:
            await resolve_segment(500.0, 1.1)

        assert excinfo.value.confidence == pytest.approx(0.0423, abs=1e-4), (
            "Centre-of-road fix must score (27.1-24.9)/52; got "
            f"{excinfo.value.confidence}"
        )
        assert excinfo.value.confidence < DEFAULT_CONFIDENCE_THRESHOLD, (
            "A fix at the centre of the road is a CORRECT refusal"
        )
