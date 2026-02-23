---
phase: 04-home-assistant-integration
plan: 01
subsystem: ha-integration
tags: [homeassistant, custom-component, coordinator, debounce, event-driven]

# Dependency graph
requires:
  - phase: 01-gps-to-street
    provides: "resolve() async GPS-to-street pipeline with OutsideNYCError/NoSegmentFoundError"
  - phase: 02-sign-retrieval
    provides: "retrieve_signs() SODA API sign lookup with SignRetrievalSuccess/NoASPSigns/NoMatchFound"
  - phase: 03-schedule-computation
    provides: "compute_schedule() sign-to-schedule pipeline with ScheduleResult union"
provides:
  - "custom_components/asp_parking/ directory structure with integration metadata"
  - "ASPParkingCoordinator: event-driven GPS-to-schedule orchestrator"
  - "ASPParkingData: mutable state container for entity consumption"
  - "Foundation files: const.py, manifest.json, strings.json, services.yaml"
affects: [04-02, 04-03]

# Tech tracking
tech-stack:
  added: [homeassistant.helpers.debounce.Debouncer, homeassistant.helpers.event]
  patterns: [event-driven coordinator (not DataUpdateCoordinator), mutable dataclass for state]

key-files:
  created:
    - custom_components/asp_parking/__init__.py
    - custom_components/asp_parking/const.py
    - custom_components/asp_parking/manifest.json
    - custom_components/asp_parking/strings.json
    - custom_components/asp_parking/translations/en.json
    - custom_components/asp_parking/services.yaml
    - custom_components/asp_parking/coordinator.py
  modified: []

key-decisions:
  - "Custom coordinator (not DataUpdateCoordinator) since data source is event-driven GPS, not polled"
  - "ASPParkingData is mutable dataclass (not frozen) since coordinator updates incrementally"
  - "Debouncer with 5s cooldown and immediate=False to coalesce rapid GPS jitter"
  - "Pipeline errors retain last known schedule (fall back, not clear)"
  - "OutsideNYC and NoSegmentFound produce distinct special_state sentinels"

patterns-established:
  - "Event-driven coordinator: subscribe to state changes, debounce, threshold check, pipeline"
  - "Entity notification: coordinator._entity_update_callbacks list with @callback decorator"
  - "Config access: properties reading from entry.data (immutable) and entry.options (reconfigurable)"

requirements-completed: [HA-01, HA-04]

# Metrics
duration: 2min
completed: 2026-02-22
---

# Phase 4 Plan 1: Foundation and Coordinator Summary

**Event-driven ASPParkingCoordinator wiring GPS state changes to the three-phase pipeline with 50m threshold, 5s debounce, and 8hr periodic refresh**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-23T01:12:38Z
- **Completed:** 2026-02-23T01:14:55Z
- **Tasks:** 2
- **Files created:** 7

## Accomplishments
- Created asp_parking custom component directory structure with all metadata files
- Built event-driven coordinator that wires all three pipeline phases together
- Implemented movement threshold (50m), GPS jitter debounce (5s), and periodic refresh (8hr)
- Error handling with distinct states for OutsideNYC, NoSegmentFound, and SODA failures

## Task Commits

Each task was committed atomically:

1. **Task 1: Create foundation files (const, manifest, strings, services)** - `79d7e7b` (feat)
2. **Task 2: Create event-driven ASPParkingCoordinator** - `c95d3fd` (feat)

## Files Created/Modified
- `custom_components/asp_parking/__init__.py` - Placeholder with docstring (entry point logic deferred to Plan 02)
- `custom_components/asp_parking/const.py` - DOMAIN, PLATFORMS, CONF_*/DEFAULT_* constants, GPS_DEBOUNCE_COOLDOWN
- `custom_components/asp_parking/manifest.json` - Integration metadata with config_flow: true, requirements list
- `custom_components/asp_parking/strings.json` - Full translations: config (3 steps + abort), options, entity names
- `custom_components/asp_parking/translations/en.json` - English translations (copy of strings.json per HA convention)
- `custom_components/asp_parking/services.yaml` - resolve_now service definition
- `custom_components/asp_parking/coordinator.py` - ASPParkingCoordinator with ASPParkingData, GPS subscription, debounce, full pipeline, error handling, periodic refresh, force resolve

## Decisions Made
- Custom coordinator instead of DataUpdateCoordinator since GPS events are the primary data source (not polling)
- ASPParkingData is a mutable dataclass (breaking project convention of frozen) because coordinator updates fields incrementally
- Debouncer set to immediate=False so multiple rapid GPS updates coalesce into one pipeline run after cooldown
- Pipeline errors fall back to last known state rather than clearing (user decision from CONTEXT.md)
- OutsideNYCError produces "outside_coverage" sentinel, NoSegmentFound/Ambiguous produces "no_street_match" sentinel

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Coordinator ready for Plan 02 (config flow and __init__.py entry points)
- Entity notification callback system ready for Plan 02 sensor/binary_sensor entities
- All constants defined for config flow step validation
- strings.json covers the multi-step wizard design (user -> vehicle -> settings)

## Self-Check: PASSED

All 7 created files verified on disk. Both task commits (79d7e7b, c95d3fd) verified in git log.

---
*Phase: 04-home-assistant-integration*
*Completed: 2026-02-22*
