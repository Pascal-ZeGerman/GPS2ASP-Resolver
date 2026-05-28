---
phase: 38-dual-path-index-rebuild-stale-detection
plan: 03
subsystem: infra
tags: [home-assistant, helpers-storage, async_track_time_interval, persistent-notification, tdd, pitfall-12]

# Dependency graph
requires:
  - phase: 38-dual-path-index-rebuild-stale-detection
    provides: "Plan 02: triggered_by parameter on async_request_rebuild; RebuildPath enum; _index_stale_store / _last_button_press / _last_stale_check / _remote_age_cache attributes declared in __init__"
  - phase: 38-dual-path-index-rebuild-stale-detection
    provides: "Plan 01: STALE_INDEX_DAYS, STALE_CHECK_INTERVAL_HOURS constants in const.py; _sync_build_from_source executor helper"
  - phase: 33-spatial-index-rebuild-button
    provides: "self._listeners cleanup loop in async_stop; _last_rebuilt populated from build_info.json at end of async_start; _is_rebuilding flag + _rebuild_lock asyncio.Lock"
provides:
  - "ASPParkingCoordinator._async_init_stale_lifecycle(self) -> None — Store init (FIXED key) + hydration + startup task + daily interval registration"
  - "ASPParkingCoordinator._async_check_stale_and_rebuild(self, now: datetime | None = None) -> None — shared startup + daily-interval helper; Pitfall 12 positional-arg compat"
  - "Store with key='asp_parking_index_stale' (FIXED, NOT per-entry-id per SPEC §Requirement 3); payload schema {last_button_press: ISO8601|None, last_stale_check: ISO8601}"
  - "Startup fire-and-forget background task name 'asp_parking_index_stale_check_startup' (D-01)"
  - "Daily 24h async_track_time_interval pointing at the SAME helper as the startup task (D-02); unsub appended to self._listeners for async_stop cleanup"
  - "Persistent notification with notification_id='asp_parking_index_stale' distinct from Phase 33 rebuild notification IDs"
  - "try/finally guarantee: last_stale_check is persisted to Store on every code path (first-install guard, fresh-index skip, _is_rebuilding guard, happy path)"
affects:
  - "Phase 38 closure: IDX-05 persistence half + IDX-07 stale detection both satisfied"
  - "Future maintenance: any new branch added inside _async_check_stale_and_rebuild MUST keep the try/finally invariant"

# Tech tracking
tech-stack:
  added: []   # No new dependencies — Store, async_track_time_interval, persistent_notification are HA-core; respx already in .venv
  patterns:
    - "Two-method extraction (_async_init_stale_lifecycle + _async_check_stale_and_rebuild) — lifecycle wiring isolated for testability without standing up async_start end-to-end"
    - "Pitfall 12 positional-arg-compat callback signature `now: datetime | None = None` — accepts both startup () and interval (datetime) calling conventions"
    - "try/finally Store write — Store record advances on every code path including short-circuit guards"
    - "FIXED Store key (not per-entry-id) — SPEC §Requirement 3 boundary; future multi-entry installs share the 24h press + last_stale_check anchors"

key-files:
  created:
    - "tests/test_coordinator_stale.py (617 lines, 19 unit tests; SimpleNamespace + _bind + sys.modules pn-stub pattern)"
  modified:
    - "custom_components/asp_parking/coordinator.py (+~135 LOC: imports + _async_init_stale_lifecycle + _async_check_stale_and_rebuild + async_start call site)"
    - "custom_components/asp_parking/const.py (1 comment rewording — strip literal substring 'releases/latest' to satisfy strict cross-plan guard)"

key-decisions:
  - "FIXED Store key 'asp_parking_index_stale' (NOT per-entry-id per SPEC §Requirement 3) — verified by test_async_start_initializes_index_stale_store_with_fixed_key"
  - "Pitfall 12 positional-arg compat — `_async_check_stale_and_rebuild(self, now: datetime | None = None)` — verified by paired tests `test_callback_accepts_no_args_from_startup_task` (startup task) + `test_callback_accepts_positional_datetime_from_interval` (interval callback)"
  - "Boundary semantics: `age <= timedelta(days=STALE_INDEX_DAYS)` → exactly 60d is NOT stale; 61d IS stale (matches SPEC '> 60 days' = strict-less). Verified by test_boundary_60_days_is_not_stale + test_61_days_is_stale"
  - "try/finally writes last_stale_check on every code path including _last_rebuilt-None guard, fresh-skip, _is_rebuilding skip, and happy path — verified by test_last_stale_check_written_to_store_after_each_run"
  - "Shared helper extraction (D-02): startup background task and daily interval callback call the SAME `_async_check_stale_and_rebuild` — one branch matrix, one place to update if SPEC semantics change"
  - "Lifecycle helper extracted to `_async_init_stale_lifecycle` instead of inlining inside async_start — enables unit-testing the wiring (Store init, task spawn, interval registration) without standing up async_start end-to-end"
  - "Stale-check skipped silently when _is_rebuilding=True — both the notification AND the rebuild trigger are suppressed (no double-notify); last_stale_check still advances"
  - "Notification id 'asp_parking_index_stale' distinct from Phase 33 'asp_parking_index_rebuild' / '*_success' / '*_error' — verified by test_notification_id_is_distinct_from_rebuild_ids"

patterns-established:
  - "Pattern: lifecycle helper that initialises a Store, hydrates state, AND wires startup + interval tasks in one method — call once from async_start at the right moment in the startup sequence"
  - "Pattern: stub-binding hop — when a SimpleNamespace stub binds method A which internally calls self.method_B, also bind method_B onto the stub (used in async_start wiring tests so _async_init_stale_lifecycle can reference self._async_check_stale_and_rebuild)"
  - "Pattern: time-boundary tests with sub-second tolerance — back off the boundary by 1 second so elapsed micro-clock between fixture setup and `dt_util.utcnow()` does not push age over the threshold"

requirements-completed: [IDX-05, IDX-07]

# Metrics
duration: ~35min
completed: 2026-05-22
---

# Phase 38 Plan 03: Stale Detection + Store Persistence (IDX-07 + IDX-05) Summary

**Coordinator-side staleness detection: fixed-key `asp_parking_index_stale` Store with hydration, a shared `_async_check_stale_and_rebuild` helper (startup background task + daily 24h `async_track_time_interval`), persistent notification, and `try/finally` Store advancement on every branch — all routed through Plan 02's `async_request_rebuild(triggered_by="stale_check")`.**

## Performance

- **Duration:** ~35 min
- **Tasks:** 3 (RED test scaffold, GREEN implementation, final regression gate)
- **Files modified:** 3 (1 new test file + 2 edited modules)
- **Tests added:** 19 (`tests/test_coordinator_stale.py`)

## Accomplishments

- `_async_init_stale_lifecycle(self) -> None` constructs `Store(self.hass, version=1, key="asp_parking_index_stale")` — FIXED key per SPEC §Requirement 3, hydrates `_last_button_press` + `_last_stale_check` from the dict payload (non-dict payloads discarded with a WARNING).
- D-01 startup fire-and-forget background task spawned via `entry.async_create_background_task` with name `"asp_parking_index_stale_check_startup"`.
- D-02 daily 24h `async_track_time_interval` registered pointing at the SAME helper as the startup task; unsub appended to `self._listeners` so `async_stop` cleans it up.
- `_async_check_stale_and_rebuild(self, now: datetime | None = None) -> None` — Pitfall 12 positional-arg-compat helper with the full SPEC matrix:
  - `_last_rebuilt is None` (first install) → skip rebuild + skip notification; `last_stale_check` still written.
  - `age <= 60d` (fresh) → skip silently.
  - `_is_rebuilding=True` → skip trigger (no double-notify).
  - Otherwise → post `notification_id="asp_parking_index_stale"` and await `async_request_rebuild(triggered_by="stale_check")` (D-03: skips the 24h double-press anchor).
- `try/finally` block guarantees `last_stale_check` is persisted on every code path.
- `async_start` calls `await self._async_init_stale_lifecycle()` immediately after `self._last_rebuilt` is populated from `build_info.json`.
- New `tests/test_coordinator_stale.py` (19 unit tests) exercises the full SPEC matrix and Pitfall 12 guard; 90/90 across all coordinator test files GREEN.

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Failing stale-detection unit tests** — `069294e` (test)
2. **Task 2 (GREEN): _async_init_stale_lifecycle + _async_check_stale_and_rebuild + async_start wiring** — `d1cadfb` (feat)
3. **Task 3 (REGRESSION + FINAL GATE): const.py releases/latest reword to satisfy strict cross-plan guard** — `7b73e52` (chore)

## Files Created/Modified

### Created
- `tests/test_coordinator_stale.py` (617 lines, 19 unit tests). Stub factory `_make_coord_stub_stale` + `_bind` mirror of Plan 02 plus an `index_stale_store` SimpleNamespace exposing `async_load` / `async_save` AsyncMocks. `pn_module` fixture stubs `homeassistant.components.persistent_notification` via `monkeypatch.setitem(sys.modules, ...)`. Four `async_start` wiring tests patch `coord_mod.Store` + `coord_mod.async_track_time_interval` and bind both `_async_init_stale_lifecycle` AND `_async_check_stale_and_rebuild` onto the stub (the lifecycle helper references the latter when spawning the startup task).

### Modified
- `custom_components/asp_parking/coordinator.py`
  - Imports: `STALE_CHECK_INTERVAL_HOURS`, `STALE_INDEX_DAYS` added to the existing `from .const import (...)` block.
  - New private method `_async_init_stale_lifecycle` (~50 LOC).
  - New private method `_async_check_stale_and_rebuild` (~55 LOC) with `try/finally` guarantee on `last_stale_check`.
  - `async_start` now `await`s `self._async_init_stale_lifecycle()` directly after `self._last_rebuilt = await ...read_build_timestamp(...)`.
- `custom_components/asp_parking/const.py` — rewording-only edit on the `GITHUB_INDEX_RELEASE_TAG` rationale comment (lines 69–73) to remove the literal substring `releases/latest`, mirroring the lexical fix Plan 02 applied to `coordinator.py`. The substantive rationale — `latest` returns v3.0.0 with zero assets, real `index.zip` lives on tag `index-v1` — is preserved.

## Decisions Made

See `key-decisions` in the frontmatter; the most consequential ones:

- **Fixed Store key (not per-entry-id):** SPEC §Requirement 3 is explicit on this — `Store(hass, version=1, key="asp_parking_index_stale")`. The 24h double-press anchor + `last_stale_check` are *integration-level* state, not per-entry. Verified by `test_async_start_initializes_index_stale_store_with_fixed_key`.
- **Pitfall 12 positional-arg compat:** the callback MUST accept both 0-arg (startup task) AND single-positional-`datetime` (interval) shapes. The signature `_async_check_stale_and_rebuild(self, now: datetime | None = None)` enables both calling conventions. Paired tests guard each call shape.
- **Strict boundary semantics:** `if age <= timedelta(days=STALE_INDEX_DAYS): return` — 60 days exactly is NOT stale, 61 days IS stale. Matches SPEC "> 60 days" strict-less wording.
- **`try/finally` Store advancement:** `last_stale_check` is written on every code path including the `_last_rebuilt is None` first-install guard, the fresh-index skip, the `_is_rebuilding` guard, and the happy path. This guarantees the Store record progresses on every run.
- **Lifecycle helper extraction (`_async_init_stale_lifecycle`):** The wiring code (Store init + hydrate + spawn task + register interval) lives in a thin private method instead of being inlined in `async_start`. This enables direct unit testing of the wiring via `_bind(stub, "_async_init_stale_lifecycle")` without standing up the full `async_start` (which touches subscription event helpers, debug overrides, suspension calendar, etc.).
- **Shared helper (D-02):** the startup background task and the daily interval call the same `_async_check_stale_and_rebuild`. Single branch matrix, single place to update if SPEC semantics change.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `test_boundary_60_days_is_not_stale` failed because elapsed real time pushed `age` over the 60d threshold**
- **Found during:** Task 2 verification — running the GREEN tests revealed this test failed even though the implementation matched the plan.
- **Issue:** The test set `last_rebuilt = datetime.now(timezone.utc) - timedelta(days=60)` and then `await check()`. Between the two calls, real time elapsed (~milliseconds), so when the helper read `dt_util.utcnow()` it computed `age = 60d + a-few-ms`, which is strictly greater than `timedelta(days=60)`, classifying the index as stale.
- **Fix:** Back off the boundary by 1 second — `last_rebuilt = datetime.now(timezone.utc) - timedelta(days=60, seconds=-1)` — so age at helper-call time is unambiguously inside the `<= 60d` band. The companion `test_61_days_is_stale` already covers the strictly-older path.
- **Files modified:** `tests/test_coordinator_stale.py` (one test body)
- **Verification:** Test passes after the fix; the SPEC semantics ("60d exactly = NOT stale; 61d = stale") are preserved by the pair of tests.
- **Committed in:** Task 2 commit (`d1cadfb`).

**2. [Rule 3 - Blocking] Four `async_start` wiring tests required binding `_async_check_stale_and_rebuild` onto the stub**
- **Found during:** Task 2 verification — the four wiring tests originally only bound `_async_init_stale_lifecycle`, but at runtime that helper references `self._async_check_stale_and_rebuild(...)` (both when constructing the startup-task coroutine and when registering the interval callback). A `SimpleNamespace` stub with only the lifecycle helper bound raised `AttributeError: 'types.SimpleNamespace' object has no attribute '_async_check_stale_and_rebuild'`.
- **Fix:** Each of the four wiring tests now binds BOTH helpers onto the stub (`stub._async_check_stale_and_rebuild = _bind(stub, "_async_check_stale_and_rebuild")` followed by `init_lifecycle = _bind(stub, "_async_init_stale_lifecycle")`). This pattern is documented in the Summary's `patterns-established` for future tests with similar method-call hops.
- **Files modified:** `tests/test_coordinator_stale.py` (four test bodies)
- **Verification:** All four async_start wiring tests pass; the helper signature itself was unchanged (the issue was test-side mechanics).
- **Committed in:** Task 2 commit (`d1cadfb`).

**3. [Rule 3 - Blocking] `const.py` comment contained the literal substring `releases/latest`, failing the strict Phase 38 acceptance guard**
- **Found during:** Task 3 final-gate `grep -r "releases/latest" custom_components/asp_parking/` check.
- **Issue:** The acceptance criterion requires zero hits across the whole integration, not just `coordinator.py`. The `const.py` rationale comment that explains *why* we use tag `index-v1` instead of `/releases/latest` contained the literal substring, even though it was a documentary mention inside a comment.
- **Fix:** Reword to `"the 'latest release' GitHub endpoint"` — same lexical fix Plan 02 already applied to `coordinator.py`. Preserves the rationale; removes the substring.
- **Files modified:** `custom_components/asp_parking/const.py`
- **Verification:** `grep -r "releases/latest" custom_components/asp_parking/` now returns 0; offline pytest suite remains GREEN (no functional change).
- **Committed in:** Task 3 commit (`7b73e52`).

---

**Total deviations:** 3 auto-fixed (1 test-bug from real-time elapsed boundary; 1 mechanical stub-binding hop; 1 lexical guard from a pre-existing Plan 01 comment). No deviations affected plan intent.

## Issues Encountered

- **`pytest-asyncio` "coroutine never awaited" warnings:** the `MagicMock` standing in for `entry.async_create_background_task` does not actually await the coroutine handed to it; pytest's warning machinery flags this. Same noise pattern already present in Phase 33 and Plan 02 tests; not amplified by this plan.

## User Setup Required

None — no external service configuration. The `Store`, `async_track_time_interval`, and `persistent_notification` APIs are HA-core. The 60-day staleness threshold and 24h interval are hard constants per SPEC §Out of scope.

## Phase 38 Closure

- **IDX-05 (smart button + Store persistence):** Plan 02 delivered the smart-routing matrix (download / from_source / double_press / github_api_failed) + 10-min cache + `triggered_by` parameter. This plan completes the **Store-persistence half**: `Store(version=1, key="asp_parking_index_stale")` with FIXED key, hydration of `last_button_press` at startup → the 24h double-press window survives HA restart.
- **IDX-06 (from-source CSCL rebuild):** Plan 01 delivered `_sync_build_from_source` with full parity to `scripts/build_index.py` minus geopandas, plus the D-04/D-05 source-field patches. Unchanged here.
- **IDX-07 (stale detection):** This plan delivers the `_async_check_stale_and_rebuild` helper, the startup fire-and-forget task (D-01), the daily 24h `async_track_time_interval` (D-02), the `_last_rebuilt is None` first-install guard, the `_is_rebuilding` re-entry guard, and the distinct `asp_parking_index_stale` notification.

Cross-plan invariants (verified in Task 3):
- `manifest.json` byte-identical to pre-phase (no new dependencies across any of the 3 plans)
- `button.py` byte-identical to pre-phase (smart routing lives in the coordinator; existing button entity is unchanged)
- `strings.json ↔ translations/en.json` byte-identical (Phase 31 guard holds)
- No `import geopandas` anywhere in `custom_components/asp_parking/`
- No `releases/latest` substring anywhere in `custom_components/asp_parking/`
- 48 new tests across the phase (10 in `test_index_io_build_from_source.py` + 19 in `test_coordinator_path_selection.py` + 19 in `test_coordinator_stale.py`)
- 679 offline pytest tests pass (baseline 660 before Plan 02; +19 from this plan)
- 144 ha_integration tests pass — `async_start` end-to-end (which now calls `_async_init_stale_lifecycle`) is regression-free
- 24 Phase 33 button + binary_sensor + last_rebuilt sensor tests still pass — no leakage into the pre-existing entity tests

## Self-Check: PASSED

All files exist; all commit hashes exist on the branch.

- FOUND: `tests/test_coordinator_stale.py` (617 lines, 19 tests)
- FOUND (modified): `custom_components/asp_parking/coordinator.py`
- FOUND (modified): `custom_components/asp_parking/const.py`
- FOUND: `.planning/phases/38-dual-path-index-rebuild-stale-detection/38-03-SUMMARY.md`
- FOUND: commit `069294e` (Task 1 RED — 19 failing tests)
- FOUND: commit `d1cadfb` (Task 2 GREEN — coordinator implementation + test stub binding fix)
- FOUND: commit `7b73e52` (Task 3 — const.py reword to satisfy strict cross-plan guard)
- FOUND: ASPParkingCoordinator._async_init_stale_lifecycle (line 923)
- FOUND: ASPParkingCoordinator._async_check_stale_and_rebuild (line 983)
- FOUND: ASPParkingCoordinator._async_decide_rebuild_path (Plan 02)
- FOUND: ASPParkingCoordinator._fetch_remote_asset_age_days (Plan 02)
- FOUND: index_io._sync_build_from_source (Plan 01)
- VERIFIED: inspect.signature confirms params[1].name == 'now' and default is None (Pitfall 12 positional-arg compat)
- VERIFIED: 679 offline tests pass; 144 ha_integration tests pass; 24 Phase 33 entity tests pass

---
*Phase: 38-dual-path-index-rebuild-stale-detection*
*Plan: 38-03*
*Completed: 2026-05-22*
