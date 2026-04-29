---
phase: 20-suspension-merge-layer-and-pipeline-wiring
plan: 01
subsystem: suspension
tags: [suspension, merge, dataclasses, tdd, schedule-models]

# Dependency graph
requires:
  - phase: 19-suspension-package-foundation
    provides: SuspensionInfo, HolidayCalendar, iCalendar parsing with fallback
provides:
  - SuspensionInfo.source field (Literal['holiday', 'emergency', 'none'])
  - ScheduleFound/ASPActiveNow suspension_reason + resolution_reason fields
  - apply_suspension() pure function in src/gps2asp/suspension/merge.py
  - Re-export of apply_suspension from suspension/__init__.py
affects:
  - 20-02 (pipeline wiring will call apply_suspension())
  - 22-ha-coordinator-and-sensor-integration (coordinator uses apply_suspension())

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "dataclasses.replace() for frozen dataclass mutation in suspension merge layer"
    - "TDD RED-GREEN-REFACTOR for pure function implementation"
    - "Literal source field dispatch to derive resolution_reason"

key-files:
  created:
    - src/gps2asp/suspension/merge.py
    - tests/test_suspension_merge.py
  modified:
    - src/gps2asp/suspension/__init__.py
    - src/gps2asp/schedule/models.py

key-decisions:
  - "apply_suspension() is a pure function using dataclasses.replace() — no mutation, frozen dataclasses throughout"
  - "source field dispatch (not string parsing) to map 'holiday'/'emergency' to resolution_reason literals"
  - "Non-schedule types (NoASPSchedule, NoMatchSchedule, AllUnparseable) pass through unchanged regardless of suspension status"
  - "Unknown source value falls back to 'suspended_holiday' — conservative safe default"

patterns-established:
  - "Suspension merge: apply_suspension(schedule, info) -> ScheduleResult always returns same type as input"
  - "Schema: suspended=False is the default, suspension_reason=None, resolution_reason=None until apply_suspension() annotates"

requirements-completed: [SUSP-03]

# Metrics
duration: 15min
completed: 2026-04-02
---

# Phase 20 Plan 01: Suspension Merge Layer Summary

**apply_suspension() pure function with dataclasses.replace() annotates ScheduleFound/ASPActiveNow with suspended=True, suspension_reason, and resolution_reason derived from SuspensionInfo.source**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-04-02T00:00:00Z
- **Completed:** 2026-04-02
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Extended `SuspensionInfo` with `source: Literal['holiday', 'emergency', 'none'] = 'none'` field
- Extended `ScheduleFound` and `ASPActiveNow` with `suspension_reason: str | None = None` and `resolution_reason: Literal[...] | None = None` — all with defaults so no existing construction sites break
- Implemented `apply_suspension()` as a pure function using `dataclasses.replace()` in `src/gps2asp/suspension/merge.py`
- Full TDD coverage: 8 new tests (holiday/emergency on ScheduleFound/ASPActiveNow, all pass-through cases), all passing alongside 10 existing suspension tests

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend SuspensionInfo and schedule models** - `7b98dad` (feat)
2. **Task 2 RED: Failing tests for apply_suspension()** - `f32ea8b` (test)
3. **Task 2 GREEN: Implement apply_suspension()** - `1e4f3eb` (feat)

_Note: TDD tasks have multiple commits (test RED → feat GREEN)_

## Files Created/Modified

- `src/gps2asp/suspension/merge.py` — new apply_suspension() pure function
- `tests/test_suspension_merge.py` — 8 TDD tests for all merge scenarios
- `src/gps2asp/suspension/__init__.py` — source field already in place; re-export of apply_suspension added
- `src/gps2asp/schedule/models.py` — suspension_reason + resolution_reason added to ScheduleFound and ASPActiveNow

## Decisions Made

- `apply_suspension()` uses `dataclasses.replace()` (per D-03 from research) — frozen dataclasses require this pattern
- Source field dispatch (not string parsing) cleanly maps 'holiday' -> 'suspended_holiday', 'emergency' -> 'suspended_emergency'
- Unknown source falls back to 'suspended_holiday' as the conservative default
- Non-schedule result types pass through unchanged — suspension only applies to schedule types that have a `suspended` field

## Deviations from Plan

None — plan executed exactly as written. Task 1 schema changes were already partially in place from a prior session; confirmed and committed as-is.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `apply_suspension()` is ready for pipeline wiring in Plan 02
- All 54 tests (suspension + suspension_merge + schedule) pass with no regressions
- Phase 20 Plan 02 can call `apply_suspension(schedule_result, holiday_calendar.is_suspended(today))` directly

---
*Phase: 20-suspension-merge-layer-and-pipeline-wiring*
*Completed: 2026-04-02*
