---
phase: 33-spatial-index-rebuild-button
plan: 04
subsystem: home-assistant-integration
tags: [button-entity, binary-sensor, sensor, strings, refactor, green, phase-33]
requirements_completed: [IDX-01, IDX-02, IDX-03, IDX-04]
dependency_graph:
  requires:
    - 33-01 (RED entity contract tests — button, binary_sensor, last_rebuilt sensor)
    - 33-02 (RED orchestration tests — async_request_rebuild, _async_do_rebuild)
    - 33-03 (index_io.py shared sync helpers + coordinator orchestration state)
  provides:
    - "ASPIndexRebuildButton entity (button.asp_parking_rebuild_index, mdi:database-refresh, CONFIG)"
    - "ASPIndexRebuildingBinarySensor entity (binary_sensor.asp_parking_index_rebuilding, mdi:progress-download, DIAGNOSTIC)"
    - "ASPIndexLastRebuiltSensor entity (sensor.asp_parking_index_last_rebuilt, mdi:clock-check, TIMESTAMP, DIAGNOSTIC)"
    - "PLATFORMS includes 'button' so HA loads the new platform"
    - "__init__.py first-time-setup flow routes through shared index_io helpers (D-01 closed)"
    - "i18n entries (strings.json + translations/en.json) for the three new entity friendly names — byte-equivalent across both files"
  affects:
    - "HA dashboard now exposes three new entities on the ASP Parking device card"
    - "Single source of truth for spatial-index zip-slip safety + atomic swap (index_io.py)"
tech-stack:
  added: []
  patterns:
    - "ButtonEntity.async_press → coordinator.async_request_rebuild() (fire-and-forget background task)"
    - "Live property reads against coordinator fields (_is_rebuilding, _last_rebuilt) — no caching"
    - "Multi-import SensorDeviceClass alongside SensorEntity/SensorStateClass (mirrors existing import style)"
    - "Three sequential hass.async_add_executor_job calls into index_io sync helpers (cleanup_stale → download_and_extract → atomic_swap)"
key-files:
  created:
    - "custom_components/asp_parking/button.py — ASPIndexRebuildButton (NEW platform)"
  modified:
    - "custom_components/asp_parking/binary_sensor.py — appended ASPIndexRebuildingBinarySensor + EntityCategory import + setup_entry list"
    - "custom_components/asp_parking/sensor.py — appended ASPIndexLastRebuiltSensor + SensorDeviceClass import + setup_entry list"
    - "custom_components/asp_parking/const.py — PLATFORMS extended with 'button'"
    - "custom_components/asp_parking/__init__.py — refactored to use shared index_io helpers (D-01); removed duplicated zip-slip code"
    - "custom_components/asp_parking/strings.json — three new entity name keys"
    - "custom_components/asp_parking/translations/en.json — byte-equivalent mirror of strings.json"
decisions:
  - "Task 4 (manual HA dashboard verification) deferred to post-HACS-release per Phase 25 precedent — no live HA environment was available during execution. The 8-step manual verification (button press, notification appearance, binary_sensor flip, last_rebuilt sensor update, concurrent-press no-op, failure-path) is logged as a milestone-close item alongside Phase 25 Task 3 deferral pattern."
  - "First-time-setup notification IDs (asp_parking_index_download, asp_parking_index_error) kept DISTINCT from rebuild-flow IDs (asp_parking_index_rebuild, *_success, *_error) per RESEARCH Pitfall 7 — same shared sync helpers, different UX per lifecycle event."
  - "Vendored-mirror parity (src/gps2asp ↔ custom_components/asp_parking/gps2asp) was NOT modified by Phase 33 — boundary confirmed per RESEARCH Architectural Responsibility Map and Phase 31 CI guard precedent."
metrics:
  duration_minutes: 6
  completed_date: 2026-05-14
  tasks_completed: 3
  tasks_deferred: 1
  task_4_status: deferred
  files_created: 1
  files_modified: 6
  lines_added: 231
  lines_removed: 35
  tests_added: 0
  tests_now_passing: 50
  full_suite_pass_count: 455
---

# Phase 33 Plan 04: Wave 3 — Entities + Const + __init__.py Refactor + i18n Summary

Wires the user-visible surface (one button, one diagnostic binary sensor, one diagnostic timestamp sensor) to the coordinator orchestration state Wave 2 (plan 03) added, registers the new `"button"` platform in `PLATFORMS`, closes the D-01 single-source-of-truth refactor by routing first-time spatial-index setup through the shared `index_io.py` helpers, and adds matching i18n entries for the three new entity friendly names. All 24 entity RED tests from Wave 1 (plan 01) are now GREEN; all 50 Phase 33 test assertions across the five Phase 33 test files pass; the full 455-test non-network suite reports zero regressions.

## Files Created / Modified

| File | Status | Lines (+/-) | Purpose |
|------|--------|-------------|---------|
| `custom_components/asp_parking/button.py` | NEW | +85 / -0 | `ASPIndexRebuildButton` platform — async_press delegates to `coordinator.async_request_rebuild()` |
| `custom_components/asp_parking/binary_sensor.py` | edit | +57 / -4 | Append `ASPIndexRebuildingBinarySensor` class; extend `async_setup_entry` list; import `EntityCategory` |
| `custom_components/asp_parking/sensor.py` | edit | +35 / -4 | Append `ASPIndexLastRebuiltSensor` class; extend imports with `SensorDeviceClass`; extend `async_setup_entry` list |
| `custom_components/asp_parking/const.py` | edit | +1 / -1 | `PLATFORMS` extended with `"button"` |
| `custom_components/asp_parking/__init__.py` | refactor | +27 / -30 | Route first-time setup through `index_io._sync_cleanup_stale → _sync_download_and_extract → _sync_atomic_swap`; drop duplicated zip-slip code; drop local `_INDEX_DIR`/`_INDEX_FILES` constants and unused `import zipfile`/`from pathlib import Path` |
| `custom_components/asp_parking/strings.json` | edit | +11 / -1 | Three new entity name keys (sensor.index_last_rebuilt, binary_sensor.index_rebuilding, button.rebuild_index) |
| `custom_components/asp_parking/translations/en.json` | edit | +11 / -1 | Byte-equivalent mirror of strings.json edit |

Net: **+231 / -35 across 7 files** (1 new + 6 modified).

## Per-Task Commits

| Task | Commit | Files | Lines (+/-) |
|------|--------|-------|-------------|
| Task 1: Add button + binary_sensor + sensor entity classes | `b15e38a` | button.py (NEW), binary_sensor.py, sensor.py | +181 / -4 |
| Task 2: Refactor `__init__.py` to use index_io helpers (closes D-01) | `af71431` | __init__.py | +27 / -30 |
| Task 3: Register "button" platform + add i18n keys (byte-equivalent) | `9ead116` | const.py, strings.json, translations/en.json | +23 / -1 |

## Test Outcomes

### All five Phase 33 RED test files turn GREEN (50 assertions total)

```text
$ .venv/bin/python -m pytest tests/test_index_rebuild_button.py \
    tests/test_index_rebuilding_binary_sensor.py \
    tests/test_index_last_rebuilt_sensor.py \
    tests/test_index_io.py \
    tests/test_coordinator_rebuild.py -q

..................................................                       [100%]
50 passed, 1 warning in 1.17s
```

Breakdown by file:
- `test_index_rebuild_button.py` — **7 tests GREEN** (unique_id, translation_key, icon, has_entity_name, entity_category, async_press, device_info, async_setup_entry)
- `test_index_rebuilding_binary_sensor.py` — **8 tests GREEN** (unique_id, translation_key+icon, has_entity_name, entity_category, is_on false, is_on true, is_on flips live, device_info)
- `test_index_last_rebuilt_sensor.py` — **9 tests GREEN** (unique_id, translation_key+icon, has_entity_name, device_class TIMESTAMP, entity_category DIAGNOSTIC, native_value None, tz-aware datetime, live read, device_info)
- `test_index_io.py` — Wave 2 plan 03 tests, already GREEN (no Phase 33 P04 changes touched these — sanity included in the run)
- `test_coordinator_rebuild.py` — Wave 2 plan 03 tests, already GREEN (sanity included in the run)

### Full non-network suite — zero regressions

```text
$ .venv/bin/python -m pytest -m "not integration and not ha_integration" -q

455 passed, 136 deselected, 1 warning in 10.49s
```

The lone warning is a pre-existing AsyncMock teardown trace in `test_coordinator_rebuild.py::test_async_do_rebuild_flips_is_rebuilding_around_work` (Wave 2 plan 03 artifact — not introduced by this plan).

## i18n Byte-Equivalence Confirmation

```text
$ python -c "import json
s = json.load(open('custom_components/asp_parking/strings.json'))['entity']
t = json.load(open('custom_components/asp_parking/translations/en.json'))['entity']
assert s == t
print('OK: byte-equivalent entity blocks')"
OK: byte-equivalent entity blocks

$ diff <(python -c "import json; print(json.dumps(json.load(open('custom_components/asp_parking/strings.json'))['entity'], indent=2, sort_keys=True))") \
       <(python -c "import json; print(json.dumps(json.load(open('custom_components/asp_parking/translations/en.json'))['entity'], indent=2, sort_keys=True))")
(no diff)
```

All three new entity-name paths resolve to the expected values:
- `entity.sensor.index_last_rebuilt.name == "Index Last Rebuilt"`
- `entity.binary_sensor.index_rebuilding.name == "Index Rebuilding"`
- `entity.button.rebuild_index.name == "Rebuild Index"`

Phase 31 CI guard precedent (`D-03 lines 137-139`) is satisfied: strings.json and translations/en.json remain byte-equivalent in their `entity` block.

## src/gps2asp Untouched (Phase 31 CI Guard Unaffected)

```text
$ git diff --name-only d1b6415..HEAD -- src/gps2asp/
(empty)
```

No file under `src/gps2asp/` was modified by Phase 33 — boundary confirmed per RESEARCH §"Architectural Responsibility Map". The pre-existing `src/gps2asp ↔ custom_components/asp_parking/gps2asp` mirror diff (unrelated to Phase 33) is unchanged.

## D-01 Single-Source-of-Truth Refactor Outcome

Before plan 04, the zip-slip safety check and the httpx download pattern existed in **two** places:
1. `__init__.py::_sync_download` (first-time setup, lines 80-98 of the pre-refactor file)
2. `index_io.py::_sync_extract_zip` + `_sync_download_and_extract` (Wave 2 plan 03 — only used by `coordinator._async_do_rebuild`)

After plan 04, the zip-slip check exists in exactly **one** place (`index_io.py::_sync_extract_zip`), and the httpx streaming download lives in exactly **one** place (`index_io.py::_sync_download_and_extract`). Both first-time setup AND the manual rebuild flow consume the same three sync helpers via `hass.async_add_executor_job(...)`:

```text
cleanup_stale → download_and_extract → atomic_swap
```

The first-time-setup notification IDs (`asp_parking_index_download`, `asp_parking_index_error`) remain **distinct** from the rebuild-flow IDs (`asp_parking_index_rebuild`, `asp_parking_index_rebuild_success`, `asp_parking_index_rebuild_error`) by design — RESEARCH Pitfall 7 calls out that the two lifecycle events have different user-visible UX (first-time setup blocks integration startup; manual rebuild keeps the existing index live and is informational).

Grep proof:

```text
$ grep -cE "def _sync_download|with zipfile.ZipFile\(" custom_components/asp_parking/__init__.py
0  # zero — both removed

$ grep -nE "_sync_cleanup_stale|_sync_download_and_extract|_sync_atomic_swap" custom_components/asp_parking/__init__.py
22:    _sync_atomic_swap,
23:    _sync_cleanup_stale,
24:    _sync_download_and_extract,
94:        await hass.async_add_executor_job(_sync_cleanup_stale, INDEX_DIR)
96:            _sync_download_and_extract, INDEX_DIR, INDEX_DOWNLOAD_URL
98:        await hass.async_add_executor_job(_sync_atomic_swap, INDEX_DIR)
```

D-01 is closed.

## Task 4 — Manual HA Dashboard Verification: DEFERRED

Per the plan's `<resume-signal>`, Task 4 is a `checkpoint:human-verify` that requires:
1. A live HA instance with the integration installed via HACS
2. A working device tracker producing GPS coordinates
3. (Optional) the ability to air-gap github.com to exercise the failure path

None of these were available during this plan's execution window. Per Phase 25 precedent (Plan 01 Task 3, also a `checkpoint:human-verify` deferred), Task 4 is marked **deferred to post-HACS-release** and logged in the v3.2 milestone-close items list alongside the Phase 25 Task 3 deferral.

The 8-step manual verification flow (button press → notification → binary_sensor flip → success notification → last_rebuilt update → concurrent-press no-op → optional failure-path) is fully documented in the plan's `<how-to-verify>` block and can be executed by the user at any point after the integration ships in a HACS release.

## Deviations from Plan

**None.** All three executable tasks (1, 2, 3) followed the plan verbatim:

- **Task 1**: Created `button.py` from scratch using the structure described in the plan's `<behavior>` block; appended `ASPIndexRebuildingBinarySensor` to `binary_sensor.py` after the existing `ASPActiveNowBinarySensor` class and extended the `async_setup_entry` list; appended `ASPIndexLastRebuiltSensor` to `sensor.py` after the existing `ASPLastErrorSensor` class (the closest "expose a coordinator datetime" analog the plan called out) and added it to the existing `async_setup_entry` list. All `_attr_*` values match the plan's `<interfaces>` block character-for-character — the RED tests asserted these literally.
- **Task 2**: Refactored `__init__.py` exactly as specified — removed `_INDEX_DIR` and `_INDEX_FILES` module-level constants (now imported from `index_io`), removed unused `import zipfile` and `from pathlib import Path` (no other code in `__init__.py` referenced them), removed the orphan `_sync_download` nested closure, and replaced its work with three sequential `hass.async_add_executor_job(...)` calls into the shared helpers. The pn_create/pn_dismiss + try/except + logger calls + first-time-setup notification IDs are preserved byte-equivalent.
- **Task 3**: Extended `PLATFORMS` with `"button"`; added three new entity-name keys to both i18n files using the same 2-space-indent style as the surrounding JSON; verified byte-equivalence via `json.load(...)` equality assertion.

No auto-fixes (Rule 1) were required — the plan was complete and unambiguous, and Wave 2 plan 03 had already populated the coordinator with the exact fields/methods the entity classes consume (`_is_rebuilding`, `_last_rebuilt`, `async_request_rebuild`).

No architectural changes (Rule 4) were needed.

## Self-Check: PASSED

- [x] `custom_components/asp_parking/button.py` exists and contains `class ASPIndexRebuildButton(ButtonEntity):`
- [x] `custom_components/asp_parking/binary_sensor.py` contains `class ASPIndexRebuildingBinarySensor(BinarySensorEntity):` and `return self._coordinator._is_rebuilding`
- [x] `custom_components/asp_parking/sensor.py` contains `class ASPIndexLastRebuiltSensor(_ASPDiagnosticSensor):` and `_attr_device_class = SensorDeviceClass.TIMESTAMP` and `return self._coordinator._last_rebuilt`
- [x] `custom_components/asp_parking/const.py` line 8 reads `PLATFORMS = ["sensor", "binary_sensor", "switch", "button"]`
- [x] `custom_components/asp_parking/__init__.py` imports from `.index_io`, contains the three helper invocations, and does NOT contain `with zipfile.ZipFile(` or `def _sync_download`
- [x] `strings.json` and `translations/en.json` `entity` blocks compare equal under `json.load + ==`
- [x] All three new entity-name paths resolve to the expected strings ("Rebuild Index", "Index Rebuilding", "Index Last Rebuilt")
- [x] All 50 Phase 33 test assertions across the 5 Phase 33 test files pass
- [x] Full non-network suite (455 tests) reports zero regressions
- [x] Commits exist: `b15e38a` (Task 1), `af71431` (Task 2), `9ead116` (Task 3)

## Known Stubs

None. All three new entities are wired to live coordinator state (`_is_rebuilding`, `_last_rebuilt`, `async_request_rebuild`); no hardcoded empty values, placeholder text, or unbound props.

## Threat Flags

None. No new network endpoints, no new auth paths, no new file access patterns, and no schema changes were introduced by this plan. The button entity does delegate to coordinator orchestration that downloads a ZIP — but that orchestration (and its threat model entry) lives in plan 03's threat surface, not plan 04's.
