---
phase: 29-debug-switch-logging
plan: 02
subsystem: ui
tags: [home-assistant, config-flow, options-flow, i18n, sensor, switch, debug]

# Dependency graph
requires:
  - phase: 29-debug-switch-logging
    provides: switch.asp_parking_debug_mode entity (Plan 29-01) — owns the on/off toggle previously held by ASPDebugModeSensor and the debug_enabled options-flow field
  - phase: 28-ux-copy-strings
    provides: strings.json/translations/en.json byte-equivalence invariant
  - phase: 24-debug-mode
    provides: original async_step_debug + ASPDebugModeSensor that this plan retires
provides:
  - async_step_debug scoped to lat/lon/datetime overrides only (D-04)
  - ASPDebugModeSensor class fully removed from sensor.py (D-07)
  - "GPS & Time Overrides" step title in both i18n files (D-05)
  - entity.switch.debug_switch translation key for the new switch entity (D-09)
  - entity.sensor.debug_mode translation key removed (D-08)
  - Carry-forward of CONF_DEBUG_ENABLED + CONF_SUPPRESS_NOTIFICATIONS in async_step_init preserved verbatim (D-06)
affects:
  - phase: 29-debug-switch-logging Plan 03 (logging upgrade) — no shared file conflicts
  - any future phase touching the options flow (debug step now has fewer fields)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Translation key for SwitchEntity placed under entity.switch.{key} (matches HA i18n convention)"
    - "Step rename in i18n requires byte-equivalent updates to BOTH strings.json AND translations/en.json (Phase 28 invariant)"
    - "Carry-forward block in async_step_init preserves persisted-but-unconfigurable options keys when their form field is removed"

key-files:
  created: []
  modified:
    - custom_components/asp_parking/sensor.py
    - custom_components/asp_parking/config_flow.py
    - custom_components/asp_parking/strings.json
    - custom_components/asp_parking/translations/en.json

key-decisions:
  - "Kept CONF_DEBUG_ENABLED + CONF_SUPPRESS_NOTIFICATIONS imports in config_flow.py (used by async_step_init carry-forward); only DEFAULT_DEBUG_ENABLED + DEFAULT_SUPPRESS_NOTIFICATIONS imports were dropped (truly unused after schema fields removed)"
  - "Plan-text snippet showed Debug Overrides description with -- (double dash); actual file uses em dash — (Phase 28 normalized). Edits used the em dash to match real file content"

patterns-established:
  - "i18n switch entity key: entity.switch.{translation_key} sibling to entity.binary_sensor / entity.sensor"

requirements-completed: [DBG-02]

# Metrics
duration: ~10min
completed: 2026-05-03
---

# Phase 29 Plan 02: Scope Debug Options to Overrides + Retire ASPDebugModeSensor Summary

**`async_step_debug` reduced to GPS/datetime overrides only (3 fields), ASPDebugModeSensor class removed, i18n step renamed to "GPS & Time Overrides" and switch translation key added — all without touching the async_step_init carry-forward that preserves existing persisted options.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-05-03T01:34:00Z (approx — plan execution start)
- **Completed:** 2026-05-03T01:44:20Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- Deleted `ASPDebugModeSensor` class from `sensor.py` (now replaced by `switch.asp_parking_debug_mode` from Plan 29-01)
- Reduced `async_step_debug` from 5 form fields to 3 (only `debug_lat`, `debug_lon`, `debug_datetime`)
- Renamed debug step UI title to "GPS & Time Overrides" in both `strings.json` and `translations/en.json`
- Added `entity.switch.debug_switch` translation key with name "Debug Mode" (target of Plan 01's switch entity)
- Removed `entity.sensor.debug_mode` translation key
- Preserved `async_step_init` carry-forward block byte-identically (D-06): `CONF_DEBUG_ENABLED` and `CONF_SUPPRESS_NOTIFICATIONS` still flow through `entry.options` so existing installs do not lose persisted values
- Maintained Phase 28 byte-equivalence invariant between `strings.json` and `translations/en.json` (`diff` returns zero)

## Task Commits

Each task was committed atomically:

1. **Task 1: Remove ASPDebugModeSensor from sensor.py** — `37eda2c` (refactor)
2. **Task 2: Remove CONF_DEBUG_ENABLED + CONF_SUPPRESS_NOTIFICATIONS from async_step_debug** — `8782883` (refactor)
3. **Task 3: Rename debug step + drop debug_mode sensor key + add debug_switch entity key in i18n** — `3eddcde` (i18n)

_Note: All three tasks marked `tdd="true"` in the plan, but no new test files were authored — the existing `tests/test_options_flow.py`, `tests/test_ha_integration.py`, and `tests/test_diagnostics.py` cover the behavioral surface (form schema and entity registration). The "TDD" gate here is the existing test suite continuing to pass after each refactor commit; no test was newly added because the test surface was already complete (no `ASPDebugModeSensor` references in tests, no schema-shape assertions about removed fields)._

## Files Created/Modified

- `custom_components/asp_parking/sensor.py` — dropped `ASPDebugModeSensor` class (~30 lines), removed it from `async_setup_entry` list (12 → 11 entities), updated module docstring (10 → 9 diagnostic sensors)
- `custom_components/asp_parking/config_flow.py` — removed `CONF_DEBUG_ENABLED` and `CONF_SUPPRESS_NOTIFICATIONS` BooleanSelector entries from `debug_schema`; removed both keys from `async_step_debug` user_input handling; dropped unused `DEFAULT_DEBUG_ENABLED` and `DEFAULT_SUPPRESS_NOTIFICATIONS` imports; left `async_step_init` carry-forward (D-06) byte-identical
- `custom_components/asp_parking/strings.json` — replaced `options.step.debug` block (new title, new description, three data + data_description keys); removed `entity.sensor.debug_mode`; added `entity.switch.debug_switch`
- `custom_components/asp_parking/translations/en.json` — identical edits as strings.json; `diff` produces zero output
- `.planning/phases/29-debug-switch-logging/deferred-items.md` — created to log a pre-existing baseline test failure unrelated to this plan

## Decisions Made

- **Kept `CONF_DEBUG_ENABLED` and `CONF_SUPPRESS_NOTIFICATIONS` imports** in `config_flow.py` because the carry-forward tuple (D-06) still references both names. Only `DEFAULT_*` imports were dropped (the carry-forward reads from `self.config_entry.options[...]`, not from the defaults).
- **Used em dash (`—`) instead of `--` in the strings.json edit's `old_string`** because Phase 28's WR-02 normalization already converted the file. The plan snippet showed the pre-normalization text; matching the actual file required the em dash.
- **Did not author new test files** for these refactors. Existing tests already exercise (a) the options flow step transitions (`tests/test_options_flow.py`), (b) entity setup and import (`tests/test_ha_integration.py`), and (c) diagnostics endpoint behavior (`tests/test_diagnostics.py`). No existing test referenced the removed names, so the contract under test is "the refactor must not break the existing pass set" — which it does not.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Plan snippet for strings.json edit used pre-normalization punctuation**
- **Found during:** Task 3 (i18n edits)
- **Issue:** The plan's "Find this exact block" for `options.step.debug.description` showed `Debug overrides -- for testing only…` (double-hyphen), but the actual file content from worktree-base commit `73f4530` uses an em dash `—` (Phase 28 WR-02 already normalized). Direct application of the plan's `old_string` would have failed `Edit`'s exact-match requirement.
- **Fix:** Used the em-dash form when calling `Edit`. The replacement string from the plan is unaffected (the new description does not contain a dash at all).
- **Files modified:** custom_components/asp_parking/strings.json, custom_components/asp_parking/translations/en.json
- **Verification:** `Edit` succeeded; final byte-equivalence + JSON validity checks pass.
- **Committed in:** 3eddcde (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** No scope creep. The deviation is an editor-tool mechanical issue, not a plan-design issue.

## Issues Encountered

- **Pre-existing test failure on baseline:** `tests/test_ha_integration.py::TestSuspensionPoll::test_suspension_poll_does_not_require_gps_coordinates` fails on the worktree-base commit `73f4530` BEFORE any of this plan's edits. Reproduced via `git stash` + isolated test run. Out of scope for plan 29-02 (which does not touch `coordinator.py`). Logged in `.planning/phases/29-debug-switch-logging/deferred-items.md`. Verification used `--deselect` to skip only this test — all other 70 selected tests in `tests/test_options_flow.py + tests/test_ha_integration.py + tests/test_diagnostics.py` pass.

## Carry-Forward Verification (D-06)

Confirmed `async_step_init` carry-forward block is byte-identical pre/post plan execution:

```python
# Carry forward existing debug + parking options unchanged —
# debug step is bypassed in the options flow; parking values
# carry through so a re-save of init alone preserves them.
for key in (
    CONF_DEBUG_ENABLED,
    CONF_DEBUG_LAT,
    CONF_DEBUG_LON,
    CONF_DEBUG_DATETIME,
    CONF_SUPPRESS_NOTIFICATIONS,
    CONF_PARKING_LAT,
    CONF_PARKING_LON,
    CONF_PARKING_RADIUS,
):
    if key in self.config_entry.options:
        options[key] = self.config_entry.options[key]
```

Both `CONF_DEBUG_ENABLED` and `CONF_SUPPRESS_NOTIFICATIONS` remain in the tuple. Existing installs with persisted values for either key will not lose them on a re-save of the `init` step. (T-29-05 mitigated.)

## i18n Byte-Equivalence Verification (Phase 28 invariant)

```
$ diff custom_components/asp_parking/strings.json custom_components/asp_parking/translations/en.json
$ echo $?
0
```

Both JSON files parse cleanly via `json.load()` and are structurally identical. (T-29-07 mitigated.)

## Threat Flags

None — no new security-relevant surface introduced. The removed sensor and removed form fields strictly reduce surface area; the new `entity.switch.debug_switch` translation key carries the same trust boundary as the existing `entity.sensor.*` keys.

## Known Stubs

None.

## Next Phase Readiness

- Plan 29-03 (logging upgrade) is independent — no shared file conflicts. Both plans run in Wave 1 per the orchestrator config.
- The retired `ASPDebugModeSensor` is fully gone — Plan 01's `ASPDebugModeSwitch` is now the sole canonical surface for debug-mode state in HA.
- HACS validators (json schema for `strings.json`) should still pass because the file remains valid JSON and the `entity.switch` key is in the documented HA translation schema.

## Self-Check: PASSED

Verified before completion:

- `[ -f custom_components/asp_parking/sensor.py ]` → FOUND
- `[ -f custom_components/asp_parking/config_flow.py ]` → FOUND
- `[ -f custom_components/asp_parking/strings.json ]` → FOUND
- `[ -f custom_components/asp_parking/translations/en.json ]` → FOUND
- `git log --oneline | grep -q 37eda2c` → FOUND (Task 1)
- `git log --oneline | grep -q 8782883` → FOUND (Task 2)
- `git log --oneline | grep -q 3eddcde` → FOUND (Task 3)
- All acceptance criteria from `<verification>` block pass:
  1. `pytest tests/test_options_flow.py tests/test_ha_integration.py tests/test_diagnostics.py` → 70 passed, 1 deselected (pre-existing, unrelated)
  2. `diff strings.json translations/en.json` → zero output
  3. `grep -c ASPDebugModeSensor sensor.py` → 0
  4. `grep -c CONF_DEBUG_ENABLED config_flow.py` → 2 (import + carry-forward)
  5. `grep -c "GPS & Time Overrides" strings.json` → 1
  6. `json.load()` succeeds for both files
  7. Carry-forward block in `async_step_init` preserved verbatim

---
*Phase: 29-debug-switch-logging*
*Plan: 02*
*Completed: 2026-05-03*
