# Roadmap: GPS2ASP Resolver

## Milestones

- ✅ **v1.0 MVP** — Phases 1-4 (shipped 2026-02-23)
- ✅ **v1.1 Bug Fixes** — Phases 5-11 (shipped 2026-03-07)
- ✅ **v2.0 Full Borough Coverage** — Phases 12-18 (shipped 2026-03-30)
- ✅ **v3.0 Suspension Handling** — Phases 19-24 (shipped 2026-04-30)
- ✅ **v3.1 Polish & UX** — Phases 25-30 (shipped 2026-05-03)
- ✅ **v3.2 UX Improvements and Monthly Updates** — Phases 31-34 (shipped 2026-05-19)
- 🚧 **v3.3 UX Improvements** — Phases 35-38 (in progress, started 2026-05-19)

## Phases

<details>
<summary>✅ v1.0 through v3.0 (Phases 1-24) — See MILESTONES.md for details</summary>

Phases 1-24 delivered: GPS-to-street resolution, SODA sign retrieval, schedule parsing,
HA integration, confidence scoring, public API, BFS graph propagation, SODA level threading,
compressed graph, borough coverage fixtures, ASP suspension calendar, and debug options flow.

</details>

<details>
<summary>✅ v3.1 Polish & UX (Phases 25-30) — Shipped 2026-05-03</summary>

**Milestone Goal:** Harden the HA integration for HACS end users — proper selectors, diagnostics, consistent UI copy, and a one-tap debug toggle.

- [~] **Phase 25: Notification UX** — EntitySelector notify dropdown + lead-time NumberSelector (code complete 2026-04-30; live UI verification deferred)
- [x] **Phase 26: Parking Area Config** — Options flow for home parking area center + radius (completed 2026-05-01)
- [x] **Phase 27: Diagnostics** — HA diagnostics endpoint, ImportError repair issue, 4 diagnostic sensor entities (completed 2026-05-02)
- [x] **Phase 28: UX Copy & Strings** — Sync strings.json byte-identical to translations/en.json; fix vehicle/user step mismatch (completed 2026-05-02)
- [x] **Phase 29: Debug Switch & Logging** — switch.asp_parking_debug_mode entity; debug step scoped to overrides-only (completed 2026-05-03)
- [x] **Phase 30: Richer Debug Sensor Pipeline Attributes** — borocode, distance_ft, street_width_ft, segment_id end-to-end (completed 2026-05-03)

</details>

<details>
<summary>✅ v3.2 UX Improvements and Monthly Updates (Phases 31-34) — Shipped 2026-05-19</summary>

**Milestone Goal:** Make the integration more informative and self-maintaining — polish how parking times display, enable on-demand index refresh, and add CalDAV calendar sync for passive awareness.

- [x] **Phase 31: CI Guard & strings.json Sync** — vendor-guard.yml + sync_vendored.py; strings.json byte-identical to translations/en.json (completed 2026-05-11)
- [x] **Phase 32: Sensor Display Format** — Three-tier date-aware next-move format; HA-local timezone Today gate; now_ha_local() helper (completed 2026-05-13)
- [x] **Phase 33: Spatial Index Rebuild Button** — button + binary_sensor + sensor entities; index_io.py with atomic swap, zip-slip guard, asyncio.Lock (completed 2026-05-15)
- [x] **Phase 34: CalDAV Calendar Integration** — caldav_sync.py async glue; SHA-256 UID; coordinator write/delete/remove lifecycle; credentials redacted from diagnostics (completed 2026-05-17)

</details>

### 🚧 v3.3 UX Improvements (Phases 35-38) — In Progress

**Milestone Goal:** Polish user-facing UX — fix the visible CalDAV tooltip bug, surface a human-readable street side label, show step progress through the config flow, and add a true rebuild-from-source path with staleness-aware auto-redownload for the spatial index.

- [x] **Phase 35: CalDAV Tooltip Fix (formatjs ICU escape)** — ICU single-quote-wrap all curly-brace placeholders in CalDAV title-template tooltip/error strings (strings-only) — shipped 2026-05-19; human UAT pending live HA deploy
- [x] **Phase 35.1: Bug Sweep — Vendored Copy Sync + Silent Failure Fixes** (INSERTED) — Sync `custom_components/gps2asp/` vendored copy with `src/gps2asp/` (critical: `suspended_dates` AttributeError silently stops all schedule updates after startup); fix 33 additional silent, correctness, and performance bugs surfaced by 50-UC behavioral analysis
- [x] **Phase 36: Cardinal Direction Label** — Additive `side_label` attribute ("North side", etc.) on resolved-street + next-move sensors; raw `side_of_street` letter preserved — shipped 2026-05-21 (commits bac5556 + bec1ed1)
- [x] **Phase 37: Config Flow Step Tracker** — "Step N of 3" indicator added to the 3-step config flow titles (config flow only; options flow excluded) (completed 2026-05-22)
- [ ] **Phase 38: Dual-Path Index Rebuild + Stale Detection** — From-source CSCL rebuild path (httpx/shapely/rtree, no geopandas); staleness detection (>60 days) auto-triggers fast-path redownload

## Phase Details

### Phase 35: CalDAV Tooltip Fix (formatjs ICU escape)

**Goal**: Users see the literal placeholder text in the CalDAV title-template tooltip instead of a formatjs `MISSING_VALUE` runtime error
**Depends on**: Phase 31 CI guard (strings.json ↔ translations/en.json byte-identity), Phase 34 CalDAV strings
**Requirements**: CALDAV-09
**Success Criteria** (what must be TRUE):

  1. The CalDAV options-flow "Calendar title template" tooltip renders the literal text "Placeholders: {street}, {time}, {side}" with no formatjs error overlay
  2. The `caldav_invalid_template` error string renders correctly with no formatjs `MISSING_VALUE` error when a bad template is submitted
  3. `strings.json` and `translations/en.json` remain byte-identical after the edit (Phase 31 CI guard passes locally before push and on PR)
  4. Every curly-brace placeholder reference in CalDAV-related strings uses the ICU single-quote-wrap escape `'{name}'` (ASCII `'`); doubled-brace `{{name}}` and backslash escapes are explicitly NOT used

**Architectural notes**:

  - ICU escape syntax is `'{street}'` (single-quote wrap) — NOT `{{street}}` and NOT `\{street\}`
  - Fix ALL occurrences across CalDAV strings, including the `caldav_invalid_template` error block — partial fixes leave the bug visible elsewhere
  - Run `diff strings.json translations/en.json` locally before every push; CI vendor-guard fails on any drift

**Plans**: 1 plan
Plans:

- [ ] 35-01-PLAN.md — Wave 0 RED unit-test scaffold (4 tests), Wave 1 ICU single-quote-wrap edit on `strings.json` + `translations/en.json` lines 115 & 132 + full pytest suite gate, Wave 2 human UAT on live HA

### Phase 36: Cardinal Direction Label

**Goal**: Users see a human-readable cardinal-direction label for the parking side on both the resolved-street and next-move sensors, while existing automations depending on the raw letter continue to work
**Depends on**: Nothing in v3.3 (independent additive change in `custom_components/asp_parking/sensor.py`)
**Requirements**: SENSOR-01
**Success Criteria** (what must be TRUE):

  1. `sensor.asp_parking_resolved_street` exposes a `side_label` attribute with values "North side", "South side", "East side", or "West side" derived from the raw `side_of_street` letter (N/S/E/W)
  2. `sensor.asp_parking_next_move_time` exposes the same `side_label` attribute with the same mapping — both sensors stay in sync
  3. The existing `side_of_street` attribute on both sensors continues to expose the raw single-letter code unchanged (backward compatibility for existing automations)
  4. When `side_of_street` is missing/unknown, `side_label` is `None` (or absent) — no crash, no misleading default

**Architectural notes**:

  - Mapping dict (`_SIDE_LABELS`) lives in `custom_components/asp_parking/sensor.py` — NOT in `src/gps2asp/` (would trigger vendor-guard sync requirement for a purely UI-layer concern)
  - Add `side_label` to BOTH `ASPNextMoveTimeSensor` AND `ASPResolvedStreetSensor`; do not partially apply
  - Hardcoded English labels match the `_BOROUGH_NAMES` precedent — localization deferred per REQUIREMENTS Future

**Plans**: 1 plan
Plans:

- [x] 36-01-PLAN.md — Wave 1 RED (failing side_label tests on both sensors + _SIDE_LABELS constant test), GREEN (add _SIDE_LABELS dict + side_label attribute insertion in both ASPNextMoveTimeSensor and ASPResolvedStreetSensor), then full-pytest gate + vendor-guard sanity check + SUMMARY — shipped 2026-05-21 (commits bac5556 + bec1ed1)

### Phase 37: Config Flow Step Tracker

**Goal**: Users see their current position in the 3-step config flow ("Step 1 of 3", "Step 2 of 3", "Step 3 of 3") in the step title so they know how much setup remains
**Depends on**: Phase 35 (proves the strings-sync workflow end-to-end first)
**Requirements**: CONFIG-01
**Success Criteria** (what must be TRUE):

  1. The first config flow step title reads "Step 1 of 3: Select Vehicle" (or equivalent existing label prefixed with "Step 1 of 3:")
  2. The second config flow step title reads "Step 2 of 3: Settings" with the matching prefix
  3. The third config flow step title reads "Step 3 of 3: API Keys" with the matching prefix
  4. Options-flow step titles are NOT modified — the tree-shaped options flow has a conditional `caldav_calendar` step that makes a static "Step N of M" count ambiguous (out of scope per REQUIREMENTS)
  5. `strings.json` and `translations/en.json` remain byte-identical after the edit (Phase 31 CI guard passes)

**Architectural notes**:

  - Strings-only change — no Python edits to `config_flow.py`
  - Prefer static string prefixes ("Step 1 of 3: …") over any dynamic mechanism — the flow is linear and the count is fixed at 3
  - Apply edits to BOTH `strings.json` and `translations/en.json` in the same commit; diff before push

**Plans**: 1 plan
Plans:

- [x] 37-01-PLAN.md — Wave 0 RED unit-test scaffold (4 named tests: exact-title equality, "Step N of 3:" prefix parametrized, byte-identity guard, options-flow-not-prefixed boundary), Wave 1 prefix edit on lines 5/12/26 of strings.json + translations/en.json + full offline pytest suite regression gate

### Phase 38: Dual-Path Index Rebuild + Stale Detection

**Goal**: Users can choose between a fast prebuilt-index redownload (existing button) and a true from-source CSCL rebuild (new button), and the integration auto-redownloads when the local index is stale (>60 days) so the index never silently rots
**Depends on**: Phase 33 (`_sync_atomic_swap`, `SpatialIndex.reset()`, `_is_rebuilding` lock, `sensor.asp_parking_index_last_rebuilt`)
**Requirements**: IDX-05, IDX-06, IDX-07
**Success Criteria** (what must be TRUE):

  1. A new HA button entity (e.g. `button.asp_parking_rebuild_index_from_source`) triggers a full CSCL-API rebuild that runs to completion and atomically swaps in the new index using the Phase 33 helpers
  2. The from-source rebuild paginates the NYC Open Data CSCL GeoJSON endpoint, constructs the R-tree index and the adjacency graph from raw data, writes a fresh `build_info.json`, and uses only the existing stack (httpx, shapely, rtree, zstandard) — `manifest.json` requirements are unchanged (no geopandas)
  3. On coordinator startup (and during a daily check), if `build_info.json` reports the index is >60 days old, the integration auto-triggers a fast-path redownload AND posts a persistent HA notification informing the user; the slower from-source rebuild remains user-initiated via the button
  4. Concurrent rebuild attempts (button press while a rebuild is already running, or stale-check firing during a button-driven rebuild) are blocked by the Phase 33 `_is_rebuilding` guard — no double-swap, no corrupted index
  5. Stale-check correctly handles a missing or `None` `_last_rebuilt` (first install): it does NOT classify "unknown age" as "infinitely stale" and does NOT race the first-run download

**Architectural notes**:

  - `manifest.json` requirements MUST remain unchanged — NO geopandas; from-source rebuild uses httpx (CSCL GeoJSON pagination) + shapely (geometry) + rtree (index) + zstandard (graph)
  - Reuse Phase 33 plumbing exactly: `_sync_atomic_swap`, `SpatialIndex.reset()`, `_is_rebuilding` asyncio.Lock guard, zip-slip refusal pattern
  - Stale check must explicitly guard `_last_rebuilt is None` — treat "unknown" as "fresh enough" until the first successful build registers a timestamp
  - Throttle/last-stale-check state goes in `helpers.storage.Store`, never `entry.options` (writing options triggers a full config-entry reload)
  - Fail-open on CSCL network errors — never leave the user with a zero-segment index

**Plans**: 3 plans

Plans:
**Wave 1**

- [x] 38-01-PLAN.md — Wave 1 (TDD): `_sync_build_from_source` in `index_io.py` + D-04/D-05 `source: github_release` patch in `_sync_download_and_extract` + Phase 38 constants in `const.py` + CSCL/SODA respx fixtures + `tests/test_index_io_build_from_source.py` (IDX-06)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 38-02-PLAN.md — Wave 2 (TDD): `RebuildPath` enum + `triggered_by` parameter on `async_request_rebuild`/`_async_do_rebuild` + `_async_decide_rebuild_path` + `_fetch_remote_asset_age_days` with 10-min cache (uses `releases/tags/index-v1`, NOT `/releases/latest`) + routing in `_async_do_rebuild` + `tests/test_coordinator_path_selection.py` (IDX-05)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 38-03-PLAN.md — Wave 3 (TDD): `_async_init_stale_lifecycle` + `_async_check_stale_and_rebuild` (positional-arg compat for `async_track_time_interval`) + `asp_parking_index_stale` Store (FIXED key, not per-entry-id) + startup background task + daily 24h interval + persistent notification + `tests/test_coordinator_stale.py` (IDX-07 + IDX-05 persistence half)

**Note (SPEC supersedes ROADMAP success criterion #1):** Per SPEC §Out of scope and CONTEXT D-03, the implementation uses a SINGLE smart button (existing `button.asp_parking_rebuild_index`); no new button entity is added. The smart path-selection lives in the coordinator. SPEC § Requirement 1 fully replaces success criterion #1's "new HA button entity" wording.

**Note (deviation from ROADMAP):** Live API probe confirmed `GET .../releases/latest` returns v3.0.0 with ZERO assets; the `index.zip` lives on tag `index-v1`. Plans use `GET /repos/.../releases/tags/index-v1` via `GITHUB_INDEX_RELEASE_TAG = "index-v1"` constant.

### Phase 39: Window-Boundary Timer

**Goal**: Sensor advances automatically when a cleaning window opens or closes — no GPS movement required
**Depends on**: Phase 35.1 (coordinator pipeline must be stable)
**Requirements**: N/A (reliability improvement)
**Plans**: 1 plan

After each successful pipeline run that produces a `ScheduleFound` or `ASPActiveNow` result, schedule a one-shot `async_call_later` timer at the relevant window boundary. When the timer fires the pipeline re-runs (bypassing the debouncer) so the sensor transitions state at the exact moment the window opens or closes — even if the car has not moved and the 8-hour heartbeat has not fired.

**Success Criteria** (what must be TRUE):

  1. After a pipeline run returning `ASPActiveNow`, a timer is registered to fire at `active_window.end_datetime`; when it fires the pipeline re-runs and the sensor reflects the post-window state
  2. After a pipeline run returning `ScheduleFound`, a timer is registered to fire at `next_window.start_datetime`; when it fires the pipeline re-runs and the sensor transitions to `ASPActiveNow`
  3. Any previously registered boundary timer is cancelled before a new one is registered (no dangling timers)
  4. Full pytest suite passes with no regressions

Plans:

- [x] 39-01-PLAN.md — Wave 1 (TDD): `_boundary_timer_cancel` + `_async_schedule_boundary_timer` in `coordinator.py`, fired from `_async_resolve_pipeline` after schedule computation

### Phase 35.1: Bug Sweep — Vendored Copy Sync + Silent Failure Fixes (INSERTED)

**Goal**: Fix all bugs surfaced by the 50-UC behavioral analysis — the integration currently silently stops updating the schedule after startup due to a vendored-copy drift, plus 33 additional bugs across all pipeline stages
**Depends on**: Phase 34 (CalDAV integration must be complete; fixes touch caldav_sync.py)
**Requirements**: N/A (defect remediation, no new requirements)
**Plans**: 5 plans

#### Critical (fix immediately — integration broken in production)

| ID | File | Description |
|---|---|---|
| BUG-H-001 | `coordinator.py:1117` | Every Stage 3 pipeline run raises `AttributeError: 'HolidayCalendar' has no attribute 'suspended_dates'` — swallowed by `except Exception`; schedule **never updated after startup** |
| BUG-H-002 | `gps2asp/suspension/__init__.py` | Vendored copy missing `suspended_dates` property — root cause of H-001; `custom_components/gps2asp/` was never synced after `src/gps2asp/` added it |

#### High

| ID | File | Description |
|---|---|---|
| BUG-H-003 | `gps2asp/schedule/next_move.py` | Vendored `find_next_window()` lacks `suspended_dates` skip logic — holiday windows offered as "next cleaning" even after H-001/H-002 fixed |
| BUG-R-002 | `resolver/__init__.py:233` | `has_asp` OR logic regardless of resolved side — car on ASP-free side of a one-sided block gets `has_asp=True` |
| BUG-S-002 | `signs/__init__.py:410` | L4 broad match sets `any_soda_results=True`; if spanning fails, returns `NoASPSigns` instead of `NoMatchFound` — silently suppresses schedule display for unmatched blocks |
| BUG-C-002 | `coordinator.py:758` | Suspension-during-write race: `is_suspended` checked before `await write_or_update_event()` but not after — CalDAV event left on-server if suspension fires during network I/O |

#### Medium

| ID | File | Description |
|---|---|---|
| BUG-R-001 | `resolver/__init__.py:282` | `_classify_ambiguity()` hardcoded 10ft threshold vs width-relative ~4.95ft in `compute_confidence()` — wrong label for points between thresholds |
| BUG-R-004 | `side_resolver.py:88` | Degenerate zero-length segment silently returns `"S"` for all points (zero direction vector) |
| BUG-R-005 | `spatial_index.py:155` | `nearest(n=5)` is bounding-box nearest, not geometry-nearest — long diagonal streets (Broadway) may have closest segment at rank 6+, wrong street selected |
| BUG-R-008 | `spatial_index.py:64` | `SpatialIndex.get(index_dir=...)` silently ignores `index_dir` after first call — dangerous during index rebuilds |
| BUG-S-001 | `signs/__init__.py` | L4 re-issues the identical broad HTTP request already made by L3 |
| BUG-S-003 | `signs/__init__.py` | `_cross_streets_match()` false-positive on empty strings — `name_variants("")` returns `[""]`, any no-cross-street record matches |
| BUG-S-004 | `signs/graph.py` | `StreetGraph.load()` unhandled exception on malformed `graph.json` — propagates on every subsequent L4 call |
| BUG-T-003 | `schedule/next_move.py:39` | `find_active_window()` has no `suspended_dates` — on a holiday during an active window, `ASPActiveNow.suspended` is `False` until sensor read time |
| BUG-T-004 | `schedule/parser.py:228` | Cross-midnight windows silently rejected — `end > start` guard fails for `11PM–MIDNIGHT`; Night Regulation signs wholly unparseable |
| BUG-T-008 | `suspension/__init__.py:163` | ICS fallback returns `{}` for years after 2026 with no error — network failure = zero holiday awareness |
| BUG-H-004 | `binary_sensor.py:80,147` | Hardcoded `sw_version="0.1.0"` instead of `VERSION` constant |
| BUG-H-005 | `coordinator.py:313` | `_get_now()` uses hardcoded `NYC_TZ` instead of `dt_util.now()` — violates project convention for date-boundary checks |
| BUG-C-003 | `caldav_sync.py:228` | Bare `options[CONF_CALDAV_URL]` subscript — `KeyError` swallowed as opaque "CalDAV sync failed" notification |
| BUG-C-004 | `coordinator.py:905` | Unnecessary background task spawned when `_caldav_uid is None` and `next_window is None` — no-op task every pipeline run |

#### Low

| ID | File | Description |
|---|---|---|
| BUG-R-003 | `resolver/__init__.py:182` | `determine_side()` computed before confidence check — misleading debug side value when confidence=0 |
| BUG-R-006 | `spatial_index.py:178` | Missing `rw_type` silently uses 30ft fallback with no segment ID in log |
| BUG-R-007 | `pipeline.py:14` | Asymmetric exception handling (`AmbiguousResolutionError` soft-handled, others propagate) — intentional but undocumented |
| BUG-S-005 | `signs/graph.py` | `_pids_with_cross_street()` O(N) called 4× per span — ~32M dict lookups on major avenues |
| BUG-S-006 | `signs/client.py` | Last retry delay computed and logged as "retry in 4.0s" but `asyncio.sleep()` guard skips it — misleading log |
| BUG-S-007 | `coordinator.py:1104` | `materialize_cached_records()` hardcodes `soda_level=1` for all cache hits |
| BUG-T-001 | `schedule/models.py` | Docstring says "7 days" but `range(8)` lookahead is 8 days |
| BUG-T-002 | `schedule/next_move.py` | `find_next_window()` returns `None` with one generic warning for three distinct failure causes |
| BUG-T-005 | `coordinator.py` | `ASPActiveNow` drops `cleaning_days` sensor attribute — `weekly=None` with dead comment |
| BUG-T-006 | `suspension/merge.py` | `apply_suspension()` defaults unknown source to `"suspended_holiday"` — wrong for any future source |
| BUG-T-009 | `suspension/__init__.py` | `_fetch_ics` retries HTTP 401/403 — unlike `NYC311Client` which fast-fails on auth errors |
| BUG-T-011 | `schedule/__init__.py` | Dead `try/except ValueError` on `ASPDay(weekday)` — `weekday()` returns 0–6, all valid |
| BUG-C-005 | `caldav_sync.py:140` | Caldav 2.x compatibility shim calls `principal()` (no network) instead of `get_principal()` — wrong base URL on Nextcloud |

**Note**: BUG-C-001 (`await principal.calendar()`) already fixed in commit `bac9da8`. BUG-T-010 (`frozenset(self._holidays)`) confirmed NOT a bug.

**Success Criteria** (what must be TRUE):

  1. Full pytest suite passes (`.venv/bin/pytest`) with no regressions
  2. BUG-H-001/002 fixed: `HolidayCalendar.suspended_dates` property exists in vendored copy; coordinator Stage 3 call no longer raises `AttributeError`
  3. BUG-H-003 fixed: vendored `find_next_window()` has `suspended_dates` parameter and skip logic byte-identical to `src/` version
  4. BUG-T-004 fixed: cross-midnight windows parse correctly; `11PM–MIDNIGHT` produces a valid `TimeWindow`
  5. BUG-S-002 fixed: L4 with no covering span returns `NoMatchFound`, not `NoASPSigns`, when the block was never confirmed in SODA
  6. All remaining High + Medium bugs addressed or explicitly deferred with rationale

Plans:

- [x] 35.1-01-PLAN.md — Wave 1: venv repair + vendored copy sync (BUG-H-001/002/003)
- [x] 35.1-02-PLAN.md — Wave 2 (TDD): resolver bugs (BUG-R-001/002/003/004/005/006/008)
- [x] 35.1-03-PLAN.md — Wave 2 (TDD): signs bugs (BUG-S-001/002/003/004/006)
- [x] 35.1-04-PLAN.md — Wave 2 (TDD): schedule + suspension bugs (BUG-T-001/002/003/004/006/008/009/011)
- [x] 35.1-05-PLAN.md — Wave 3: HA glue + coordinator (BUG-H-004/005, BUG-T-005, BUG-S-007, BUG-R-007)
- [x] 35.1-06-PLAN.md — Wave 3: CalDAV bugs (BUG-C-002/003/004/005)

## Backlog

### Phase 999.1: Update formatting to add date (BACKLOG)

**Goal:** [Captured for future planning] — superseded by Phase 32 (Sensor Display Format) in v3.2; close on next backlog review
**Requirements:** TBD
**Plans:** 0 plans

Plans:

- [ ] TBD (promote with /gsd-review-backlog when ready)

## Progress (v3.3)

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 35. CalDAV Tooltip Fix | 1/1 | Complete (pending human UAT) | 2026-05-19 |
| 35.1. Bug Sweep — Vendored Copy Sync (INSERTED) | 6/6 | Complete | 2026-05-21 |
| 36. Cardinal Direction Label | 1/1 | Complete   | 2026-05-21 |
| 37. Config Flow Step Tracker | 1/1 | Complete   | 2026-05-22 |
| 38. Dual-Path Index Rebuild + Stale Detection | 3/3 | Complete    | 2026-05-23 |
| 39. Window-Boundary Timer | 1/1 | Complete   | 2026-05-23 |
