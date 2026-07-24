"""Tests for the build-time curb-derivation core (plan 40-05, SC-1).

Synthetic-geometry tests for :func:`derive_segment_calibration`: clean flanking
curbs produce the fitted centre ``c`` and true width; a missing flank or a
high per-side spread self-flags as non-calibrated. No network — the geometry is
constructed in-process with shapely ``LineString`` fixtures in EPSG:2263 feet.
"""

from __future__ import annotations

import pytest
from shapely.geometry import LineString

from gps2asp.resolver.curb_calibration import (
    CURB_SAMPLE_STEP_FT,
    SPREAD_GATE_FT,
    SegmentCalibration,
    derive_segment_calibration,
)

# East-running CSCL centerline along y=0 from x=0..300 ft (State Plane feet).
# For this orientation the signed offset of a point equals its y-coordinate:
# +ve = North, -ve = South.
CENTERLINE = LineString([(0.0, 0.0), (300.0, 0.0)])


class TestDeriveCleanGeometry:
    """Behaviour case 1: clean flanking curbs -> c/width, calibrated True."""

    def test_clean_flanking_curbs_give_c_and_width(self) -> None:
        north = LineString([(0.0, 16.0), (300.0, 16.0)])
        south = LineString([(0.0, -14.0), (300.0, -14.0)])
        cal = derive_segment_calibration(
            CENTERLINE, [north, south], cscl_width_ft=30.0
        )
        assert cal.calibrated is True
        # c = (median(N) + median(S)) / 2 = (16 + -14) / 2 = +1.0
        assert cal.center_offset_c == pytest.approx(1.0)
        # width = median(N) - median(S) = 16 - (-14) = 30.0
        assert cal.curb_width_ft == pytest.approx(30.0)
        # perfectly straight curbs -> per-side spread ~0
        assert cal.spread_n is not None and cal.spread_n < 0.1
        assert cal.spread_s is not None and cal.spread_s < 0.1

    def test_returns_frozen_segment_calibration(self) -> None:
        north = LineString([(0.0, 16.0), (300.0, 16.0)])
        south = LineString([(0.0, -14.0), (300.0, -14.0)])
        cal = derive_segment_calibration(
            CENTERLINE, [north, south], cscl_width_ft=30.0
        )
        assert isinstance(cal, SegmentCalibration)
        with pytest.raises((AttributeError, Exception)):
            cal.center_offset_c = 99.0  # type: ignore[misc]

    def test_default_sample_step_is_six_feet(self) -> None:
        assert CURB_SAMPLE_STEP_FT == pytest.approx(6.0)


class TestDeriveMissingSide:
    """Behaviour case 2: a missing flank -> non-calibrated, c=0.0, width None."""

    def test_only_north_curb_is_non_calibrated(self) -> None:
        north = LineString([(0.0, 16.0), (300.0, 16.0)])
        cal = derive_segment_calibration(CENTERLINE, [north], cscl_width_ft=30.0)
        assert cal.calibrated is False
        assert cal.center_offset_c == 0.0
        assert cal.curb_width_ft is None
        # a missing flank yields no per-side spreads at all (distinguishable
        # from the spread-gate rejection which DOES report spreads)
        assert cal.spread_n is None
        assert cal.spread_s is None

    def test_only_south_curb_is_non_calibrated(self) -> None:
        south = LineString([(0.0, -14.0), (300.0, -14.0)])
        cal = derive_segment_calibration(CENTERLINE, [south], cscl_width_ft=30.0)
        assert cal.calibrated is False
        assert cal.center_offset_c == 0.0
        assert cal.curb_width_ft is None

    def test_no_curbs_is_non_calibrated(self) -> None:
        cal = derive_segment_calibration(CENTERLINE, [], cscl_width_ft=30.0)
        assert cal.calibrated is False
        assert cal.center_offset_c == 0.0
        assert cal.curb_width_ft is None


class TestDeriveIgnoresOutOfRange:
    """Behaviour case 3: samples beyond max_perp do not enter the medians."""

    def test_stray_curb_beyond_max_perp_is_ignored(self) -> None:
        north = LineString([(0.0, 16.0), (300.0, 16.0)])
        south = LineString([(0.0, -14.0), (300.0, -14.0)])
        # 60 ft > max_perp = max(45, 30*1.5=45) = 45 -> excluded entirely
        stray = LineString([(0.0, 60.0), (300.0, 60.0)])
        cal = derive_segment_calibration(
            CENTERLINE, [north, south, stray], cscl_width_ft=30.0
        )
        assert cal.calibrated is True
        assert cal.center_offset_c == pytest.approx(1.0)
        assert cal.curb_width_ft == pytest.approx(30.0)

    def test_all_samples_beyond_max_perp_yield_missing_side(self) -> None:
        # A lone far-away curb contributes nothing -> both buckets empty ->
        # the missing-side path (not a computed c).
        stray = LineString([(0.0, 80.0), (300.0, 80.0)])
        cal = derive_segment_calibration(
            CENTERLINE, [stray], cscl_width_ft=30.0
        )
        assert cal.calibrated is False
        assert cal.center_offset_c == 0.0
        assert cal.curb_width_ft is None
