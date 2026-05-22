---
phase: 38-dual-path-index-rebuild-stale-detection
plan: 01
subsystem: infra
tags: [spatial-index, cscl, soda, httpx, shapely, rtree, pyproj, zstandard, respx, tdd]

# Dependency graph
requires:
  - phase: 33-spatial-index-rebuild-button
    provides: index_io sync helpers (atomic swap, extract, cleanup, build_timestamp)
provides:
  - _sync_build_from_source(index_dir: Path) -> None — from-source CSCL rebuild helper
  - D-04 source field patch in _sync_download_and_extract (stamps source=github_release)
  - D-05 silent skip for missing/malformed build_info.json post-extract
  - 12 Phase 38 constants in const.py (GITHUB_INDEX_RELEASE_TAG, CSCL_GEOJSON_URL, MAX_CSCL_PAGES, …)
  - CSCL + SODA test fixtures (UPPERCASE keys, MultiLineString, filter-exclusion)
  - 10 respx-mocked unit tests for the new helper
  - 2 D-04/D-05 patch tests appended to test_index_io.py
affects: [38-02-coordinator-path-selection, 38-03-stale-detection, future-ha-rebuild-flow]

# Tech tracking
tech-stack:
  added: []   # No new dependencies — pyproj/shapely/rtree/zstandard already vetted in Phase 33; respx 0.22.0 already present
  patterns:
    - "Pure-shapely + pyproj batch reproject (geopandas-free) for HA-compatible builds"
    - "Module-level pyproj Transformer (mirrors src/gps2asp/resolver/converter.py:_transformer pattern)"
    - "X-App-Token forwarding via os.environ.get + dict-merge headers (mirrors signs/client.py)"
    - "respx-mocked sync httpx.Client tests with side_effect=[Response, …] for pagination"
    - "D-04/D-05 source-field stamping pattern: post-extract opportunistic patch with silent skip"

key-files:
  created:
    - tests/test_index_io_build_from_source.py
    - tests/fixtures/cscl_geojson_sample.json
    - tests/fixtures/soda_asp_signs_sample.json
  modified:
    - custom_components/asp_parking/const.py
    - custom_components/asp_parking/index_io.py
    - tests/test_index_io.py

key-decisions:
  - "GITHUB_INDEX_RELEASE_TAG = 'index-v1' (deviation acknowledgement from ROADMAP/SPEC text that referenced /releases/latest); index.zip lives only on tag index-v1, /releases/latest returns v3.0.0 with zero assets"
  - "CSCL HTTP errors propagate (fail-hard); SODA HTTP errors are logged + swallowed (fail-soft) — matches scripts/build_index.py:633-642 semantics"
  - "MAX_CSCL_PAGES = 30 DoS guard raises RuntimeError when pagination runs away; verified by test_pagination_cap_raises"
  - "All file writes go ONLY to <index_dir>_tmp; caller (Plan 02 coordinator) owns the atomic swap (V12 T-38-01-03)"
  - "Module-level _TRANSFORMER_4326_TO_2263 instead of per-call construction (thread-safe; pyproj convention)"
  - "Filter rw_type BEFORE TRAFDIR=='NV' exclusion (Pitfall 9 parity with scripts/build_index.py)"
  - "rtree idx.insert(pid, bbox) in a loop with close() in finally — NEVER the generator constructor (rtree bug #159)"
  - "build_info.json schema: build_timestamp, source, filtered_count, build_duration_seconds, graph_segment_count (extends Phase 33 schema with source provenance)"

patterns-established:
  - "From-source rebuild parity: _sync_build_from_source mirrors scripts/build_index.py pipeline but drops the geopandas dependency entirely (V12-compatible)"
  - "Source provenance pattern: build_info.json['source'] in {'cscl_api', 'github_release'} lets the coordinator distinguish the two rebuild paths"
  - "respx pagination fixture: side_effect=[Response(200, json=fixture), Response(200, json={features:[]})] terminates after one full page"

requirements-completed: [IDX-06]

# Metrics
duration: ~28min
completed: 2026-05-22
---

# Phase 38 Plan 01: From-source CSCL rebuild helper Summary

**Pure-shapely `_sync_build_from_source(index_dir)` that builds the 5-file spatial index directly from the NYC CSCL + SODA APIs, with `source=cscl_api` provenance, MAX_CSCL_PAGES DoS guard, and SODA fail-soft semantics — no geopandas, no manifest change.**

## Performance

- **Duration:** ~28 min
- **Started:** 2026-05-22T17:06:50Z
- **Completed:** 2026-05-22T17:34:37Z
- **Tasks:** 3 (RED, GREEN, regression gate)
- **Files modified:** 6 (3 created, 3 edited)

## Accomplishments
- Implemented `_sync_build_from_source(index_dir: Path) -> None` writing 5 files (segments.idx/dat/json, graph.json.zst, build_info.json) to `<index_dir>_tmp` only, with full parity to scripts/build_index.py minus the geopandas dependency.
- Added D-04 + D-05 source-field patch to `_sync_download_and_extract` so the release-zip path stamps `source: "github_release"` while the CSCL-API path stamps `source: "cscl_api"` — enabling Plan 02 coordinator to distinguish provenance.
- Added 12 Phase 38 constants in `const.py` consumed by this plan + Plans 02 / 03 (GITHUB_INDEX_RELEASE_TAG=`index-v1`, CSCL_GEOJSON_URL, SODA_PARKING_SIGNS_URL, MAX_CSCL_PAGES, STALE_INDEX_DAYS, REMOTE_FRESH_DAYS, BUTTON_DOUBLE_PRESS_WINDOW_HOURS, STALE_CHECK_INTERVAL_HOURS, CSCL_BATCH_SIZE, SIGNS_BATCH_SIZE, VEHICULAR_RW_TYPES, GITHUB_RELEASES_API_BASE).
- 12 new tests pass (10 in `test_index_io_build_from_source.py`, 2 in `test_index_io.py`); full offline suite still green at 641 passing.
- `manifest.json` byte-identical (no new dependencies — all imports already vetted in Phase 33).

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Constants + fixtures + failing tests** — `eef8bf5` (test)
2. **Task 2 (GREEN): Implement _sync_build_from_source + D-04 patch** — `70b1514` (feat)
3. **Task 3 (Regression Gate): Full offline pytest sweep** — no commit (verification-only, no file changes)

**Plan metadata:** [committed by orchestrator after worktree merge]

_Note: TDD plan; commits follow RED → GREEN sequence._

## Files Created/Modified

### Created
- `tests/test_index_io_build_from_source.py` (239 lines) — 10 respx-mocked unit tests for `_sync_build_from_source`
- `tests/fixtures/cscl_geojson_sample.json` — 6 CSCL Features (incl. RW_TYPE=9 filter-exclusion, TRAFDIR='NV' exclusion, MultiLineString variants) with UPPERCASE property keys
- `tests/fixtures/soda_asp_signs_sample.json` — 4 SODA ASP sign rows matching the CSCL fixture's street names

### Modified
- `custom_components/asp_parking/const.py` (+26 lines) — 12 Phase 38 constants block after the INDEX_DOWNLOAD_URL block
- `custom_components/asp_parking/index_io.py` (+718 lines) — `_sync_build_from_source` public helper + 9 private helpers (`_build_headers`, `_normalize_street_name`, `_sync_fetch_cscl_features`, `_sync_filter_and_reproject`, `_build_node_lookup`, `_find_cross_street`, `_compute_cross_streets`, `_build_street_adjacency`, `_build_intersection_index`, `_bfs_between`, `_propagate_asp_to_interior_blocks`, `_sync_fetch_asp_signs`, `_check_has_asp`, `_filter_2hop_neighborhood`, `_build_rtree_and_metadata`, `_write_graph_zst`) + module-level `_TRANSFORMER_4326_TO_2263` + D-04/D-05 patch inside `_sync_download_and_extract`
- `tests/test_index_io.py` (+92 lines) — two new tests `test_download_and_extract_patches_source_github_release` and `test_download_and_extract_silent_skip_when_build_info_missing`

## Decisions Made

- **`GITHUB_INDEX_RELEASE_TAG = "index-v1"` (acknowledged ROADMAP deviation).** ROADMAP / SPEC text referenced `GET /releases/latest`, but a research probe documented in `38-RESEARCH.md` confirmed `/releases/latest` returns v3.0.0 with zero release assets while the actual `index.zip` lives on the tag `index-v1`. Hard-coding the tag avoids a guaranteed-broken release-API lookup. Plan 02 will consume this constant via `GET /repos/.../releases/tags/{GITHUB_INDEX_RELEASE_TAG}`.
- **SODA fail-soft / CSCL fail-hard.** SODA being unavailable does not invalidate a CSCL rebuild — segments simply get `has_asp_left=has_asp_right=False`. CSCL being unavailable does invalidate the rebuild (there's nothing to swap in). Matches `scripts/build_index.py` semantics so the two builders remain interchangeable.
- **`MAX_CSCL_PAGES = 30`.** With `CSCL_BATCH_SIZE = 10000`, that caps the rebuild at 300k features (current full dataset is ~160k). Anything past 30 pages signals a runaway loop (e.g., the SODA API stopped honouring `$offset`) and we raise `RuntimeError` to surface it.
- **Helper factoring.** Instead of one giant function, the implementation is broken into 9 private helpers prefixed `_sync_` (for HTTP-touching code that the executor must dispatch) and unprefixed (for pure data transforms). This keeps the public signature minimal (just `index_dir`) while letting Plan 02 mock individual stages if needed.
- **Module-level `_TRANSFORMER_4326_TO_2263`.** pyproj `Transformer` objects are thread-safe and expensive to construct (~5ms each); creating one at module load avoids ~800ms across the 160k-segment reproject loop. Pattern mirrors `src/gps2asp/resolver/converter.py::_transformer`.
- **D-05 silent-skip semantics for missing `build_info.json`.** The release zip historically always contains `build_info.json`; the silent-skip exists to guard against malformed zips without raising into the HA reload path. Verified by `test_download_and_extract_silent_skip_when_build_info_missing`.

## Deviations from Plan

None — plan executed exactly as written. The `GITHUB_INDEX_RELEASE_TAG = "index-v1"` choice was explicitly pre-declared in the plan's `<objective>` Notes section and is therefore part of the plan, not a deviation.

The two D-04 patch tests added to `test_index_io.py` — one of them (`silent_skip`) was already passing pre-implementation (the existing code did not write `build_info.json` when none was extracted, so the negative assertion held by accident). This is a characterization test that locks the behaviour in for the future; it is RED in spirit (proves the desired behaviour) even though it is GREEN at the file level. The companion test (`patches_source_github_release`) was strictly RED → GREEN.

## Issues Encountered

None. Test infrastructure (`respx`, `zstandard`, `shapely`, `pyproj`, `rtree`, `numpy`) was already installed in the project `.venv`; no install step required.

## User Setup Required

None — no external service configuration required. The `NYC_OPEN_DATA_APP_TOKEN` env var is optional and falls back cleanly to anonymous request quotas if unset.

## Next Phase Readiness

- **Plan 38-02** can import `_sync_build_from_source` from `custom_components.asp_parking.index_io` and dispatch it via `hass.async_add_executor_job`. The function signature is byte-exact to the spec: `(index_dir: Path) -> None`.
- **Plan 38-02** can also use the 11 supporting constants (`GITHUB_INDEX_RELEASE_TAG`, `CSCL_GEOJSON_URL`, `SODA_PARKING_SIGNS_URL`, `STALE_INDEX_DAYS`, `REMOTE_FRESH_DAYS`, `BUTTON_DOUBLE_PRESS_WINDOW_HOURS`, `STALE_CHECK_INTERVAL_HOURS`, `MAX_CSCL_PAGES`, `CSCL_BATCH_SIZE`, `SIGNS_BATCH_SIZE`, `VEHICULAR_RW_TYPES`, `GITHUB_RELEASES_API_BASE`) from `const.py`.
- **`source` field convention** is now live in both rebuild paths: any caller reading a freshly built `build_info.json` can disambiguate via `bi.get("source")` ∈ `{"cscl_api", "github_release"}`.

## Self-Check: PASSED

- `tests/test_index_io_build_from_source.py` exists ✓
- `tests/fixtures/cscl_geojson_sample.json` exists ✓
- `tests/fixtures/soda_asp_signs_sample.json` exists ✓
- `_sync_build_from_source` importable from `custom_components.asp_parking.index_io` ✓
- Commit `eef8bf5` (Task 1 RED) found in `git log` ✓
- Commit `70b1514` (Task 2 GREEN) found in `git log` ✓
- 12 + 10 new tests passing under `tests/test_index_io.py` and `tests/test_index_io_build_from_source.py` ✓
- 641 offline tests passing (`-m "not integration and not ha_integration"`) ✓
- `manifest.json` byte-identical ✓
- No `import geopandas` in `custom_components/asp_parking/` ✓

---
*Phase: 38-dual-path-index-rebuild-stale-detection*
*Plan: 38-01*
*Completed: 2026-05-22*
