---
plan: 34-04
phase: 34
status: complete
completed_at: "2026-05-15"
subsystem: coordinator
tags: [caldav, ha-integration, coordinator, async, storage, suspension]
requirements_satisfied: [CALDAV-03, CALDAV-04, CALDAV-05, CALDAV-06]
dependency_graph:
  requires: [34-01, 34-02, 34-03]
  provides: [caldav-coordinator-hooks]
  affects: [custom_components/asp_parking/coordinator.py]
tech_stack:
  added: [homeassistant.helpers.storage.Store]
  patterns:
    - Background task via entry.async_create_background_task (Pitfall 10 compliant)
    - asyncio.Lock in __init__ (Pitfall 2 — bound to current event loop)
    - D-09 single-fire persistent notification per failure streak
    - Suspension mutation choke-point (_async_apply_suspension_state)
key_files:
  modified:
    - custom_components/asp_parking/coordinator.py
decisions:
  - "Duck-type next_window check in _async_caldav_hook_after_resolve instead of isinstance(schedule, ScheduleFound) so both real ScheduleFound dataclass and SimpleNamespace test stubs pass the gate"
  - "Store storage_key: f'{DOMAIN}_caldav_{entry.entry_id}' — per-entry namespace prevents cross-entry collisions"
  - "All CalDAV coroutines referenced via ASPParkingCoordinator.method(self) pattern (not self.method()) to support SimpleNamespace stub tests (mirrors Phase 33 _async_do_rebuild pattern)"
  - "_maybe_delete_caldav_on_move declared async def (not sync def) to match test expectations (await hook())"
metrics:
  duration: "~25 minutes"
  completed: "2026-05-15"
  tasks_completed: 2
  files_modified: 1
---

# Phase 34 Plan 04: Coordinator CalDAV Wiring Summary

Wired CalDAV write/delete lifecycle into `coordinator.py`. All 12 RED tests in `tests/test_coordinator_caldav.py` turn GREEN. Pre-existing tests remain green (467 passed).

## One-liner

Full CalDAV coordinator wiring: Store load on startup, suspension choke-point refactor, write-on-resolve + delete-on-move + delete-on-suspension background tasks with asyncio.Lock and D-09 streak notification.

## What Was Built

### Task 1: CalDAV state fields + Store load + suspension choke-point

**Imports added:**
- `from homeassistant.helpers.storage import Store` (module-level)
- `from . import caldav_sync` and `from .caldav_sync import CalDAVConfig`
- `CONF_CALDAV_*`, `DEFAULT_CALDAV_*` constants from `.const`
- `DOMAIN` from `.const` (needed for Store key)

**7 new fields in `__init__`** (Pitfall 2 — bound to current event loop, NOT class scope):
```python
self._caldav_store: Store | None = None
self._caldav_uid: str | None = None
self._caldav_error_notified: bool = False
self._last_suspension_state: bool = False
self._caldav_lock: asyncio.Lock = asyncio.Lock()
self._caldav_write_task: asyncio.Task[None] | None = None
self._caldav_delete_task: asyncio.Task[None] | None = None
```

**Store load in `async_start`** (CALDAV-06):
```python
if self.entry.options.get(CONF_CALDAV_URL):
    self._caldav_store = Store(hass, version=1, key=f"{DOMAIN}_caldav_{entry.entry_id}")
    raw = await self._caldav_store.async_load()
    self._caldav_uid = (raw or {}).get("uid")  # Pitfall 5: coerce None → {}
    self._last_suspension_state = self.data.suspension_state.is_suspended
```

**`_async_apply_suspension_state` choke-point** (D-08 / Pitfall 8 / T-34-06):
- `@callback` decorated synchronous method
- Compares `_last_suspension_state` vs `new.is_suspended`
- Assigns `self.data.suspension_state = new` and updates `_last_suspension_state`
- On False → True transition with `_caldav_uid` + `_caldav_store`: spawns `asp_parking_caldav_delete_on_suspension` background task

**6 direct mutation sites refactored** (T-34-06 mitigation):
| Original location | Method | Before | After |
|---|---|---|---|
| `async_start` ~line 369 | holiday startup | `self.data.suspension_state = holiday_info` | `self._async_apply_suspension_state(holiday_info)` |
| `async_start` ~line 421 | bridge startup | `self.data.suspension_state = _bridge_info` | `self._async_apply_suspension_state(_bridge_info)` |
| `_async_on_nyc311_state_change` ~line 657 | bridge state change | direct assign | `self._async_apply_suspension_state(...)` |
| `_async_initial_311_fetch` ~line 929 | 311 startup | direct assign | `self._async_apply_suspension_state(info)` |
| `_async_update_suspension` ~line 1067 | bridge periodic | direct assign | `self._async_apply_suspension_state(...)` |
| `_async_update_suspension` ~line 1088 | poll fallback | direct assign | `self._async_apply_suspension_state(info)` |

### Task 2: Full CalDAV method implementations + pipeline wiring

**`_async_caldav_write_or_update`**:
- Builds `CalDAVConfig.from_options(self.entry.options)`
- `async with self._caldav_lock` — T-34-07 serialisation
- On success: `self._caldav_uid = new_uid`, `Store.async_save({"uid": new_uid})`, dismiss streak notification
- On exception: sanitise error (T-34-01/T-34-05), log WARNING, D-09 single-fire `pn_create("asp_parking_caldav_error")`

**`_async_caldav_delete_current`**:
- Guards: `_caldav_uid is None` or `_caldav_store is None` → return
- Same Lock + try/except + D-09 notification pattern as write
- On success: `_caldav_uid = None`, `Store.async_save({})`

**`_async_caldav_hook_after_resolve`**:
- `async def` (test stubs use `await hook(schedule)`)
- D-02 guard: `_caldav_store is None` → return
- Pitfall 4 guard: `suspension_state.is_suspended` → return
- Duck-type `next_window` check (not isinstance) for SimpleNamespace test compatibility
- Spawns `asp_parking_caldav_write` task (write path) or `asp_parking_caldav_delete_on_move` (no window)

**`_maybe_delete_caldav_on_move`**:
- `async def` (test stubs use `await hook()`)
- Guards: `_caldav_uid is None`, `_caldav_store is None`, `schedule.next_window is None`
- Safety window: `boundary = next_window.start_datetime - timedelta(minutes=safety_min)`
- Uses `now_ha_local()` (HA configured TZ, not hardcoded NYC)
- If `now >= boundary` (inside window): no-op; else spawn `asp_parking_caldav_delete_on_move`

**Pipeline wiring:**
- `_async_resolve_pipeline`: `await self._async_caldav_hook_after_resolve(schedule)` inserted immediately after `await self._async_maybe_send_notification(schedule)` (Pitfall 10: hook is async but spawns bg task, never awaits CalDAV inline)
- `_async_on_gps_update`: `self.hass.async_create_task(self._maybe_delete_caldav_on_move())` inserted after movement threshold clears, before debouncer call

## Notification ID Inventory

| Notification ID | Phase | Created by | Dismissed by |
|---|---|---|---|
| `asp_parking_caldav_error` | 34 | `_async_caldav_write_or_update` / `_async_caldav_delete_current` on failure | Same methods on next success |
| `asp_parking_index_rebuild` | 33 | `_async_do_rebuild` (in-progress) | `_async_do_rebuild` on complete/fail |
| `asp_parking_index_rebuild_success` | 33 | `_async_do_rebuild` success | Manual |
| `asp_parking_index_rebuild_error` | 33 | `_async_do_rebuild` failure | Manual |

No ID collisions (Pitfall 7 compliant).

## Background Task Names

| Task Name | Created by | Lifecycle |
|---|---|---|
| `asp_parking_caldav_write` | `_async_caldav_hook_after_resolve` | Auto-cancel on entry unload |
| `asp_parking_caldav_delete_on_suspension` | `_async_apply_suspension_state` | Auto-cancel on entry unload |
| `asp_parking_caldav_delete_on_move` | `_async_caldav_hook_after_resolve` (no-window) + `_maybe_delete_caldav_on_move` | Auto-cancel on entry unload |

## Test Results

`tests/test_coordinator_caldav.py`: **12/12 passed**

Full suite (excluding caldav_sync + ha_integration): **467 passed, 149 deselected**

## Commits

| Task | Commit | Description |
|---|---|---|
| Task 1 | `fb1a6c9` | CalDAV fields, Store load, suspension choke-point |
| Task 2 | `ba68be4` | CalDAV write/delete/hook/safety-window + pipeline wiring |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `_async_caldav_hook_after_resolve` and `_maybe_delete_caldav_on_move` declared `async def` instead of sync `def`**
- **Found during:** Task 2 test run
- **Issue:** Tests use `await hook()` / `await hook(schedule)`. Sync functions cannot be awaited — `await None` raises `TypeError`.
- **Fix:** Declared both methods as `async def`. In production, `_async_caldav_hook_after_resolve` awaits nothing (it only spawns bg tasks) and `_maybe_delete_caldav_on_move` uses no async operations either; the `async def` has zero behavioral cost.
- **Files modified:** `custom_components/asp_parking/coordinator.py`

**2. [Rule 1 - Bug] `isinstance(schedule, ScheduleFound)` check incompatible with SimpleNamespace test stubs**
- **Found during:** Task 2 first test run (`test_resolve_writes_event_when_caldav_configured` FAILED — name was `asp_parking_caldav_delete_on_move` instead of `asp_parking_caldav_write`)
- **Issue:** Test stubs use `SimpleNamespace` for `schedule`; `isinstance(SimpleNamespace(), ScheduleFound)` is always False, so the hook fell to the delete path instead of write path.
- **Fix:** Replaced `isinstance(schedule, ScheduleFound) and schedule.next_window is not None` with duck-type `getattr(schedule, 'next_window', None) is not None`. In production the real `compute_schedule` always returns a typed union; duck-type is equivalent and test-compatible.
- **Files modified:** `custom_components/asp_parking/coordinator.py`

**3. [Rule 1 - Bug] `_async_apply_suspension_state` couldn't call `self._async_caldav_delete_current()` on SimpleNamespace stub**
- **Found during:** Task 1 test run
- **Issue:** `_bind` binds one class method to the stub, but internal `self._async_caldav_delete_current()` lookup on a SimpleNamespace (not a real coordinator) raises AttributeError.
- **Fix:** Changed to `ASPParkingCoordinator._async_caldav_delete_current(self)` — same pattern as Phase 33's `ASPParkingCoordinator._async_do_rebuild(self)` (PATTERNS.md confirmed this pattern).
- **Files modified:** `custom_components/asp_parking/coordinator.py`

## Threat Flags

None — all threats in plan's `<threat_model>` were mitigated:
- T-34-01/T-34-05: password sanitised via `.replace(password, "***")` before logging + pn_create
- T-34-04: all CalDAV calls spawned via bg task (Pitfall 10 — never inline await)
- T-34-06: grep -c "self.data.suspension_state = " returns 1 (choke-point body only)
- T-34-07: `_caldav_lock = asyncio.Lock()` in `__init__`; both write and delete use `async with self._caldav_lock`

## Self-Check

Files created/modified:
- [FOUND] `custom_components/asp_parking/coordinator.py`
- [FOUND] `.planning/phases/34-caldav-calendar-integration/34-04-SUMMARY.md`

Commits:
- [FOUND] `fb1a6c9` — Task 1
- [FOUND] `ba68be4` — Task 2

## Self-Check: PASSED
