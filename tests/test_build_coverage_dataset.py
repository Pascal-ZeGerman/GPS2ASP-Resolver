"""Offline Wave-1 unit tests for scripts/build_coverage_dataset.py.

The coverage dumper is a presentation-layer snapshot producer for the static
street-sign coverage explorer (docs/explorer/). This module exercises the two
hardest-to-get-right, purely-deterministic pieces of the dumper BEFORE any
SODA/network wiring (42-02) or client rendering (42-04) consumes them:

  1. The street+side GROUPING KEY (D-01/D-02) — decides dedup correctness. Each
     segment's two candidate parking sides are derived from its geometry bearing
     (E-W street -> {N,S}; N-S street -> {E,W}), and normalize_to_soda collapses
     casing/whitespace/abbreviation variants of the same street to ONE key.
  2. The TIER PARTITION — the single documented half-open boundary rule the whole
     UI depends on, shared by R2 (marker color), R3 (popup tier label) and R4
     (tier filter). tier_for_confidence maps a confidence in [0,1] to exactly one
     of {high, medium, low, unresolved}; confidence_for_level maps SODA level.

These tests are pure (no network, no SODAClient, no 39 MB spatial index) so CI's
``-m "not integration"`` selection runs them.
"""

from __future__ import annotations

from scripts.build_coverage_dataset import (
    confidence_for_level,
    derive_segment_sides,
    group_key,
    tier_for_confidence,
)

# EPSG:2263 (NY State Plane, US survey feet) test geometries. Exact coordinates
# are irrelevant to the bearing; only the run direction matters.
#   E-W segment: runs horizontally (delta-y == 0) -> bearing 0 deg   -> {N, S}
#   N-S segment: runs vertically   (delta-x == 0) -> bearing 90 deg  -> {E, W}
_EW_WKT = "LINESTRING (980000 200000, 980100 200000)"
_NS_WKT = "LINESTRING (980000 200000, 980000 200100)"


def test_grouping_key_and_side_derivation():
    """Sides come from geometry bearing; group_key canonicalizes the street."""
    # --- side derivation from bearing (D-02): NEVER from has_asp_left/right ---
    assert derive_segment_sides(_EW_WKT) == ("N", "S")
    assert derive_segment_sides(_NS_WKT) == ("E", "W")

    # --- normalize_to_soda collapses casing/whitespace/abbreviation variants ---
    # BROADWAY / Broadway / broadway all canonicalize to one grouping key.
    key_upper = group_key("BROADWAY", "N")
    key_title = group_key("Broadway", "N")
    key_lower = group_key("broadway", "N")
    assert key_upper == key_title == key_lower

    # Collapsed internal whitespace ("W  THAMES ST") maps to the same key as its
    # single-spaced form ("W THAMES ST").
    assert group_key("W  THAMES ST", "N") == group_key("W THAMES ST", "N")

    # --- property: no double-count, no drop across the group boundary ---
    # Two distinct segments on the same normalized street+side must produce an
    # IDENTICAL group_key (so they collapse into one group), and the two sides of
    # one street must produce DIFFERENT keys (so neither side is dropped).
    seg_a_side = group_key("BROADWAY", "N")
    seg_b_side = group_key("broadway", "N")
    assert seg_a_side == seg_b_side  # same street+side -> one group (no double-count)

    north_key = group_key("BROADWAY", "N")
    south_key = group_key("BROADWAY", "S")
    assert north_key != south_key  # both sides recoverable (no drop)

    # The key exposes the canonical street and side for downstream recovery.
    assert north_key[1] == "N"
    assert south_key[1] == "S"
    assert north_key[0] == south_key[0]  # same canonical street on both sides


def test_tier_boundary_partition():
    """One documented half-open rule partitions [0,1] into four named tiers."""
    tiers = {"high", "medium", "low", "unresolved"}

    # Fine grid over [0,1] plus the exact boundary values: every value maps to
    # exactly one of the four named tiers.
    grid = [i / 100 for i in range(0, 101)] + [0.33, 0.50, 0.75]
    for v in grid:
        tier = tier_for_confidence(v)
        assert tier in tiers, f"{v!r} produced non-tier {tier!r}"

    # The four named boundary landings (the single half-open rule):
    #   [0.00, 0.33) unresolved | [0.33, 0.50) low | [0.50, 0.75) medium |
    #   [0.75, 1.00] high  (top tier inclusive of 1.0)
    assert tier_for_confidence(0.0) == "unresolved"
    assert tier_for_confidence(0.33) == "low"  # boundary lands in low, NOT unresolved
    assert tier_for_confidence(0.50) == "medium"
    assert tier_for_confidence(0.75) == "high"
    assert tier_for_confidence(1.0) == "high"

    # --- confidence_for_level maps SODA level deterministically (D-18) ---
    assert confidence_for_level(1) == 0.90
    assert confidence_for_level(2) == 0.66
    assert confidence_for_level(3) == 0.40
    assert confidence_for_level(0) == 0.00

    # ...and each level's confidence lands in the expected tier.
    assert tier_for_confidence(confidence_for_level(1)) == "high"
    assert tier_for_confidence(confidence_for_level(2)) == "medium"
    assert tier_for_confidence(confidence_for_level(3)) == "low"
    assert tier_for_confidence(confidence_for_level(0)) == "unresolved"
