# Pitfalls Research

**Domain:** Adding BFS graph optimization, borough-specific coverage fixes, and observability metrics to an existing GPS-to-ASP spatial index system (v2.0 milestone)
**Researched:** 2026-03-13
**Confidence:** HIGH — based on direct code inspection of the live codebase, v1.1 known pitfalls from milestone context, and domain-specific analysis of BFS graph traversal, normalization coupling, and HA sensor attribute plumbing patterns.

---

## Critical Pitfalls

### Pitfall 1: Filtering graph.json to ASP-only severs BFS traversal

**What goes wrong:**
graph.json is reduced from 7.9 MB by removing non-ASP segments. BFS traversal in Level 4 — both at build time in `_bfs_between()` and at runtime in `StreetGraph._bfs_min_hops()` — needs to navigate *through* non-ASP intermediate blocks to connect span endpoints. Removing those intermediate blocks severs the adjacency graph. BFS returns `float('inf')` for spans that were previously reachable, and Level 4 coverage drops silently.

**Why it happens:**
The intuition is "if a segment has no ASP signs, it doesn't need to be in graph.json." This is true for endpoint *lookup* purposes but false for *traversal* purposes. A SODA span covering "72nd to 86th STREET" includes interior blocks like "73rd to 74th STREET" that have no ASP record of their own — the adjacency graph must traverse through them to reach the span endpoints. PROJECT.md Key Decisions documents this explicitly: "graph.json covers all segments (not ASP-only) — Level 4 must navigate between any adjacent blocks to find covering span."

The correct optimization is to filter `segment_streets` and `segment_cross_streets` (endpoint lookup tables used by `_pids_with_cross_street`) to ASP-relevant entries only, while keeping the full adjacency list for traversal. This reduces the JSON size of the lookup dictionaries without removing adjacency edges.

**How to avoid:**
Never filter the `adjacency` dict by `has_asp`. If the goal is file size reduction, filter only the endpoint metadata (`segment_streets`, `segment_cross_streets`) to entries that are either (a) ASP-tagged or (b) reachable within N hops from an ASP-tagged segment. Validate by running Level 4 match rate against a fixed set of known mid-span blocks before and after compression — the rate must be unchanged.

**Warning signs:**
- Manhattan coverage drops below its pre-compression baseline after the optimization
- Level 4 log messages increase in "best span unreachable" / `_find_best_covering_span` returning `None`
- `_bfs_min_hops` returns `inf` for spans that were 2-3 hops before compression

**Phase to address:**
graph.json compression phase. Level 4 match rate regression test is the acceptance criterion, not file size alone.

---

### Pitfall 2: Queens normalization fix regresses other boroughs

**What goes wrong:**
A normalization change intended to fix Queens — adding a new suffix mapping, handling numbered street ordinals ("162ND" vs "162"), or adjusting directional prefix logic — silently breaks previously-working blocks in Manhattan, Brooklyn, or Bronx. The normalization functions `normalize_to_soda` and `name_variants` in `signs/normalize.py` are shared across all boroughs with no borough-aware branching.

**Why it happens:**
Queens has street naming patterns not found elsewhere: numbered streets with directional suffixes ("162 STREET" vs "162ND STREET"), hyphenated address-style names, and AVENUE/AVE inconsistencies specific to Queens conventions. The three-step normalization (directional prefix expand → suffix expand → directional suffix expand) applies globally. A new rule that matches a Queens pattern may inadvertently mutate valid Manhattan or Brooklyn names. For example, a rule targeting Queens numbered street ordinals could interfere with Manhattan ordinal avenues ("3 AVE" → "3 AVENUE" is correct; modifying ordinal logic risks "3RD AVE" → something wrong).

**How to avoid:**
Before any normalization change, build a regression fixture: record the current `normalize_to_soda` and `name_variants` output for 20+ known-working blocks across all boroughs, verified against live Level 1 SODA matches. After the change, assert all fixtures still produce the same output. Add Queens-specific test cases with expected SODA output verified against live API responses first. If the fix requires borough-specific behavior, add a `borough` parameter to `normalize_to_soda` rather than a global mutation.

**Warning signs:**
- Brooklyn coverage (74.1%) or Manhattan coverage (58.2%) drops after a Queens normalization commit
- A previously-passing Level 1 test now requires Level 2 or Level 3 to match
- `name_variants()` produces a new third variant that previously had only two

**Phase to address:**
Queens normalization audit phase. Per-borough before/after coverage snapshot is the acceptance criterion, not Queens coverage target in isolation.

---

### Pitfall 3: Level 4 fires on blocks where SODA has records but no broom signs

**What goes wrong:**
Level 4 is supposed to fire only when `any_soda_results is False` — i.e., when SODA returned zero records across all four levels. The `any_soda_results` flag is a local variable in `retrieve_signs()` set by three separate code paths (Level 1 match, Level 2 match, Level 3 broad query returning records). If this flag is reset, renamed, or misplaced during a refactor — for example, when adding structured logging, timing instrumentation, or restructuring the fallback logic into helper functions — Level 4 can fire on blocks where SODA has valid non-broom sign records. This wastes a network round-trip and may produce confusing log output.

**Why it happens:**
The `any_soda_results` flag is a load-bearing sentinel whose semantics are not obvious from its name alone. It distinguishes "SODA returned records on this street but none were broom signs" (meaning the data is complete, there are no ASP rules here) from "SODA returned nothing at all" (meaning our query failed to reach the right records). Developers adding observability or restructuring the control flow may not recognize this distinction and accidentally clear or re-initialize the flag.

**How to avoid:**
Write an explicit unit test that verifies Level 4 does NOT fire when Level 3 receives SODA records containing no broom signs (i.e., `any_soda_results=True` but `filtered=[]`). The test should mock the SODA client and assert `StreetGraph.get()` is never called. Treat the `any_soda_results` flag logic in `signs/__init__.py` at the Level 4 guard as invariant — add a comment marking it as a load-bearing sentinel before any refactor.

**Warning signs:**
- "Level 4: broad query" appears in logs for streets that return non-broom SODA records in Levels 1-3
- Coverage numbers inflate artificially without a corresponding reduction in `NoMatchFound` returns
- The existing Level 4 guard unit test is absent from the test suite after a refactor

**Phase to address:**
Any phase that touches `retrieve_signs()` control flow, including the observability metrics phase. Add the guard unit test before making any control flow changes.

---

### Pitfall 4: StreetGraph singleton not invalidated after graph.json rebuild

**What goes wrong:**
`StreetGraph` uses a class-level singleton (`_instance: StreetGraph | None = None`). If graph.json is rebuilt (e.g., during a coverage improvement rebuild while running `build_index.py`) while a Python process is still running — either the HA integration or a pytest session — the singleton continues serving the stale in-memory graph. The new graph.json on disk is never loaded. Coverage changes from the rebuild are not reflected until the process restarts.

**Why it happens:**
The singleton pattern in `StreetGraph.get()` is correct for production (graph.json never changes at runtime). But during development — running `build_index.py`, then immediately running coverage tests in the same pytest session without resetting `StreetGraph._instance = None` — the test session sees the old graph. `SpatialIndex` already has a `reset()` class method for exactly this purpose; `StreetGraph` lacks one.

**How to avoid:**
Add a `StreetGraph.reset()` class method mirroring `SpatialIndex.reset()`. Call it in test fixtures that supply a custom `index_dir` or rebuild graph.json. Ensure all integration tests that test graph compression call reset before and after the test. For HA, document that graph.json changes require an HA restart (not just a reload).

**Warning signs:**
- Coverage test shows no improvement after a known-good graph rebuild
- Test assertions about graph segment counts or Level 4 behavior fail intermittently based on test execution order
- `StreetGraph.load()` is called only once across a test session that expects it to be called multiple times

**Phase to address:**
graph.json compression phase and any phase that modifies the build script output format.

---

### Pitfall 5: soda_level not reachable in HA sensor without coordinator plumbing

**What goes wrong:**
`soda_level` is available on `SignRetrievalSuccess.soda_level` (an `int` field) and in `ASPDebugResult.soda_level`, but the HA coordinator (`coordinator.py`) does not call `resolve_asp()` — it calls the three pipeline stages manually (tech debt item COV-03 in PROJECT.md). `sign_result` is a local variable inside `_async_resolve_pipeline`, never persisted to `ASPParkingData`. Adding `soda_level` as a sensor attribute requires either (a) adding it to `ASPParkingData` and setting it from `sign_result`, or (b) migrating the coordinator to use `resolve_asp()`. If only the sensor attribute is added without the coordinator plumbing, the attribute exists but always shows `0`.

**Why it happens:**
The coordinator predates `resolve_asp()` as a unified API. Sensor attributes are read from `coordinator.data` (an `ASPParkingData` dataclass), not from the pipeline result directly. Developers adding a new sensor attribute may add it to `sensor.py` without also adding the corresponding field to `ASPParkingData` and the assignment in `_async_resolve_pipeline`. The mismatch is not caught by the type checker because `extra_state_attributes` returns `dict[str, ...]` with no field validation.

**How to avoid:**
Add `soda_level: int = 0` to `ASPParkingData` at the same time as the sensor attribute. Set it from `sign_result.soda_level` when `sign_result` is a `SignRetrievalSuccess` in `_async_resolve_pipeline`, alongside the existing `sign_count` assignment pattern. If migrating the coordinator to `resolve_asp(debug=True)`, map all `ASPDebugResult` fields to `ASPParkingData` in a single pass rather than piecemeal. Never add a sensor attribute that has no corresponding source in `ASPParkingData`.

**Warning signs:**
- `soda_level` attribute in the HA sensor always shows `0` regardless of real resolve level
- `ASPParkingData` has no `soda_level` field but `sensor.py` references `data.soda_level`
- `ASPParkingData` and `ASPDebugResult` have different field sets for overlapping pipeline data

**Phase to address:**
Level 4 observability / COV-03 coordinator migration phase. Both changes (coordinator plumbing and sensor attribute) must happen in the same commit.

---

### Pitfall 6: Structured logging adds blocking I/O or confounds timing metrics

**What goes wrong:**
Adding structured log output (JSON file handlers, metrics push clients, latency counters) to the async pipeline stages (`pipeline.py`, `signs/__init__.py`, `signs/client.py`) introduces blocking I/O on the asyncio event loop. HA runs all integrations on a single event loop; blocking calls in `retrieve_signs()` delay all other integrations. Additionally, adding `time.time()` calls for latency metrics measures wall-clock time that includes event loop contention, not actual pipeline latency, producing misleading observability data.

**Why it happens:**
Python's `logging` module is synchronous. The existing code already wraps R-tree index loading with `await asyncio.to_thread(_blocking_load)` in `SpatialIndex._load()` to avoid this — but that pattern is easy to forget for new instrumentation. Developers adding "just a quick timer" use `time.time()` without realizing event loop scheduling means the measured interval includes idle wait time.

**How to avoid:**
Use only HA's standard `logging` module — HA proxies it through its own async-safe handler. Do not add file handlers, Prometheus push clients, or InfluxDB emitters directly in pipeline code. For latency metrics, use `time.monotonic()` and capture only within a single coroutine scope (not across `await` points). If latency histograms are needed, collect them as in-memory scalars on `ASPParkingData` and expose as sensor attributes — do not push externally. Any new I/O in an async function must be wrapped in `asyncio.to_thread`.

**Warning signs:**
- HA logs show "Task exceeded timeout" or slow response during GPS pipeline runs after observability changes
- Other HA integrations miss updates or respond slowly after the change
- New `import` statements for file I/O, third-party metric clients, or synchronous HTTP in pipeline modules

**Phase to address:**
Observability / structured logging phase. Baseline other-integration latency before and after as acceptance criterion.

---

### Pitfall 7: Coverage improvement declared done from build-time index stats alone

**What goes wrong:**
Coverage percentages (Manhattan 58.2%, Brooklyn 74.1%, etc.) are computed at build time by counting segments with `has_asp_left` or `has_asp_right` flags in the spatial index. This is a proxy metric, not the actual pipeline success rate. A segment with `has_asp=True` (tagged via BFS propagation) can still return `NoMatchFound` at runtime if the SODA query fails to match due to normalization differences. Conversely, `has_asp=False` segments can succeed via Level 3 or Level 4. Treating the build-time stat as the completion criterion for Queens (currently 36.8% → target ≥50%) means the target can be "hit" on paper while real-world resolve rate stays the same.

**Why it happens:**
Build-time coverage statistics are fast to compute and are immediately visible in `build_info.json`. Runtime SODA success rates require running the full pipeline against real GPS coordinates. For v1.1, BFS propagation directly improved the `has_asp` index and the proxy metric was valid — the fix was purely in the index. For v2.0, Queens normalization changes and graph compression affect runtime SODA query matching, which the index stat cannot measure.

**How to avoid:**
Add a spot-check test suite: a fixed set of 10-20 known GPS coordinates per borough with recorded expected Level 1/2/3/4 outcomes (verified against live SODA API once, then fixture-recorded). Run these spot-check tests after any normalization or BFS change. Use the Level 1/2 success rate as the Queens acceptance criterion — not the BFS propagation segment count from `build_info.json`.

**Warning signs:**
- Queens `has_asp` segment count increases but no new Level 1 or Level 2 SODA matches appear in test logs
- A coverage phase is marked complete based only on `build_info.json` stats
- No spot-check GPS coordinate fixtures exist in the test suite for Queens blocks

**Phase to address:**
Queens normalization audit phase and any coverage improvement phase. Establish the spot-check fixture set before making any normalization changes.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Coordinator calls three pipeline stages manually (not `resolve_asp()`) | Avoids coordinator refactor | `soda_level` and other debug fields never reach HA sensor; adding new pipeline outputs requires changes in two places | Only until COV-03; must fix before adding more pipeline-derived sensor attributes |
| Build-time `has_asp` coverage as proxy for runtime success | Fast feedback on index changes | Queens normalization fix may pass build metric while real resolve rate stays flat | Acceptable for BFS propagation changes; unacceptable for normalization or query changes |
| `StreetGraph` singleton without a `reset()` method | Simple load-once pattern | Test isolation failures when graph.json is rebuilt between test cases | Never acceptable once any test rebuilds or overrides graph.json |
| Exposing `soda_level` as raw integer (1-4) without description | No translation work | Users see "4" with no explanation of what it means | Acceptable as initial implementation if documented; should become a string in follow-up |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| SODA API (nfid-uabd) | Reverting or weakening the `sign_design_voided_on_date IS NULL` filter during query refactors | This filter is the v1.1 fix for voided signs; it must be in every `build_block_query` and `build_on_street_query` call — treat it as invariant |
| SODA API pagination | Changing the break condition from `len(records) < DEFAULT_BATCH_SIZE` to `== 0` to save a round-trip | The current condition is correct; `== 0` would require one extra empty request per paginated query — not worth the saved logic |
| HA sensor `extra_state_attributes` | Returning Python Enum values (e.g., `ASPDay.MONDAY`) directly as attribute values | HA serializes attributes to JSON; use `.name` or `.value`; `soda_level` as `int` is safe |
| HA event loop | Calling `StreetGraph.load()` (JSON parse of a large file) synchronously on the first `retrieve_signs()` call from an async context | The current call is in a task created by `hass.async_create_task`, so it is in an async context, but `json.load` inside `StreetGraph.load()` is blocking; for a compressed ≤4 MB file this is ~20-40ms and acceptable, but if file size grows, wrap with `asyncio.to_thread` |
| NYC Open Data CSCL (inkn-q76z) | Assuming paginated CSCL download is stable across runs without checking `rowsUpdatedAt` | CSCL data updates periodically; always check the metadata URL against `build_info.json` before trusting cached index files |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| `_pids_with_cross_street()` scans full `segment_cross_streets` dict on every BFS call | Level 4 latency grows with graph size; multiple spans × 4 BFS calls each | Build an inverted index at load time: `{cross_street_name: set[pid]}` instead of scanning all entries | Noticeable now at 60K+ entries when a single Level 4 resolve issues 4+ `_pids_with_cross_street` lookups |
| Level 2 combinatorial variant explosion | For streets with 3 on/from/to variants = 27 SODA queries before Level 3 | `name_variants()` currently caps at 2 entries; verify Queens normalization does not add a third | Breaks at 3+ variants per street; current code avoids this but normalization changes could regress it |
| graph.json cold-parse on first `retrieve_signs()` call | HA startup shows brief stall; first GPS update after restart is slow | graph.json compression to ≤4 MB reduces but does not eliminate this; consider pre-loading in `async_setup_entry` via `asyncio.to_thread` | Affects every cold start; 7.9 MB JSON parse is ~50-100ms blocking on HA hardware |
| Coverage spot-check tests against live SODA API in CI | Tests are slow and non-deterministic when SODA data changes | Record fixtures once against live API (VCR-style); use fixtures in CI; run live-API tests manually | Breaks CI reliability immediately if live API is used in automated tests |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Logging GPS coordinates at INFO level in structured log output | GPS location data in HA logs may be accessible to other HA add-ons or logged to external services configured by the user | Keep GPS lat/lon at DEBUG level only (current pattern); INFO logs reference street names only |
| Exposing raw SODA API record dicts in HA sensor attributes | No sensitive data in SODA parking signs, but large dict attributes slow HA database writes and may appear in HA cloud sync | Never expose raw record dicts; always summarize to scalar counts (`sign_count`, `soda_level`) |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| `soda_level` exposed as raw integer (1-4) | User sees "soda_level: 4" with no context | Expose as a descriptive string ("mid_span_match") or document integer values in the sensor's translation strings |
| "No restrictions" shown for both `NoMatchFound` and `NoASPSigns` | User cannot tell if their block genuinely has no ASP ("no broom signs found") vs SODA has no data for the block ("no records at all") | `NoMatchFound` and `NoASPSigns` should produce different `resolution_status` sensor states or attributes; currently both produce "No restrictions" which conflates two distinct situations |
| Queens coverage improvement not observable to users | User with a Queens address cannot tell if the fix helped their specific location | `soda_level` in sensor attributes provides the signal: if they previously got Level 4 or `NoMatchFound` and now get Level 1 or 2, the fix worked for their location |

---

## "Looks Done But Isn't" Checklist

- [ ] **graph.json compression:** Adjacency for non-ASP intermediate blocks preserved — verify with Level 4 match rate spot-check, not just file size
- [ ] **Queens normalization fix:** Brooklyn 74.1% and Manhattan 58.2% unchanged — per-borough regression fixture passes, not just Queens target met
- [ ] **soda_level in HA sensor:** Attribute is non-zero after a real Level 1 GPS resolve — verify coordinator has `ASPParkingData.soda_level` field populated from `sign_result.soda_level`
- [ ] **Observability structured logs:** No blocking I/O in async path — check HA logs for `BlockingIOError`; verify other-integration latency is unchanged
- [ ] **Level 4 guard logic:** `any_soda_results` flag still correctly prevents Level 4 on non-broom SODA results — unit test "Level 4 does not fire when any_soda_results=True" must pass after any refactor
- [ ] **StreetGraph singleton reset:** Test isolation — a test supplying a custom graph.json does not leak state into subsequent tests; `StreetGraph.reset()` exists and is called in teardown

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| graph.json compressed to ASP-only, coverage drops | MEDIUM | Restore full adjacency in graph.json build; re-run `build_index.py`; redeploy; restart HA integration |
| Queens normalization breaks Brooklyn | LOW | Revert the normalization commit; re-audit with per-borough fixtures before retrying the fix |
| soda_level always 0 in sensor | LOW | Add `soda_level: int = 0` to `ASPParkingData`; set it from `sign_result.soda_level` in coordinator; no schema migration needed for HA sensor attributes |
| StreetGraph singleton stale in test session | LOW | Add `StreetGraph.reset()` method; call in test teardown; no production impact |
| Blocking I/O in async pipeline | MEDIUM | Identify new synchronous I/O introduced during observability work; wrap with `await asyncio.to_thread()`; re-test HA integration timing |
| Coverage target met on index stats but not real resolves | MEDIUM | Add spot-check GPS fixtures against live SODA; re-audit normalization; iterate until fixture pass rate meets borough target |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| graph.json compression breaks BFS traversal | graph.json compression phase | Level 4 match rate unchanged vs pre-compression baseline; Manhattan/Brooklyn coverage unchanged |
| Queens normalization regresses other boroughs | Queens normalization audit phase | Per-borough coverage snapshot before and after; regression fixture suite passes |
| Level 4 fires on non-broom SODA results | Any phase touching `retrieve_signs()` control flow | Unit test: `StreetGraph.get()` not called when `any_soda_results=True` with empty filtered records |
| StreetGraph singleton not invalidated after rebuild | graph.json compression phase | Test isolation: each test supplying a custom graph gets a fresh `StreetGraph` instance |
| soda_level not plumbed through coordinator | Level 4 observability / COV-03 coordinator migration phase | Sensor attribute `soda_level` is non-zero after a real GPS resolve with known Level 1 match |
| Structured logging adds blocking I/O | Observability metrics phase | No `BlockingIOError` in HA logs; other-integration update latency unchanged before/after |
| Coverage declared done from build-time stats | Queens coverage phase | Spot-check GPS fixture set shows Level 1/2 success rate ≥50% for Queens, not just `build_info.json` segment count |

---

## Sources

- Direct code inspection: `src/gps2asp/signs/graph.py`, `src/gps2asp/signs/__init__.py`, `src/gps2asp/signs/normalize.py`, `scripts/build_index.py`, `custom_components/asp_parking/coordinator.py`, `custom_components/asp_parking/sensor.py`, `src/gps2asp/resolver/spatial_index.py`, `src/gps2asp/api_models.py`
- v1.1 known pitfalls from milestone context: BFS false-positive propagation (solved with strict end validation in `_bfs_between`), `max_depth=30` prevents runaway, Level 4 guard on `any_soda_results`, Staten Island 0.0% as data gap not a code bug
- PROJECT.md Key Decisions table: "graph.json covers all segments (not ASP-only)" documents the BFS traversal requirement explicitly; COV-03 documents the coordinator-vs-`resolve_asp()` tech debt
- `SpatialIndex.reset()` in `src/gps2asp/resolver/spatial_index.py`: established precedent for singleton reset pattern that `StreetGraph` should mirror
- `asyncio.to_thread(_blocking_load)` in `SpatialIndex._load()`: established precedent for offloading blocking I/O that new observability code must follow

---
*Pitfalls research for: GPS2ASP Resolver v2.0 — BFS optimization, Queens coverage, Level 4 observability*
*Researched: 2026-03-13*
