"""Parking-history cluster-mean calibration estimator (SC-4 fallback tier 2).

When a segment has no trustworthy curb ``c``, its centre offset can be learned
from the segment's settled-park signed offsets. The car parks on BOTH sides of
the street across cleaning days, so the offset sample splits into two clusters
(one per lane) and is frequently lopsided — more parks on one side than the
other.

The estimator recovers the street's centre with the **cluster-mean** form::

    c = (mean(low_cluster) + mean(high_cluster)) / 2

which is immune to N/S imbalance because each lane contributes equally
regardless of how many samples fall in it. The naive raw whole-list mean is
NOT used: it is pulled toward whichever lane has more samples and drifts up to
~5.85 ft under imbalance (see spike 003 / the averaging dead-end note).

Below the settled-park gate (`MIN_SETTLED_PARKS`) — or when the sample does not
split into two clusters — the estimator returns ``None`` so the caller can fall
through to plain CSCL (``c = 0``). The fallback CHAIN wiring
(curb ``c`` -> learned ``c`` -> 0) lives in plan 40-06; the collection and
persistence of per-segment offsets is out of scope here. This module is the
pure, testable estimator unit only.

Ported from the spike ``calibrate()`` in
``.planning/spikes/004-side-determination/approaches.py``.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

# Minimum number of settled parking offsets required before an estimate is
# trusted. Matches the spike SETTLED_MIN_POLLS gate — below this the sample is
# too thin to separate settled parks from transients, so the caller falls
# through to plain CSCL (c = 0).
MIN_SETTLED_PARKS: int = 5

# Floor for the residual-noise estimate. Per-cluster residual noise is ~1.2 ft
# against an ~8 ft lane margin; the floor guards against an over-confident
# (near-zero) sigma when only a couple of residuals happen to coincide.
_MIN_SIGMA: float = 0.75


@dataclass(frozen=True)
class CalibrationEstimate:
    """A learned per-segment side calibration derived from parking history.

    Attributes:
        c: Estimated centre offset (feet) of the street's parking geometry
            relative to the CSCL centerline — the midpoint between the two
            learned lane centres.
        p: Half the spacing between the two lane centres (feet); lane centres
            sit at ``c - p`` (low side) and ``c + p`` (high side).
        sigma: Residual noise estimate (feet) of settled offsets about their
            nearer lane centre, floored at 0.75 ft.
        n: Number of settled offsets the estimate was derived from.
    """

    c: float
    p: float
    sigma: float
    n: int


def estimate_center_offset(offsets: list[float]) -> CalibrationEstimate | None:
    """Estimate a segment's centre offset from settled-park signed offsets.

    Uses the cluster-mean estimator (immune to N/S imbalance), NOT the raw mean.

    Args:
        offsets: Signed perpendicular offsets (feet) of settled parks about the
            CSCL centerline. Positive and negative values correspond to opposite
            lanes.

    Returns:
        A ``CalibrationEstimate`` when at least ``MIN_SETTLED_PARKS`` offsets are
        supplied and they split into two non-empty clusters; otherwise ``None``
        (the caller falls through to plain CSCL, ``c = 0``).
    """
    if len(offsets) < MIN_SETTLED_PARKS:
        return None

    ordered = sorted(offsets)

    # Split at the largest adjacent gap: the low lane and the high lane are
    # separated by the widest jump in the sorted offsets.
    split_index = max(
        range(len(ordered) - 1),
        key=lambda i: ordered[i + 1] - ordered[i],
    )
    low = ordered[: split_index + 1]
    high = ordered[split_index + 1 :]

    # Degenerate case: everything landed in a single cluster (only reachable if
    # a caller passed an empty slice; the gap-split above always yields two
    # non-empty sides for len >= 2). Guard defensively — a single cluster cannot
    # locate the centre.
    if not low or not high:
        return None

    low_mean = statistics.mean(low)
    high_mean = statistics.mean(high)

    c = (low_mean + high_mean) / 2.0
    p = (high_mean - low_mean) / 2.0

    # Residual of each offset to its nearer lane centre, floored so a fluke of
    # coincident residuals cannot manufacture false confidence.
    residuals = [min(abs(v - (c - p)), abs(v - (c + p))) for v in ordered]
    sigma = max(
        statistics.pstdev(residuals) if len(residuals) > 1 else _MIN_SIGMA,
        _MIN_SIGMA,
    )

    return CalibrationEstimate(c=c, p=p, sigma=sigma, n=len(offsets))
