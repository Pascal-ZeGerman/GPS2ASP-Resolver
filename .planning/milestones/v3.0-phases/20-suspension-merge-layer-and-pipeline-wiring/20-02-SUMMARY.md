---
phase: 20-suspension-merge-layer-and-pipeline-wiring
plan: 02
subsystem: suspension
tags: [suspension, pipeline, vendor-sync, apply_suspension, schedule-models]

# Dependency graph
requires:
  - phase: 20-01
    provides: apply_suspension() pure function, SuspensionInfo.source field, ScheduleFound/ASPActiveNow suspension fields
provides:
  - resolve_asp() with optional suspension_status: SuspensionInfo | None = None parameter
  - Stage 4 conditional suspension annotation in pipeline.py after compute_schedule()
  - Vendored custom_components/asp_parking/gps2asp/suspension/__init__.py with source field
  - Vendored custom_components/asp_parking/gps2asp/suspension/merge.py with apply_suspension()
  - Vendored custom_components/asp_parking/gps2asp/schedule/models.py with suspension_reason + resolution_reason
affects:
  - 22-ha-coordinator-and-sensor-integration (coordinator can now call resolve_asp(suspension_status=...) directly)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Stage 4 as optional post-pipeline annotation: guard with `if suspension_status is not None`"
    - "Vendor sync: Write tool copy from src/ to custom_components/asp_parking/gps2asp/ — no import path changes needed (mirror structure)"

key-files:
  created:
    - custom_components/asp_parking/gps2asp/suspension/merge.py
  modified:
    - src/gps2asp/pipeline.py
    - custom_components/asp_parking/gps2asp/suspension/__init__.py
    - custom_components/asp_parking/gps2asp/schedule/models.py

key-decisions:
  - "Stage 4 inserts after compute_schedule() as a simple conditional guard — no debug branch duplication needed because schedule variable is shared"
  - "suspension_status default is None (not SuspensionInfo(is_suspended=False)) — explicit None means 'caller did not check', preserving strict backwards compatibility"
  - "Vendor sync uses Write tool for exact copy — shell cp avoided per plan instruction to allow import verification"

patterns-established:
  - "Pipeline Stage 4: optional post-pipeline annotation via if suspension_status is not None: schedule = apply_suspension(schedule, suspension_status)"
  - "Public API extension: add optional keyword-arg with None default to maintain backwards compatibility across @overload signatures"

requirements-completed: [SUSP-03]

# Metrics
duration: 10min
completed: 2026-04-02
---

# Phase 20 Plan 02: Pipeline Wiring and Vendor Sync Summary

**resolve_asp() extended with optional suspension_status parameter wiring apply_suspension() as Stage 4; vendored HA copy synced with source field, merge.py, and suspension_reason/resolution_reason fields**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-04-02T16:13:10Z
- **Completed:** 2026-04-02T16:20:40Z
- **Tasks:** 2
- **Files modified:** 4 (1 created, 3 modified)

## Accomplishments

- Wired `apply_suspension()` as optional Stage 4 in `pipeline.py` — `resolve_asp()` now accepts `suspension_status: SuspensionInfo | None = None`
- Updated both `@overload` signatures with the new parameter for correct type narrowing
- Confirmed strict backwards compatibility: None default means Stage 4 is a no-op when caller omits the argument
- Synced all Phase 20 changes to the vendored copy in `custom_components/asp_parking/gps2asp/`:
  - `suspension/__init__.py` — added `source: Literal` field and `apply_suspension` re-export
  - `suspension/merge.py` — new file, exact copy of `src/gps2asp/suspension/merge.py`
  - `schedule/models.py` — added `suspension_reason` and `resolution_reason` to `ScheduleFound` and `ASPActiveNow`

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire apply_suspension() as Stage 4 in pipeline.py** - `9a6ff86` (feat)
2. **Task 2: Sync Phase 20 changes to vendored copy** - `90924e5` (feat)

## Files Created/Modified

- `src/gps2asp/pipeline.py` — added suspension_status parameter, Stage 4 guard, SuspensionInfo/apply_suspension imports
- `custom_components/asp_parking/gps2asp/suspension/__init__.py` — source field on SuspensionInfo, apply_suspension re-export
- `custom_components/asp_parking/gps2asp/suspension/merge.py` — new: apply_suspension() pure function (vendored copy)
- `custom_components/asp_parking/gps2asp/schedule/models.py` — suspension_reason + resolution_reason on ScheduleFound and ASPActiveNow

## Decisions Made

- Stage 4 inserts after `compute_schedule()` — the `schedule` variable is already shared between the debug and non-debug paths, so no duplication needed. `apply_suspension()` runs once and both branches use the annotated result.
- `suspension_status=None` (not `SuspensionInfo(is_suspended=False)`) is the backwards-compatible default — explicit None means the caller made no suspension check, not that suspension was checked and found inactive.
- Vendor sync via Write tool (not shell `cp`) per plan instruction, verifying that the relative import paths (`from ..schedule.models import`) are correct for the vendored package structure.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None. Pre-existing test failures in `test_resolver.py` (NoSegmentFoundError from missing spatial index in sandbox) and `test_sign_retrieval.py` (network blocked by pytest_socket) are unrelated to Phase 20 changes and were failing before this plan.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `resolve_asp(lat, lon, suspension_status=SuspensionInfo(is_suspended=True, reason='MLK Day', source='holiday'))` returns an `ASPResult` whose `schedule.suspended` is `True` — all success criteria met
- Phase 20 is complete; vendored copy is fully in sync
- Phase 22 (HA Coordinator and Sensor Integration) can now call `resolve_asp(suspension_status=...)` directly without any additional library changes

---
*Phase: 20-suspension-merge-layer-and-pipeline-wiring*
*Completed: 2026-04-02*
