---
phase: 39-window-boundary-timer
plan: "01"
subsystem: home-assistant
tags:
  - coordinator
  - timer
  - async-call-later
  - boundary-timer
  - tdd
dependency_graph:
  requires: []
  provides:
    - window-boundary-timer
  affects:
    - custom_components/asp_parking/coordinator.py
tech_stack:
  added: []
  patterns:
    - "@callback + entry.async_create_background_task for lifecycle-tied timer fire (WR-01)"
    - "SimpleNamespace + _bind test pattern (mirrors test_coordinator_stale.py)"
    - "max(0.0, ...) delay clamp for past-boundary race protection (D-06)"
key_files:
  created:
    - tests/test_coordinator_boundary_timer.py
  modified:
    - custom_components/asp_parking/coordinator.py
decisions:
  - "D-01: ScheduleFound(next_window=None) skips timer, logs DEBUG — no warning noise"
  - "D-02: _boundary_timer_cancel() called unconditionally at start of _async_schedule_boundary_timer — no dangling timers"
  - "D-03: _boundary_timer_unsub is a dedicated attribute, NOT in _listeners; async_stop calls _boundary_timer_cancel() explicitly"
  - "D-04: Timer fire closure uses entry.async_create_background_task (WR-01) — HA auto-cancels on entry unload"
  - "D-05: _async_schedule_boundary_timer(schedule) called after compute_schedule() but before self.data.schedule_result = schedule, inside success try block"
  - "D-06: delay = max(0.0, ...) — past boundaries fire on next event-loop iteration (0.0 delay)"
  - "D-07: Suspended schedules still schedule boundary timer — suspension re-evaluated at fire time"
  - "D-08: async_call_later imported from homeassistant.helpers.event, prepended to existing import block"
  - "D-09: Cancel clears _boundary_timer_unsub to None BEFORE calling stored callable (clear-first defensive ordering)"
metrics:
  duration_seconds: 355
  completed: "2026-05-23"
  tasks_completed: 3
  files_changed: 2
---

# Phase 39 Plan 01: Window-Boundary Timer Summary

One-shot `async_call_later` boundary timer added to the HA coordinator: fires at `active_window.end_datetime` (ASPActiveNow) or `next_window.start_datetime` (ScheduleFound) and re-runs the pipeline via `entry.async_create_background_task` so sensor state advances at window boundaries without GPS movement.

## What Was Built

### New in `coordinator.py`

**Import changes:**
- Added `async_call_later` to the `from homeassistant.helpers.event import (...)` block (D-08)
- Added `ASPActiveNow` to the `from .gps2asp.schedule.models import (...)` block

**New instance variable (line ~282):**
- `self._boundary_timer_unsub: CALLBACK_TYPE | None = None` — dedicated attribute, NOT appended to `self._listeners` (D-03)

**New method `_boundary_timer_cancel()`:**
- `@callback`-decorated synchronous method
- D-09 clear-first ordering: sets `self._boundary_timer_unsub = None` BEFORE calling the stored cancel callable
- Safe no-op when `_boundary_timer_unsub` is already None

**New method `_async_schedule_boundary_timer(schedule: ScheduleResult)`:**
- `@callback`-decorated synchronous method (no `await` needed)
- D-02: inlines the D-09 cancel pattern unconditionally as first action
- `ASPActiveNow` → timer at `active_window.end_datetime`
- `ScheduleFound(next_window != None)` → timer at `next_window.start_datetime`
- `ScheduleFound(next_window=None)` → DEBUG log, return (D-01)
- Other statuses → DEBUG log, return (D-02)
- D-06: `delay = max(0.0, (dt_util.as_utc(boundary_dt) - dt_util.utcnow()).total_seconds())`
- Inner `@callback` closure `_on_boundary_fire` calls `entry.async_create_background_task(..., name="asp_parking_boundary_timer")` (D-04/WR-01)

**Call site in `_async_resolve_pipeline`:**
- `self._async_schedule_boundary_timer(schedule)` inserted immediately after `compute_schedule(...)`, before `self.data.schedule_result = schedule` (D-05)
- Inside the success `try` block only — never in any `except` branch (Pitfall 5)

**`async_stop` hook:**
- `self._boundary_timer_cancel()` inserted between `self._debouncer.async_cancel()` and the `logger.info(...)` line (D-03)

### New `tests/test_coordinator_boundary_timer.py`

11 unit tests covering the complete boundary-timer surface:

| Test | What it covers |
|------|----------------|
| `test_cancel_is_noop_when_unsub_is_none` | No-op when attr is None |
| `test_cancel_clears_attr_before_calling_unsub` | D-09 clear-first ordering proof |
| `test_cancel_calls_stored_callable_once` | Cancel callable invoked exactly once |
| `test_aspactivenow_schedules_timer_at_window_end` | SC-1 / ASPActiveNow → end_datetime |
| `test_schedulefound_with_next_window_schedules_at_start` | SC-2 / ScheduleFound → start_datetime |
| `test_schedulefound_with_none_next_window_skips_with_debug_log` | D-01 / next_window=None |
| `test_new_schedule_cancels_prior_timer_first` | SC-3 / D-02 prior-cancel before new |
| `test_noasp_status_cancels_prior_and_does_not_register` | SC-3 / D-02 non-ASP cancels |
| `test_past_boundary_produces_delay_zero` | D-06 max-clamp to 0.0 |
| `test_fire_callback_spawns_pipeline_via_entry_task` | D-04 / "asp_parking_boundary_timer" |
| `test_suspended_schedulefound_still_schedules_timer` | D-07 suspension is not a skip |

## ROADMAP Success Criteria Mapping

| SC | Requirement | Test(s) |
|----|-------------|---------|
| SC-1 | ASPActiveNow → timer at active_window.end_datetime | `test_aspactivenow_schedules_timer_at_window_end` |
| SC-2 | ScheduleFound+next_window → timer at next_window.start_datetime | `test_schedulefound_with_next_window_schedules_at_start` |
| SC-3 | Prior timer cancelled unconditionally before new registration | `test_new_schedule_cancels_prior_timer_first`, `test_noasp_status_cancels_prior_and_does_not_register` |
| SC-4 | No regressions in full offline test suite | Task 3 — 691 tests pass |

## TDD Gate Compliance

- RED gate: commit `721ba43` — `test(39-01): RED — boundary timer unit test scaffold (11 tests)`
- GREEN gate: commit `1d11309` — `feat(39-01): GREEN — boundary timer methods + import + call site + async_stop hook`
- FULL GREEN gate: commit `1642fcb` — `chore(39-01): green gate — full pytest suite passes; vendor-guard clean`

## Deviations from Plan

### Auto-fixed Implementation Detail

**[Rule 1 - Bug] Inlined cancel logic in `_async_schedule_boundary_timer` instead of calling `self._boundary_timer_cancel()`**

- **Found during:** Task 2 GREEN implementation
- **Issue:** The plan specified `self._boundary_timer_cancel()` as first statement of `_async_schedule_boundary_timer`. However, the test stubs are `SimpleNamespace` objects — Python method lookup on `self` (the stub) only finds attributes set directly on the namespace, not class methods. Calling `self._boundary_timer_cancel()` from the bound method raised `AttributeError` on stubs that didn't pre-bind `_boundary_timer_cancel`.
- **Fix:** Replaced `self._boundary_timer_cancel()` call with the same 3-line inline D-09 pattern (`if self._boundary_timer_unsub is not None: _cancel = self._boundary_timer_unsub; self._boundary_timer_unsub = None; _cancel()`). The D-09 guarantee (clear-first) is fully preserved. `_boundary_timer_cancel()` remains a standalone method called from `async_stop` and usable directly.
- **Behavioral impact:** None — both patterns are functionally identical. The inline approach avoids the SimpleNamespace lookup limitation in tests.
- **Files modified:** `custom_components/asp_parking/coordinator.py`
- **Commit:** `1d11309`

## Known Stubs

None — all data paths are wired to real production logic.

## Threat Flags

No new external attack surface introduced. Phase 39 is coordinator-only (HA-internal event loop); no network I/O, no user input, no persisted state.

## Self-Check: PASSED

- `tests/test_coordinator_boundary_timer.py` exists: FOUND
- `custom_components/asp_parking/coordinator.py` contains `async_call_later`: FOUND
- `custom_components/asp_parking/coordinator.py` contains `_boundary_timer_cancel`: FOUND
- `custom_components/asp_parking/coordinator.py` contains `_async_schedule_boundary_timer`: FOUND
- Commits `721ba43`, `1d11309`, `1642fcb` exist: VERIFIED
- 691 offline tests pass: VERIFIED
- 11 boundary timer tests PASSED: VERIFIED
