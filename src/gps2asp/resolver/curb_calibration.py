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
4. ``c = (median(north) + median(south)) / 2`` (true centre vs the CSCL line);
   ``width = median(north) - median(south)`` (true curb-to-curb width).

**The spread gate is mandatory (spike 007).** ``spread_n`` / ``spread_s`` are the
per-side population stdevs. When ``max(spread_n, spread_s) > SPREAD_GATE_FT`` the
geometry is complex (median, divided road, service road) and ``c`` is NOT to be
trusted: the segment is marked non-calibrated and ``c`` is blanked to 0.0. A
segment missing a curb on either flank is likewise non-calibrated. This gate is
the whole reason the method is safe at scale — it lets bad geometry self-flag.

No network here. The caller (plan 40-08, the offline index build) fetches the
curb lines and, for accepted segments, cross-validates against the roadbed
polygon before writing the calibration fields into ``segments.json``.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from shapely.geometry import LineString

from gps2asp.resolver.side_resolver import signed_offset

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


def derive_segment_calibration(
    centerline: LineString,
    curb_lines: list[LineString],
    cscl_width_ft: float,
    sample_step_ft: float = CURB_SAMPLE_STEP_FT,
    endpoint_trim_ft: float = 0.0,
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

    med_n = statistics.median(north)
    med_s = statistics.median(south)
    center_offset_c = round((med_n + med_s) / 2.0, 2)
    curb_width_ft = round(med_n - med_s, 1)
    spread_n = round(statistics.pstdev(north), 2) if len(north) > 1 else 0.0
    spread_s = round(statistics.pstdev(south), 2) if len(south) > 1 else 0.0

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
