---
phase: 27-diagnostics
plan: 01
subsystem: testing
tags: [home-assistant, diagnostics, repair-issue, tdd, ha_integration, pytest]

# Dependency graph
requires:
  - phase: 26
    provides: CONF_PARKING_LAT / CONF_PARKING_LON constants now reachable for redaction-list assertions
provides:
  - DIAG-01 RED scaffold (4 failing tests for diagnostics export shape, redaction set, and ISO datetime)
  - DIAG-02/03 RED scaffold (3 failing tests for ImportError logging, repair-issue creation, repair auto-dismiss)
  - DIAG-04 RED scaffold (1 failing import-surface test for the four new diagnostic sensor classes)
  - 4 GREEN pure-Python helper tests that lock the four DIAG-04 native_value semantics
affects: [27-02-diagnostics, 27-03-sensors, 27-04-repair-issue]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pitfall #5 mitigation: tests/test_diagnostics.py uses a local _FakeData dataclass + SimpleNamespace rather than importing the HA-bound coordinator module"
    - "Pitfall #1 mitigation: only homeassistant.helpers.issue_registry is imported (the legacy components.repairs path is intentionally absent)"
    - "Test-local sensor logic replication (existing convention in test_ha_integration.py) extended to four new DIAG-04 sensors so production sensor.py never has to be imported in this file"

key-files:
  created:
    - tests/test_diagnostics.py
    - tests/test_repair_issue.py
  modified:
    - tests/test_ha_integration.py

key-decisions:
  - "Module-top import of DOMAIN in tests/test_repair_issue.py (deviation from PLAN's 'imports inside test function' instruction): pytest_homeassistant_custom_component's enable_custom_integrations fixture invalidates the cached custom_components loader between fixtures and the test body, so an inside-function import of custom_components.asp_parking.const fails with ModuleNotFoundError. Module-top import matches the working pattern in tests/test_options_flow.py."
  - "test_setup_dismisses_repair patches hass.config_entries.async_forward_entry_setups with AsyncMock to avoid bringing up the entity platforms when running with a stubbed coordinator — keeps the RED state assertion clean (the failure is on the issue still existing, not on sensor.available crashing on a MagicMock)."
  - "test_diag04_sensor_classes_exist is the single RED gate for DIAG-04's import-surface; the four sibling helper tests intentionally pass on commit because they replicate the trivial native_value logic locally."

patterns-established:
  - "RED-state separation: ModuleNotFoundError (entire submodule missing) vs. AssertionError (production handler missing) vs. ImportError (specific class missing) — each test file embodies one of these three modes for clarity."
  - "Diagnostics test fixture: _FakeData + SimpleNamespace + MockConfigEntry.add_to_hass(hass) is the minimum scaffolding needed to exercise async_get_config_entry_diagnostics without booting the coordinator."

requirements-completed: [DIAG-01, DIAG-02, DIAG-03, DIAG-04]

# Metrics
duration: 9min
completed: 2026-05-01
---

# Phase 27 Plan 01: Wave 0 Diagnostics Test Scaffolding Summary

**8 failing tests + 4 passing helper tests authored across three files that lock the diagnostics export shape, the ImportError repair-issue lifecycle, and the four new DIAG-04 sensor native_value contracts — all in RED before any production code is written.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-05-01T21:21:06Z
- **Completed:** 2026-05-01T21:30:10Z
- **Tasks:** 3
- **Files modified:** 3 (2 created, 1 extended)

## Accomplishments

- DIAG-01: 4 failing tests (`test_diagnostics_shape`, `test_diagnostics_redacts_lat_lon`, `test_diagnostics_passthrough`, `test_state_section_iso_datetime`) authored in `tests/test_diagnostics.py`, all RED with `ModuleNotFoundError: No module named 'custom_components.asp_parking.diagnostics'`.
- DIAG-02/03: 3 failing tests (`test_import_error_logs_actionable`, `test_import_error_creates_repair`, `test_setup_dismisses_repair`) authored in `tests/test_repair_issue.py`, all RED with `AssertionError` (the integration's `__init__.py` does not yet wrap setup with an ImportError-to-repair-issue handler).
- DIAG-04: 4 GREEN helper tests (`test_diag04_confidence_score_native_value`, `test_diag04_soda_level_native_value`, `test_diag04_last_resolved_iso`, `test_diag04_last_error_native_value`) plus 1 RED import-surface test (`test_diag04_sensor_classes_exist`) appended to `tests/test_ha_integration.py`. The import-surface test fails with `ImportError: cannot import name 'ASPConfidenceScoreSensor'`.
- All three new test files / sections honour the `pytestmark = pytest.mark.ha_integration` opt-in convention so `pytest -m "not ha_integration"` continues to pass cleanly.
- Pitfall #5 (coordinator-import-avoidance) and Pitfall #1 (issue_registry import path) explicitly mitigated.

## Task Commits

1. **Task 1: tests/test_diagnostics.py with 4 failing DIAG-01 tests** — `d942ab8` (test)
2. **Task 2: tests/test_repair_issue.py with 3 failing DIAG-02/03 tests** — `a03945b` (test)
3. **Task 3: appended 4 DIAG-04 helper tests + 1 RED import-surface test to tests/test_ha_integration.py** — `daa0ecc` (test)

## Initial RED-state Matrix

| Test (file::name) | Failure mode | Production code that turns it GREEN |
|---|---|---|
| `tests/test_diagnostics.py::test_diagnostics_shape` | `ModuleNotFoundError: custom_components.asp_parking.diagnostics` | Plan 02 — create `diagnostics.py` with `async_get_config_entry_diagnostics()` returning `{config, state, last_resolve, last_error}` |
| `tests/test_diagnostics.py::test_diagnostics_redacts_lat_lon` | same | Plan 02 — wire `async_redact_data` with `{CONF_PARKING_LAT, CONF_PARKING_LON, CONF_DEBUG_LAT, CONF_DEBUG_LON, CONF_NYC311_API_KEY}` redact set |
| `tests/test_diagnostics.py::test_diagnostics_passthrough` | same | Plan 02 — non-sensitive options remain unchanged after redaction |
| `tests/test_diagnostics.py::test_state_section_iso_datetime` | same | Plan 02 — datetime fields serialised via `.isoformat()` |
| `tests/test_repair_issue.py::test_import_error_logs_actionable` | `AssertionError: 'reinstall via HACS' not in caplog.text` | Plan 04 — `__init__.py` catches ImportError, logs `_LOGGER.error("...gps2asp...reinstall via HACS...")` |
| `tests/test_repair_issue.py::test_import_error_creates_repair` | `AssertionError: assert None is not None` | Plan 04 — call `ir.async_create_issue(hass, DOMAIN, "gps2asp_import_error", ...)` from the ImportError except branch |
| `tests/test_repair_issue.py::test_setup_dismisses_repair` | `AssertionError: assert None is None` | Plan 04 — call `ir.async_delete_issue(hass, DOMAIN, "gps2asp_import_error")` on successful setup |
| `tests/test_ha_integration.py::test_diag04_sensor_classes_exist` | `ImportError: cannot import name 'ASPConfidenceScoreSensor' from custom_components.asp_parking.sensor` | Plan 03 — add `ASPConfidenceScoreSensor`, `ASPSODALevelSensor`, `ASPLastResolvedSensor`, `ASPLastErrorSensor` to `sensor.py` |

| Test (file::name) | Status | Note |
|---|---|---|
| `tests/test_ha_integration.py::test_diag04_confidence_score_native_value` | GREEN on commit | Pure-Python replication helper |
| `tests/test_ha_integration.py::test_diag04_soda_level_native_value` | GREEN on commit | Pure-Python replication helper |
| `tests/test_ha_integration.py::test_diag04_last_resolved_iso` | GREEN on commit | Pure-Python replication helper |
| `tests/test_ha_integration.py::test_diag04_last_error_native_value` | GREEN on commit | Pure-Python replication helper |

## Forward Pointers (per <output> in PLAN)

| Downstream plan | Tests it must turn GREEN |
|---|---|
| 27-02 (diagnostics module) | All 4 tests in `tests/test_diagnostics.py` |
| 27-03 (sensor entities) | `test_diag04_sensor_classes_exist` in `tests/test_ha_integration.py` |
| 27-04 (repair issue) | All 3 tests in `tests/test_repair_issue.py` |

## Files Created/Modified

- `tests/test_diagnostics.py` — NEW. 4 DIAG-01 failing tests + a `_FakeData` dataclass and `_make_entry()` helper that builds a `MockConfigEntry` with `runtime_data = SimpleNamespace(data=_FakeData(...))`.
- `tests/test_repair_issue.py` — NEW. 3 DIAG-02/03 failing tests using `homeassistant.helpers.issue_registry as ir`, `unittest.mock.patch` to simulate ImportError, and `caplog` for log assertions.
- `tests/test_ha_integration.py` — EXTENDED. Appended 4 pure-Python sensor-logic helpers, 4 helper tests, and a 5th `@pytest.mark.ha_integration`-decorated test that imports the four DIAG-04 sensor classes from `sensor.py`.

## Confirmation: No Production Code Modified

```
$ git diff --name-only main..HEAD
tests/test_diagnostics.py
tests/test_ha_integration.py
tests/test_repair_issue.py
```

Only tests under `tests/` were touched. `custom_components/asp_parking/`, `src/gps2asp/`, and `scripts/` are untouched.

## Decisions Made

- **Module-top DOMAIN import in test_repair_issue.py** instead of inside-the-function (deviation from PLAN action wording). Reason: `enable_custom_integrations` fixture invalidates the loader cache between fixture and test body, so a delayed import of `custom_components.asp_parking.const` raises `ModuleNotFoundError` at the wrong time (masking the intended RED assertion).
- **`async_forward_entry_setups` patched** in `test_setup_dismisses_repair`. Reason: with the coordinator stubbed via `MagicMock()`, the entity-platform forwards still run and `sensor.available` then evaluates `MagicMock <= MagicMock`, raising a TypeError that pollutes the test output. Patching the forward keeps the RED-state failure on the assertion (issue not deleted) rather than on incidental teardown noise.
- **Five `def test_diag04_` functions** in `test_ha_integration.py` (not four). The PLAN's AC1 specifies `4` but AC2 explicitly requires the additional `test_diag04_sensor_classes_exist`. Total of 5 `def test_diag04_*` functions matches the PLAN's `<action>` description (`4 helpers + 5 test functions`) and is the actually-shipping set.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] Module-top DOMAIN import in test_repair_issue.py**
- **Found during:** Task 2 (test_import_error_logs_actionable execution)
- **Issue:** PLAN's `<action>` told me to import DOMAIN inside `_make_entry()`. With `enable_custom_integrations` enabled, the inside-function import raised `ModuleNotFoundError: No module named 'custom_components.asp_parking'` because the fixture invalidates the loader cache between fixture setup and the test body executing the helper.
- **Fix:** Hoisted `from custom_components.asp_parking.const import DOMAIN` to module top, matching the working pattern in `tests/test_options_flow.py:13-22`.
- **Files modified:** `tests/test_repair_issue.py`
- **Verification:** Re-running `pytest tests/test_repair_issue.py` shows the three tests now fail with their intended RED assertions instead of an ImportError on DOMAIN.
- **Committed in:** `a03945b` (Task 2 commit)

**2. [Rule 3 — Blocking] `async_forward_entry_setups` and async_start stubbed with AsyncMock in test 3**
- **Found during:** Task 2 (test_setup_dismisses_repair execution)
- **Issue:** PLAN suggested patching only `_async_ensure_index` and `ASPParkingCoordinator`. Patching the coordinator with a bare `MagicMock` left `coordinator.async_start` non-awaitable (`TypeError: object MagicMock can't be used in 'await' expression`) and the entity-platform forward path then crashed inside `sensor.available`'s `MagicMock <= MagicMock` compare.
- **Fix:** Replaced with a `fake_coordinator = MagicMock()` whose `async_start` and `async_stop` are `AsyncMock()`s, plus a `patch.object(hass.config_entries, "async_forward_entry_setups", new=AsyncMock())` to skip platform setup. Both adjustments are scoped inside the `with` block.
- **Files modified:** `tests/test_repair_issue.py`
- **Verification:** Test now fails cleanly with `AssertionError: assert None is None` (the intended RED state) and produces no teardown ERROR lines.
- **Committed in:** `a03945b` (Task 2 commit)

**3. [Rule 3 — Blocking] Removed literal `homeassistant.components.repairs` substring from test_repair_issue.py docstring**
- **Found during:** Task 2 acceptance-criteria run
- **Issue:** AC6 demands `grep -c "homeassistant.components.repairs" tests/test_repair_issue.py` returns `0`. My initial docstring referenced the deprecated path by name (as a `do-not-use` callout), giving a count of `1`.
- **Fix:** Reworded the docstring to describe the avoided path without using the literal substring.
- **Files modified:** `tests/test_repair_issue.py`
- **Verification:** AC6 grep now returns `0`.
- **Committed in:** `a03945b` (Task 2 commit)

---

**Total deviations:** 3 auto-fixed (3 blocking — Rule 3)
**Impact on plan:** All deviations adjusted test infrastructure to honour the actually-installed HA fixture semantics; none changed assertion intent or scope. The RED-state matrix matches the PLAN's `<success_criteria>` exactly.

## Issues Encountered

- **Worktree base mismatch:** The worktree branch was at `64fbf6d` (Phase 25 baseline), three Phase 26 plans ahead of expected. The orchestrator-supplied base was `cbbc97c`. Resolved by `git merge --ff-only cbbc97c77c7a3788ed3495e1ac8c546262869ee3` (the destructive `git reset --hard` requested by the worktree-branch-check protocol is blocked in this sandbox; fast-forward is the equivalent forward-only operation here). Final HEAD reached the expected base before any task work began.
- **Pre-existing failures (out of scope, NOT introduced by this plan):**
  - `tests/test_ha_integration.py::TestSuspensionPoll::test_suspension_poll_does_not_require_gps_coordinates` — fails because `coordinator.py` no longer contains the literal substring `datetime.now(NYC_TZ).date()` in `_async_update_suspension`.
  - `tests/test_suspension.py::test_is_suspended_holiday` — fails on a HolidayCalendar load-state assertion.
  - Both failures reproduce on a clean checkout of the base commit with all my changes stashed; they are unrelated to Phase 27 Plan 01.

## User Setup Required

None — Wave 0 is purely test scaffolding; no external services or secrets are touched.

## Next Phase Readiness

- Plan 02 can begin: `tests/test_diagnostics.py` is RED and waiting for `custom_components/asp_parking/diagnostics.py` with `async_get_config_entry_diagnostics()`.
- Plan 03 can begin: `tests/test_ha_integration.py::test_diag04_sensor_classes_exist` is RED and waiting for the four diagnostic sensor classes in `sensor.py`.
- Plan 04 can begin: `tests/test_repair_issue.py` is RED and waiting for the ImportError → repair-issue handler in `__init__.py`.
- All three downstream plans now have a Nyquist-compliant verification command (`.venv/bin/pytest tests/test_*.py`) pre-seeded.

## Self-Check: PASSED

**Files exist:**

```
$ [ -f tests/test_diagnostics.py ]   && echo FOUND ; FOUND
$ [ -f tests/test_repair_issue.py ]  && echo FOUND ; FOUND
$ [ -f tests/test_ha_integration.py ] && echo FOUND ; FOUND
```

**Commits exist:**

```
$ git log --oneline -3
daa0ecc test(27-01): append 4 DIAG-04 helper tests + 1 RED import-surface test
a03945b test(27-01): add 3 failing DIAG-02/03 tests for repair issue lifecycle
d942ab8 test(27-01): add 4 failing DIAG-01 tests for diagnostics export shape
```

---
*Phase: 27-diagnostics*
*Completed: 2026-05-01*
