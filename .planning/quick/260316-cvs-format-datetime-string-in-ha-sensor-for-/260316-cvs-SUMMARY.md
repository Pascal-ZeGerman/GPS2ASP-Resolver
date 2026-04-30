---
phase: quick-260316-cvs
plan: 01
subsystem: ui
tags: [home-assistant, sensor, datetime-formatting, lovelace]

# Dependency graph
requires: []
provides:
  - _format_move_time() helper on ASPNextMoveTimeSensor converting UTC datetime to human-friendly local time string
  - Human-friendly native_value for ScheduleFound ("Mon 8:00 AM") and ASPActiveNow ("⚠ Today 8:00 AM")
  - urgency attribute ("high"/"normal") in extra_state_attributes for conditional Lovelace card styling
affects: [lovelace-dashboard, conditional-card-styling]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_format_move_time() uses dt_util.as_local() for TZ conversion and strftime('%-I:%M %p') for no-leading-zero 12h format"
    - "urgency threshold is 12h — same constant used in both _format_move_time and extra_state_attributes block"

key-files:
  created: []
  modified:
    - custom_components/asp_parking/sensor.py
    - tests/test_ha_integration.py

key-decisions:
  - "%-I:%M %p strftime format used for no-leading-zero 12h time (Linux-specific, matches HA host environment)"
  - "Urgency threshold hardcoded as 12*3600 seconds (not a named constant) — consistent with _format_move_time"
  - "ISO datetime attributes (next_window_start/end, current_window_start/end) deliberately unchanged — raw ISO retained for programmatic use"
  - "urgency key absent when next_window is None for ScheduleFound — avoids misleading urgency with no concrete datetime"

patterns-established:
  - "Test helpers in test_ha_integration.py mirror sensor.py logic using stdlib only (no dt_util dependency)"

requirements-completed: []

# Metrics
duration: 8min
completed: 2026-03-16
---

# Quick Task 260316-cvs: Format datetime string in HA sensor Summary

**Human-readable native_value ("Mon 8:00 AM" / "⚠ Today 8:00 AM") and urgency attribute added to ASPNextMoveTimeSensor, replacing raw ISO 8601 dashboard output.**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-03-16T13:38:00Z
- **Completed:** 2026-03-16T13:46:00Z
- **Tasks:** 1 (TDD: RED + GREEN)
- **Files modified:** 2

## Accomplishments

- Added `_format_move_time(dt)` private method to `ASPNextMoveTimeSensor` that converts a timezone-aware datetime to local time and returns "Mon 8:00 AM" (normal) or "⚠ Today 8:00 AM" (urgent, <12h threshold)
- Updated `native_value` for both `ScheduleFound` and `ASPActiveNow` branches to call the helper, eliminating raw ISO strings from the HA dashboard
- Added `urgency` attribute ("high"/"normal") to `extra_state_attributes` inside the ScheduleFound/ASPActiveNow block, keyed on the same 12-hour threshold — enables conditional Lovelace card styling
- All ISO datetime attributes (`next_window_start`, `next_window_end`, `current_window_start`, `current_window_end`) left unchanged for programmatic use
- 270 non-network tests pass with zero regressions

## Task Commits

TDD — two commits:

1. **RED — failing tests** - `1731bdc` (test: add failing tests for human-friendly native_value and urgency attribute)
2. **GREEN — implementation** - `88f580d` (feat: format native_value as human-friendly string, add urgency attribute)

## Files Created/Modified

- `custom_components/asp_parking/sensor.py` — added `_format_move_time()`, updated `native_value`, added `urgency` to `extra_state_attributes`
- `tests/test_ha_integration.py` — added Group 6 (TestHumanFriendlyNativeValue) and TestUrgencyAttribute test classes; updated Group 1 assertions to match new format; updated `sensor_native_value` and `sensor_extra_attributes` helpers to mirror new sensor logic

## Decisions Made

- `%-I:%M %p` strftime format for no-leading-zero 12h time (Linux-specific, matches HA host environment)
- Urgency threshold is 12 hours (hardcoded) — same value in both the helper and the attributes block
- ISO attributes deliberately unchanged — raw ISO datetimes still available for automations/scripts
- `urgency` key absent when `next_window is None` (ScheduleFound with no upcoming window)

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

- Test assertion `"T" not in state` failed for "Tue ..." (Tuesday abbreviation contains "T") — fixed to use `re.match(r"\d{4}-\d{2}-\d{2}T", state)` instead.

## Next Phase Readiness

- Lovelace conditional cards can now use `urgency == 'high'` to trigger visual alerts when move time is <12h away
- No blockers for Phase 12

---
*Quick task: 260316-cvs*
*Completed: 2026-03-16*
