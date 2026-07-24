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
2. Keep a sample only when its projection lands within ``[0, centerline.length]``
   AND its offset is within ``max_perp = max(45, cscl_width * 1.5)`` feet — this
   rejects curbs belonging to cross-streets or a parallel block.
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

    Returns:
        A :class:`SegmentCalibration`. ``calibrated`` is ``True`` only when both
        flanks have samples AND ``max(spread_n, spread_s) <= SPREAD_GATE_FT``;
        otherwise ``center_offset_c`` is ``0.0`` and ``curb_width_ft`` is
        ``None`` (proven-safe plain-CSCL fallback).
    """
    max_perp = max(45.0, cscl_width_ft * 1.5)
    length = centerline.length

    north: list[float] = []
    south: list[float] = []
    for line in curb_lines:
        steps = max(2, int(line.length / sample_step_ft))
        for i in range(steps + 1):
            p = line.interpolate(i / steps, normalized=True)
            along = centerline.project(p)
            off = signed_offset(p.x, p.y, centerline)
            if 0.0 <= along <= length and abs(off) <= max_perp:
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
