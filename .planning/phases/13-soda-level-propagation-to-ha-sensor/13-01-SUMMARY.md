---
phase: 13-soda-level-propagation-to-ha-sensor
plan: 01
subsystem: testing
tags: [tdd, soda-level, ha-sensor, dataclass]

# Dependency graph
requires:
  - phase: 07-pipeline-stabilization
    provides: ASPResult/ASPDebugResult models and resolve_asp() pipeline
provides:
  - TDD test scaffold for soda_level propagation (Wave 0 contract)
  - TestSodaLevelAttribute class with 4 unit tests for HA sensor attributes
  - TestASPResultSodaLevel class with 2 RED tests for ASPResult.soda_level
affects: [13-02-PLAN]

# Tech tracking
tech-stack:
  added: []
  patterns: [test-local ASPParkingData mirror extended, TDD Wave 0 RED-first]

key-files:
  created: []
  modified:
    - tests/test_ha_integration.py
    - tests/test_resolve_asp.py

key-decisions:
  - "TestSodaLevelAttribute tests pass immediately (test-local mirror, not production code) -- TDD contract verified by Plan 02 integration"
  - "TestASPResultSodaLevel tests are RED (AttributeError on ASPResult.soda_level) -- Plan 02 makes them GREEN"

patterns-established:
  - "Group 7 soda_level attribute tests in test_ha_integration.py follow same pattern as Groups 1-6"

requirements-completed: []

# Metrics
duration: 5min
completed: 2026-03-16
---

# Phase 13 Plan 01: TDD Wave 0 - soda_level Test Scaffold Summary

**TDD RED tests for soda_level propagation: 4 passing unit tests on test-local mirror + 2 failing integration tests on production ASPResult**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-16T19:39:58Z
- **Completed:** 2026-03-16T19:45:13Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments
- Added soda_level: int = 0 to test-local ASPParkingData mirror and sensor_extra_attributes() helper
- Created TestSodaLevelAttribute (Group 7) with 4 passing tests exercising the test-local helper
- Created TestASPResultSodaLevel with 2 RED tests confirming ASPResult lacks soda_level (Plan 02 contract)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add soda_level to test-local mirror and helper** - `c04fcf0` (test)
2. **Task 2: Add TestSodaLevelAttribute with 4 tests** - `87a2c73` (test)
3. **Task 3: Add failing TestASPResultSodaLevel tests** - `abfc664` (test)

## Files Created/Modified
- `tests/test_ha_integration.py` - Added soda_level field to ASPParkingData mirror, soda_level emission in sensor_extra_attributes(), TestSodaLevelAttribute class (Group 7)
- `tests/test_resolve_asp.py` - Added TestASPResultSodaLevel class with 2 RED tests for non-debug ASPResult.soda_level

## Decisions Made
- TestSodaLevelAttribute tests pass immediately because they exercise only the test-local mirror and helper (not production code) -- this is correct for TDD Wave 0
- TestASPResultSodaLevel tests are intentionally RED (AttributeError) -- Plan 02 adds soda_level to ASPResult and makes them GREEN

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Test contract established: Plan 02 must add soda_level to ASPResult and populate it in pipeline.py
- 2 RED tests in test_resolve_asp.py will serve as acceptance criteria for Plan 02
- 4 passing tests in test_ha_integration.py verify test helper propagation works

---
*Phase: 13-soda-level-propagation-to-ha-sensor*
*Completed: 2026-03-16*
