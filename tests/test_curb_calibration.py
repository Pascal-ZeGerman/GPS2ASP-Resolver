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
    ENDPOINT_TRIM_FT,
    SPREAD_GATE_FT,
    SegmentCalibration,
    derive_segment_calibration,
    derive_segment_calibration_with_endpoint_retry,
)

# East-running CSCL centerline along y=0 from x=0..300 ft (State Plane feet).
# For this orientation the signed offset of a point equals its y-coordinate:
# +ve = North, -ve = South.
CENTERLINE = LineString([(0.0, 0.0), (300.0, 0.0)])

# --- Corner-contaminated fixture (the spike 008 / Vanderbilt Ave mechanism) ---
#
# A SHORTER 200 ft block so the two 25 ft end zones are a meaningful fraction of
# the span (a quarter of it), as they are on the real wide/long blocks the trim
# was measured on. Each flanking curb is three pieces: an intersection
# corner-return flare swinging far outward at the start, a straight mid-block
# run, and a mirrored flare at the end.
#
# The flares reach +/-70 ft, and `cscl_width_ft=50.0` sets
# max_perp = max(45, 50*1.5) = 75 — so the flare samples SURVIVE the
# perpendicular gate and actually reach the spread computation. That is the
# point of the fixture: it must exercise the spread gate, not the max_perp gate,
# which is why the untrimmed test asserts the spread genuinely exceeds
# SPREAD_GATE_FT rather than assuming it.
#
# The flare zone is 20 ft wide against the 25 ft trim, so the trim clears the
# whole corner-return plus a 5 ft margin — no float-rounding of
# centerline.project() can decide the outcome on a boundary sample.
CORNER_CENTERLINE = LineString([(0.0, 0.0), (200.0, 0.0)])
CORNER_NORTH = LineString([(0.0, 70.0), (20.0, 18.0), (180.0, 18.0), (200.0, 70.0)])
CORNER_SOUTH = LineString([(0.0, -70.0), (20.0, -16.0), (180.0, -16.0), (200.0, -70.0)])
CORNER_WIDTH_FT = 50.0


class TestDeriveCleanGeometry:
    """Behaviour case 1: clean flanking curbs -> c/width, calibrated True."""

    def test_clean_flanking_curbs_give_c_and_width(self) -> None:
        north = LineString([(0.0, 16.0), (300.0, 16.0)])
        south = LineString([(0.0, -14.0), (300.0, -14.0)])
        cal = derive_segment_calibration(CENTERLINE, [north, south], cscl_width_ft=30.0)
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
        cal = derive_segment_calibration(CENTERLINE, [north, south], cscl_width_ft=30.0)
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
        cal = derive_segment_calibration(CENTERLINE, [stray], cscl_width_ft=30.0)
        assert cal.calibrated is False
        assert cal.center_offset_c == 0.0
        assert cal.curb_width_ft is None


class TestSpreadGate:
    """The mandatory >12 ft spread gate (spike 007) — the safety boundary.

    Both flanks have samples in these cases, so the ONLY thing separating
    calibrated from non-calibrated is the per-side spread. A widely scattered
    curb (e.g. a divided road / median where two roadbeds' curbs get captured)
    must self-flag as non-calibrated even though c/width are numerically
    computable — that is exactly the geometry that produces a confident-wrong c.
    """

    def test_gate_constant_is_twelve_feet(self) -> None:
        assert SPREAD_GATE_FT == pytest.approx(12.0)

    def test_high_spread_north_curb_is_non_calibrated(self) -> None:
        # A steeply diagonal north curb: sampled offsets sweep ~4..58 ft, giving
        # a per-side pstdev well above 12 ft. Wide street so max_perp=60 keeps
        # every sample (isolating the spread gate, not the range gate).
        scattered_north = LineString([(0.0, 4.0), (300.0, 58.0)])
        tight_south = LineString([(0.0, -16.0), (300.0, -16.0)])
        cal = derive_segment_calibration(
            CENTERLINE, [scattered_north, tight_south], cscl_width_ft=40.0
        )
        assert cal.calibrated is False
        # c blanked despite both buckets being non-empty (do not trust it)
        assert cal.center_offset_c == 0.0
        assert cal.curb_width_ft is None
        # spreads ARE reported (rejection reason stays inspectable) and the
        # north spread is what tripped the gate
        assert cal.spread_n is not None and cal.spread_n > SPREAD_GATE_FT
        assert cal.spread_s is not None

    def test_tight_spread_is_calibrated(self) -> None:
        # Same flanks, but straight (near-zero spread) -> calibrated True.
        tight_north = LineString([(0.0, 18.0), (300.0, 18.0)])
        tight_south = LineString([(0.0, -16.0), (300.0, -16.0)])
        cal = derive_segment_calibration(
            CENTERLINE, [tight_north, tight_south], cscl_width_ft=40.0
        )
        assert cal.calibrated is True
        assert cal.center_offset_c == pytest.approx(1.0)
        assert cal.curb_width_ft == pytest.approx(34.0)
        assert cal.spread_n is not None and cal.spread_n <= SPREAD_GATE_FT
        assert cal.spread_s is not None and cal.spread_s <= SPREAD_GATE_FT


class TestEndpointTrim:
    """The along-span endpoint trim itself (spike 008), on the core function.

    Spike 008 backtested 250 real spread-gate-rejected segments and found that
    intersection corner-return curb curves at each end of a block still satisfy
    the ``0 <= along <= length`` filter while swinging toward the cross street.
    They inflate the per-side spread past ``SPREAD_GATE_FT`` on blocks whose
    MID-BLOCK curb offset is in fact rock-steady — a false rejection. Insetting
    the along-span window by 25 ft at each end drops exactly those samples.

    These tests drive ``derive_segment_calibration`` directly, i.e. the trim
    MATH. The retry POLICY that decides when the trim is allowed to run is
    pinned separately in :class:`TestEndpointRetry`.
    """

    def test_trim_constant_is_twenty_five_feet(self) -> None:
        """D-01: a FIXED 25 ft, deliberately not derived from cscl_width_ft.

        25 ft is the only value with backtest evidence behind it — spike 008
        measured 15 ft and 25 ft (20% vs 26% flip rate through the full
        pipeline). A width-relative formula was floated in that spike's
        limitations section but never measured, so shipping one would be an
        untuned guess wearing the spike's credibility.
        """
        assert ENDPOINT_TRIM_FT == pytest.approx(25.0)

    def test_default_trim_is_a_no_op(self) -> None:
        """The 3-arg call and an explicit 0.0 trim must be indistinguishable.

        This is the floor under D-02: the new parameter may not perturb the
        shipped derivation by a single float. ``SegmentCalibration`` is a frozen
        dataclass, so ``==`` compares every field.
        """
        north = LineString([(0.0, 16.0), (300.0, 16.0)])
        south = LineString([(0.0, -14.0), (300.0, -14.0)])
        implicit = derive_segment_calibration(
            CENTERLINE, [north, south], cscl_width_ft=30.0
        )
        explicit = derive_segment_calibration(
            CENTERLINE, [north, south], cscl_width_ft=30.0, endpoint_trim_ft=0.0
        )
        assert implicit == explicit
        assert implicit.calibrated is True

    def test_corner_flare_trips_spread_gate_untrimmed(self) -> None:
        """The fixture must genuinely FAIL today — otherwise it proves nothing.

        Asserted, not assumed: the corner returns have to clear ``max_perp`` and
        reach the spread computation, and the resulting spread has to actually
        exceed the gate. Both spreads are still reported (the rejection reason
        stays inspectable) while ``c``/width are blanked.
        """
        cal = derive_segment_calibration(
            CORNER_CENTERLINE,
            [CORNER_NORTH, CORNER_SOUTH],
            cscl_width_ft=CORNER_WIDTH_FT,
        )
        assert cal.calibrated is False
        assert cal.center_offset_c == 0.0
        assert cal.curb_width_ft is None
        # Measured: spread_n ~16.98, spread_s ~17.70 -- the corner returns, not
        # the mid-block run, are what blow past the 12 ft gate.
        assert cal.spread_n is not None and cal.spread_n > SPREAD_GATE_FT
        assert cal.spread_s is not None and cal.spread_s > SPREAD_GATE_FT

    def test_trim_excludes_corner_samples_and_calibrates(self) -> None:
        """With the 25 ft trim only the straight mid-block run survives.

        The recovered numbers are the mid-block geometry exactly: north +18,
        south -16 -> c = +1.0, width = 34.0, spreads ~0. This is the whole
        mechanism spike 008 measured, reproduced offline.
        """
        cal = derive_segment_calibration(
            CORNER_CENTERLINE,
            [CORNER_NORTH, CORNER_SOUTH],
            cscl_width_ft=CORNER_WIDTH_FT,
            endpoint_trim_ft=ENDPOINT_TRIM_FT,
        )
        assert cal.calibrated is True
        assert cal.center_offset_c == pytest.approx(1.0)
        assert cal.curb_width_ft == pytest.approx(34.0)
        assert cal.spread_n is not None and cal.spread_n < 0.1
        assert cal.spread_s is not None and cal.spread_s < 0.1

    def test_trim_wider_than_the_block_is_non_calibrated_not_an_error(self) -> None:
        """A block shorter than 2x the trim degenerates safely, it does not raise.

        The window collapses, both buckets come back empty, and the ordinary
        missing-flank path returns non-calibrated with ``None`` spreads. This is
        why no bespoke minimum-length guard exists in production: adding one
        would make it diverge from spike 008's backtested window formula for no
        behavioural gain.
        """
        short = LineString([(0.0, 0.0), (30.0, 0.0)])
        north = LineString([(0.0, 16.0), (30.0, 16.0)])
        south = LineString([(0.0, -14.0), (30.0, -14.0)])
        cal = derive_segment_calibration(
            short, [north, south], cscl_width_ft=30.0, endpoint_trim_ft=ENDPOINT_TRIM_FT
        )
        assert cal.calibrated is False
        assert cal.center_offset_c == 0.0
        assert cal.curb_width_ft is None
        assert cal.spread_n is None
        assert cal.spread_s is None


class TestEndpointRetry:
    """The wrapper's untrimmed-first fallback semantics — the D-02 boundary.

    The trim is a FALLBACK RETRY, never an always-on change. Spike 008 measured
    the trim's effect only on the REJECTED population; it never measured whether
    trimming would shift an already-passing segment's ``center_offset_c`` /
    ``curb_width_ft``. So the ~50k segments the shipped index already calibrates
    must come out byte-for-byte identical, which means the trimmed derivation
    must never even run for them. All three branches are pinned below:
    passes-untrimmed, rescued-by-trim, fails-both.
    """

    def test_passing_segment_is_returned_untouched(self) -> None:
        """A segment that calibrates today is returned verbatim, field-for-field.

        If this ever fails, the citywide index's 50,333 calibrated segments
        would silently move on the next rebuild.
        """
        north = LineString([(0.0, 16.0), (300.0, 16.0)])
        south = LineString([(0.0, -14.0), (300.0, -14.0)])
        plain = derive_segment_calibration(
            CENTERLINE, [north, south], cscl_width_ft=30.0
        )
        retried = derive_segment_calibration_with_endpoint_retry(
            CENTERLINE, [north, south], cscl_width_ft=30.0
        )
        assert plain.calibrated is True
        assert retried == plain

    def test_retry_rescues_corner_contaminated_segment(self) -> None:
        """The headline behaviour: a false rejection becomes a calibration."""
        plain = derive_segment_calibration(
            CORNER_CENTERLINE,
            [CORNER_NORTH, CORNER_SOUTH],
            cscl_width_ft=CORNER_WIDTH_FT,
        )
        retried = derive_segment_calibration_with_endpoint_retry(
            CORNER_CENTERLINE,
            [CORNER_NORTH, CORNER_SOUTH],
            cscl_width_ft=CORNER_WIDTH_FT,
        )
        assert plain.calibrated is False
        assert retried.calibrated is True
        assert retried.center_offset_c == pytest.approx(1.0)
        assert retried.curb_width_ft == pytest.approx(34.0)

    def test_both_passes_failing_returns_the_untrimmed_result(self) -> None:
        """When trimming cannot help, the UNTRIMMED spreads are what get stored.

        A steeply diagonal north curb scatters through the block INTERIOR, not
        at the corners — spike 008's ~74% non-rescuable majority (bus stops,
        loading zones, driveway aprons, divided geometry). Trimming the ends
        narrows the spread (~21.19 -> ~17.11) but never below the gate, so the
        wrapper must hand back the baseline: a still-rejected segment keeps
        reporting the same rejection reason the current index already carries,
        rather than a trimmed number nothing else in the pipeline produced.
        """
        diagonal_north = LineString([(0.0, 2.0), (300.0, 74.0)])
        tight_south = LineString([(0.0, -20.0), (300.0, -20.0)])
        plain = derive_segment_calibration(
            CENTERLINE, [diagonal_north, tight_south], cscl_width_ft=60.0
        )
        trimmed = derive_segment_calibration(
            CENTERLINE,
            [diagonal_north, tight_south],
            cscl_width_ft=60.0,
            endpoint_trim_ft=ENDPOINT_TRIM_FT,
        )
        retried = derive_segment_calibration_with_endpoint_retry(
            CENTERLINE, [diagonal_north, tight_south], cscl_width_ft=60.0
        )
        # Both passes genuinely fail (asserted, so the test cannot pass for the
        # wrong reason if the geometry ever drifts).
        assert plain.calibrated is False
        assert trimmed.calibrated is False
        assert trimmed.spread_n is not None and trimmed.spread_n > SPREAD_GATE_FT
        # ... and the baseline, not the trimmed pass, is what comes back.
        assert retried == plain
        assert retried.spread_n == plain.spread_n

    def test_zero_trim_disables_the_retry(self) -> None:
        """An explicit 0.0 trim opts out: the non-calibrated baseline stands."""
        plain = derive_segment_calibration(
            CORNER_CENTERLINE,
            [CORNER_NORTH, CORNER_SOUTH],
            cscl_width_ft=CORNER_WIDTH_FT,
        )
        retried = derive_segment_calibration_with_endpoint_retry(
            CORNER_CENTERLINE,
            [CORNER_NORTH, CORNER_SOUTH],
            cscl_width_ft=CORNER_WIDTH_FT,
            endpoint_trim_ft=0.0,
        )
        assert retried.calibrated is False
        assert retried == plain
