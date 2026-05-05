---
phase: 30-add-richer-debug-sensor-pipeline-attributes
plan: 04
subsystem: homeassistant-sensor
tags: [python, homeassistant, sensor, extra_state_attributes, diagnostic]

# Dependency graph
requires:
  - phase: 30-add-richer-debug-sensor-pipeline-attributes
    plan: 03
    provides: ASPParkingData.borough / .distance_ft / .street_width_ft / .segment_id (consumed by sensor.extra_state_attributes)
provides:
  - "ASPResolvedStreetSensor.extra_state_attributes returns 8 keys (4 existing + 4 new diagnostic) read from coordinator.data"
  - "ASPNextMoveTimeSensor.extra_state_attributes['borough'] populated from coordinator.data.borough (no longer hardcoded None)"
  - "Test helper sensor_extra_attributes() in tests/test_ha_integration.py mirrors the production borough behavior"
  - "Local ASPParkingData mirror in tests/test_ha_integration.py gains 4 Phase 30 fields so the helper read of data.borough resolves"
  - "Two new HA-marked tests covering both sensor branches"
affects:
  - End users (Phase 30 user-visible deliverable: borough/distance/width/segment_id appear on the resolved-street sensor card; borough appears on the next-move sensor)

# Tech tracking
tech-stack:
  added: []  # No new deps; uses existing pytest + unittest.mock
  patterns:
    - "Sensor extra_state_attributes returns a fresh dict literal each access (no shared mutable state across HA polling cycles)"
    - "Test imports HA-dependent symbols inside the test function body (consistent with the file's no-HA-imports-at-module-top convention)"
    - "Vendored class import pattern: tests that exercise sensor.py's isinstance() branches MUST import ScheduleFound from custom_components/asp_parking/gps2asp/ (the vendored copy used by sensor.py), not from src/gps2asp/, because they are different class objects"
    - "Local ASPParkingData mirror in tests/test_ha_integration.py is extended in lockstep with the production dataclass when new fields flow into helper logic"

key-files:
  created: []
  modified:
    - custom_components/asp_parking/sensor.py
    - tests/test_ha_integration.py
    - .planning/phases/30-add-richer-debug-sensor-pipeline-attributes/deferred-items.md

key-decisions:
  - "D-13 (closed): ASPResolvedStreetSensor.extra_state_attributes returns 4 new keys (borough, distance_ft, street_width_ft, segment_id) read from coordinator.data alongside existing 4 keys"
  - "D-14 (closed): ASPNextMoveTimeSensor borough placeholder (previously hardcoded None with 'Not in current pipeline output' comment) is replaced with data.borough"

patterns-established:
  - "Vendored gps2asp imports in HA tests: when a test asserts against an isinstance() branch in sensor.py / coordinator.py / binary_sensor.py, import ScheduleFound (and other schedule.models classes) from custom_components.asp_parking.gps2asp.schedule.models inside the test, not from the canonical src/gps2asp/ at module top — the vendored class is a different class object and isinstance() against the canonical class will silently return False"
  - "Local ASPParkingData mirror at tests/test_ha_integration.py:60-79 is co-evolved with the production dataclass — when production grows a new field that flows into a sensor_extra_attributes helper read, the mirror must gain the same field with the same default"

requirements-completed: [DIAG-04]

# Metrics
duration: ~10min
completed: 2026-05-03
---

# Phase 30 Plan 04: Sensor diagnostic attributes Summary

**ASPResolvedStreetSensor surfaces 4 new diagnostic attributes (borough, distance_ft, street_width_ft, segment_id) and ASPNextMoveTimeSensor's borough placeholder is replaced with the live coordinator value — completing Phase 30's user-visible deliverable; only sensor attributes added, no new entities.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-05-03 (approx — execution start)
- **Completed:** 2026-05-03 (approx — final commit)
- **Tasks:** 2 (both edits committed atomically per the plan's Task 2 commit instruction)
- **Files modified:** 2 (sensor.py, tests/test_ha_integration.py)
- **Files created:** 0 (this plan only adds attributes to existing entities; no new sensor classes)

## Accomplishments

- **`ASPResolvedStreetSensor.extra_state_attributes`** (sensor.py lines 407-422) extended from 4 keys to 8: the existing `from_street`, `to_street`, `side_of_street`, `confidence_score` plus the 4 new Phase 30 diagnostic fields `borough`, `distance_ft`, `street_width_ft`, `segment_id`. Return type widened from `dict[str, str | float | None]` to `dict[str, str | float | int | None]` because `segment_id` is `int` per Plan 03's ASPParkingData (D-13).
- **`ASPNextMoveTimeSensor.extra_state_attributes`** (sensor.py line 243) borough placeholder replaced. Before: `attrs["borough"] = None  # Not in current pipeline output`. After: `attrs["borough"] = data.borough`. The stale comment is removed (D-14).
- **`tests/test_ha_integration.py` helper** at line 178 (`sensor_extra_attributes()`) updated in lockstep with the production change: `attrs["borough"] = data.borough`.
- **Local `ASPParkingData` mirror** in tests/test_ha_integration.py (lines 60-79) extended with the 4 Phase 30 diagnostic fields (`borough: str | None = None`, `distance_ft: float | None = None`, `street_width_ft: float | None = None`, `segment_id: int | None = None`). Required so the helper's new `data.borough` read resolves at runtime.
- **Two new HA-marked focused tests** appended at end of test_ha_integration.py:
  - `test_resolved_street_sensor_exposes_phase_30_diagnostic_attributes` — instantiates the real `ASPResolvedStreetSensor` with a `MagicMock` coordinator whose `.data` is a populated local `ASPParkingData`; asserts all 4 new attribute keys equal the populated values and the 4 existing keys are still present.
  - `test_next_move_time_sensor_borough_attribute_populated_from_coordinator_data` — calls the helper directly with `data.borough = "Manhattan"` and asserts `attrs["borough"] == "Manhattan"`.
- Phase 30's user-visible deliverable is now complete end-to-end: Plan 01 added the 4 fields to `ResolutionResult`; Plan 02 added them to `ASPDebugResult`; Plan 03 threaded them through `ASPParkingData` with borough mapping; Plan 04 surfaces them on the HA sensor cards.

## Task Commits

Each task was committed atomically per the plan instructions (Task 1 was a non-committing prep step; Task 2 committed both edits together):

1. **Task 1 (sensor.py edits) + Task 2 (tests + helper)** — `d8b6073` (feat) — `feat(30-04): expose borough and 3 diagnostic attributes on resolved-street + next-move sensors`

The plan's Task 1 explicitly says "Do NOT commit yet — Task 2 updates the test helper in the same logical change", so this single commit covers both tasks.

## Files Created/Modified

- `custom_components/asp_parking/sensor.py` — **modified** — `ASPResolvedStreetSensor.extra_state_attributes` (lines 407-422): +5 lines (4 new dict entries + widened return-type annotation, with one new docstring line); `ASPNextMoveTimeSensor.extra_state_attributes` (line 243): one-line replacement (drops the stale comment).
- `tests/test_ha_integration.py` — **modified** — local `ASPParkingData` mirror gains 4 fields (+5 lines incl. comment); helper at line 178 one-line replacement; two new test functions appended (~64 lines total incl. docstrings, marker decorators, vendored-import pattern explanation).
- `.planning/phases/30-add-richer-debug-sensor-pipeline-attributes/deferred-items.md` — **modified** — appended one entry documenting the pre-existing `TestSuspensionPoll::test_suspension_poll_does_not_require_gps_coordinates` failure (Phase 22 string-based check vs. Phase 24 `_get_now()` indirection).

## Sensor Attribute Surface Change

| Sensor | Method | Before keys | After keys | Net delta |
|--------|--------|-------------|------------|-----------|
| `ASPResolvedStreetSensor` | `extra_state_attributes` | 4 | 8 | +4 (`borough`, `distance_ft`, `street_width_ft`, `segment_id`) |
| `ASPNextMoveTimeSensor` | `extra_state_attributes` (location group) | borough hardcoded `None` | borough = `data.borough` | placeholder replaced |

No new sensor classes. No changes to `async_setup_entry`. No changes to `__init__.py` or `manifest.json`.

## Test Count Delta

- 2 new tests appended to `tests/test_ha_integration.py`: `test_resolved_street_sensor_exposes_phase_30_diagnostic_attributes` and `test_next_move_time_sensor_borough_attribute_populated_from_coordinator_data`
- Net delta: **+2 HA tests** (no existing tests modified or deleted)
- Pre-edit (Plan 30-03 baseline) `test_ha_integration.py` results: 64 passed, 1 failed
- Post-edit `test_ha_integration.py` results: **66 passed, 1 failed** (the +2 are the new tests; the 1 failure is the pre-existing `TestSuspensionPoll::test_suspension_poll_does_not_require_gps_coordinates`)
- Full fast suite (`pytest tests/ -m "not integration"`) results: **420 passed, 4 failed, 32 deselected** — all 4 failures verified pre-existing by stashing edits + re-running (same 4 failures appear at the worktree base commit `6ca1f58`)

## Decisions Made

Followed plan as specified — D-13 and D-14 implemented exactly as defined. No new decisions required.

## Deviations from Plan

### `[Rule 3 - Blocking issue]` Vendored ScheduleFound import in new test

- **Found during:** Task 2 (first run of `test_resolved_street_sensor_exposes_phase_30_diagnostic_attributes` failed with `KeyError: 'borough'`)
- **Issue:** The plan's example test built `ScheduleFound` via `_make_schedule_found()`, which constructs the **canonical** `gps2asp.schedule.models.ScheduleFound`. But `sensor.py` imports `from .gps2asp.schedule.models import ScheduleFound` — the **vendored** copy at `custom_components/asp_parking/gps2asp/schedule/models.py`. These are two different class objects, so `isinstance(schedule, ScheduleFound)` in the sensor returns `False` against a canonical-class instance, triggering the early `return {}` branch and returning an empty dict.
- **Fix:** In the new `test_resolved_street_sensor_exposes_phase_30_diagnostic_attributes` test, import `ScheduleFound as VendoredScheduleFound` from `custom_components.asp_parking.gps2asp.schedule.models` inside the test function and construct the schedule with the vendored class. Added an inline comment explaining the rationale for future maintainers.
- **Files modified:** tests/test_ha_integration.py (within the new test function)
- **Commit:** d8b6073

### `[Rule 3 - Blocking issue]` Add 4 Phase 30 fields to local ASPParkingData mirror

- **Found during:** Task 2 (helper change to `attrs["borough"] = data.borough` would `AttributeError` without the field)
- **Issue:** The plan's Task 2 Edit 1 instructs replacing the hardcoded `attrs["borough"] = None` with `attrs["borough"] = data.borough` in `sensor_extra_attributes()`. But the local `ASPParkingData` mirror at `tests/test_ha_integration.py:60-79` did not yet have the `borough` field — calling the helper would fail with `AttributeError: 'ASPParkingData' object has no attribute 'borough'`.
- **Fix:** Added all 4 Phase 30 fields (`borough`, `distance_ft`, `street_width_ft`, `segment_id`) to the local mirror with `None` defaults (mirrors production exactly, see coordinator.py lines 150-153). Added a comment marking the section as Phase 30 mirrors. The other 3 fields aren't strictly required by the helper today, but are added for symmetry with production and to avoid future surprises if/when the helper grows additional reads.
- **Files modified:** tests/test_ha_integration.py (lines 75-80, ASPParkingData mirror)
- **Commit:** d8b6073

Both deviations are Rule 3 (auto-fix blocking issues) — without them, the new test or the updated helper would fail at runtime, blocking task completion.

## Issues Encountered

- **Pre-existing failure: `tests/test_ha_integration.py::TestSuspensionPoll::test_suspension_poll_does_not_require_gps_coordinates`** — Verified pre-existing by stashing all 30-04 edits and re-running the same test (still fails with the same `AssertionError: 'datetime.now(NYC_TZ).date()' in src` substring missing). Root cause: Phase 22 wrote a string-based assertion looking for the literal `datetime.now(NYC_TZ).date()` in coordinator.py source, but Phase 24 replaced direct `datetime.now()` calls with a `_get_now()` indirection. Behavioral intent is still satisfied. Logged to `deferred-items.md`. Out-of-scope per scope boundary rule (Plan 30-04 only touches sensor.py and test helper / 2 new tests in test_ha_integration.py).
- **Pre-existing failures: `tests/test_repair_issue.py::test_import_error_logs_actionable`, `tests/test_repair_issue.py::test_import_error_creates_repair`, `tests/test_suspension.py::test_is_suspended_holiday`** — All verified pre-existing by stash-and-rerun. Already tracked in `deferred-items.md` (the suspension test was logged in Plan 30-01).
- **No new regressions** — total fast-suite delta is exactly +2 passing tests, 0 new failures.

## User Setup Required

None — once the integration is reloaded in HA (or HA is restarted), the resolved-street sensor card will surface the 4 new attributes on the next pipeline run, and the next-move sensor card will show the live borough name. No config-flow changes; no new entities to add to dashboards.

## Phase 30 Readiness

This is the final wave of Phase 30. All four plans are now complete:

- Plan 30-01: ResolutionResult exposes borocode / perpendicular_distance_ft / street_width_ft / segment_id ✓
- Plan 30-02: ASPDebugResult exposes the same 4 fields at the pipeline boundary ✓
- Plan 30-03: ASPParkingData threads the 4 fields through with borough mapping ✓
- Plan 30-04: HA sensor entities surface the 4 fields as `extra_state_attributes` ✓

The Phase 30 user-visible deliverable (borough + 3 diagnostic fields visible on the HA sensor card) is end-to-end complete.

## Self-Check: PASSED

- `custom_components/asp_parking/sensor.py` modified ✓ (FOUND in `git diff HEAD~1 HEAD`)
- `tests/test_ha_integration.py` modified ✓ (FOUND in `git diff HEAD~1 HEAD`)
- Commit `d8b6073` exists in git log ✓ (FOUND via `git log --oneline -1`)
- ASPResolvedStreetSensor returns 8 keys ✓ (4 new keys present in dict literal via `awk` range; verified via `grep -c '"borough":\|"distance_ft":\|"street_width_ft":\|"segment_id":'` returning 4)
- ASPResolvedStreetSensor reads from coordinator.data ✓ (4 reads of `self._coordinator.data.<field>` for the new fields)
- Type annotation widened to include `int` ✓ (`dict[str, str | float | int | None]` present)
- Old hardcoded `attrs["borough"] = None` removed from sensor.py ✓ (count: 0)
- "Not in current pipeline output" comment removed ✓ (count: 0)
- New `attrs["borough"] = data.borough` present in sensor.py ✓ (count: 1)
- Test helper updated ✓ (`grep -c 'attrs\["borough"\] = data\.borough' tests/test_ha_integration.py` returns 1)
- Old hardcoded helper line removed ✓ (`grep -c 'attrs\["borough"\] = None' tests/test_ha_integration.py` returns 0)
- Two new tests added ✓ (both function names found in test file)
- Both new tests pass ✓ (`pytest -k "test_resolved_street_sensor_exposes_phase_30_diagnostic_attributes or test_next_move_time_sensor_borough_attribute_populated_from_coordinator_data"` reports `2 passed`)
- Module compiles cleanly ✓ (`python -m py_compile custom_components/asp_parking/sensor.py` exits 0)
- No file deletions in commit ✓ (verified via `git diff --diff-filter=D --name-only HEAD~1 HEAD` returning empty)
- Zero new test regressions ✓ (4 fast-suite failures all verified pre-existing via stash-and-rerun)

---
*Phase: 30-add-richer-debug-sensor-pipeline-attributes*
*Completed: 2026-05-03*
