---
phase: 15-queens-and-manhattan-coverage-fix
plan: 01
subsystem: testing
tags: [coverage, fixtures, normalization, tdd, audit]

# Dependency graph
requires:
  - phase: 12-structured-level-4-logging
    provides: l4_event structured log entries visible during audit
provides:
  - Queens GPS coverage fixture (25 locations across 6 neighborhoods)
  - Manhattan GPS coverage fixture (18 locations across 4 areas)
  - Live SODA audit script with per-location breakdown and summary
  - RED tests for TPKE and CRES suffix normalization gaps
affects: [15-02, 15-queens-and-manhattan-coverage-fix]

# Tech tracking
tech-stack:
  added: []
  patterns: [coverage-fixture-format, audit-script-pattern]

key-files:
  created:
    - tests/fixtures/queens_coverage.json
    - tests/fixtures/manhattan_coverage.json
    - scripts/audit_queens_coverage.py
  modified:
    - tests/test_normalize.py

key-decisions:
  - "Coverage fixtures use 'description' key (not 'name') since they are spot-check locations without expected_on_street/side"
  - "Audit script catches all exceptions including OutsideNYCError/NoSegmentFoundError and records as errors with soda_level=0"

patterns-established:
  - "Coverage fixture format: JSON array of {description, lat, lon} objects for spot-check auditing"
  - "Audit script pattern: asyncio.run + per-location resolve_asp(debug=True) with tabular output and Level 1+2 summary"

requirements-completed: [COV-02, COV-04]

# Metrics
duration: 4min
completed: 2026-03-18
---

# Phase 15 Plan 01: Diagnosis Tooling Summary

**Queens/Manhattan GPS fixtures (25+18 locations), live SODA audit script, and RED TDD tests for TPKE/CRES normalization gaps**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-18T14:04:46Z
- **Completed:** 2026-03-18T14:09:25Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Created 25-location Queens fixture covering Jamaica, Flushing, Astoria, Jackson Heights, Forest Hills, and Union Tpke
- Created 18-location Manhattan fixture covering Upper West Side, Harlem, East Village, and Midtown
- Built audit script that runs resolve_asp(debug=True) per location and outputs Level 1+2 target metric
- Confirmed TPKE and CRES normalization gaps with failing RED tests against current normalize.py

## Task Commits

Each task was committed atomically:

1. **Task 1: Create Queens/Manhattan GPS fixtures and TDD RED tests** - `5603469` (test)
2. **Task 2: Create live SODA audit script** - `3d6dd98` (feat)

## Files Created/Modified
- `tests/fixtures/queens_coverage.json` - 25 Queens GPS spot-check locations across 6 neighborhoods
- `tests/fixtures/manhattan_coverage.json` - 18 Manhattan GPS spot-check locations across 4 areas
- `scripts/audit_queens_coverage.py` - CLI audit script with --fixture flag, resolve_asp(debug=True), tabular output
- `tests/test_normalize.py` - Added test_suffix_expansion_tpke and test_suffix_expansion_cres (RED)

## Decisions Made
- Coverage fixtures use "description" key (not "name") since they are spot-check locations without expected_on_street/side
- Audit script catches all exceptions and records as errors with soda_level=0 for summary calculation

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- pytest_homeassistant_custom_component plugin causes PermissionError on cert files in sandbox mode; tests verified with sandbox disabled (pre-existing issue, not caused by this plan)

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Fixtures and audit script ready for Plan 02 normalization fixes (TPKE, CRES suffix expansions)
- RED tests will turn GREEN when _SUFFIX_EXPANSIONS dict is updated in normalize.py
- Audit script can be run manually with `python scripts/audit_queens_coverage.py` to measure baseline coverage

---
*Phase: 15-queens-and-manhattan-coverage-fix*
*Completed: 2026-03-18*
