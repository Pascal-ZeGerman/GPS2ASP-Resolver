---
phase: 06-improve-confidence-scoring-to-account-for-nyc-street-widths
plan: "01"
subsystem: resolver/confidence
tags: [confidence-scoring, street-width, nyc, algorithm, regression-fix]
dependency_graph:
  requires: []
  provides: [width-relative-confidence, resolve_effective_width, parking_lane_fraction-param, street_width_ft-debug-field, nan-streetwidth-fix]
  affects: [resolver/__init__.py, resolver/confidence.py, resolver/models.py, build/build_index.py]
tech_stack:
  added: []
  patterns: [width-relative-guard, rw_type-fallback, frozen-dataclass-field-append]
key_files:
  created: []
  modified:
    - tests/test_confidence.py
    - src/gps2asp/resolver/confidence.py
    - src/gps2asp/resolver/models.py
    - src/gps2asp/resolver/__init__.py
    - src/gps2asp/build/build_index.py
decisions:
  - "_classify_ambiguity() retains 10ft absolute heuristic for log labels only — width-relative logic not needed there since it is debug-only classification, not the confidence algorithm"
  - "_NYC_DEFAULT_WIDTHS is a code constant (not runtime-configurable) per CONTEXT.md user decision"
  - "Fallback width usage is logged at DEBUG level only, not surfaced in AmbiguousResolutionError messages"
metrics:
  duration: "8 min"
  completed_date: "2026-02-28"
  tasks_completed: 2
  files_modified: 5
---

# Phase 06 Plan 01: Width-Relative Confidence Algorithm Summary

**One-liner:** Width-relative near-centerline guard in confidence.py replacing absolute 10ft threshold, fixing PROSPECT PL 9.2ft case from confidence=0.0 to 0.6133.

## What Was Implemented

### Algorithm Changes (confidence.py)

Replaced the absolute `if perp_distance_ft < 10.0: return 0.0` guard with a width-relative threshold:

```python
effective_width = resolve_effective_width(street_width_ft, rw_type)
near_center_threshold = effective_width * parking_lane_fraction / 2.0
if perp_distance_ft < near_center_threshold:
    return 0.0
```

For a 30ft street with `parking_lane_fraction=0.33`: threshold = 30 * 0.33 / 2 = **4.95ft** (vs old 10ft absolute).

### New Public Helper: resolve_effective_width()

Added to `confidence.py` and exported from `__init__.py`:
- Returns CSCL `streetwidth` if positive and not NaN
- Falls back to `_NYC_DEFAULT_WIDTHS[rw_type]` when data is missing
- Logs at DEBUG level only on fallback

### _NYC_DEFAULT_WIDTHS Dictionary

```python
_NYC_DEFAULT_WIDTHS: dict[int, float] = {
    1: 30.0,   # Street (typical NYC residential/commercial)
    2: 60.0,   # Highway / expressway
    3: 60.0,   # Bridge
    4: 30.0,   # Tunnel
    5: 30.0,   # Boardwalk / service road
}
```

### New Parameters

- `parking_lane_fraction: float = 0.33` added to `compute_confidence()`, `resolve()`, and `resolve_segment()`
- `rw_type: int = 1` added to `compute_confidence()`

### ResolutionDebugInfo Enhancement (models.py)

Added `street_width_ft: float | None = None` field (post-fallback effective width, for programmatic access).

### Enriched AmbiguousResolutionError Message (__init__.py)

Old: `"(perpendicular distance: 9.2ft, endpoint distance: 200.0ft)"`
New: `"(street_width=30ft, perp_dist=9.2ft, endpoint_dist=200.0ft)"`

### NaN Fix (build_index.py)

Added `import math` and replaced fallback logic:
- Old: missing streetwidth stored as `30.0` (hid missing data, bypassed rw_type fallback)
- New: missing/NaN/zero stored as `0.0` (triggers rw_type fallback at runtime in confidence.py)

## PROSPECT PL Confidence Result

```
PROSPECT PL confidence: 0.6133
Threshold: 0.6
PASS
```

Before fix: `confidence = 0.0` (absolute 10ft guard fired on 9.2ft offset)
After fix: `confidence = 0.6133` (width-relative 4.95ft threshold does not fire on 9.2ft)

## Test Count

| | Before | After |
|---|---|---|
| TestComputeConfidence | 8 tests | 13 tests |
| TestIsConfident | 6 tests | 6 tests |
| **Total test_confidence.py** | **14** | **19** |
| Full suite (passing) | 207 | 213 |

New tests added:
1. `test_near_centerline_within_fraction_returns_zero` — 3ft < 4.95ft guard
2. `test_regression_prospect_pl_9ft` — PROSPECT PL E2E regression
3. `test_nan_streetwidth_uses_rw_type_fallback` — NaN falls back to rw_type=1 -> 30ft
4. `test_highway_width_fallback` — rw_type=2 falls back to 60ft
5. `test_custom_parking_lane_fraction` — fraction=0.5 and 0.7 boundary tests

Updated tests:
- `test_near_centerline_below_threshold` (was `test_near_centerline_returns_zero`) — 5ft now passes guard, returns <0.6 not 0.0
- `test_exact_centerline_threshold` — 10ft now confidently in parking lane (>0.6), not just >0.0
- `test_zero_street_width` — updated comment to reflect rw_type fallback semantics
- `test_confidence_range` — updated comment for 5ft case

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | 8099587 | test(06-01): add failing tests for width-relative confidence algorithm |
| 2 | 907f84b | feat(06-01): implement width-relative confidence algorithm |

## Deviations from Plan

### Decision: _classify_ambiguity() 10ft check

The plan noted "Either is acceptable; note the choice in a comment." Decision: left `perp_distance < 10.0` as-is with a comment explaining it's a rough heuristic for debug log labels only, not the confidence algorithm. No behavioral impact.

No other deviations — plan executed exactly as specified.

## Self-Check: PASSED

Files verified present:
- tests/test_confidence.py — FOUND
- src/gps2asp/resolver/confidence.py — FOUND
- src/gps2asp/resolver/models.py — FOUND
- src/gps2asp/resolver/__init__.py — FOUND
- src/gps2asp/build/build_index.py — FOUND

Commits verified:
- 8099587 — FOUND
- 907f84b — FOUND

All 19 test_confidence.py tests pass GREEN. Full suite: 213 passed (6 pre-existing socket failures in test_sign_retrieval.py, unrelated to this plan).
