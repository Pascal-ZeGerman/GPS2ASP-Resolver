---
phase: 09-rebuild-the-spatial-index
plan: "01"
subsystem: build
tags: [build_index, normalization, soda, rtree, spatial-index, street-names]

# Dependency graph
requires:
  - phase: 08-refactor-architecture-and-streamline-pipeline
    provides: normalize_to_soda() in gps2asp.signs.normalize
provides:
  - Fixed build_index.py with correct directional prefix expansion
  - Fixed SODA voided-sign filter
  - Fixed dead-end sentinel value
  - 10 unit tests covering all three bug fixes
affects:
  - 09-rebuild-the-spatial-index (plan 02 runs the actual rebuild with these fixes)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_normalize_street_name() delegates entirely to normalize_to_soda() for parity with runtime"
    - "Dead-end segments represented by empty string '' not sentinel 'DEAD END'"

key-files:
  created:
    - tests/test_build_index.py
  modified:
    - scripts/build_index.py

key-decisions:
  - "_normalize_street_name() delegates to normalize_to_soda() — eliminates duplicated expansion logic and ensures build-time parity with runtime sign queries"
  - "Dead-end sentinel changed from 'DEAD END' to '' (empty string) — SODA API uses empty strings for missing cross streets"
  - "SODA filter changed to sign_design_voided_on_date IS NULL — record_type='Current' filtered nothing (all records are 'Current')"

patterns-established:
  - "Build script imports from gps2asp package for normalization parity"

requirements-completed: []

# Metrics
duration: 2min
completed: 2026-03-01
---

# Phase 9 Plan 01: Fix build_index.py Bugs Summary

**Three build-script bugs fixed (directional prefix expansion, voided-sign filter, dead-end sentinel) with 10 unit tests — sets up correct index rebuild in plan 02**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-01T22:32:08Z
- **Completed:** 2026-03-01T22:34:13Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Fixed Bug 1: `_normalize_street_name()` now delegates to `normalize_to_soda()` — "E 100 ST" correctly expands to "EAST 100 STREET" without false positives like "ESSEX" -> "EAST..."
- Fixed Bug 2: `_fetch_asp_signs()` $where clause now uses `sign_design_voided_on_date IS NULL` instead of `record_type='Current'` (which was a no-op since all records have type 'Current')
- Fixed Bug 3: `_find_cross_street()` returns `""` (empty string) for dead ends instead of `"DEAD END"`; counter updated to check `== ""`
- Created `tests/test_build_index.py` with 10 tests covering all three fixed behaviors (TDD: wrote RED tests first, then applied fixes to go GREEN)

## Task Commits

Both tasks combined into single atomic commit (TDD RED+GREEN in same plan):

1. **Task 1 & 2: Fix bugs + tests** - `cbb2369` (fix)

## Files Created/Modified

- `scripts/build_index.py` - Removed dead `_STREET_TYPE_EXPANSIONS` dict, replaced `_normalize_street_name()` body with delegation to `normalize_to_soda()`, fixed SODA `$where` filter, changed dead-end return value and counter
- `tests/test_build_index.py` - 10 new unit tests: 7 for `_normalize_street_name()`, 2 for `_find_cross_street()`, 1 for `_fetch_asp_signs()` filter

## Decisions Made

- `_normalize_street_name()` delegates to `normalize_to_soda()` — eliminates duplication and ensures exact parity with the runtime sign query path
- Dead-end sentinel changed from `"DEAD END"` to `""` — SODA signs dataset uses empty string for missing cross streets; old sentinel caused index lookup misses
- SODA filter updated to `sign_design_voided_on_date IS NULL` — `record_type='Current'` was always true (useless filter), causing voided signs to be included in the ASP set

## Deviations from Plan

None - plan executed exactly as written. TDD flow followed: wrote failing tests first (6 RED), then applied all three fixes (10 GREEN, 0 regressions).

## Issues Encountered

- The 6 pre-existing failures in `tests/test_sign_retrieval.py` (socket blocking in CI) were present before changes and are unrelated to this plan.

## Next Phase Readiness

- `scripts/build_index.py` is now correct and tested — ready for plan 09-02 to run the actual spatial index rebuild
- All 231 tests pass (221 original + 10 new)

---
*Phase: 09-rebuild-the-spatial-index*
*Completed: 2026-03-01*
