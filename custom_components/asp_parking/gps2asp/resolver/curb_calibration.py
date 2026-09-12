"""Build-time curb-derivation core for per-segment side-of-street calibration (SC-1).

From a CSCL segment centerline plus its flanking NYC planimetric curb lines
(already projected to EPSG:2263 State Plane feet), derive the fitted centre
offset ``c``, the true curb-to-curb width, the per-side sample spreads, and the
spread-gated ``calibrated`` flag. This is the deterministic, unit-testable heart
of the method proven in spikes 005 (single segment) and 007 (citywide batch).

The algorithm (spike 005 ``derive.py`` / spike 007 ``curb_c``):

1. For each curb line, sample every ``sample_step_ft`` and compute the signed
   perpendicular offset against the centerline using the SAME convention as the
   resolver (:func:`gps2asp.resolver.side_resolver.signed_offset`, +ve = LEFT/N).
2. Keep a sample only when its projection lands within the along-span window
   AND its offset is within ``max_perp = max(45, cscl_width * 1.5)`` feet — this
   rejects curbs belonging to cross-streets or a parallel block. The window is
   ``[0, centerline.length]`` by default; it can be inset at each end by
   ``endpoint_trim_ft``, which the FALLBACK RETRY path
   (:func:`derive_segment_calibration_with_endpoint_retry`) uses to drop the
   intersection corner-return curves (spike 008).
3. Bucket kept samples by sign into north (offset > 0) / south (offset < 0).
   Optionally — only when ``majority_threshold`` is supplied, which only the
   THIRD fallback tier does — each side is then reduced to its dominant
   widest-gap cluster if that cluster holds at least ``majority_threshold`` of
   that side's samples (:func:`widest_gap_majority`, spike 009). This discards a
   minority of locally-bulging samples (bus stop, loading zone, driveway apron)
   BEFORE the medians and the spread gate are computed.
4. ``c = (median(north) + median(south)) / 2`` (true centre vs the CSCL line);
   ``width = median(north) - median(south)`` (true curb-to-curb width).

**The spread gate is mandatory (spike 007).** ``spread_n`` / ``spread_s`` are the
per-side population stdevs. When ``max(spread_n, spread_s) > SPREAD_GATE_FT`` the
geometry is complex (median, divided road, service road) and ``c`` is NOT to be
trusted: the segment is marked non-calibrated and ``c`` is blanked to 0.0. A
segment missing a curb on either flank is likewise non-calibrated. This gate is
the whole reason the method is safe at scale — it lets bad geometry self-flag.

Two optional rescue layers sit in FRONT of that gate, never replacing it, and
:func:`derive_segment_calibration_with_fallback_retries` chains them in strict
order: (a) the plain untrimmed derivation — today's shipped behaviour — then (b)
one retry with the 25 ft along-span endpoint trim (spike 008, the intersection
corner-return failure mode), then (c) one retry adding the per-side
dominant-cluster reduction on top of those trimmed samples (spike 009, the
mid-block-bulge failure mode). Each tier runs only when the previous one leaves
the segment non-calibrated, so a segment that calibrates today is returned
verbatim and never recomputed.

No network here. The caller (plan 40-08, the offline index build) fetches the
curb lines and, for accepted segments, cross-validates against the roadbed
polygon before writing the calibration fields into ``segments.json``.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from shapely.geometry import LineString

from .side_resolver import signed_offset

# Per-side spread threshold (feet). max(spread_n, spread_s) > SPREAD_GATE_FT
# marks the segment non-calibrated (spike 007 CLEAN_CURB_SPREAD). Left
# un-annotated (inferred float) so the literal `SPREAD_GATE_FT = 12` remains
# grep-visible for the plan's acceptance check.
SPREAD_GATE_FT = 12.0

# Curb sampling interval along each curb line (feet); spike 007 SAMPLE_STEP_FT.
CURB_SAMPLE_STEP_FT = 6.0

# Along-span inset applied at EACH end of the centerline on the FALLBACK RETRY
# only (see derive_segment_calibration_with_endpoint_retry) — never on the
# default derivation. Intersection corner-return curb curves live in these end
# zones: they satisfy `0 <= along <= length` while swinging toward the cross
# street, inflating the per-side spread past SPREAD_GATE_FT on blocks whose
# mid-block curb offset is in fact rock-steady.
#
# A FIXED 25 ft, deliberately NOT derived from cscl_width_ft: 25 ft is the only
# value with backtest evidence. Spike 008 backtested 15 ft and 25 ft over 250
# real spread-gate-rejected segments — 25 ft flipped 26% of genuine rejections
# to calibrated through the full pipeline vs 20% for 15 ft. A width-relative
# formula was floated in that spike's limitations section but was never
# measured, so it is deliberately not implemented here.
ENDPOINT_TRIM_FT = 25.0

# Share of ONE side's curb samples that its dominant widest-gap cluster must hold
# before that cluster is trusted as "the curb" and the rest discarded as
# contamination. Used on the THIRD fallback tier only (see
# derive_segment_calibration_with_fallback_retries) — never on the default
# derivation, where the reduction is off entirely.
#
# A FIXED 0.8, and deliberately NOT 0.6: spike 009 swept 0.6 / 0.7 / 0.8 over the
# 61 mid-block-DISTRIBUTED spread-gate failures that spike 008's endpoint trim
# could not touch. 0.6 recovered more segments (31% vs 18% through the full
# pipeline) but only 73% of the ones clearing the spread gate also survived the
# INDEPENDENT roadbed cross-check, against 92% at 0.8. The extra yield at 0.6 is
# therefore mostly segments the independent source does not corroborate — exactly
# the confident-wrong-c miscalibration the spread gate exists to prevent. A
# rising roadbed-survival rate as the threshold tightens is the evidence the
# technique is doing something real rather than cherry-picking noise past a gate.
#
# Open limitation, carried over from that spike: 0.8 was chosen by inspecting
# three points, not by a grid search or a cross-validated fit, and the n=61
# population was inherited from spike 008's single 250-sample seed. So like
# ENDPOINT_TRIM_FT this is an evidence-backed constant rather than a tuned one,
# and like it, it is a MODULE constant — not a per-segment or per-call tunable,
# and never derived from any segment property. Left un-annotated (inferred float)
# so the literal `MAJORITY_THRESHOLD = 0.8` stays grep-visible.
MAJORITY_THRESHOLD = 0.8


@dataclass(frozen=True)
class SegmentCalibration:
    """Result of deriving one segment's calibration from flanking curbs.

    The field names/types mirror the ``segments.json`` calibration contract
    consumed by :class:`gps2asp.resolver.models.SegmentCandidate` (plan 40-04):
    ``center_offset_c`` (float), ``curb_width_ft`` / ``spread_n`` / ``spread_s``
    (float | None), ``calibrated`` (bool).

    Non-calibrated results (missing flank OR spread-gate rejection) always carry
    ``center_offset_c == 0.0`` and ``curb_width_ft is None`` so the resolver
    falls through to plain CSCL (``c = 0``). A missing flank reports
    ``spread_n``/``spread_s`` as ``None`` (nothing was measurable); a spread-gate
    rejection reports the measured spreads so the reason is inspectable.
    """

    center_offset_c: float
    curb_width_ft: float | None
    spread_n: float | None
    spread_s: float | None
    calibrated: bool


def widest_gap_majority(values: list[float]) -> tuple[list[float], float]:
    """Split one side's offsets at their widest gap; return the dominant cluster.

    Sorts the values, finds the single largest adjacent gap, slices into a low and
    a high cluster there, and returns the LARGER cluster together with its share
    of the total. A size tie prefers the LOW cluster (``len(low) >= len(high)``),
    which keeps the helper deterministic and identical to spike 009's.

    This function ONLY performs the split and reports the share. The threshold
    decision — is this cluster dominant enough to trust as the curb? — belongs to
    the caller (see ``majority_threshold`` on
    :func:`derive_segment_calibration`).

    This mirrors the widest-gap split inside
    :func:`gps2asp.resolver.calibration.estimate_center_offset`, and the mirroring
    is deliberate: that function is NOT imported here, because the two contracts
    differ. ``estimate_center_offset`` always splits settled-park offsets into two
    REAL parking lanes and returns a centre BETWEEN them; this split is a
    dominant-cluster-versus-contamination decision that returns ONE surviving
    cluster plus a share for a threshold test, and must therefore also answer
    "how lopsided was the split?" — a question the production estimator has no
    reason to ask. Mirroring the algorithm and saying so is the project's
    convention for exactly this case (``.planning/spikes/CONVENTIONS.md``).

    Fewer than two values returns the input unchanged with share ``1.0`` —
    nothing to split.

    One harmless degenerate case WILL be hit in production and must not be
    mistaken for a bug: on a perfectly uniform side every adjacent gap is ``0.0``,
    so ``max`` returns index 0 and the split point is arbitrary. But both clusters
    then carry the same value, so the reduced side's median and spread are
    identical to the full side's. Reduction on such a side is a no-op, not a
    distortion.

    Args:
        values: One side's signed perpendicular curb offsets (feet).

    Returns:
        ``(majority_cluster, share)`` where ``share`` is
        ``len(majority_cluster) / len(values)`` — in ``(0.5, 1.0]`` for any input
        of two or more values.
    """
    if len(values) < 2:
        return values, 1.0
    ordered = sorted(values)
    split_index = max(
        range(len(ordered) - 1), key=lambda i: ordered[i + 1] - ordered[i]
    )
    low = ordered[: split_index + 1]
    high = ordered[split_index + 1 :]
    majority = low if len(low) >= len(high) else high
    return majority, len(majority) / len(ordered)


def derive_segment_calibration(
    centerline: LineString,
    curb_lines: list[LineString],
    cscl_width_ft: float,
    sample_step_ft: float = CURB_SAMPLE_STEP_FT,
    endpoint_trim_ft: float = 0.0,
    majority_threshold: float | None = None,
) -> SegmentCalibration:
    """Derive a segment's centre offset ``c`` and true width from flanking curbs.

    Args:
        centerline: CSCL segment centerline (EPSG:2263 State Plane feet).
        curb_lines: Candidate flanking curb ``LineString``\\ s (same CRS). May
            include stray curbs from cross-streets / adjacent blocks; these are
            filtered out by the along-span and ``max_perp`` gates.
        cscl_width_ft: The segment's nominal CSCL street width (feet); sets
            ``max_perp = max(45, cscl_width_ft * 1.5)``.
        sample_step_ft: Sampling interval along each curb line (feet).
        endpoint_trim_ft: Insets the along-span window by this many feet at EACH
            end, excluding samples that project within that distance of either
            endpoint — where the intersection corner-return curves live (spike
            008). The ``0.0`` default reproduces the shipped ``[0, length]``
            behaviour exactly, to the float. Callers wanting the trim should
            prefer :func:`derive_segment_calibration_with_endpoint_retry` over
            passing this directly, so an already-calibrated segment is never
            recomputed.
        majority_threshold: When not ``None``, each side is independently reduced
            to its dominant widest-gap cluster (:func:`widest_gap_majority`) if
            that cluster holds at least this share of the side's samples; a side
            whose split comes out closer to even than the threshold is used
            WHOLE. The reduction happens AFTER the along-span and ``max_perp``
            filters and BEFORE the medians and the spread gate, so the unchanged
            gate is re-run against the possibly-cleaned samples — this is a
            pre-processing step in FRONT of the two existing independent checks,
            not a new trust mechanism. ``None`` (the default) means NO reduction
            and reproduces today's shipped behaviour to the float; ``None`` is
            used rather than a ``0.0`` sentinel precisely because
            ``share >= 0.0`` is always true, so ``0.0`` would mean "always
            clean" — the opposite of an off switch. Callers wanting the
            reduction should prefer
            :func:`derive_segment_calibration_with_fallback_retries`, so an
            already-calibrated segment is never recomputed.

    Returns:
        A :class:`SegmentCalibration`. ``calibrated`` is ``True`` only when both
        flanks have samples AND ``max(spread_n, spread_s) <= SPREAD_GATE_FT``;
        otherwise ``center_offset_c`` is ``0.0`` and ``curb_width_ft`` is
        ``None`` (proven-safe plain-CSCL fallback).
    """
    max_perp = max(45.0, cscl_width_ft * 1.5)
    length = centerline.length
    # With the 0.0 default this is exactly [0.0, length] — max(0.0, length) is
    # length for any real centerline — so no existing caller shifts by a float.
    along_lo = endpoint_trim_ft
    along_hi = max(endpoint_trim_ft, length - endpoint_trim_ft)

    north: list[float] = []
    south: list[float] = []
    for line in curb_lines:
        steps = max(2, int(line.length / sample_step_ft))
        for i in range(steps + 1):
            p = line.interpolate(i / steps, normalized=True)
            along = centerline.project(p)
            off = signed_offset(p.x, p.y, centerline)
            if along_lo <= along <= along_hi and abs(off) <= max_perp:
                (north if off > 0 else south).append(off)

    # A missing flank cannot yield a two-sided centre -> non-calibrated. Report
    # spreads as None: nothing was measurable on the empty side(s).
    if not north or not south:
        return SegmentCalibration(
            center_offset_c=0.0,
            curb_width_ft=None,
            spread_n=None,
            spread_s=None,
            calibrated=False,
        )

    # Optional per-side dominant-cluster reduction (spike 009), third fallback
    # tier only. Each side decides independently: a side whose widest-gap split is
    # lopsided enough is reduced to its dominant cluster, a side closer to even is
    # used whole. With the None default neither list is touched.
    north_used, south_used = north, south
    if majority_threshold is not None:
        north_majority, north_share = widest_gap_majority(north)
        south_majority, south_share = widest_gap_majority(south)
        north_used = north_majority if north_share >= majority_threshold else north
        south_used = south_majority if south_share >= majority_threshold else south

    med_n = statistics.median(north_used)
    med_s = statistics.median(south_used)
    center_offset_c = round((med_n + med_s) / 2.0, 2)
    curb_width_ft = round(med_n - med_s, 1)
    spread_n = round(statistics.pstdev(north_used), 2) if len(north_used) > 1 else 0.0
    spread_s = round(statistics.pstdev(south_used), 2) if len(south_used) > 1 else 0.0

    # Mandatory spread gate (spike 007): complex geometry (median/divided road)
    # produces a confident-WRONG c. Blank c/width but keep the measured spreads
    # so the rejection reason stays inspectable.
    if max(spread_n, spread_s) > SPREAD_GATE_FT:
        return SegmentCalibration(
            center_offset_c=0.0,
            curb_width_ft=None,
            spread_n=spread_n,
            spread_s=spread_s,
            calibrated=False,
        )

    return SegmentCalibration(
        center_offset_c=center_offset_c,
        curb_width_ft=curb_width_ft,
        spread_n=spread_n,
        spread_s=spread_s,
        calibrated=True,
    )


def derive_segment_calibration_with_endpoint_retry(
    centerline: LineString,
    curb_lines: list[LineString],
    cscl_width_ft: float,
    sample_step_ft: float = CURB_SAMPLE_STEP_FT,
    endpoint_trim_ft: float = ENDPOINT_TRIM_FT,
) -> SegmentCalibration:
    """Derive a segment's calibration, retrying ONCE with an endpoint trim.

    **This is a fallback retry, never an always-on change.** The untrimmed
    derivation — today's shipped behaviour — runs first and its result is
    returned verbatim whenever it is calibrated. A segment that passes today is
    therefore never recomputed, so its ``center_offset_c`` / ``curb_width_ft``
    cannot shift. That guarantee matters: spike 008 only measured the trim's
    effect on the REJECTED population; it never measured whether trimming would
    move an already-passing segment's numbers.

    Only when the untrimmed pass is non-calibrated is the derivation retried
    once with ``endpoint_trim_ft`` applied to the along-span window, dropping
    the intersection corner-return curves at each end of the block. The trimmed
    result is returned only if it flips to calibrated; otherwise the UNTRIMMED
    baseline is returned, so a still-rejected segment keeps reporting the
    untrimmed ``spread_n`` / ``spread_s`` that the shipped index already stores
    as its rejection reason.

    Measured yield (spike 008, 250 real spread-gate-rejected segments): ~26% of
    genuine, currently-reproducible rejections flip to calibrated through the
    FULL pipeline (this spread gate plus the caller's independent roadbed
    cross-check), skewed toward wide (>=45 ft) and long (>=150 ft) blocks. Its
    scope limit is equally measured: it does nothing for the ~74% whose spread
    is distributed through the block interior (bus stops, loading zones,
    driveway aprons, divided geometry), and nothing at all for segments that
    are non-calibrated because a flank is missing.

    Args:
        centerline: CSCL segment centerline (EPSG:2263 State Plane feet).
        curb_lines: Candidate flanking curb ``LineString``\\ s (same CRS).
        cscl_width_ft: The segment's nominal CSCL street width (feet).
        sample_step_ft: Sampling interval along each curb line (feet).
        endpoint_trim_ft: Along-span inset used on the RETRY pass only. Defaults
            to :data:`ENDPOINT_TRIM_FT`; ``0.0`` disables the retry entirely.

    Returns:
        A :class:`SegmentCalibration` — the untrimmed baseline when it is
        calibrated OR when both passes fail; the trimmed result only when the
        trim rescued the segment.
    """
    baseline = derive_segment_calibration(
        centerline,
        curb_lines,
        cscl_width_ft,
        sample_step_ft=sample_step_ft,
        endpoint_trim_ft=0.0,
    )
    if baseline.calibrated:
        return baseline

    # Explicit opt-out, and it stops a zero trim from burning a second pass
    # that is guaranteed to reproduce the baseline.
    if endpoint_trim_ft <= 0.0:
        return baseline

    # No minimum-length guard here, deliberately: when `length` is at most twice
    # the trim the window collapses, the buckets come back empty, the
    # missing-flank path returns non-calibrated, and the baseline is handed back
    # below. That degenerate case is safe by construction and keeps production
    # identical to spike 008's backtested window formula — a bespoke guard would
    # make the two diverge.
    trimmed = derive_segment_calibration(
        centerline,
        curb_lines,
        cscl_width_ft,
        sample_step_ft=sample_step_ft,
        endpoint_trim_ft=endpoint_trim_ft,
    )
    if trimmed.calibrated:
        return trimmed

    return baseline


def derive_segment_calibration_with_fallback_retries(
    centerline: LineString,
    curb_lines: list[LineString],
    cscl_width_ft: float,
    sample_step_ft: float = CURB_SAMPLE_STEP_FT,
    endpoint_trim_ft: float = ENDPOINT_TRIM_FT,
    majority_threshold: float | None = MAJORITY_THRESHOLD,
) -> SegmentCalibration:
    """Derive a segment's calibration through the full three-tier fallback chain.

    The tiers are strictly ordered, each reached only when the previous one leaves
    the segment non-calibrated:

    (a) the plain UNTRIMMED derivation — today's shipped behaviour;
    (b) ONE retry with the 25 ft along-span endpoint trim, which drops the
        intersection corner-return curb curves at each end of the block (spike
        008);
    (c) ONE further retry adding the per-side dominant-cluster reduction at
        :data:`MAJORITY_THRESHOLD` ON TOP of those same endpoint-trimmed samples,
        which discards a minority of mid-block-bulging samples — bus stop, loading
        zone, driveway apron (spike 009).

    Tiers (a) and (b) are delegated to
    :func:`derive_segment_calibration_with_endpoint_retry` rather than
    reimplemented, so :func:`derive_segment_calibration` stays the single source
    of truth for the core math and a trim-rescued segment keeps exactly the
    numbers the two-tier wrapper already produces. An already-calibrated segment
    is returned verbatim and neither retry runs: neither spike measured what
    trimming or cleaning would do to a PASSING segment's ``center_offset_c`` /
    ``curb_width_ft``, so the ~50k segments the shipped index already calibrates
    must never be recomputed. When all three tiers fail, the UNTRIMMED baseline is
    returned, so a still-rejected segment keeps reporting the untrimmed
    ``spread_n`` / ``spread_s`` the shipped index already stores as its rejection
    reason.

    Measured yield (spike 009, on the 61 genuine spread-gate failures from spike
    008's population whose spread was distributed through the block INTERIOR and
    which the 25 ft trim therefore could not rescue): ~18% flip to calibrated
    through the FULL pipeline at a 0.8 threshold, and 92% of the ones clearing the
    spread gate also survived the caller's independent roadbed cross-check (vs 73%
    at a 0.6 threshold). Scaled against spike 008's own population split that is
    roughly ~11% additional citywide flip rate, on top of spike 008's ~26%. No new
    NYC dataset is involved — the reduction operates purely on curb samples the
    build already downloads.

    Its scope limits are equally measured. It does nothing for a segment whose
    sides split closer to even than the threshold: that is treated as genuinely
    divided/ambiguous geometry which must SELF-FLAG rather than be silently
    cleaned. It does nothing for a segment that is non-calibrated because a flank
    is missing. And its n=61 population was inherited from spike 008's single
    250-sample seed rather than independently re-sampled, so — exactly like the
    trim — it should be re-validated against a fresh citywide draw.

    Args:
        centerline: CSCL segment centerline (EPSG:2263 State Plane feet).
        curb_lines: Candidate flanking curb ``LineString``\\ s (same CRS).
        cscl_width_ft: The segment's nominal CSCL street width (feet).
        sample_step_ft: Sampling interval along each curb line (feet).
        endpoint_trim_ft: Along-span inset used on tiers (b) and (c). Defaults to
            :data:`ENDPOINT_TRIM_FT`; ``0.0`` disables BOTH retries.
        majority_threshold: Dominant-cluster share required on tier (c). Defaults
            to :data:`MAJORITY_THRESHOLD`; ``None`` disables tier (c) only.

    Returns:
        A :class:`SegmentCalibration` — the untrimmed baseline when it calibrates
        OR when all three tiers fail; the trim-only result when tier (b) rescued
        the segment; the trim-plus-cleaned result when tier (c) did.
    """
    # Tiers (a) + (b). A calibrated result here is final: returning it untouched
    # is what guarantees passing and trim-rescued segments are byte-identical to
    # what production produces today.
    retried = derive_segment_calibration_with_endpoint_retry(
        centerline,
        curb_lines,
        cscl_width_ft,
        sample_step_ft=sample_step_ft,
        endpoint_trim_ft=endpoint_trim_ft,
    )
    if retried.calibrated:
        return retried

    # Explicit opt-out of tier (c).
    if majority_threshold is None:
        return retried

    # Spike 009 measured the majority-cluster reduction layered ON TOP of spike
    # 008's validated 25 ft trim, and never standalone. Running it on untrimmed
    # samples would ship a combination for which there is no evidence at all, so a
    # disabled trim disables the cleaning with it.
    if endpoint_trim_ft <= 0.0:
        return retried

    cleaned = derive_segment_calibration(
        centerline,
        curb_lines,
        cscl_width_ft,
        sample_step_ft=sample_step_ft,
        endpoint_trim_ft=endpoint_trim_ft,
        majority_threshold=majority_threshold,
    )
    if cleaned.calibrated:
        return cleaned

    # All three tiers failed. `retried` is, by the two-tier wrapper's own
    # contract, the UNTRIMMED baseline in this branch — so the stored rejection
    # spreads stay the ones the shipped index already carries.
    return retried
