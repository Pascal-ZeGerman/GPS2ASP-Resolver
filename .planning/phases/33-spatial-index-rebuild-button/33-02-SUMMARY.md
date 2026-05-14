---
phase: 33-spatial-index-rebuild-button
plan: 02
subsystem: testing
tags: [tdd, red, asyncio-lock, atomic-swap, zip-slip, build-info, coordinator, index-io, phase-33]

# Dependency graph
requires:
  - phase: 33-spatial-index-rebuild-button (Plan 01)
    provides: Phase 33 requirements (IDX-01..IDX-04), CONTEXT/RESEARCH/PATTERNS docs locking the contract
provides:
  - tests/test_index_io.py — 17 RED tests for the future sync helpers (atomic swap, zip-slip refusal, idempotent cleanup, tz-aware build_info parse)
  - tests/test_coordinator_rebuild.py — 9 RED tests for the future coordinator methods (async_request_rebuild gate, _async_do_rebuild orchestration)
  - Machine-checkable contract for IDX-02 (asyncio.Lock + _is_rebuilding flag) and IDX-04 (atomic swap → SpatialIndex.reset → _sign_cache.clear sequencing)
  - Test fixtures use tmp_path + SimpleNamespace stubs (no HA harness, no network, runs in <1s)
affects: [33-03-PLAN.md (Wave 2 implementation), 33-04-PLAN.md (Wave 2 plumbing), all Phase-33 GREEN waves]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "RED-first TDD: failing tests created before any production module exists (ModuleNotFoundError + AttributeError as RED-state signals)"
    - "SimpleNamespace stub coordinator + AsyncMock executor + MagicMock notification spies — mirrors tests/test_debug_switch.py"
    - "Future-method binding via `getattr(ASPParkingCoordinator, name).__get__(stub, cls)` — exercises real (Wave-2-implemented) code paths"
    - "Recording dict subclass for ordering assertions where dict.clear() can't be monkeypatched"
    - "Zip-slip test uses zf.writestr('../escape.txt') (relative attack) and '../../../etc/escape.txt' (absolute-path attempt)"

key-files:
  created:
    - "tests/test_index_io.py — 17 stdlib-only RED tests targeting custom_components/asp_parking/index_io.py (future module)"
    - "tests/test_coordinator_rebuild.py — 9 RED tests targeting ASPParkingCoordinator.async_request_rebuild and _async_do_rebuild (future methods)"
  modified: []

key-decisions:
  - "Test files import from custom_components.asp_parking.index_io at module top so collection fails with ModuleNotFoundError in RED state — clearest possible RED signal"
  - "Coordinator tests use _bind() helper that does getattr() inside each test (not at module top) — keeps Task 2 collection green so the 9 tests are individually visible in pytest output rather than masked behind a collection error"
  - "Notification spies installed via monkeypatch.setitem(sys.modules, 'homeassistant.components.persistent_notification', ...) — covers both `from homeassistant.components.persistent_notification import ...` and `homeassistant.components.persistent_notification.async_create(...)` access patterns the production code may use"
  - "Ordering test uses _RecordingDict subclass instead of monkeypatching dict.clear (which fails with 'read-only attribute') — pattern documented for future tests that need to record built-in method calls"
  - "Zip-slip test asserts no escape.txt with PWNED payload exists anywhere under base/.. (belt-and-braces) rather than just message inspection — directly catches a production code that returns ValueError after writing"

patterns-established:
  - "Pattern: future-method binding for RED tests — `method = getattr(Cls, name); method.__get__(stub, Cls)` lets tests reference unwritten methods without breaking collection"
  - "Pattern: stdlib-only zip-slip test — `zipfile.ZipFile.writestr('../escape.txt', b'PWNED')` + pytest.raises(ValueError) + recursive scan for payload"
  - "Pattern: notification spy installation via sys.modules — mocks the entire persistent_notification module so the production code can `import ... as pn_create/pn_dismiss` freely"

requirements-completed: [IDX-02, IDX-04]

# Metrics
duration: ~10min
completed: 2026-05-14
---

# Phase 33 Plan 02: RED Tests for Index Rebuild Sync Helpers + Coordinator Orchestration

**Two RED-state pytest files (26 failing tests total) lock the contract for the to-be-created `custom_components/asp_parking/index_io.py` module and the new `ASPParkingCoordinator.async_request_rebuild` / `_async_do_rebuild` orchestration methods — atomic swap ordering, zip-slip refusal, idempotent stale cleanup, tz-aware build_info parsing, asyncio.Lock + flag gate, distinct notification IDs all have machine-checkable assertions before any production code is written.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-05-14T16:04:18Z
- **Completed:** 2026-05-14T16:14:18Z
- **Tasks:** 2
- **Files created:** 2

## Accomplishments

- Created `tests/test_index_io.py` (329 lines, 17 tests) targeting four pure sync helpers (`_sync_atomic_swap`, `_sync_cleanup_stale`, `_sync_extract_zip`, `_sync_read_build_timestamp`) plus two module constants (`INDEX_DIR`, `INDEX_FILES`). All tests use `tmp_path` — no production paths touched.
- Created `tests/test_coordinator_rebuild.py` (489 lines, 9 tests) targeting `async_request_rebuild` (IDX-02 gate semantics) and `_async_do_rebuild` (IDX-04 ordering invariants, success/failure notifications, finally-block flag reset).
- Locked the strict swap-ordering contract: `cleanup_stale → download_and_extract → atomic_swap → SpatialIndex.reset → _sign_cache.clear → read_build_timestamp` is now machine-checkable via the `order: list[str]` recording side-effect pattern.
- Locked the distinct-notification-ID contract (Pitfall 7): `asp_parking_index_rebuild` (in-progress), `asp_parking_index_rebuild_success` (success), `asp_parking_index_rebuild_error` (failure).
- Confirmed RED state via two independent failure modes: collection-time `ModuleNotFoundError: No module named 'custom_components.asp_parking.index_io'` for Task 1; runtime `AttributeError: type object 'ASPParkingCoordinator' has no attribute 'async_request_rebuild' / '_async_do_rebuild'` for Task 2 (9 tests fail individually rather than being masked behind a single collection error).
- Verified zero regressions: 405 non-Phase-33 tests still pass with both new test files ignored.

## Task Commits

Each task was committed atomically on branch `worktree-agent-a92d90f194d12b394`:

1. **Task 1: RED tests for sync helpers in custom_components/asp_parking/index_io.py** — `8b2f218` (test)
2. **Task 2: RED tests for coordinator rebuild orchestration (IDX-02 lock + IDX-04 sequence)** — `4256622` (test)

_Note: This is a `type: tdd` plan executing only the RED phase — GREEN/REFACTOR are owned by Wave 2 plans 03 and 04. No `feat(...)` commits are expected in this plan._

## Files Created/Modified

- `tests/test_index_io.py` — 17 stdlib-only RED tests for the four sync helpers plus two module constants. Covers atomic swap (4 cases incl. prior-_bak cleanup and missing-tmp error), idempotent stale-artifact cleanup (3 cases), zip-slip refusal (3 cases incl. relative `../escape.txt` and absolute `../../../etc/escape.txt`), build_info.json parse (5 fault-tolerant cases incl. tz-awareness per Pitfall 6).
- `tests/test_coordinator_rebuild.py` — 9 RED tests for the two new async methods. Covers IDX-02 lock+flag gate (3 cases), `_async_do_rebuild` happy path (4 cases: flag flip, cache+index reset, last_rebuilt update, strict swap ordering), success notification (1 case: D-04 + Pitfall 7 distinct id), failure path (1 case: D-05 reassurance message + D-06 finally-block flag reset + Pitfall 7 distinct error id).

## Decisions Made

- **Future-method binding pattern (Task 2):** Tests use `_bind(stub, method_name)` which calls `getattr(ASPParkingCoordinator, method_name).__get__(stub, cls)` at test-call time, not module-load time. This keeps Task 2 collection green (so the 9 RED failures are individually visible in pytest output) while still producing the required `AttributeError` RED signal on missing methods.
- **Notification spy strategy:** Patch `sys.modules['homeassistant.components.persistent_notification']` rather than monkeypatching individual attributes inside `custom_components.asp_parking.coordinator`. This is import-style-agnostic — works whether the production code uses `from ... import async_create as pn_create` or `pn.async_create(...)`.
- **Ordering assertion approach:** Introduced `_RecordingDict(dict)` subclass to record `clear()` calls (Python forbids monkeypatching `dict.clear` directly — `'dict' object attribute 'clear' is read-only`). Pattern documented for future tests that need to record built-in method calls.
- **Zip-slip belt-and-braces:** Beyond `pytest.raises(ValueError)` and message inspection, the test also runs `list((base / '..').rglob('escape.txt'))` and asserts no file contains the `b'PWNED'` payload — would catch a production bug where `ValueError` is raised AFTER the malicious write occurred.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed `dict.clear` monkeypatch in swap-ordering test**

- **Found during:** Task 2 (initial pytest run)
- **Issue:** First implementation of `test_async_do_rebuild_swap_ordering` attempted to wrap `stub._sign_cache.clear` with a recording lambda via `stub._sign_cache.clear = _clear_with_record`. Python raises `AttributeError: 'dict' object attribute 'clear' is read-only` because built-in method slots are immutable on dict instances. This bug would have made the test ALWAYS fail (even after Wave 2 implements the production code), defeating its purpose as a RED test that should pass once the contract is met.
- **Fix:** Introduced a `_RecordingDict(dict)` subclass that overrides `clear()` to append `"sign_cache_clear"` to a shared `order` list before delegating to `super().clear()`. The stub's `_sign_cache` is instantiated as `_RecordingDict({...}, _order=order)`.
- **Files modified:** `tests/test_coordinator_rebuild.py`
- **Verification:** Re-ran `pytest tests/test_coordinator_rebuild.py --tb=line` — all 9 tests now fail uniformly with `AttributeError` on the missing coordinator methods (the intended RED signal), not on the `dict.clear` monkeypatch.
- **Committed in:** `4256622` (Task 2 commit — fix applied before commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - test-infrastructure bug)
**Impact on plan:** Test would have been broken-by-design; fix preserves the RED→GREEN contract.

## Issues Encountered

- **Worktree absolute-path drift (recovered before commit):** First Write of `tests/test_index_io.py` used an absolute path computed from a stale `pwd` context, placing the file in the main repo (`/home/pascal/.../GPS2ASP-Resolver/tests/`) instead of the worktree (`/home/pascal/.../GPS2ASP-Resolver/.claude/worktrees/agent-a92d90f194d12b394/tests/`). Caught by `pytest` reporting "no tests collected" when run against the worktree path. Removed the stray file from the main repo via `rm` and re-Wrote to the correct worktree-anchored absolute path. No commit, no merge contamination. The execute-plan worktree-path-safety reference (#3099) flagged this exact failure mode; future Write calls in this session used worktree-rooted paths derived from `git rev-parse --show-toplevel`.
- **Stale `pytest` shebang:** The `.venv/bin/pytest` script has a hardcoded shebang pointing to a typo'd path (`GSP2ASP-Resolver` vs `GPS2ASP-Resolver`). Worked around by invoking via `.venv/bin/python -m pytest` everywhere — pre-existing project issue, out of scope for this plan.

## RED-State Evidence

**Task 1 (`tests/test_index_io.py`) — collection-time failure:**
```
ModuleNotFoundError: No module named 'custom_components.asp_parking.index_io'
```
Command: `pytest tests/test_index_io.py --collect-only`
→ 1 error, 0 tests collected. Production module `custom_components/asp_parking/index_io.py` does not exist; Wave 2 plan 03 must create it.

**Task 2 (`tests/test_coordinator_rebuild.py`) — runtime failure (9 tests collected, 9 fail):**
```
AttributeError: type object 'ASPParkingCoordinator' has no attribute 'async_request_rebuild'
AttributeError: type object 'ASPParkingCoordinator' has no attribute '_async_do_rebuild'
```
Command: `pytest tests/test_coordinator_rebuild.py --tb=line`
→ 9 failed, 0 passed. Wave 2 plan 03 must add `async_request_rebuild` and `_async_do_rebuild` to `custom_components/asp_parking/coordinator.py`.

**Regression check:** `pytest -m "not integration and not ha_integration" --ignore=tests/test_index_io.py --ignore=tests/test_coordinator_rebuild.py --ignore=tests/test_index_rebuild_button.py --ignore=tests/test_index_rebuilding_binary_sensor.py --ignore=tests/test_index_last_rebuilt_sensor.py`
→ 405 passed, 0 failed, 136 deselected. No regressions in pre-existing suite.

## Self-Check: PASSED

**Files exist (worktree path):**
- FOUND: `tests/test_index_io.py` (329 lines, 17 tests)
- FOUND: `tests/test_coordinator_rebuild.py` (489 lines, 9 tests)

**Commits exist:**
- FOUND: `8b2f218` (Task 1)
- FOUND: `4256622` (Task 2)

**Acceptance criteria (Task 1 substrings):**
- FOUND: `_sync_atomic_swap`, `_sync_cleanup_stale`, `_sync_extract_zip`, `_sync_read_build_timestamp`
- FOUND: `INDEX_DIR`, `INDEX_FILES`, `path traversal`, `tzinfo`, `tmp_path`

**Acceptance criteria (Task 2 substrings):**
- FOUND: `async_request_rebuild`, `_async_do_rebuild`, `_is_rebuilding`, `_rebuild_lock`, `_last_rebuilt`
- FOUND: `asp_parking_index_rebuild_error`, `asp_parking_index_rebuild_success`
- FOUND: `Your existing index is still active`
- FOUND: `spatial_index_reset`, `SpatialIndex.reset`, `sign_cache`
- FOUND: ordering assertion (`order[0:3] == ["cleanup_stale", "download_and_extract", "atomic_swap"]` — equivalent enforcement)

**Verification commands (per-plan):**
- PASSED: `pytest tests/test_index_io.py --collect-only` → ModuleNotFoundError on `index_io`
- PASSED: `pytest tests/test_coordinator_rebuild.py -x --tb=short` → AttributeError on `async_request_rebuild`
- PASSED: Full non-Phase-33 suite → 405 passed, 0 failed

## Next Phase Readiness

- **Wave 2 plan 03 (Production sync helpers + coordinator methods):** All 26 RED tests serve as the GREEN-gate contract. Plan 03 must:
  1. Create `custom_components/asp_parking/index_io.py` with the four sync helpers + two constants — satisfies `test_index_io.py` (17 tests).
  2. Add `async_request_rebuild`, `_async_do_rebuild`, and the four new fields (`_is_rebuilding`, `_rebuild_task`, `_rebuild_lock`, `_last_rebuilt`) to `ASPParkingCoordinator.__init__` — satisfies `test_coordinator_rebuild.py` (9 tests).
  3. Preserve the strict ordering invariant: `cleanup_stale → download → atomic_swap → SpatialIndex.reset → _sign_cache.clear → read_build_timestamp` (test asserts via `order` list).
  4. Use distinct notification IDs per Pitfall 7: `asp_parking_index_rebuild` / `_success` / `_error`.
  5. Reset `_is_rebuilding` in a `finally` block (D-06) and emit failure message containing `"Your existing index is still active"` (D-05).
- **Wave 2 plan 04 (Entity plumbing):** Button/binary_sensor/sensor entities still pending — RED tests for those entities live in separate files (`test_index_rebuild_button.py`, `test_index_rebuilding_binary_sensor.py`, `test_index_last_rebuilt_sensor.py`) created by Phase 33 Plan 01 task scope or future plan.
- **No blockers, no concerns.** The RED contract is locked; GREEN is purely additive.

---

## TDD Gate Compliance

This plan is `type: tdd` and ships ONLY the RED phase. Per the TDD gate sequence:

1. **RED gate:** PASSED — two `test(33-02): ...` commits exist (`8b2f218`, `4256622`).
2. **GREEN gate:** DEFERRED to Wave 2 plan 03 (intentional — this plan's scope is exclusively RED).
3. **REFACTOR gate:** DEFERRED to post-GREEN.

The plan frontmatter (`type: tdd`, `must_haves.truths`) and `<success_criteria>` explicitly scope this plan to RED-only ("RED tests file ... exists with at least N tests", "RED state proves Wave 2 has work to do"). No GREEN expected within this plan boundary.

---
*Phase: 33-spatial-index-rebuild-button*
*Plan: 02*
*Completed: 2026-05-14*
