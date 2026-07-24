"""TDD coverage for the four new diagnostic fields on ``ResolutionResult``.

Phase 30 Plan 01: extends ``ResolutionResult`` with ``borocode``,
``perpendicular_distance_ft``, ``street_width_ft``, and ``segment_id`` —
optional with ``None`` defaults so existing callers keep working (D-04, D-05).
``resolve_segment()`` is updated to populate all four from the winning
``SegmentCandidate`` plus the ``perp_distance`` / ``effective_width`` values
already in scope (D-06). The vendored mirror under
``custom_components/asp_parking/gps2asp/resolver/`` must stay byte-for-byte
identical for ``models.py`` (D-15).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from shapely.geometry import LineString

from gps2asp.resolver import resolve_segment
from gps2asp.resolver.confidence import resolve_effective_width
from gps2asp.resolver.models import ResolutionResult, SegmentCandidate
from gps2asp.resolver.side_resolver import compute_perpendicular_distance
from gps2asp.resolver.spatial_index import SpatialIndex


def _make_segment_candidate(
    *,
    segment_id: int = 42,
    geometry: LineString | None = None,
    full_street_name: str = "PROSPECT PL",
    from_street: str = "VANDERBILT AVE",
    to_street: str = "CARLTON AVE",
    trafdir: str = "TW",
    nominaldir: str = "E",
    rw_type: int = 1,
    streetwidth: float = 30.0,
    borocode: str = "3",
    has_asp_left: bool = True,
    has_asp_right: bool = True,
    distance_ft: float = 5.0,
) -> SegmentCandidate:
    """Build a SegmentCandidate fixture with all required fields populated."""
    if geometry is None:
        # Horizontal 200ft segment along y=178432. Long enough that the test
        # query point (midpoint) sits >30ft from either endpoint, avoiding the
        # near-intersection ambiguity guard in compute_confidence().
        geometry = LineString([(987600.0, 178432.0), (987800.0, 178432.0)])
    return SegmentCandidate(
        segment_id=segment_id,
        geometry=geometry,
        full_street_name=full_street_name,
        from_street=from_street,
        to_street=to_street,
        trafdir=trafdir,
        nominaldir=nominaldir,
        rw_type=rw_type,
        streetwidth=streetwidth,
        borocode=borocode,
        has_asp_left=has_asp_left,
        has_asp_right=has_asp_right,
        distance_ft=distance_ft,
    )


def test_resolution_result_has_new_optional_fields() -> None:
    """ResolutionResult constructs without the four new fields and exposes them as None."""
    result = ResolutionResult(
        on_street="X",
        from_street="Y",
        to_street="Z",
        side_of_street="N",
        confidence=0.9,
        has_asp=True,
    )

    assert result.borocode is None
    assert result.perpendicular_distance_ft is None
    assert result.street_width_ft is None
    assert result.segment_id is None


def test_resolution_result_accepts_new_fields_explicitly() -> None:
    """Passing the four new fields explicitly round-trips the values."""
    result = ResolutionResult(
        on_street="X",
        from_street="Y",
        to_street="Z",
        side_of_street="N",
        confidence=0.9,
        has_asp=True,
        borocode="3",
        perpendicular_distance_ft=12.34,
        street_width_ft=34.0,
        segment_id=987654,
    )

    assert result.borocode == "3"
    assert result.perpendicular_distance_ft == pytest.approx(12.34)
    assert result.street_width_ft == pytest.approx(34.0)
    assert result.segment_id == 987654


async def test_resolve_segment_populates_new_fields_from_best_candidate() -> None:
    """resolve_segment() threads the four new diagnostic fields onto the result."""
    candidate = _make_segment_candidate(
        segment_id=42,
        streetwidth=30.0,
        rw_type=1,
        borocode="3",
    )

    # Query point sits at the segment midpoint (x=987700) but offset 10ft
    # perpendicular to the centerline (y=178442 vs centerline y=178432).
    # For width=30ft this yields perp_dist=10ft (>4.95ft near-center guard),
    # endpoint distance ~100ft (>30ft near-intersection guard) and
    # confidence ~0.67 — comfortably above the 0.33 threshold.
    query_x, query_y = 987700.0, 178442.0
    expected_perp = compute_perpendicular_distance(
        query_x,
        query_y,
        candidate.geometry,
    )
    expected_width = resolve_effective_width(30.0, 1)

    mock_idx = MagicMock()
    mock_idx.nearest = MagicMock(return_value=[candidate])

    with patch(
        "gps2asp.resolver.SpatialIndex.get",
        new=AsyncMock(return_value=mock_idx),
    ):
        result = await resolve_segment(x=query_x, y=query_y)

    assert result.borocode == "3"
    assert result.segment_id == 42
    assert result.street_width_ft == pytest.approx(expected_width)
    assert result.perpendicular_distance_ft == pytest.approx(round(expected_perp, 2))


class TestSegmentCandidateCalibrationFields:
    """Phase 40 Plan 04: per-segment calibration fields on SegmentCandidate.

    Five defaulted fields are appended AFTER ``distance_ft`` so existing
    positional/keyword construction sites keep working. When absent, the
    candidate is EXPLICITLY non-calibrated (``calibrated=False``,
    ``center_offset_c=0.0``) -> resolver uses c=0 / plain CSCL fallback.
    """

    def test_defaults_to_non_calibrated(self) -> None:
        """Built without calibration args: calibrated False, c=0.0, spreads None."""
        candidate = _make_segment_candidate()

        assert candidate.calibrated is False
        assert candidate.center_offset_c == 0.0
        assert candidate.curb_width_ft is None
        assert candidate.spread_n is None
        assert candidate.spread_s is None

    def test_accepts_explicit_calibration_values(self) -> None:
        """Passing calibration fields explicitly round-trips the values."""
        candidate = SegmentCandidate(
            segment_id=42,
            geometry=LineString([(987600.0, 178432.0), (987800.0, 178432.0)]),
            full_street_name="PROSPECT PL",
            from_street="VANDERBILT AVE",
            to_street="CARLTON AVE",
            trafdir="TW",
            nominaldir="E",
            rw_type=1,
            streetwidth=30.0,
            borocode="3",
            has_asp_left=True,
            has_asp_right=True,
            distance_ft=5.0,
            center_offset_c=-2.38,
            curb_width_ft=32.0,
            spread_n=1.5,
            spread_s=2.0,
            calibrated=True,
        )

        assert candidate.center_offset_c == pytest.approx(-2.38)
        assert candidate.curb_width_ft == pytest.approx(32.0)
        assert candidate.spread_n == pytest.approx(1.5)
        assert candidate.spread_s == pytest.approx(2.0)
        assert candidate.calibrated is True


class _FakeRTree:
    """Minimal rtree stand-in: returns the same ids for nearest()/intersection().

    The real geometry-distance filter in nearest()/query_radius() still runs, so
    the returned candidates are governed by the WKT + query point, not this stub.
    """

    def __init__(self, ids: list[int]) -> None:
        self._ids = list(ids)

    def nearest(self, coords: tuple, n: int) -> list[int]:
        return list(self._ids)

    def intersection(self, coords: tuple) -> list[int]:
        return list(self._ids)


def _make_loader_index(segments: dict) -> SpatialIndex:
    """Build a SpatialIndex wired to an in-memory fake rtree + segment dict."""
    idx = SpatialIndex(index_dir="/nonexistent")
    idx._index = _FakeRTree([int(k) for k in segments])  # type: ignore[assignment]
    idx._segments = segments
    return idx


class TestSpatialIndexLoaderCalibration:
    """Phase 40 Plan 04: both loader paths surface calibration fields.

    Absent calibration keys (legacy index / from-source rebuild) MUST degrade
    to the safe non-calibrated candidate (center_offset_c=0.0, calibrated=False)
    with no KeyError.
    """

    _GEOM_WKT = "LINESTRING (1000 1000, 1100 1000)"
    _QX, _QY = 1050.0, 1005.0  # 5ft off the centerline -> within all radii

    def _segments(self) -> dict:
        return {
            "1": {
                "geometry_wkt": self._GEOM_WKT,
                "full_street_name": "CALIBRATED ST",
                "center_offset_c": -2.38,
                "curb_width_ft": 32.0,
                "spread_n": 1.5,
                "spread_s": 2.0,
                "calibrated": True,
            },
            "2": {
                "geometry_wkt": self._GEOM_WKT,
                "full_street_name": "LEGACY ST",
                # NONE of the calibration keys — must default safely.
            },
        }

    def test_nearest_populates_calibration_and_legacy_defaults(self) -> None:
        idx = _make_loader_index(self._segments())

        by_id = {c.segment_id: c for c in idx.nearest(self._QX, self._QY)}

        cal = by_id[1]
        assert cal.calibrated is True
        assert cal.center_offset_c == pytest.approx(-2.38)
        assert cal.curb_width_ft == pytest.approx(32.0)
        assert cal.spread_n == pytest.approx(1.5)
        assert cal.spread_s == pytest.approx(2.0)

        legacy = by_id[2]
        assert legacy.calibrated is False
        assert legacy.center_offset_c == 0.0
        assert legacy.curb_width_ft is None
        assert legacy.spread_n is None
        assert legacy.spread_s is None

    def test_query_radius_populates_calibration_and_legacy_defaults(self) -> None:
        idx = _make_loader_index(self._segments())

        by_id = {c.segment_id: c for c in idx.query_radius(self._QX, self._QY, 500.0)}

        cal = by_id[1]
        assert cal.calibrated is True
        assert cal.center_offset_c == pytest.approx(-2.38)
        assert cal.curb_width_ft == pytest.approx(32.0)

        legacy = by_id[2]
        assert legacy.calibrated is False
        assert legacy.center_offset_c == 0.0
        assert legacy.curb_width_ft is None
        assert legacy.spread_n is None
        assert legacy.spread_s is None


def test_vendored_mirror_resolution_result_has_new_fields() -> None:
    """Vendored mirror exposes the same four optional fields with None defaults."""
    from custom_components.asp_parking.gps2asp.resolver.models import (
        ResolutionResult as MirrorRR,
    )

    result = MirrorRR(
        on_street="X",
        from_street="Y",
        to_street="Z",
        side_of_street="N",
        confidence=0.9,
        has_asp=True,
    )

    assert result.borocode is None
    assert result.perpendicular_distance_ft is None
    assert result.street_width_ft is None
    assert result.segment_id is None
