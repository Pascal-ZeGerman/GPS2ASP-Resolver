---
phase: 33-spatial-index-rebuild-button
plan: 01
subsystem: testing
tags: [home-assistant, button-entity, binary-sensor, sensor, tdd, red, phase-33, pytest, SimpleNamespace, AsyncMock]

# Dependency graph
requires:
  - phase: 29-debug-switch-logging
    provides: tests/test_debug_switch.py SimpleNamespace+MagicMock entity-contract test pattern
  - phase: 33-spatial-index-rebuild-button
    provides: 33-CONTEXT.md, 33-RESEARCH.md, 33-PATTERNS.md — entity contract specifications for IDX-01/02/03
provides:
  - "RED test coverage for IDX-01 (ASPIndexRebuildButton) — 7 tests"
  - "RED test coverage for IDX-02 (ASPIndexRebuildingBinarySensor) — 8 tests"
  - "RED test coverage for IDX-03 (ASPIndexLastRebuiltSensor) — 9 tests"
  - "Machine-checkable contract for Wave 2 plan 03 to satisfy (24 tests total)"
affects: [33-02, 33-03, 33-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "RED-state TDD: import production class that does not yet exist; pytest collection fails with ImportError (NOT silently passing)"
    - "SimpleNamespace + MagicMock + AsyncMock coordinator stubs (no HA harness, < 100ms per test file)"
    - "Live-property assertions: mutate coordinator field after entity construction, assert entity property reads new value"

key-files:
  created:
    - tests/test_index_rebuild_button.py
    - tests/test_index_rebuilding_binary_sensor.py
    - tests/test_index_last_rebuilt_sensor.py
  modified: []

key-decisions:
  - "All three RED test files share the SimpleNamespace + MagicMock pattern from tests/test_debug_switch.py — no @pytest.mark.ha_integration, no full HA harness needed"
  - "AsyncMock used for coordinator.async_request_rebuild in button tests (Task 1) — verifies await + call count without a real event loop coordinator"
  - "is_on / native_value tests explicitly assert LIVE property semantics by mutating coord._is_rebuilding / coord._last_rebuilt after entity construction — prevents an implementation that caches the value at __init__"
  - "tz-awareness test (tzinfo is not None) encoded as a hard assertion per Pitfall 6 — TIMESTAMP device class rejects naive datetimes at runtime"

patterns-established:
  - "RED tests with import at module top: pytest collection fails before any test runs; greps for 'ImportError' or 'No module named' confirm RED state (NOT 'no tests found')"
  - "Test-file structure mirrors the corresponding production file's existing test pattern (test_debug_switch.py -> test_index_rebuild_button.py for the writable-entity pattern)"

requirements-completed: []  # RED tests partially encode IDX-01/02/03 contract; the requirements close only when GREEN code lands in plan 03

# Metrics
duration: 4 min
completed: 2026-05-14
---

# Phase 33 Plan 01: RED tests for index-rebuild HA entities Summary

**Three pytest files asserting the IDX-01 / IDX-02 / IDX-03 entity contracts (button, binary_sensor, sensor) via SimpleNamespace+MagicMock coordinator stubs — all fail collection with ImportError until Wave 2 plan 03 creates the production classes.**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-05-14T16:07:13Z
- **Completed:** 2026-05-14T16:11:03Z
- **Tasks:** 3
- **Files created:** 3 (tests/)
- **Files modified:** 0 (no production code touched)

## Accomplishments

- Locked the IDX-01 button contract in 7 machine-checkable assertions (unique_id format, translation_key, mdi icon, EntityCategory.CONFIG, async_press → async_request_rebuild delegation, has_entity_name, device_info grouping, async_setup_entry adds exactly one entity).
- Locked the IDX-02 binary_sensor contract in 8 assertions, including a `test_is_on_flips_with_coordinator_state` test that proves `is_on` MUST be a live property reading `coord._is_rebuilding` (not captured at construction).
- Locked the IDX-03 sensor contract in 9 assertions, including `SensorDeviceClass.TIMESTAMP`, `EntityCategory.DIAGNOSTIC` (inherited from `_ASPDiagnosticSensor`), tz-aware datetime enforcement (Pitfall 6), None fallback, and live-property semantics.
- Verified the existing test suite (405 non-integration tests) still passes — no production code modified, zero regressions.

## Task Commits

Each task committed atomically:

1. **Task 1: RED test for ASPIndexRebuildButton (IDX-01)** — `345881d` (test)
2. **Task 2: RED test for ASPIndexRebuildingBinarySensor (IDX-02)** — `be793a4` (test)
3. **Task 3: RED test for ASPIndexLastRebuiltSensor (IDX-03)** — `e96929e` (test)

## Files Created/Modified

- `tests/test_index_rebuild_button.py` — 7 tests for `ASPIndexRebuildButton` (entity-contract via SimpleNamespace stub; AsyncMock for `async_request_rebuild`); fails collection with `ModuleNotFoundError: No module named 'custom_components.asp_parking.button'`.
- `tests/test_index_rebuilding_binary_sensor.py` — 8 tests for `ASPIndexRebuildingBinarySensor` (is_on mirrors coordinator `_is_rebuilding` flag live); fails collection with `ImportError: cannot import name 'ASPIndexRebuildingBinarySensor'`.
- `tests/test_index_last_rebuilt_sensor.py` — 9 tests for `ASPIndexLastRebuiltSensor` (`SensorDeviceClass.TIMESTAMP`, tz-aware datetime, None fallback, live property); fails collection with `ImportError: cannot import name 'ASPIndexLastRebuiltSensor'`.

**Total: 24 test functions across 3 files (≥ 23 required by plan success criteria).**

## RED-state Grep Evidence

```text
tests/test_index_rebuild_button.py:
  E   ModuleNotFoundError: No module named 'custom_components.asp_parking.button'

tests/test_index_rebuilding_binary_sensor.py:
  E   ImportError: cannot import name 'ASPIndexRebuildingBinarySensor' from
      'custom_components.asp_parking.binary_sensor'

tests/test_index_last_rebuilt_sensor.py:
  E   ImportError: cannot import name 'ASPIndexLastRebuiltSensor' from
      'custom_components.asp_parking.sensor'
```

Each error names the class the production code must define, confirming a true RED state (not "0 tests collected" / silent skip).

## Decisions Made

- **AsyncMock vs MagicMock for `async_request_rebuild`:** Used `AsyncMock()` so `await self._coordinator.async_request_rebuild()` succeeds inside the test, and `assert_awaited_once()` verifies the coroutine was actually awaited (not just called). This matches the planned production signature where `async_request_rebuild` is a coroutine method.
- **Live-property assertions:** Each entity's primary state-reading property has an explicit "flip after construction" test (`test_is_on_flips_with_coordinator_state`, `test_native_value_reads_live`). This guards against a future implementation that captures the coordinator value at `__init__` time — which would silently break HA's update-callback model.
- **`tzinfo` hard assertion (Pitfall 6):** `test_native_value_returns_tz_aware_datetime` includes `assert s.native_value.tzinfo is not None` as a separate assertion line, so a regression that drops timezone info (e.g., using `datetime.fromisoformat` instead of `dt_util.parse_datetime`) trips the test immediately.
- **No `async_added_to_hass` callback-registration tests:** The plan's `<behavior>` for Task 1 listed 7 tests; the `test_debug_switch.py` analog includes a `test_async_added_to_hass_registers_callback` test, but the plan did not require it for any of the three new entities. Omitted to stay within the contract the planner asked for. Wave 2 plan 03 can add these tests when production code lands if needed.

## Deviations from Plan

None — plan executed exactly as written. All three task acceptance criteria pass on first attempt; no auto-fixes required (Rules 1-3); no architectural questions (Rule 4); no out-of-scope discoveries.

## Issues Encountered

- **`.venv/bin/pytest` shebang typo (pre-existing, NOT introduced by this plan):** The wrapper script `.venv/bin/pytest` contains a typo in its shebang (`/home/pascal/Vibe-Coding/VW-CarNet/GSP2ASP-Resolver/...` instead of `GPS2ASP-Resolver`), causing `cannot execute: required file not found`. Worked around by invoking `.venv/bin/python -m pytest` directly. The typo is in the venv's installed `pytest` console script, not in any tracked file — likely caused by a renamed parent directory at some point. Flagged for the user (recreating the venv or `pip install --force-reinstall pytest` inside it would fix the shebang).

## User Setup Required

None — RED tests only; no external services, no env vars, no UI configuration.

## Next Phase Readiness

- **Wave 2 plan 03 (production-code GREEN step) is unblocked.** The contract is now machine-checkable. Plan 03 will:
  - Create `custom_components/asp_parking/button.py` with `ASPIndexRebuildButton` + `async_setup_entry`.
  - Add `ASPIndexRebuildingBinarySensor` to `custom_components/asp_parking/binary_sensor.py`.
  - Add `ASPIndexLastRebuiltSensor` to `custom_components/asp_parking/sensor.py`.
  - Add coordinator fields `_is_rebuilding`, `_last_rebuilt`, `async_request_rebuild` (plan 02 owns the lock/task lifecycle).
- **No blockers for plan 02** (coordinator lifecycle): coordinator-side `asyncio.Lock` + background-task tests are not in this plan's scope, per `<done>` note in Task 2.

## Self-Check: PASSED

**File existence:**
- FOUND: tests/test_index_rebuild_button.py
- FOUND: tests/test_index_rebuilding_binary_sensor.py
- FOUND: tests/test_index_last_rebuilt_sensor.py

**Commits in git log:**
- FOUND: 345881d (Task 1 — IDX-01 RED)
- FOUND: be793a4 (Task 2 — IDX-02 RED)
- FOUND: e96929e (Task 3 — IDX-03 RED)

**Plan-level verification:**
- Existing test suite (excluding the three new RED files): `405 passed, 136 deselected in 11.56s` — zero regressions.
- All three new files report ImportError / ModuleNotFoundError on `pytest --collect-only` — RED state confirmed.

---
*Phase: 33-spatial-index-rebuild-button*
*Completed: 2026-05-14*
