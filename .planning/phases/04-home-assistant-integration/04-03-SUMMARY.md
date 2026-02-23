---
phase: 04-home-assistant-integration
plan: 03
subsystem: testing
tags: [homeassistant, pytest, hacs, integration-testing, sensor-mapping]

# Dependency graph
requires:
  - phase: 04-home-assistant-integration
    plan: 01
    provides: "ASPParkingCoordinator, ASPParkingData, coordinator movement threshold logic"
  - phase: 04-home-assistant-integration
    plan: 02
    provides: "ASPNextMoveTimeSensor, ASPActiveNowBinarySensor, state mapping logic"
  - phase: 03-schedule-computation
    provides: "ScheduleResult union (ScheduleFound, ASPActiveNow, NoASPSchedule, NoMatchSchedule, AllUnparseable)"
provides:
  - "24 unit tests validating all sensor/binary sensor state mappings"
  - "Movement threshold and stale timeout behavior verification"
  - "HACS repository configuration (hacs.json)"
  - "ha_integration pytest marker for selective test execution"
affects: []

# Tech tracking
tech-stack:
  added: [pytest-homeassistant-custom-component]
  patterns: [HA-independent testing via data model mirroring and logic replication]

key-files:
  created:
    - tests/test_ha_integration.py
    - hacs.json
  modified:
    - pyproject.toml

key-decisions:
  - "Test state mapping logic by replicating sensor native_value/is_on locally instead of importing HA-dependent modules"
  - "ASPParkingData mirrored as test-local dataclass to avoid homeassistant import requirement"
  - "Haversine distance used for threshold tests instead of HA location_util"
  - "24 tests organized in 5 groups: sensor state, binary sensor, movement threshold, attributes, stale timeout"

patterns-established:
  - "HA-independent testing: mirror data models and replicate logic for tests that don't need HA runtime"
  - "Group tests by concern with @pytest.mark.ha_integration for selective execution"

requirements-completed: [HA-01, HA-02, HA-03, HA-04]

# Metrics
duration: 3min
completed: 2026-02-22
---

# Phase 4 Plan 3: Integration Tests and HACS Configuration Summary

**24 unit tests covering all ScheduleResult-to-sensor state mappings, binary sensor ON/OFF, movement threshold, rich attributes, and stale timeout plus HACS packaging**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-23T01:22:09Z
- **Completed:** 2026-02-23T01:25:12Z
- **Tasks:** 2
- **Files created:** 2, modified: 1

## Accomplishments
- 24 tests validating all 5 ScheduleResult variants mapped to correct sensor states
- Binary sensor ON/OFF for ASPActiveNow tested across 5 variants
- Movement threshold haversine distance tests for below/above 50m and first-GPS edge case
- Rich sensor attribute verification for all 5 groups (schedule, location, window, metadata, error)
- Stale timeout tests for unavailable marking after 8 hours, recent GPS, initial state, and boundary
- HACS-ready repository with hacs.json and pytest marker registration

## Task Commits

Each task was committed atomically:

1. **Task 1: Create unit tests for coordinator state mapping and sensor output** - `6ca651b` (test)
2. **Task 2: Add HACS config, update pyproject.toml, and verify complete integration structure** - `a397ddd` (chore)

## Files Created/Modified
- `tests/test_ha_integration.py` - 24 tests in 5 groups: sensor state mapping (8), binary sensor (5), movement threshold (3), attributes (4), stale timeout (4)
- `hacs.json` - HACS custom repository configuration with name "ASP Parking"
- `pyproject.toml` - Added pytest-homeassistant-custom-component dev dependency, registered ha_integration marker

## Decisions Made
- Tested state mapping logic by replicating sensor.py native_value and binary_sensor.py is_on logic locally, avoiding HA runtime dependency
- Used haversine distance calculation for threshold tests instead of importing HA location_util
- Mirrored ASPParkingData as a test-local dataclass to keep tests independent of homeassistant package
- 24 tests (above the 15 minimum) organized in 5 clearly named test classes

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Phase 4 is now complete: all 3 plans executed (foundation, config flow/sensors, tests/HACS)
- Full custom_components/asp_parking/ integration ready for deployment to Home Assistant
- 213 total tests (189 existing + 24 new) all passing
- HACS-ready for custom repository installation

## Self-Check: PASSED

All 3 created/modified files verified on disk. Both task commits (6ca651b, a397ddd) verified in git log.

---
*Phase: 04-home-assistant-integration*
*Completed: 2026-02-22*
