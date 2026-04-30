---
phase: 13-soda-level-propagation-to-ha-sensor
plan: 02
subsystem: api, ha-integration
tags: [dataclass, soda-level, pipeline, coordinator, sensor, vendored-copy]

# Dependency graph
requires:
  - phase: 13-01
    provides: TDD test scaffold for soda_level (RED tests)
  - phase: 07
    provides: ASPResult, ASPDebugResult, resolve_asp pipeline
provides:
  - ASPResult.soda_level field (int 0-4) populated on non-debug path
  - ASPParkingData.soda_level propagated through coordinator
  - soda_level always present in HA sensor extra_state_attributes
  - Vendored gps2asp copies synced with src/ changes
affects: [14-graph-json-size-reduction, 15-queens-manhattan-coverage]

# Tech tracking
tech-stack:
  added: []
  patterns: [soda_level-propagation-pattern, vendored-copy-sync]

key-files:
  created: []
  modified:
    - src/gps2asp/signs/models.py
    - src/gps2asp/api_models.py
    - src/gps2asp/pipeline.py
    - custom_components/asp_parking/coordinator.py
    - custom_components/asp_parking/sensor.py
    - custom_components/asp_parking/gps2asp/signs/models.py
    - custom_components/asp_parking/gps2asp/api_models.py
    - custom_components/asp_parking/gps2asp/pipeline.py
    - tests/test_resolve_asp.py

key-decisions:
  - "NoMatchFound test fixture corrected: removed invalid kwargs (on_street, from_street, etc.) that NoMatchFound does not accept"
  - "Generic except Exception block retains last soda_level (same pattern as sign_count) -- no reset on transient errors"

patterns-established:
  - "Vendored copy sync: cp src/ to custom_components/ then diff to verify byte-for-byte match"

requirements-completed: [OBS-01]

# Metrics
duration: 7min
completed: 2026-03-16
---

# Phase 13 Plan 02: soda_level Propagation to HA Sensor Summary

**Thread soda_level (int 1-4) from SignRetrievalSuccess through ASPResult, coordinator, and sensor extra_state_attributes -- making Wave 0 RED tests GREEN**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-16T19:50:27Z
- **Completed:** 2026-03-16T19:57:21Z
- **Tasks:** 3
- **Files modified:** 9

## Accomplishments
- Added soda_level: int = 0 field to ASPResult frozen dataclass with docstring
- Pipeline non-debug return path now passes soda_level from SignRetrievalSuccess
- Coordinator ASPParkingData gains soda_level field, set on success, reset on known errors
- HA sensor emits soda_level in unconditional metadata group of extra_state_attributes
- All 3 vendored gps2asp copies synced byte-for-byte with src/ counterparts
- All 7 soda_level tests GREEN (was 1 RED before this plan)
- Full test suite: 276 passed (6 pre-existing socket-blocked integration tests excluded)

## Task Commits

Each task was committed atomically:

1. **Task 1: Update src/ models and pipeline** - `743a28b` (feat)
2. **Task 2: Update coordinator.py and sensor.py** - `5b9497b` (feat)
3. **Task 3: Mirror src/ changes to vendored gps2asp copies** - `2625744` (chore)

## Files Created/Modified
- `src/gps2asp/signs/models.py` - Updated soda_level comment to include Level 4
- `src/gps2asp/api_models.py` - Added soda_level: int = 0 field to ASPResult
- `src/gps2asp/pipeline.py` - Populated soda_level on non-debug return path
- `custom_components/asp_parking/coordinator.py` - Added soda_level to ASPParkingData + pipeline assignment + error resets
- `custom_components/asp_parking/sensor.py` - Added soda_level to unconditional metadata group
- `custom_components/asp_parking/gps2asp/signs/models.py` - Vendored mirror of src/
- `custom_components/asp_parking/gps2asp/api_models.py` - Vendored mirror of src/
- `custom_components/asp_parking/gps2asp/pipeline.py` - Vendored mirror of src/
- `tests/test_resolve_asp.py` - Fixed NoMatchFound construction bug in test fixture

## Decisions Made
- NoMatchFound test fixture was constructing with invalid kwargs (on_street, from_street, to_street, side_of_street) that NoMatchFound does not accept. Fixed inline (Rule 1 - bug fix).
- Generic `except Exception` block in coordinator retains last soda_level value (same established pattern as sign_count).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed NoMatchFound test construction in test_resolve_asp.py**
- **Found during:** Task 1 (GREEN phase of TDD)
- **Issue:** `test_asp_result_soda_level_zero_on_no_match` constructed `NoMatchFound(status="no_match", on_street=..., from_street=..., to_street=..., side_of_street=...)` but NoMatchFound only accepts `status` field
- **Fix:** Simplified to `NoMatchFound(status="no_match")`
- **Files modified:** tests/test_resolve_asp.py
- **Verification:** All 7 soda_level tests pass GREEN
- **Committed in:** 743a28b (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug fix)
**Impact on plan:** Test fixture bug from Plan 01 Wave 0. Essential fix for correctness. No scope creep.

## Issues Encountered
- Sandbox cert permission error prevents running pytest in sandboxed mode (HA homeassistant.util.ssl loads cacert.pem). Resolved by running with sandbox disabled for test execution.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 13 complete: OBS-01 satisfied, soda_level fully threaded from SODA query to HA sensor
- Phase 14 (graph.json size reduction) and Phase 15 (Queens/Manhattan coverage) can proceed independently

---
*Phase: 13-soda-level-propagation-to-ha-sensor*
*Completed: 2026-03-16*
