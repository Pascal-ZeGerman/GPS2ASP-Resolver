---
phase: 17-manhattan-coverage-fix-geocoded-fixtures-l3-diagnosis
plan: 01
subsystem: testing
tags: [geocoding, geosearch-v2, soda, coverage, manhattan, fixtures]

# Dependency graph
requires:
  - phase: 16-queens-coverage-fix-geocoded-fixtures
    provides: "geocode_fixtures.py with MANHATTAN_ADDRESSES placeholder, audit script with --fixture manhattan support"
provides:
  - "18 geocoded Manhattan GPS fixture locations in manhattan_coverage.json"
  - "L3 diagnostic audit output for Manhattan showing CSCL-vs-SODA mismatch patterns"
affects: [17-02-manhattan-normalization-fixes]

# Tech tracking
tech-stack:
  added: []
  patterns: ["Address-geocoded fixtures via GeoSearch v2 (same as Phase 16 Queens)"]

key-files:
  created: []
  modified:
    - "scripts/geocode_fixtures.py"
    - "tests/fixtures/manhattan_coverage.json"

key-decisions:
  - "Replaced E 43rd St address (215->320) after GeoSearch returned Brooklyn borough for 215"
  - "Manhattan Level 1+2 at 5.6% (1/18) with geocoded fixtures -- baseline for Plan 02 normalization fixes"
  - "L3 diagnostics show CSCL/SODA cross-street boundary mismatches as primary failure pattern (same as Queens)"

patterns-established:
  - "Phase 16 geocoding methodology confirmed reusable for additional boroughs"

requirements-completed: []

# Metrics
duration: 9min
completed: 2026-03-19
---

# Phase 17 Plan 01: Manhattan Geocoded Fixtures + L3 Diagnostic Audit Summary

**18 Manhattan addresses geocoded via GeoSearch v2 across 4 neighborhoods; L3 diagnostic audit reveals 5.6% Level 1+2 baseline with cross-street boundary mismatches as dominant failure pattern**

## Performance

- **Duration:** 9 min
- **Started:** 2026-03-19T17:20:24Z
- **Completed:** 2026-03-19T17:29:30Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Populated 18 Manhattan residential street addresses in geocoding script across UWS (5), Harlem (4), East Village (5), Midtown (4)
- Regenerated manhattan_coverage.json with precise GeoSearch v2 geocoded coordinates (replacing approximate-coordinate fixtures)
- Ran L3 diagnostic audit capturing per-fixture soda_level breakdown and CSCL-vs-SODA cross-street analysis
- All 47 normalization tests pass (no regressions)

## Task Commits

Each task was committed atomically:

1. **Task 1: Populate Manhattan addresses and geocode fixtures** - `685fdb1` (feat)
2. **Task 2: Run L3 diagnostic audit** - no commit (audit-only task, no file changes)

## Files Created/Modified
- `scripts/geocode_fixtures.py` - Added 18 Manhattan addresses to MANHATTAN_ADDRESSES list
- `tests/fixtures/manhattan_coverage.json` - Regenerated with GeoSearch v2 geocoded coordinates

## L3 Diagnostic Audit Results

### Summary

| Level | Count | Pct |
|-------|-------|-----|
| Level 1 | 1/18 | 5.6% |
| Level 2 | 0/18 | 0.0% |
| Level 3 | 7/18 | 38.9% |
| Level 4 | 0/18 | 0.0% |
| No match (level 0) | 10/18 | 55.6% |
| **Level 1+2 (target)** | **1/18** | **5.6%** |

### Per-Fixture Breakdown

| # | Level | On Street | From | To | Description |
|---|-------|-----------|------|----|-------------|
| 1 | 3 | W 76 ST | AMSTERDAM AVE | BROADWAY | 215 WEST 76 STREET |
| 2 | 1 | W 83 ST | W END AVE | RIVERSIDE DR | 310 WEST 83 STREET |
| 3 | 3 | W 88 ST | AMSTERDAM AVE | BROADWAY | 225 WEST 88 STREET |
| 4 | 0 | W 72 ST | W END AVE | RIVERSIDE DR | 305 WEST 72 STREET |
| 5 | 3 | W 90 ST | CENTRAL PARK W | COLUMBUS AVE | 2 WEST 91 STREET |
| 6 | 0 | W 122 ST | ADAM CLAYTON POWELL JR BLVD | FREDERICK DOUGLASS BLVD | 210 WEST 122 STREET |
| 7 | 3 | W 130 ST | LENOX AVE | ADAM CLAYTON POWELL JR BLVD | 130 WEST 130 STREET |
| 8 | 0 | W 116 ST | FREDERICK DOUGLASS BLVD | MANHATTAN AVE | 310 WEST 116 STREET |
| 9 | 3 | W 134 ST | LENOX AVE | ADAM CLAYTON POWELL JR BLVD | 120 WEST 135 STREET |
| 10 | 0 | E 7 ST | AVE B | AVE C | 215 EAST 7 STREET |
| 11 | 3 | E 5 ST | COOPER SQ | 2 AVE | 220 EAST 5 STREET |
| 12 | 3 | E 9 ST | 2 AVE | 1 AVE | 310 EAST 9 STREET |
| 13 | 0 | E 4 ST | AVE A | AVE B | 225 EAST 4 STREET |
| 14 | 0 | ST MARKS PL | COOPER SQ | 2 AVE | 25 SAINT MARK'S PLACE |
| 15 | 0 | W 46 ST | 8 AVE | 9 AVE | 340 WEST 46 STREET |
| 16 | 0 | E 50 ST | 3 AVE | 2 AVE | 225 EAST 50 STREET |
| 17 | 0 | W 54 ST | 9 AVE | 10 AVE | 410 WEST 54 STREET |
| 18 | 0 | E 43 ST | 2 AVE | TUDOR CITY PL | 320 EAST 43 STREET |

### L3 Diagnostic Analysis

**Pattern 1: CSCL multi-block span vs SODA single-block spans (dominant)**
- Fixtures #1, #3: CSCL sends `AMSTERDAM AVE to BROADWAY` (multi-block), SODA has separate single-block spans like `AMSTERDAM AVENUE to COLUMBUS AVENUE` and `BROADWAY to AMSTERDAM AVENUE`
- Fixture #5: CSCL sends `CENTRAL PARK W to COLUMBUS AVE`, SODA has `COLUMBUS AVENUE to CENTRAL PARK WEST` (reversed direction)

**Pattern 2: Abbreviated cross-street names in CSCL vs full names in SODA**
- Fixture #6: CSCL sends `ADAM CLAYTON POWELL JR BLVD` / `FREDERICK DOUGLASS BLVD`, SODA has `ADAM C POWELL BOULEVARD` / `FRED DOUGLASS BOULEVARD` -- name abbreviation mismatch
- Fixture #9: Same pattern -- `ADAM CLAYTON POWELL JR BOULEVARD` in CSCL vs `ADAM C POWELL BOULEVARD` in SODA

**Pattern 3: AVE vs AVENUE for lettered avenues**
- Fixtures #10, #13: CSCL sends `AVE B`/`AVE C`/`AVE A`, SODA has `AVENUE B`/`AVENUE C`/`AVENUE A` -- the `AVE` suffix is not being expanded for lettered avenues

**Pattern 4: SODA data gaps (no spans on side)**
- Fixtures #17, #18: No SODA spans found at all for these street/side combinations
- Fixtures #15, #16: Only one SODA span exists, but for a different block than CSCL sent

**Fixable in Plan 02:**
- Pattern 2: Add SODA-style abbreviation matching for `ADAM CLAYTON POWELL JR` -> `ADAM C POWELL` and `FREDERICK DOUGLASS` -> `FRED DOUGLASS`
- Pattern 3: AVE -> AVENUE expansion for lettered avenues (AVE A, AVE B, etc.)
- Pattern 1: Some may be resolvable by improving cross-street matching to handle reversed from/to order

## Decisions Made
- Replaced "215 East 43rd Street" with "320 East 43rd Street" after GeoSearch returned Brooklyn borough for the original address
- Manhattan L1+2 baseline at 5.6% documented for comparison after Plan 02 normalization fixes
- Identified 3 fixable normalization patterns (abbreviated names, AVE->AVENUE, reversed from/to) for Plan 02

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed E 43rd St geocoding to wrong borough**
- **Found during:** Task 1 (geocoding)
- **Issue:** "215 East 43rd Street, New York, NY" geocoded to Brooklyn instead of Manhattan
- **Fix:** Changed house number to 320 (different block on same street)
- **Files modified:** scripts/geocode_fixtures.py
- **Verification:** Re-ran geocoding, all 18/18 succeeded with Manhattan borough
- **Committed in:** 685fdb1 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Minimal -- address replacement as anticipated by plan's contingency step.

## Issues Encountered
- pytest fails when run in sandbox due to pytest_homeassistant_custom_component plugin loading SSL certs; works with `-p no:pytest_homeassistant_custom_component` or with sandbox disabled (pre-existing issue)

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- L3 diagnostic data captured and categorized for Plan 02 normalization analysis
- Three fixable normalization patterns identified: abbreviated boulevard names, AVE->AVENUE for lettered avenues, reversed from/to cross-street order
- Plan 02 can proceed immediately with normalization fixes + index rebuild + re-audit

---
*Phase: 17-manhattan-coverage-fix-geocoded-fixtures-l3-diagnosis*
*Completed: 2026-03-19*
