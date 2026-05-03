---
phase: 29-debug-switch-logging
plan: 01
subsystem: ha-integration
tags: [home-assistant, switch-entity, logging, debug-mode, entity-category-diagnostic]

# Dependency graph
requires:
  - phase: 24-debug-overrides
    provides: Coordinator _debug_enabled / _debug_lat / _debug_lon / _debug_datetime fields and the existing options-flow toggle being replaced
  - phase: 27-diagnostics
    provides: Diagnostic-export GPS redaction context used by T-29-02 mitigation reasoning
provides:
  - HA switch.asp_parking_debug_mode dashboard entity (writable, EntityCategory.DIAGNOSTIC)
  - Public coordinator.async_update_listeners() alias for entity-side notification triggers
  - Unconditional in-memory _debug_enabled init in coordinator.async_start (no longer reads CONF_DEBUG_ENABLED from entry.options)
  - WARNING-level main-loop logs for OutsideNYCError and NoSegmentFoundError/AmbiguousResolutionError with actionable user-facing text
affects: [29-02-debug-step-refactor, future-debug-controls, ha-dashboard-ux]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "HA SwitchEntity pattern with @attr translation_key + EntityCategory.DIAGNOSTIC"
    - "Coordinator public alias method (@callback) wrapping a private notifier"
    - "Source-level grep tests using string-literal continuation joining for multi-line log message verification"

key-files:
  created:
    - custom_components/asp_parking/switch.py
    - tests/test_debug_switch.py
    - tests/test_coordinator_debug_logs.py
  modified:
    - custom_components/asp_parking/const.py
    - custom_components/asp_parking/coordinator.py

key-decisions:
  - "D-01: switch state is in-memory only -- no entry.options write; debug always resets to False on HA restart by design"
  - "D-02: coordinator.async_start initializes _debug_enabled = False unconditionally; switch.py is the sole runtime setter"
  - "D-03: added public coordinator.async_update_listeners() that aliases _async_notify_entities so the switch can stay in the public surface"
  - "D-09: extra_state_attributes exposes only debug_lat/debug_lon/debug_datetime; suppress_notifications stays in options"
  - "D-10/D-11/D-13: main-loop OutsideNYC + NoSegment/Ambiguous errors upgraded from logger.info to logger.warning with actionable diagnostic text"
  - "D-12: pre-seeder OutsideNYCError WARNING (Phase 26) left untouched"

patterns-established:
  - "Multi-line log message format verification via _join_string_continuations regex helper -- enables checking concatenated runtime strings against literal acceptance text without forcing implementation onto a single line"
  - "Coordinator-public alias pattern: when an entity needs to fire entity callbacks from outside the coordinator, expose a thin @callback method delegating to the existing private notifier rather than calling the underscore-prefixed private name from the entity"

requirements-completed: [DBG-01, DBG-03]

# Metrics
duration: 9min
completed: 2026-05-02
---

# Phase 29 Plan 01: Debug Switch + WARNING Log Upgrades Summary

**ASPDebugModeSwitch HA SwitchEntity gives users a one-tap debug toggle, the coordinator drops persistent debug-enabled and now warns users with actionable text when GPS falls outside NYC or no street segment matches.**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-05-03T01:39:40Z
- **Completed:** 2026-05-03T01:48:00Z
- **Tasks:** 3 (all autonomous, all TDD-style)
- **Files created:** 3 (switch.py, test_debug_switch.py, test_coordinator_debug_logs.py)
- **Files modified:** 2 (const.py, coordinator.py)
- **Tests added:** 23 (15 switch contract + 8 coordinator contract)

## Accomplishments

- New writable `switch.asp_parking_debug_mode` HA dashboard entity replaces the 5-click options-flow toggle from Phase 24 with a one-tap control. Entity is `EntityCategory.DIAGNOSTIC`, has `translation_key="debug_switch"`, icon `mdi:bug`, and groups under the existing ASP Parking Monitor device.
- Coordinator now initializes `_debug_enabled = False` unconditionally on every HA restart; debug is in-memory only (D-02). The legacy `entry.options.get(CONF_DEBUG_ENABLED, ...)` read in `async_start` is gone, and the now-unused `CONF_DEBUG_ENABLED` / `DEFAULT_DEBUG_ENABLED` imports were dropped.
- Added public `@callback def async_update_listeners(self)` alias that delegates to the existing private `_async_notify_entities()`. The switch calls this after mutating `_debug_enabled` so all registered entities reflect the new state immediately (D-03).
- Both error handlers in the main resolve loop were upgraded from `logger.info` to `logger.warning` with actionable user-facing text (D-10, D-11, D-13):
  - `OutsideNYCError` -> "GPS coordinates (lat, lon) are outside NYC coverage area -- check that your device tracker is reporting a valid NYC location"
  - `NoSegmentFoundError` / `AmbiguousResolutionError` -> "No street segment found at (lat, lon) -- check that your device tracker is reporting accurate coordinates within a mapped NYC street: <err>"
- Pre-seeder `OutsideNYCError` WARNING at line ~711 was left intact (D-12).
- 23 new unit tests cover the full switch + coordinator contract; the full fast-test suite passes (333 tests, 0 regressions traceable to this plan).

## Task Commits

Each task was committed atomically with a TDD red/green pair where applicable:

1. **Task 1: Add "switch" to PLATFORMS in const.py** - `5137208` (feat)
2. **Task 2 RED: Coordinator debug-log + alias contract tests** - `c21dd7c` (test)
3. **Task 2 GREEN: Coordinator refactor (D-02, D-03, D-10, D-11, D-13)** - `8c4e3d4` (feat)
4. **Task 3 RED: ASPDebugModeSwitch contract tests** - `65fdfe0` (test)
5. **Task 3 GREEN: ASPDebugModeSwitch implementation** - `a11be79` (feat)

## Files Created/Modified

- `custom_components/asp_parking/switch.py` (new, 102 lines) -- `ASPDebugModeSwitch` SwitchEntity + `async_setup_entry`. Replaces the retired options-flow debug toggle.
- `custom_components/asp_parking/const.py` (modified, 1 line) -- Appended `"switch"` to `PLATFORMS` so HA platform discovery imports `switch.py`.
- `custom_components/asp_parking/coordinator.py` (modified) -- Dropped `CONF_DEBUG_ENABLED` / `DEFAULT_DEBUG_ENABLED` imports, replaced the `entry.options.get(...)` debug read in `async_start` with an unconditional `False` init, added public `async_update_listeners()` alias, upgraded two `logger.info` calls to `logger.warning` with actionable text. Pre-seeder warning at ~line 711 untouched.
- `tests/test_debug_switch.py` (new, 15 tests) -- Switch entity contract: unique_id, translation_key, icon, has_entity_name, EntityCategory, is_on, async_turn_on/off, no entry.options write, extra_state_attributes (D-09), async_added_to_hass callback registration, DeviceInfo, async_setup_entry single-entity instantiation.
- `tests/test_coordinator_debug_logs.py` (new, 8 tests) -- Coordinator contract: async_update_listeners exists + delegates + dispatches to callbacks, async_start unconditional False init (D-02), CONF/DEFAULT_DEBUG_ENABLED imports removed, OutsideNYCError WARNING text + level (D-10/D-13), NoSegment/Ambiguous WARNING text + level (D-11/D-13), pre-seeder WARNING preserved (D-12).

## TDD Gate Compliance

Per-feature TDD cycle observed for both Task 2 and Task 3:

- **Task 2:** RED `c21dd7c` -> GREEN `8c4e3d4`. RED commit had 1 of 8 tests failing immediately (`test_async_update_listeners_method_exists`). GREEN commit makes all 8 pass.
- **Task 3:** RED `65fdfe0` -> GREEN `a11be79`. RED commit failed at module-collection (no `switch.py`). GREEN commit makes all 15 pass.

No REFACTOR commits were necessary -- the GREEN code already matches the plan's specified shape.

## Decisions Made

Followed plan as specified. Two minor judgment calls:

1. **Test layout for D-03/D-10/D-11/D-13**: Plan suggested putting coordinator-level tests in either `test_debug_switch.py` or a separate file. Chose a separate `test_coordinator_debug_logs.py` to keep concerns isolated -- the switch tests focus on entity contract, the coordinator tests focus on internal state and log emissions.
2. **`_join_string_continuations` test helper**: The plan's literal acceptance grep would only match if the WARNING strings were written on a single source line. The plan's own `<action>` snippet uses adjacent-string concatenation across two lines. Added a tiny regex helper in the test file that joins adjacent string literals before substring checks, so the test verifies the *runtime concatenated* string (which is what users see in logs) regardless of source-line breaks. Documented in the helper docstring.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] RED-test acceptance criterion was too strict for `_debug_enabled = False` count**
- **Found during:** Task 2 GREEN run
- **Issue:** Initial RED test required `re.findall(r"self\._debug_enabled\s*=\s*False\b", src)` to return 2 occurrences (per plan acceptance: "grep -c 'self._debug_enabled = False' returns 2"). After the GREEN edits the substring only matched 1 line because the existing `__init__` declaration uses an annotated form `self._debug_enabled: bool = False` (line 192, with a colon between name and `=`).
- **Fix:** Updated the RED-test regex to accept both forms: `r"self\._debug_enabled(?:\s*:\s*bool)?\s*=\s*False\b"`. The plan's acceptance grep is technically inconsistent with the pre-existing source layout; the test now mirrors the plan's *intent* (one in `__init__`, one in `async_start`) rather than its over-fitted grep.
- **Files modified:** `tests/test_coordinator_debug_logs.py`
- **Verification:** Re-ran the test file -- 8/8 pass; both `_debug_enabled = False` assignments are detected.
- **Committed in:** `8c4e3d4` (Task 2 GREEN commit).

**2. [Rule 1 - Bug] Initial WARNING string-literal substring check failed for multi-line concatenation**
- **Found during:** Task 2 GREEN run (after fixing #1)
- **Issue:** RED test asserted `"GPS coordinates (%.4f, %.4f) are outside NYC coverage area -- check..."` is a substring of `coordinator.py` source. The actual implementation (matching the plan's `<action>` snippet) splits the string across two adjacent literals: `"... area"\n " -- check..."`. The substring check fails on raw source even though the *runtime* string is exactly correct.
- **Fix:** Added `_join_string_continuations(src)` helper that strips `"\s*\n\s*"` patterns (closing quote, whitespace including newline, opening quote of adjacent literal) so substring checks operate on the runtime concatenation. Same fix applied to the NoSegment/Ambiguous test. Each test also adds a regex check confirming the call uses `logger.warning(...)` (not `logger.info(...)`).
- **Files modified:** `tests/test_coordinator_debug_logs.py`
- **Verification:** Both WARNING tests now PASS; `_join_string_continuations` is tested implicitly by both message-content assertions.
- **Committed in:** `8c4e3d4` (Task 2 GREEN commit).

**3. [Rule 1 - Bug] `suppress_notifications` token leaked into switch.py docstring**
- **Found during:** Task 3 acceptance verification
- **Issue:** Plan acceptance: `grep -c "suppress_notifications" custom_components/asp_parking/switch.py` returns 0. Initial implementation included the token in the `extra_state_attributes` docstring as a negation reference ("minus `suppress_notifications`...") -- which still shows up in `grep -c`.
- **Fix:** Rewrote the docstring to describe the exclusion semantically without naming the token: "The notification-suppression flag is intentionally excluded -- it lives only in entry.options now." Preserves intent for future readers; satisfies plan acceptance criterion.
- **Files modified:** `custom_components/asp_parking/switch.py`
- **Verification:** `grep -c "suppress_notifications" custom_components/asp_parking/switch.py` returns 0; tests still pass.
- **Committed in:** `a11be79` (Task 3 GREEN commit).

---

**Total deviations:** 3 auto-fixed (3 Rule 1 minor bugs, 0 Rule 2/3/4)
**Impact on plan:** All three are minor over-fitted-acceptance corrections. No functional or scope changes; plan deliverables landed exactly as specified.

## Issues Encountered

- **Pre-existing test failure (`test_suspension.py::test_is_suspended_holiday`)**: Unrelated to Phase 29. Reproduces against the base commit with all Phase 29 changes stashed. Logged to `.planning/phases/29-debug-switch-logging/deferred-items.md`. Skipped via `--deselect` for the regression sweep.
- **Pre-existing test failure (`test_ha_integration.py::TestSuspensionPoll::test_suspension_poll_does_not_require_gps_coordinates`)**: Asserts `datetime.now(NYC_TZ).date()` substring in `coordinator.py`; the substring is gone (likely refactored to `self._get_now().date()` in a prior phase). Reproduces against base. Logged to `deferred-items.md`. Out of scope.
- **Worktree had no `.venv`**: The worktree base commit predates the phase 29 plan files (which live under the gitignored `.planning/`), and the worktree had no `.venv`. Resolved by symlinking the main-repo `.venv` and copying plan files from the main repo's working tree. The symlink and the plan files are not committed (both paths are gitignored).

## User Setup Required

None for this plan. The new switch entity will appear automatically in HA after the integration reloads. The `entity.switch.debug_switch.name` translation key still needs a string entry to land in `strings.json` and `translations/en.json` -- handled in Plan 02 (DBG-02).

## Threat Flags

None. The switch surface and WARNING log content match the plan's `<threat_model>` (T-29-01..T-29-04 dispositions are unchanged). The two new WARNING log lines emit GPS coordinates at 4-decimal precision -- identical to the INFO lines they replace, so T-29-02's "accept" disposition still applies (Phase 27 diagnostic export already redacts these per DIAG-01).

## Known Stubs

None. All entity properties are wired to live coordinator state; no placeholder strings or hardcoded empty values that block the plan's stated goal.

## Next Phase Readiness

- **Plan 29-02** can begin: it covers DBG-02 (config_flow refactor, sensor.py retirement of `ASPDebugModeSensor`, `strings.json` / `translations/en.json` updates including the new `entity.switch.debug_switch.name` translation key). Plan 02 must add the `entity.switch.debug_switch` translation entries to both JSON files; until then HA falls back to the auto-derived "Asp Parking Monitor Debug Switch" entity name (functional but unpolished).
- **Coordinator surface**: `async_update_listeners()` is now part of the public coordinator surface. Any future entity that needs to push state from outside the GPS-driven event loop (e.g., a future "force refresh" button) can call this same method.
- **Logging surface**: Two more user-facing WARNINGs now flow into HA's standard log sink. No custom notification routing was added; the existing HA log UI surfaces them per user logging-level configuration.

## Self-Check: PASSED

Verified before close:

- `custom_components/asp_parking/switch.py` exists -- FOUND
- `tests/test_debug_switch.py` exists -- FOUND
- `tests/test_coordinator_debug_logs.py` exists -- FOUND
- Commit `5137208` (Task 1) exists in `git log` -- FOUND
- Commit `c21dd7c` (Task 2 RED) exists in `git log` -- FOUND
- Commit `8c4e3d4` (Task 2 GREEN) exists in `git log` -- FOUND
- Commit `65fdfe0` (Task 3 RED) exists in `git log` -- FOUND
- Commit `a11be79` (Task 3 GREEN) exists in `git log` -- FOUND
- 15/15 switch tests + 8/8 coordinator tests pass
- Full fast-test suite (333 tests) passes with 0 regressions caused by this plan
- Module imports succeed: `ASPDebugModeSwitch`, `async_setup_entry`, `ASPParkingCoordinator.async_update_listeners`
- `PLATFORMS = ["sensor", "binary_sensor", "switch"]`
- No stubs, no threat flags, no `_debug_enabled` persistence remaining

---
*Phase: 29-debug-switch-logging*
*Completed: 2026-05-02*
