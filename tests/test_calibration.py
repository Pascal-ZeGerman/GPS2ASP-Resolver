"""Tests for the parking-history cluster-mean calibration estimator (SC-4).

The estimator derives a per-segment centre offset ``c`` from the segment's
settled-park signed offsets. The car parks on BOTH sides across cleaning days,
so the sample is often lopsided (more parks on one side). The estimator MUST use
the cluster-mean form ``(mean(low) + mean(high)) / 2`` — immune to that N/S
imbalance — NEVER the raw whole-list mean, which drifts up to ~5.85 ft when the
sample is lopsided.
"""

from __future__ import annotations

import statistics

from gps2asp.resolver.calibration import (
    MIN_SETTLED_PARKS,
    CalibrationEstimate,
    estimate_center_offset,
)


class TestEstimateCenterOffset:
    """Cluster-mean estimator: balanced recovery, imbalance immunity, gate."""

    def test_balanced_offsets_recover_center_and_half_spacing(self):
        """8 balanced offsets around clusters at -12 and +8 -> c=-2, p=10, n=8.

        low cluster mean = -12, high cluster mean = +8:
          c = (-12 + 8) / 2 = -2.0
          p = ( 8 - -12) / 2 = 10.0
        """
        offsets = [-13.0, -12.0, -11.0, -12.0, 7.0, 8.0, 9.0, 8.0]

        est = estimate_center_offset(offsets)

        assert est is not None
        assert isinstance(est, CalibrationEstimate)
        assert est.c == -2.0
        assert est.p == 10.0
        assert est.n == 8
        assert est.sigma >= 0.75

    def test_imbalance_immunity_cluster_mean_beats_raw_mean(self):
        """7 high parks vs 2 low parks: cluster-mean stays on true centre.

        The raw whole-list mean is pulled toward the crowded high side; the
        cluster-mean is not. Asserted numerically against a self-computed raw
        mean, not by inspection.
        """
        # 2 offsets near -12, 7 offsets near +8 (lopsided high). True c = -2.
        offsets = [-12.5, -11.5, 7.5, 8.0, 8.5, 7.5, 8.0, 8.5, 8.0]
        true_center = -2.0

        est = estimate_center_offset(offsets)
        raw_mean = statistics.mean(offsets)

        assert est is not None
        # Cluster-mean recovers the true centre despite the 7:2 imbalance.
        assert est.c == -2.0
        # The raw mean is dragged toward the crowded side (~+3.6).
        assert raw_mean > 3.0
        # The two estimators disagree by more than 3 ft under imbalance.
        assert abs(est.c - raw_mean) > 3.0
        # The cluster-mean estimate is materially closer to the true centre.
        assert abs(est.c - true_center) < abs(raw_mean - true_center)
        assert abs(est.c - true_center) < 1.0

    def test_empty_offsets_returns_none(self):
        """No offsets -> no estimate (caller falls through to c=0)."""
        assert estimate_center_offset([]) is None

    def test_below_gate_returns_none(self):
        """Fewer than MIN_SETTLED_PARKS offsets -> no estimate."""
        thin = [1.0] * (MIN_SETTLED_PARKS - 1)
        assert estimate_center_offset(thin) is None

    def test_gate_threshold_is_five(self):
        """The settled-park gate is 5 (documents the spike SETTLED_MIN_POLLS)."""
        assert MIN_SETTLED_PARKS == 5
