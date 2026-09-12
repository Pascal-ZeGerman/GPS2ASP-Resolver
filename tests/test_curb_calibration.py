"""Tests for the build-time curb-derivation core (plan 40-05, SC-1).

Synthetic-geometry tests for :func:`derive_segment_calibration`: clean flanking
curbs produce the fitted centre ``c`` and true width; a missing flank or a
high per-side spread self-flags as non-calibrated. No network — the geometry is
constructed in-process with shapely ``LineString`` fixtures in EPSG:2263 feet.
"""

from __future__ import annotations

import statistics

import pytest
from shapely.geometry import LineString

from gps2asp.resolver.curb_calibration import (
    CURB_SAMPLE_STEP_FT,
    ENDPOINT_TRIM_FT,
    MAJORITY_THRESHOLD,
    SPREAD_GATE_FT,
    SegmentCalibration,
    derive_segment_calibration,
    derive_segment_calibration_with_endpoint_retry,
    derive_segment_calibration_with_fallback_retries,
    widest_gap_majority,
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

# --- Mid-block apron fixture (the spike 009 mechanism) ---
#
# The failure mode spike 008 explicitly could NOT fix: spread distributed through
# the block INTERIOR rather than concentrated at its ends. A straight north curb
# run plus a short, detached curb cluster bulging outward mid-block — a driveway
# apron / bus-stop / loading-zone curb.
#
# Every number here is load-bearing:
#
# * The apron is a SEPARATE, detached LineString, not a kink in the main run.
#   That is how NYC planimetrics actually digitize one (its own feature), and a
#   kink would additionally emit ramp samples at intermediate offsets — filling
#   in the very gap the widest-gap split keys on, so the fixture would stop
#   exercising the mechanism under test.
# * It spans x=120..160, deep in the block interior and far from both 25 ft end
#   zones. That is exactly why the endpoint trim cannot touch it: this fixture is
#   drawn from spike 008's non-rescuable ~74%.
# * BULGE_WIDTH_FT = 50.0 sets max_perp = max(45, 50*1.5) = 75, so the 65 ft apron
#   samples SURVIVE the perpendicular gate and reach the spread computation. On a
#   narrower street they would be clipped and the fixture would exercise the
#   max_perp gate instead of the spread gate.
# * The block is 300 ft, NOT the corner fixture's 200 ft, and the margin matters.
#   The 40 ft apron yields int(40/6)+1 = 7 samples while the 25 ft-trimmed main
#   run yields 41, so the dominant north share is 41/48 ~= 0.854 — clear of the
#   0.8 threshold. On a 200 ft block the same apron pushes the share to ~0.78 and
#   0.8 correctly REFUSES to clean, so the fixture would silently test the refusal
#   path instead. The span has to leave headroom above the threshold.
# * Mid-block geometry is north +18 / south -16, so a successful rescue recovers
#   c = +1.0 and width = 34.0 — deliberately the same target CORNER_* recovers,
#   making the two rescue paths directly comparable.
BULGE_CENTERLINE = LineString([(0.0, 0.0), (300.0, 0.0)])
BULGE_NORTH_MAIN = LineString([(0.0, 18.0), (300.0, 18.0)])
BULGE_NORTH_APRON = LineString([(120.0, 65.0), (160.0, 65.0)])
BULGE_SOUTH = LineString([(0.0, -16.0), (300.0, -16.0)])
BULGE_WIDTH_FT = 50.0

# --- Genuinely divided geometry (the REFUSAL path) ---
#
# Two REAL curb lines on the north flank, each spanning the whole block, so the
# widest-gap split comes out exactly even (share 0.50) and nothing may be cleaned.
# This is the geometry the 0.8 threshold exists to protect: a divided road /
# service road / median, where discarding either "cluster" would produce a
# confident-WRONG c. It must stay rejected so the bad geometry self-flags.
#
# Reused with BULGE_CENTERLINE / BULGE_SOUTH / BULGE_WIDTH_FT, so the ONLY
# difference from the apron fixture is that the outer north curb spans the full
# block instead of 40 ft of it — i.e. the share, which is the whole decision.
DIVIDED_NORTH_INNER = LineString([(0.0, 18.0), (300.0, 18.0)])
DIVIDED_NORTH_OUTER = LineString([(0.0, 65.0), (300.0, 65.0)])


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


class TestWidestGapMajority:
    """The widest-gap split in isolation (spike 009), without any geometry.

    This mirrors the split inside ``calibration.estimate_center_offset`` but
    carries a DIFFERENT contract, which is precisely why ``curb_calibration``
    re-implements it rather than importing it: the production estimator always
    separates two REAL parking lanes and returns a centre between them, whereas
    this one makes a dominant-cluster-versus-contamination decision and must
    therefore also report HOW lopsided the split was, so a caller can threshold
    on it. Mirroring and saying so is the project's convention for this case.
    """

    def test_threshold_constant_is_point_eight(self) -> None:
        """0.8, not 0.6 — the trust/yield tradeoff has a measured answer.

        Spike 009 swept 0.6 / 0.7 / 0.8 over 61 mid-block-distributed failures.
        0.6 recovered more segments (31% vs 18% through the full pipeline) but only
        73% of the ones clearing the spread gate also survived the INDEPENDENT
        roadbed cross-check, against 92% at 0.8 — so 0.6's extra yield is mostly
        segments the independent source does not corroborate, which is exactly the
        confident-wrong-c risk the spread gate exists to prevent. Loosening this
        constant would trade the technique's only external corroboration for yield.
        """
        assert MAJORITY_THRESHOLD == pytest.approx(0.8)

    def test_fewer_than_two_values_returns_input_unchanged(self) -> None:
        """Degenerate input has nothing to split, so share is 1.0 by definition.

        If this regressed to raising (``max()`` over an empty range) the reduction
        would crash on any side holding a single sample — a routine occurrence on
        short blocks and heavily-trimmed windows.
        """
        assert widest_gap_majority([]) == ([], 1.0)
        assert widest_gap_majority([5.0]) == ([5.0], 1.0)

    def test_splits_at_the_single_widest_gap_and_returns_the_larger_side(self) -> None:
        """A tight cluster plus one far outlier: the cluster wins, share 0.75.

        This is the mechanism in miniature. If the split ever keyed on something
        other than the single largest adjacent gap, a minority apron cluster would
        stop being separable from the real curb run.
        """
        assert widest_gap_majority([1.0, 1.1, 1.2, 9.0]) == ([1.0, 1.1, 1.2], 0.75)

    def test_even_split_reports_a_half_share(self) -> None:
        """Two equal clusters report 0.50 — the input the threshold must refuse.

        0.50 < 0.8, so the caller leaves the side whole. A regression that reported
        a high share here would silently clean genuinely divided geometry, which is
        the single worst outcome available to this feature.
        """
        _, share = widest_gap_majority([1.0, 1.0, 9.0, 9.0])
        assert share == pytest.approx(0.5)

    def test_size_tie_prefers_the_low_cluster(self) -> None:
        """``len(low) >= len(high)`` — pinned so the helper stays deterministic.

        Spike 009's helper resolves an exact size tie toward the LOW cluster. If
        production drifted to preferring the high side, a measured result would no
        longer be reproducible from the spike that justified shipping it.
        """
        assert widest_gap_majority([1.0, 1.0, 9.0, 9.0]) == ([1.0, 1.0], 0.5)

    def test_uniform_values_split_arbitrarily_but_harmlessly(self) -> None:
        """A perfectly uniform side splits arbitrarily — and it does not matter.

        Every adjacent gap is 0.0, so ``max`` returns index 0 and the split point
        is meaningless: low holds 1 value, high holds the rest, share = (n-1)/n.
        This WILL happen in production on a straight curb, and a reader must not
        mistake it for a bug — both clusters carry the same value, so the reduced
        side's median and spread are identical to the full side's. Reduction on
        such a side is a no-op, not a distortion.
        """
        values = [7.0, 7.0, 7.0, 7.0, 7.0]
        majority, share = widest_gap_majority(values)
        assert share == pytest.approx(4 / 5)
        assert statistics.median(majority) == pytest.approx(statistics.median(values))
        assert statistics.pstdev(majority) == pytest.approx(statistics.pstdev(values))


class TestMajorityCluster:
    """The per-side cluster reduction inside ``derive_segment_calibration``.

    The reduction is a PRE-PROCESSING step in front of the unchanged spread gate,
    not a new trust mechanism: each side is independently reduced to its dominant
    widest-gap cluster only when that cluster holds >= 0.8 of the side's samples,
    and the gate then re-runs against whatever survived. These tests drive the core
    function directly, i.e. the reduction MATH. The three-tier POLICY that decides
    when the reduction is allowed to run at all is pinned in
    :class:`TestMajorityClusterRetry`.
    """

    def test_default_is_a_no_op(self) -> None:
        """The 3-arg call and an explicit ``None`` threshold are indistinguishable.

        This is the floor under the whole task: the new parameter may not perturb
        the shipped derivation by a single float, or the ~50k segments the shipped
        index already calibrates would move on the next rebuild.
        ``SegmentCalibration`` is a frozen dataclass, so ``==`` compares every
        field.
        """
        north = LineString([(0.0, 16.0), (300.0, 16.0)])
        south = LineString([(0.0, -14.0), (300.0, -14.0)])
        implicit = derive_segment_calibration(
            CENTERLINE, [north, south], cscl_width_ft=30.0
        )
        explicit_none = derive_segment_calibration(
            CENTERLINE, [north, south], cscl_width_ft=30.0, majority_threshold=None
        )
        zero_trim = derive_segment_calibration(
            CENTERLINE, [north, south], cscl_width_ft=30.0, endpoint_trim_ft=0.0
        )
        assert implicit.calibrated is True
        assert implicit == explicit_none
        assert implicit == zero_trim

    def test_mid_block_apron_trips_spread_gate_untrimmed(self) -> None:
        """The fixture must genuinely FAIL today — otherwise it proves nothing.

        Asserted, not assumed: the 65 ft apron samples have to clear ``max_perp``
        and reach the spread computation, and the resulting north spread has to
        actually exceed the gate. ``c``/width are blanked while both spreads stay
        reported, so the rejection reason remains inspectable.
        """
        cal = derive_segment_calibration(
            BULGE_CENTERLINE,
            [BULGE_NORTH_MAIN, BULGE_NORTH_APRON, BULGE_SOUTH],
            cscl_width_ft=BULGE_WIDTH_FT,
        )
        assert cal.calibrated is False
        assert cal.center_offset_c == 0.0
        assert cal.curb_width_ft is None
        # Measured: spread_n ~15.31, spread_s ~0.0 -- the 7 apron samples alone
        # drag the north side past the 12 ft gate; the south flank is pristine.
        assert cal.spread_n is not None and cal.spread_n > SPREAD_GATE_FT
        assert cal.spread_s is not None

    def test_endpoint_trim_alone_cannot_rescue_the_apron(self) -> None:
        """The test that makes this whole task necessary.

        Spike 008's validated trim is powerless here: the apron sits at x=120..160,
        nowhere near the 25 ft end zones. Worse, the trim actually makes the north
        spread SLIGHTLY WORSE (~15.31 -> ~16.59) because it removes 10 GOOD
        mid-block samples while leaving every single apron sample in place, raising
        the contaminated fraction of the pool. If this test ever started passing,
        the apron fixture would no longer represent spike 008's non-rescuable ~74%
        and every claim below it would be testing the trim instead.
        """
        cal = derive_segment_calibration(
            BULGE_CENTERLINE,
            [BULGE_NORTH_MAIN, BULGE_NORTH_APRON, BULGE_SOUTH],
            cscl_width_ft=BULGE_WIDTH_FT,
            endpoint_trim_ft=ENDPOINT_TRIM_FT,
        )
        assert cal.calibrated is False
        # Measured: spread_n ~16.59 trimmed vs ~15.31 untrimmed.
        assert cal.spread_n is not None and cal.spread_n > SPREAD_GATE_FT

    def test_trim_plus_majority_cluster_recovers_mid_block_geometry(self) -> None:
        """The headline mechanism: the apron cluster is discounted, c is recovered.

        Measured: 48 pooled north samples under the trim, dominant share 0.854
        (41 main-run samples vs 7 apron), which clears 0.8 -> the north side is
        reduced to its main run and the recovered numbers are the mid-block
        geometry exactly (north +18, south -16).
        """
        cal = derive_segment_calibration(
            BULGE_CENTERLINE,
            [BULGE_NORTH_MAIN, BULGE_NORTH_APRON, BULGE_SOUTH],
            cscl_width_ft=BULGE_WIDTH_FT,
            endpoint_trim_ft=ENDPOINT_TRIM_FT,
            majority_threshold=MAJORITY_THRESHOLD,
        )
        assert cal.calibrated is True
        assert cal.center_offset_c == pytest.approx(1.0)
        assert cal.curb_width_ft == pytest.approx(34.0)
        assert cal.spread_n is not None and cal.spread_n < 0.1
        assert cal.spread_s is not None and cal.spread_s < 0.1

    def test_near_even_split_is_left_rejected(self) -> None:
        """Divided geometry must SELF-FLAG, never be silently cleaned.

        Two full-length north curbs split exactly evenly (measured share 0.50,
        82 pooled samples), which is below 0.8 — so the side is used WHOLE, the
        unchanged spread gate rejects it, and the measured spreads are still
        reported. Discarding either "cluster" here would produce a confident-WRONG
        c on exactly the divided-road geometry the spread gate was introduced to
        catch, so this refusal is the safety property of the feature rather than a
        missed opportunity.
        """
        cal = derive_segment_calibration(
            BULGE_CENTERLINE,
            [DIVIDED_NORTH_INNER, DIVIDED_NORTH_OUTER, BULGE_SOUTH],
            cscl_width_ft=BULGE_WIDTH_FT,
            endpoint_trim_ft=ENDPOINT_TRIM_FT,
            majority_threshold=MAJORITY_THRESHOLD,
        )
        assert cal.calibrated is False
        assert cal.center_offset_c == 0.0
        assert cal.curb_width_ft is None
        # Measured: spread_n ~23.5 (uncleaned), spread_s ~0.0.
        assert cal.spread_n is not None and cal.spread_n > SPREAD_GATE_FT
        assert cal.spread_s is not None

    def test_threshold_is_load_bearing(self) -> None:
        """0.8 is strictly the more conservative of spike 009's swept values.

        Same fixture with a LONGER apron (x=100..220): 62 pooled north samples
        under the trim, dominant share ~0.661. That is refused at 0.8 and accepted
        at 0.6 — so the shipped constant is demonstrably not inert, and loosening
        it to 0.6 would start cleaning sides this fixture shows are a third
        contaminated. It is the 0.6 behaviour whose roadbed-survival rate spike 009
        measured at 73% against 0.8's 92%.
        """
        long_apron = LineString([(100.0, 65.0), (220.0, 65.0)])
        curbs = [BULGE_NORTH_MAIN, long_apron, BULGE_SOUTH]
        strict = derive_segment_calibration(
            BULGE_CENTERLINE,
            curbs,
            cscl_width_ft=BULGE_WIDTH_FT,
            endpoint_trim_ft=ENDPOINT_TRIM_FT,
            majority_threshold=0.8,
        )
        loose = derive_segment_calibration(
            BULGE_CENTERLINE,
            curbs,
            cscl_width_ft=BULGE_WIDTH_FT,
            endpoint_trim_ft=ENDPOINT_TRIM_FT,
            majority_threshold=0.6,
        )
        # Measured: spread_n ~22.24 at 0.8 (uncleaned) vs ~0.0 at 0.6 (cleaned).
        assert strict.calibrated is False
        assert loose.calibrated is True
        assert loose.center_offset_c == pytest.approx(1.0)
        assert loose.curb_width_ft == pytest.approx(34.0)


class TestMajorityClusterRetry:
    """The three-tier fallback policy — strictly ordered, strictly a fallback.

    The tiers are (a) untrimmed, (b) one 25 ft endpoint-trim retry, (c) one
    majority-cluster-at-0.8 retry ON TOP of those trimmed samples. Spike 009
    measured the reduction layered on the validated trim and NEVER as an
    alternative to it, which is why tier (c) is unreachable without tier (b)'s
    trim. And an already-calibrated segment must never be recomputed: neither
    spike measured what trimming or cleaning would do to a PASSING segment's
    ``center_offset_c`` / ``curb_width_ft``, so the numbers the shipped index
    already carries for ~50k segments have to be returned verbatim.
    """

    def test_passing_segment_is_returned_untouched(self) -> None:
        """A segment that calibrates today comes back verbatim, field-for-field.

        If this ever fails, a rebuild would silently move the 50,334 calibrated
        segments the shipped index carries.
        """
        north = LineString([(0.0, 16.0), (300.0, 16.0)])
        south = LineString([(0.0, -14.0), (300.0, -14.0)])
        plain = derive_segment_calibration(
            CENTERLINE, [north, south], cscl_width_ft=30.0
        )
        chained = derive_segment_calibration_with_fallback_retries(
            CENTERLINE, [north, south], cscl_width_ft=30.0
        )
        assert plain.calibrated is True
        assert chained == plain

    def test_trim_rescued_segment_matches_the_two_tier_wrapper(self) -> None:
        """A tier-(b) rescue is byte-identical to what shipped in 260907-c5d.

        The corner fixture is rescued by the trim alone, so tier (c) must neither
        run nor perturb the result — otherwise the endpoint trim's own measured
        yield would no longer describe what production does.
        """
        two_tier = derive_segment_calibration_with_endpoint_retry(
            CORNER_CENTERLINE,
            [CORNER_NORTH, CORNER_SOUTH],
            cscl_width_ft=CORNER_WIDTH_FT,
        )
        three_tier = derive_segment_calibration_with_fallback_retries(
            CORNER_CENTERLINE,
            [CORNER_NORTH, CORNER_SOUTH],
            cscl_width_ft=CORNER_WIDTH_FT,
        )
        assert two_tier.calibrated is True
        assert three_tier == two_tier

    def test_apron_segment_is_rescued_by_the_third_tier(self) -> None:
        """The headline behaviour, asserted against the tier it must come from.

        The two-tier wrapper is asserted non-calibrated FIRST, so this cannot pass
        because the trim happened to fix it — the rescue is attributable to tier
        (c) alone.
        """
        curbs = [BULGE_NORTH_MAIN, BULGE_NORTH_APRON, BULGE_SOUTH]
        two_tier = derive_segment_calibration_with_endpoint_retry(
            BULGE_CENTERLINE, curbs, cscl_width_ft=BULGE_WIDTH_FT
        )
        three_tier = derive_segment_calibration_with_fallback_retries(
            BULGE_CENTERLINE, curbs, cscl_width_ft=BULGE_WIDTH_FT
        )
        assert two_tier.calibrated is False
        assert three_tier.calibrated is True
        assert three_tier.center_offset_c == pytest.approx(1.0)
        assert three_tier.curb_width_ft == pytest.approx(34.0)

    def test_all_three_tiers_failing_returns_the_untrimmed_baseline(self) -> None:
        """When nothing can help, the UNTRIMMED spreads are what get stored.

        The divided fixture fails all three tiers. The wrapper must hand back the
        untrimmed baseline, so a still-rejected segment keeps reporting the same
        rejection reason the shipped index already carries rather than a trimmed or
        cleaned number nothing else in the pipeline produced.
        """
        curbs = [DIVIDED_NORTH_INNER, DIVIDED_NORTH_OUTER, BULGE_SOUTH]
        plain = derive_segment_calibration(
            BULGE_CENTERLINE, curbs, cscl_width_ft=BULGE_WIDTH_FT
        )
        chained = derive_segment_calibration_with_fallback_retries(
            BULGE_CENTERLINE, curbs, cscl_width_ft=BULGE_WIDTH_FT
        )
        assert plain.calibrated is False
        assert chained == plain
        assert chained.spread_n == plain.spread_n

    def test_none_threshold_disables_the_third_tier(self) -> None:
        """An explicit ``None`` threshold opts out of the cleaning entirely."""
        curbs = [BULGE_NORTH_MAIN, BULGE_NORTH_APRON, BULGE_SOUTH]
        two_tier = derive_segment_calibration_with_endpoint_retry(
            BULGE_CENTERLINE, curbs, cscl_width_ft=BULGE_WIDTH_FT
        )
        chained = derive_segment_calibration_with_fallback_retries(
            BULGE_CENTERLINE,
            curbs,
            cscl_width_ft=BULGE_WIDTH_FT,
            majority_threshold=None,
        )
        assert two_tier.calibrated is False
        assert chained == two_tier

    def test_zero_trim_also_disables_the_third_tier(self) -> None:
        """A zero trim disables the cleaning with it, deliberately.

        Spike 009 measured the majority-cluster reduction layered ON TOP of spike
        008's validated 25 ft trim, and never standalone. Majority-without-trim is
        a combination for which there is no evidence at all, so production does not
        ship it: disabling the trim disables tier (c) too.
        """
        curbs = [BULGE_NORTH_MAIN, BULGE_NORTH_APRON, BULGE_SOUTH]
        plain = derive_segment_calibration(
            BULGE_CENTERLINE, curbs, cscl_width_ft=BULGE_WIDTH_FT
        )
        chained = derive_segment_calibration_with_fallback_retries(
            BULGE_CENTERLINE, curbs, cscl_width_ft=BULGE_WIDTH_FT, endpoint_trim_ft=0.0
        )
        assert chained.calibrated is False
        assert chained == plain
