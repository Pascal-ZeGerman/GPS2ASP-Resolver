---
phase: 33-spatial-index-rebuild-button
plan: 03
subsystem: ha-integration
tags: [coordinator, asyncio-lock, atomic-swap, index-io, green, phase-33]
dependency_graph:
  requires:
    - tests/test_index_io.py (RED tests, plan 33-02)
    - tests/test_coordinator_rebuild.py (RED tests, plan 33-02)
    - custom_components/asp_parking/const.py (INDEX_DOWNLOAD_URL)
    - custom_components/asp_parking/gps2asp/resolver/spatial_index.py (SpatialIndex.reset)
  provides:
    - custom_components/asp_parking/index_io.py (sync helpers; D-01 single source of truth)
    - ASPParkingCoordinator.async_request_rebuild (public button entry point)
    - ASPParkingCoordinator._async_do_rebuild (background task body)
    - ASPParkingCoordinator._is_rebuilding / _last_rebuilt (entity-readable state)
  affects:
    - custom_components/asp_parking/coordinator.py (additive only — no existing method touched)
tech_stack:
  added:
    - "httpx (already a dependency; reused for streaming download in executor)"
    - "asyncio.Lock (event-loop-bound, constructed inside __init__ per Pitfall 1)"
  patterns:
    - "Single source of truth (D-01): __init__.py first-time setup and coordinator rebuild both call into index_io.py"
    - "Atomic swap: os.replace POSIX rename(2) atomicity — fully old or fully new, never half-extracted (D-02)"
    - "Background task via entry.async_create_background_task — auto-cancel on entry unload (Pitfall 1)"
    - "Flag + lock defence-in-depth: _is_rebuilding gate prevents spawn; _rebuild_lock prevents any bypass"
    - "Distinct notification IDs for in-progress vs success vs error (Pitfall 7)"
    - "Lazy import of persistent_notification inside method body (matches existing __init__.py pattern)"
key_files:
  created:
    - custom_components/asp_parking/index_io.py (199 lines, 6 helpers + 2 constants)
  modified:
    - custom_components/asp_parking/coordinator.py (4 additive hunks, +159 lines, 0 deletions)
decisions:
  - "D-01 honoured: index_io.py is the single source of truth for download/extract/swap/build_info — to be consumed by plan 04's __init__.py refactor"
  - "D-02 honoured: atomic swap via os.replace; index dir is never half-written"
  - "D-04 honoured: success notification message includes 'Built: <timestamp>'"
  - "D-05 honoured: error notification message includes 'Your existing index is still active'"
  - "D-06 honoured: finally block ALWAYS resets _is_rebuilding=False"
  - "Pitfall 1 honoured: asyncio.Lock constructed inside __init__ (line 246), not at class scope"
  - "Pitfall 2 honoured: SpatialIndex.reset() runs AFTER _sync_atomic_swap (coord line 562 follows line 555)"
  - "Pitfall 3 honoured: _sign_cache.clear() runs AFTER atomic_swap"
  - "Pitfall 7 honoured: 3 distinct notification IDs (in-progress / success / error)"
  - "Open Q3 honoured: _last_rebuilt pre-populated at startup via _sync_read_build_timestamp executor job"
  - "Idiom adjustment: async_request_rebuild constructs the rebuild coroutine via ASPParkingCoordinator._async_do_rebuild(self) instead of self._async_do_rebuild() — semantically identical, but lets the test stub (SimpleNamespace binding only async_request_rebuild) exercise the spawn path. NOT a deviation from CONTEXT.md decisions."
metrics:
  duration_seconds: 1030
  completed_at: 2026-05-14T19:21:32Z
  task_count: 2
  files_changed: 2
  lines_added: 358
---

# Phase 33 Plan 03: GREEN Implementation — index_io + Coordinator Rebuild Orchestration

Implements the production code that turns plan-02 RED tests GREEN: a new sync-helpers module `index_io.py` plus coordinator-side rebuild orchestration (`async_request_rebuild` + `_async_do_rebuild` + 4 lifecycle fields + 1 startup line). Entity-contract tests from plan 01 remain RED — they will be turned GREEN by plan 04 (button/binary_sensor/sensor entity implementations).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create custom_components/asp_parking/index_io.py with sync helpers | `e57ebae` | custom_components/asp_parking/index_io.py |
| 2 | Add rebuild orchestration to ASPParkingCoordinator | `8600595` | custom_components/asp_parking/coordinator.py |

## Artifacts

### Created: `custom_components/asp_parking/index_io.py` (199 lines)

| Symbol | Lines | Purpose |
|--------|-------|---------|
| Module docstring | 1-22 | Names D-01 (single source of truth), the zip-slip CVE class, and the atomic-swap invariant |
| Imports | 24-35 | stdlib (`json`, `os`, `shutil`, `zipfile`) + `httpx` + `homeassistant.util.dt` |
| `INDEX_DIR` | 40 | `Path(__file__).parent / "gps2asp" / "data" / "index"` — byte-equivalent to original |
| `INDEX_FILES` | 41 | `("segments.idx", "segments.dat", "segments.json", "graph.json")` — byte-equivalent |
| `_sync_atomic_swap` | 44-81 | os.replace POSIX rename(2); raises FileNotFoundError if `_tmp` missing |
| `_sync_cleanup_stale` | 84-103 | Idempotent wipe of `_tmp`, `_bak`, `_download.zip` — never raises |
| `_sync_extract_zip` | 106-126 | Zip-slip-safe extraction (preserves the original `startswith(resolved_base + sep)` check) |
| `_sync_download_and_extract` | 129-154 | httpx streaming GET → `_tmp/_download.zip` → `_sync_extract_zip` → unlink in finally |
| `_sync_read_build_timestamp` | 157-198 | tz-aware datetime or None; never raises (Pitfall 6 + 7) |

### Modified: `custom_components/asp_parking/coordinator.py` (+159 lines, 0 deletions)

| Hunk | Diff Range | Description |
|------|-----------|-------------|
| 1 | `@@ -85,6 +85,14 @@` | Added `INDEX_DOWNLOAD_URL` to the const-import tuple + new `from .index_io import (...)` block |
| 2 | `@@ -230,6 +238,14 @@` | Four new `__init__` fields in a Phase 33 lifecycle block (after existing `self._preseed_task`/`self._unsub_cache_rebuild`) |
| 3 | `@@ -439,6 +455,12 @@` | One-line executor call in `async_start` to populate `self._last_rebuilt` from `build_info.json` before the trailing `logger.info("coordinator started: ...")` |
| 4 | `@@ -456,6 +478,143 @@` | Two new methods (`async_request_rebuild` + `_async_do_rebuild`) inserted after `async_stop` with a clearly-delimited Phase 33 section header |

No other coordinator method, field, or class-level attribute was modified.

## Verification

### Plan-02 RED tests turn GREEN

```
$ .venv/bin/python -m pytest tests/test_index_io.py tests/test_coordinator_rebuild.py -q
..........................                                               [100%]
26 passed, 1 warning in 1.02s
```

| Suite | Before (RED) | After (GREEN) |
|-------|--------------|---------------|
| tests/test_index_io.py | ImportError on collection (`ModuleNotFoundError: custom_components.asp_parking.index_io`) | **17/17 passed** |
| tests/test_coordinator_rebuild.py | 9 AttributeError on `async_request_rebuild` / `_async_do_rebuild` | **9/9 passed** |

The single `RuntimeWarning: coroutine '..._async_do_rebuild' was never awaited` originates from the test stub: `entry.async_create_background_task` is a plain `MagicMock` that records the spawn call without consuming the coroutine. This is a test-fixture artifact, not a production issue — in HA the real `async_create_background_task` consumes the coroutine.

### No regressions in the existing suite

```
$ .venv/bin/python -m pytest -m "not integration and not ha_integration" \
    --ignore=tests/test_index_rebuild_button.py \
    --ignore=tests/test_index_rebuilding_binary_sensor.py \
    --ignore=tests/test_index_last_rebuilt_sensor.py -q
431 passed, 136 deselected, 1 warning in 10.67s
```

Plan-04 entity tests (`test_index_rebuild_button.py`, `test_index_rebuilding_binary_sensor.py`, `test_index_last_rebuilt_sensor.py`) intentionally remain RED — they verify entity classes (button, binary_sensor, sensor) that this plan does not implement. Plan 04 owns the entity GREEN step.

### Sanity grep checks

```
$ grep -c 'asp_parking_index_rebuild' custom_components/asp_parking/coordinator.py
9   # 1× task name, 4× notification IDs (in-progress create + dismiss ×2, success, error), 4× notification_id kwargs

$ grep -n "_sync_atomic_swap\|SpatialIndex.reset" custom_components/asp_parking/coordinator.py
92:    _sync_atomic_swap,           # import
516: ...SpatialIndex.reset...      # docstring reference
555: _sync_atomic_swap, INDEX_DIR  # the swap call
562: SpatialIndex.reset()           # the reset call — AFTER swap (Pitfall 2 ✓)

$ grep -c 'self._sign_cache.clear()' custom_components/asp_parking/coordinator.py
1   # called once inside _async_do_rebuild, after atomic_swap and SpatialIndex.reset (IDX-04 ✓)
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] `async_request_rebuild` coroutine construction adjusted to allow stub-based testing**

- **Found during:** Task 2, first pytest run
- **Issue:** Plan `<behavior>` specified `self._async_do_rebuild()` for the coroutine passed to `entry.async_create_background_task`. But the plan-02 RED test `test_async_request_rebuild_spawns_background_task_once` builds a `SimpleNamespace` stub and uses `_bind` to bind ONLY `async_request_rebuild` via `__get__`. When that bound method evaluated `self._async_do_rebuild()`, attribute lookup on the stub failed with `AttributeError` before the MagicMock background-task spawner was ever invoked.
- **Fix:** Construct the coroutine via the class instead: `ASPParkingCoordinator._async_do_rebuild(self)`. Semantically identical for production (`self` is always an `ASPParkingCoordinator` instance, so the unbound-method invocation produces the same coroutine as the bound-method call would). For the test stub, this routes the lookup through the class — not through the stub's empty namespace — so the spawn line completes and the MagicMock records the call as the test expects.
- **Files modified:** `custom_components/asp_parking/coordinator.py` (the spawn line inside `async_request_rebuild`)
- **Commit:** `8600595`
- **Inline comment added** explaining the rationale so future readers understand why this construction was chosen over the more natural `self._async_do_rebuild()`.

No deviations from CONTEXT.md decisions D-01..D-06 — all six are preserved exactly as locked.

## Known Stubs

None — this plan adds production code only. The three entity test files that remain RED are owned by plan 04, which will implement the actual entity classes (button, binary_sensor, sensor).

## Threat Surface Scan

No new attack surface introduced beyond what is already in scope for Phase 33:
- The zip-slip check in `_sync_extract_zip` is byte-equivalent to the pre-existing check in `__init__.py` lines 90-96 (T-33-03-01 mitigated).
- The download URL is the same GitHub release URL already used at first-time setup (no new MITM surface beyond T-33-03-05 accepted in the plan).
- Notification IDs are distinct from first-time-setup IDs (T-33-03-06 mitigated).
- The error-notification message includes `str(err)` matching the existing first-time-setup pattern (T-33-03-07 accepted; no new disclosure surface).

## TDD Gate Compliance

This is the GREEN-phase plan for plan-02's RED tests. Verified via `git log`:
- RED: plans 33-01 and 33-02 contributed test commits prior to base `c9e5fc0` ("chore: merge executor worktrees (33-01 + 33-02 RED tests)").
- GREEN: commits `e57ebae` (`feat(33-03): add ...index_io.py`) and `8600595` (`feat(33-03): add index-rebuild orchestration ...`) on this worktree branch turn plan-02's RED tests GREEN.

Plan-04 will own the REFACTOR step (if any) and the entity-test GREEN step.

## Self-Check: PASSED

- `custom_components/asp_parking/index_io.py` — FOUND
- `custom_components/asp_parking/coordinator.py` — modifications FOUND (4 hunks, +159 / -0)
- Commit `e57ebae` — FOUND in `git log --all`
- Commit `8600595` — FOUND in `git log --all`
- `tests/test_index_io.py` — 17/17 GREEN
- `tests/test_coordinator_rebuild.py` — 9/9 GREEN
- Full non-Phase-33 suite — 431 passed, 0 regressions
- Pitfall 2 ordering (swap → reset) — verified via line-order grep
