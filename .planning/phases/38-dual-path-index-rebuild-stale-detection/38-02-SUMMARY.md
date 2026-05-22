---
phase: 38-dual-path-index-rebuild-stale-detection
plan: 02
subsystem: infra
tags: [home-assistant, httpx, github-releases-api, asyncio, respx, enum, tdd]

# Dependency graph
requires:
  - phase: 38-dual-path-index-rebuild-stale-detection
    provides: "Plan 01: _sync_build_from_source executor helper; D-04 build_info.json source patching; const.py constants (GITHUB_RELEASES_API_BASE, GITHUB_INDEX_RELEASE_TAG, REMOTE_FRESH_DAYS, BUTTON_DOUBLE_PRESS_WINDOW_HOURS)"
  - phase: 33-spatial-index-rebuild-button
    provides: "async_request_rebuild / _async_do_rebuild lifecycle; _is_rebuilding + _rebuild_lock guards; rebuild notification IDs"
provides:
  - "RebuildPath enum (DOWNLOAD, FROM_SOURCE) at module scope in coordinator.py"
  - "ASPParkingCoordinator._async_decide_rebuild_path(triggered_by) -> (RebuildPath, reason_str)"
  - "ASPParkingCoordinator._fetch_remote_asset_age_days() -> float | None (10-min cached, created_at-based)"
  - "triggered_by='button'|'stale_check' keyword on async_request_rebuild and _async_do_rebuild"
  - "Routing inside _async_do_rebuild: _sync_download_and_extract (DOWNLOAD) OR _sync_build_from_source (FROM_SOURCE)"
  - "INFO log line 'asp_parking: index rebuild path=<...> reason=<...>' for every rebuild dispatch"
  - "Backwards-compat default triggered_by='button' so button.py is byte-identical"
affects:
  - "Plan 03 (stale detection + Store hydration) — consumes _async_decide_rebuild_path, _last_button_press, _last_stale_check, _index_stale_store; calls async_request_rebuild(triggered_by='stale_check')"

# Tech tracking
tech-stack:
  added:
    - "respx 0.22.0 (test-only) for httpx mocking"
    - "stdlib enum.Enum used to express rebuild path strategy"
  patterns:
    - "In-memory TTL cache tuple[datetime, value] to absorb upstream rate limits"
    - "Lazy persistent_notification import + distinct notification_id per lifecycle phase"

key-files:
  created:
    - "tests/test_coordinator_path_selection.py (552 lines, 19 tests; respx httpx mocking)"
  modified:
    - "custom_components/asp_parking/coordinator.py (+~150 LOC: imports + RebuildPath enum + __init__ attrs + smart routing + helpers)"
    - "tests/test_coordinator_rebuild.py (Phase 33 stub extended with Phase 38 attrs)"
    - "tests/test_coordinator_integration.py (cross-cutting stub extended with Phase 38 attrs)"

key-decisions:
  - "Use GET /repos/.../releases/tags/index-v1 (NOT /releases/latest) — locked deviation; /releases/latest currently returns v3.0.0 with ZERO assets"
  - "Compute remote asset age from created_at, not updated_at (Pitfall 3): updated_at is bumped by metadata edits and misrepresents the actual rebuild age"
  - "10-minute in-memory TTL cache per coordinator instance to absorb the 60-req/hour anonymous GitHub Releases API rate limit"
  - "Decision boundary semantics: age_days < REMOTE_FRESH_DAYS => DOWNLOAD; >= => FROM_SOURCE (strict-less; exactly 30 days falls through to FROM_SOURCE)"
  - "D-03: triggered_by='stale_check' SKIPS the 24h double-press override entirely — that rule is button-only"
  - "_last_button_press is written to the index stale store BEFORE the rebuild spawns (SPEC 1.6) so a second press during a running rebuild still sees a recent press"
  - "Store hydration / instantiation is owned by Plan 03; this plan writes through defensively if present, otherwise the write is a no-op"

patterns-established:
  - "Pattern: in-memory tuple[datetime, value] cache with dt_util.utcnow() TTL gate — usable for any rate-limited upstream API"
  - "Pattern: Enum-based dispatch tuple from helper -> if/else branch in caller (RebuildPath enum + _async_decide_rebuild_path -> _async_do_rebuild branch)"
  - "Pattern: SimpleNamespace + _bind + respx httpx mocking for coordinator helpers with external HTTP dependencies"

requirements-completed:
  - IDX-05

# Metrics
duration: ~30min
completed: 2026-05-22
---

# Phase 38 Plan 02: Smart Path Selection (IDX-05) Summary

**Dual-path rebuild router: RebuildPath enum + GitHub Releases API age check (tag index-v1, 10-min cache) + 24h double-press override + triggered_by parameter; all wired through the existing Phase 33 button without adding a new entity.**

## Performance

- **Duration:** ~30 min
- **Started:** 2026-05-22T17:18:00Z (approx)
- **Completed:** 2026-05-22T17:49:17Z
- **Tasks:** 3 (RED test scaffold, GREEN implementation, regression gate)
- **Files modified:** 4 (coordinator.py + 3 test files)

## Accomplishments

- `RebuildPath` enum (DOWNLOAD / FROM_SOURCE) added at module scope so callers route to the right executor strategy.
- `_async_decide_rebuild_path(triggered_by)` returns `(RebuildPath, reason)` covering the full IDX-05 SPEC matrix: `remote_fresh`, `remote_stale`, `double_press`, `github_api_failed`.
- `_fetch_remote_asset_age_days()` hits `GET /repos/Pascal-ZeGerman/GPS2ASP-Resolver/releases/tags/index-v1` (the locked deviation), reads `created_at`, and caches the result for 10 minutes.
- `triggered_by` keyword parameter (`"button"` default | `"stale_check"`) added to `async_request_rebuild` and `_async_do_rebuild` — button.py is byte-identical because the default preserves the existing call shape.
- `_async_do_rebuild` now logs the decision at INFO level (`"asp_parking: index rebuild path=<...> reason=<...>"`) and routes to `_sync_download_and_extract` OR `_sync_build_from_source`; on success it also dismisses any `asp_parking_index_stale` notification.
- 19 new TDD unit tests in `tests/test_coordinator_path_selection.py` (RED → GREEN cycle); full offline pytest suite stays green (660 passed).

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Failing path-decision tests** — `3aa0177` (test)
2. **Task 2 (GREEN): RebuildPath enum + smart routing + GitHub API helper** — `7b2b1b6` (feat)
3. **Task 3 (REGRESSION): Regression gate + Plan 03 handoff** — `85bb248` (chore)

## Files Created/Modified

- `tests/test_coordinator_path_selection.py` — NEW. 19 unit tests (SimpleNamespace + `_bind` + respx) exercising the full IDX-05 matrix, GitHub API URL/cache/`created_at` guards, `triggered_by` semantics, and `_async_do_rebuild` routing/log assertions.
- `custom_components/asp_parking/coordinator.py` — Imports (`enum.Enum`, `datetime.timezone`, `httpx`, new const symbols, `_sync_build_from_source`); `RebuildPath` enum; four new `__init__` attributes (`_index_stale_store`, `_last_button_press`, `_last_stale_check`, `_remote_age_cache`); `triggered_by` parameter on `async_request_rebuild` and `_async_do_rebuild`; INFO log + path routing in `_async_do_rebuild`; success path dismisses `asp_parking_index_stale`; new `_async_decide_rebuild_path` and `_fetch_remote_asset_age_days` helpers.
- `tests/test_coordinator_rebuild.py` — Extended Phase 33 stub `_make_coord_stub` with Phase 38 attributes (`_index_stale_store=None`, `_last_button_press=None`, `_last_stale_check=None`, `_remote_age_cache=None`, default `_async_decide_rebuild_path=AsyncMock(return_value=(RebuildPath.DOWNLOAD, "remote_fresh"))`) so the 15 existing Phase 33 tests pass against the updated `_async_do_rebuild`.
- `tests/test_coordinator_integration.py` — Same extension to the cross-cutting CalDAV-vs-rebuild integration stub so `test_rebuild_does_not_wait_for_caldav_lock` still passes.

## Decisions Made

See `key-decisions` in frontmatter; the most consequential ones:

- **GitHub Releases tag pinning (deviation):** `GET /releases/tags/index-v1` — the ROADMAP wording (`/releases/latest`) is wrong against current repo state. Locked in `const.GITHUB_INDEX_RELEASE_TAG` + asserted by `test_github_api_uses_tag_v1_not_latest_url`.
- **`created_at` over `updated_at`:** Pitfall 3. Asserted by `test_remote_age_uses_created_at_not_updated_at` (52d vs 22d sentinel difference).
- **10-minute cache TTL:** Asserted by paired tests `test_remote_age_cache_hits_within_10_minutes` (route called once across two helper invocations) and `test_remote_age_cache_expires_after_10_minutes` (pre-seeded 11-min-old cache triggers refetch).
- **Strict `<` boundary:** Exactly 30 days falls through to FROM_SOURCE (`test_press_remote_exactly_30_days_uses_from_source`).
- **Store ownership boundary:** This plan declares `_index_stale_store` in `__init__` but does NOT initialise it (Plan 03 owns the `Store(hass, ..., "asp_parking_index_stale", 1)` instantiation and load). Write-through is guarded by `if self._index_stale_store is not None`; today this is a no-op for all real coordinator instances, but tests can supply an `AsyncMock` Store to exercise the write path.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Extended Phase 33 + integration test stubs to provide Phase 38 attributes**
- **Found during:** Task 2 verification — running `tests/test_coordinator_rebuild.py` after the coordinator change produced `AttributeError: 'types.SimpleNamespace' object has no attribute '_async_decide_rebuild_path'` (and similar for `_index_stale_store` in `test_coordinator_integration.py`).
- **Issue:** Phase 33's `_make_coord_stub` (and the cross-cutting integration `_make_coord_stub`) hard-coded only Phase 33 attributes. The new `_async_do_rebuild` body needs `_async_decide_rebuild_path`, and the new `async_request_rebuild` body needs `_index_stale_store` / `_last_button_press`.
- **Fix:** Extended both stubs to include the new attributes plus a default `_async_decide_rebuild_path = AsyncMock(return_value=(RebuildPath.DOWNLOAD, "remote_fresh"))` so the existing tests continue to exercise the (now-default) DOWNLOAD path with no semantic change to their assertions.
- **Files modified:** `tests/test_coordinator_rebuild.py`, `tests/test_coordinator_integration.py`
- **Verification:** Both test files pass; full offline pytest suite stays at 660 passed (0 regressions).
- **Committed in:** Task 2 commit (`7b2b1b6`) covered `tests/test_coordinator_rebuild.py`; Task 3 commit (`85bb248`) covered `tests/test_coordinator_integration.py`.

**2. [Rule 3 - Blocking] Reworded one docstring sentence to satisfy literal `grep -F "releases/latest"` acceptance criterion**
- **Found during:** Task 2 acceptance verification — the strict criterion required ZERO hits for `releases/latest` anywhere in `coordinator.py`, but the docstring for `_fetch_remote_asset_age_days` included the substring while explaining why we DON'T use it.
- **Fix:** Reworded the docstring to "The 'latest release' GitHub endpoint" — preserves the rationale, removes the substring.
- **Files modified:** `custom_components/asp_parking/coordinator.py`
- **Verification:** `grep -F "releases/latest" custom_components/asp_parking/coordinator.py` now returns 0.
- **Committed in:** Task 2 commit (`7b2b1b6`).

---

**Total deviations:** 2 auto-fixed (1 backwards-compat bug, 1 lexical literal-match)
**Impact on plan:** Both fixes preserve plan intent. The stub extensions are mechanical type-system consequences of the new attributes; the docstring rewording strengthens the acceptance guard.

## Issues Encountered

- **`pytest-asyncio` auto mode noise:** A small handful of `RuntimeWarning: coroutine '_async_do_rebuild' was never awaited` warnings appear in tests that intentionally inspect the spawned background task without awaiting it. Pre-existing in Phase 33; not amplified by this plan. No action required.

## User Setup Required

None — no external service configuration. The GitHub Releases API call is unauthenticated and inherits the 60-req/hour anonymous quota (absorbed by the 10-min cache).

## Next Phase Readiness

- Plan 03 (stale detection + Store hydration) can now consume:
  - `RebuildPath` and `_async_decide_rebuild_path` for the stale-check rebuild trigger
  - `_index_stale_store`, `_last_button_press`, `_last_stale_check` for Store load/save round-trip
  - `async_request_rebuild(triggered_by="stale_check")` to spawn rebuilds without writing the 24h press anchor
- `_async_decide_rebuild_path` and `_fetch_remote_asset_age_days` already verified by 19 unit tests; Plan 03 inherits a stable surface.
- Phase 33 and CalDAV cross-cutting tests still GREEN — no spillover risk into Plan 03.

## Plan 03 Handoff Notes

- `_last_button_press`, `_last_stale_check`, `_index_stale_store` are **declared** in `__init__` here with `None` defaults. **Population** is Plan 03's responsibility (Store instantiation in `async_start`, hydrate from `async_load`, persist via `async_save`).
- Today's tests pass with `_index_stale_store = None` (the write-through is a no-op). Plan 03 should add the Store init + `async_load` block immediately after `_last_rebuilt = await self.hass.async_add_executor_job(_sync_read_build_timestamp, INDEX_DIR)` in `async_start`.
- The GitHub API URL is reachable via `f"{GITHUB_RELEASES_API_BASE}/releases/tags/{GITHUB_INDEX_RELEASE_TAG}"`. Plan 03 does NOT need to touch this — its stale-check helper just calls `async_request_rebuild(triggered_by="stale_check")` and the existing decision matrix handles routing.

## Self-Check: PASSED

All files exist; all commit hashes exist on the branch.

- FOUND: `tests/test_coordinator_path_selection.py`
- FOUND: `.planning/phases/38-dual-path-index-rebuild-stale-detection/38-02-SUMMARY.md`
- FOUND (modified): `custom_components/asp_parking/coordinator.py`
- FOUND (modified): `tests/test_coordinator_rebuild.py`
- FOUND (modified): `tests/test_coordinator_integration.py`
- FOUND: commit `3aa0177` (Task 1 RED)
- FOUND: commit `7b2b1b6` (Task 2 GREEN)
- FOUND: commit `85bb248` (Task 3 regression gate)

---
*Phase: 38-dual-path-index-rebuild-stale-detection*
*Completed: 2026-05-22*
