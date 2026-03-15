# Architecture Research

**Domain:** GPS-to-ASP-regulation resolver — coverage improvements and observability for v2.0
**Researched:** 2026-03-13
**Confidence:** HIGH (all findings are based on direct code inspection of the live codebase)

## Standard Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         OFFLINE BUILD (scripts/)                         │
│                                                                          │
│  build_index.py                                                          │
│  ┌─────────────┐  ┌───────────────────┐  ┌───────────────────────────┐  │
│  │ CSCL SODA   │  │ ASP Signs SODA    │  │ Output files              │  │
│  │ GeoJSON     │→ │ (broom filter)    │→ │ segments.idx + .dat       │  │
│  │ ~122K segs  │  │ unique block-face │  │ segments.json             │  │
│  └─────────────┘  └───────────────────┘  │ graph.json  (7.9 MB)     │  │
│          │                │              │ build_info.json           │  │
│          │  BFS propagate │              └──────────────────────────┘  │
│          └────────────────┘                    ↓ shipped with package  │
└──────────────────────────────────────────────────────────────────────────┘
          ↓ (index files loaded lazily at runtime)
┌──────────────────────────────────────────────────────────────────────────┐
│                    RUNTIME PIPELINE (src/gps2asp/)                       │
│                                                                          │
│  resolve_asp(lat, lon) ── pipeline.py                                    │
│                                                                          │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────────────────────┐ │
│  │ Stage 1  │  │   Stage 2    │  │           Stage 3                  │ │
│  │ GPS →    │→ │ Street →     │→ │  Signs → Schedule → ScheduleResult │ │
│  │ Segment  │  │ SODA Signs   │  │                                    │ │
│  └──────────┘  └──────────────┘  └────────────────────────────────────┘ │
│  resolver/     signs/             schedule/                              │
│  SpatialIndex  retrieve_signs()   compute_schedule()                     │
│  (R-tree +     L1→L2→L3→L4       parse + merge + next_move             │
│   segments.json fallback chain   StreetGraph (graph.json, lazy)         │
│  singleton)    singleton)                                                │
│                                                                          │
│  Public API: ASPResult / ASPDebugResult (soda_level field exists here)  │
└──────────────────────────────────────────────────────────────────────────┘
          ↓ (called by HA coordinator)
┌──────────────────────────────────────────────────────────────────────────┐
│                  HOME ASSISTANT LAYER (custom_components/)               │
│                                                                          │
│  ASPParkingCoordinator (event-driven, not DataUpdateCoordinator)         │
│  - Subscribes to device_tracker state changes                            │
│  - 50m movement threshold + 5s debounce                                 │
│  - Calls THREE-STAGE pipeline MANUALLY (tech debt: not resolve_asp())   │
│  - ASPParkingData: schedule_result, sign_count, confidence_score, etc.  │
│                                                                          │
│  Sensors: ASPNextMoveTimeSensor + 6 diagnostic sensors                  │
│  Attributes: confidence_score, sign_count, parse_failures, last_error   │
│  MISSING: soda_level in HA sensor attributes (v2.0 target)              │
└──────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | File | Responsibility |
|-----------|------|----------------|
| `SpatialIndex` | `resolver/spatial_index.py` | Lazy-loaded singleton; R-tree nearest-neighbor for GPS→segment; loads segments.json |
| `StreetGraph` | `signs/graph.py` | Lazy-loaded singleton; graph.json BFS for Level 4 span scoring; loaded at first Level 4 call |
| `retrieve_signs()` | `signs/__init__.py` | Four-level fallback chain: L1 exact → L2 variants → L3 broad+filter → L4 BFS span |
| `normalize_to_soda()` | `signs/normalize.py` | CSCL abbreviation → SODA full-word; used at build time AND runtime |
| `build_index.py` | `scripts/` | Offline: downloads CSCL + ASP signs, BFS-propagates has_asp flags, writes index files |
| `ASPParkingCoordinator` | `custom_components/asp_parking/coordinator.py` | HA event-driven orchestrator; currently calls 3-stage pipeline manually (not `resolve_asp()`) |
| `ASPNextMoveTimeSensor` | `custom_components/asp_parking/sensor.py` | Primary sensor; exposes attributes but lacks `soda_level` |

## Recommended Project Structure

No structural changes needed for v2.0. All work is modifications to existing files.

```
src/gps2asp/
├── pipeline.py              [MODIFY] soda_level in ASPResult (not just ASPDebugResult)
├── api_models.py            [MODIFY] add soda_level field to ASPResult
├── signs/
│   ├── __init__.py          [MODIFY] structured logging at L4 entry/exit
│   └── graph.py             [READ-ONLY for v2.0 observability]
├── resolver/
│   └── spatial_index.py     [READ-ONLY for v2.0]
scripts/
└── build_index.py           [MODIFY] graph.json filter to ASP-reachable segments only
custom_components/asp_parking/
├── coordinator.py           [MODIFY] migrate to resolve_asp(); store soda_level
└── sensor.py                [MODIFY] expose soda_level in extra_state_attributes
```

### Structure Rationale

- **No new files needed for observability:** All three observability goals (Level 4 hit rate, soda_level in HA, Queens diagnosis) are modifications to existing components along the existing data flow.
- **graph.json reduction is a build-time change only:** The runtime `StreetGraph.load()` just reads whatever is in graph.json — no runtime code changes needed to benefit from a smaller file.
- **Queens normalization diagnostic is a logging addition, not a new module:** The failure point lives in existing code paths and needs structured log output to locate it.

## Architectural Patterns

### Pattern 1: Two-Singleton Lazy Load

Both `SpatialIndex` and `StreetGraph` use the same pattern: class-level `_instance`, `get()` classmethod that loads on first call, `reset()` for tests.

**Integration point for observability:** The StreetGraph singleton is already loaded at first Level 4 call. No changes needed to its load path to instrument hit rate — the instrumentation belongs in `retrieve_signs()` where Level 4 is invoked, not in `StreetGraph` itself.

**Current Level 4 logging (in `signs/__init__.py`):**
```python
logger.info("Level 4 matched: on_street=%r (best-covering span, %d unique signs)", ...)
```
This is INFO-level but not structured. It does not log the miss case (when Level 4 is entered but returns `NoMatchFound`).

### Pattern 2: soda_level Field Already Exists in ASPDebugResult

`ASPDebugResult` (debug=True path) already carries `soda_level: int`. `ASPResult` (debug=False path) does not. The HA coordinator calls the 3-stage pipeline manually (not `resolve_asp()`), so it never produces either result type — it gets `sign_result` directly as a `SignRetrievalResult`.

**What is needed:**
1. Add `soda_level: int` to `ASPResult` (non-debug path) so non-debug callers can see it.
2. Migrate HA coordinator to use `resolve_asp(debug=False)` so it receives `ASPResult`.
3. Store `soda_level` in `ASPParkingData` and surface it in `extra_state_attributes`.

**Data flow for soda_level (after migration):**
```
retrieve_signs() returns SignRetrievalSuccess(soda_level=4)
    │
    ▼ pipeline.py
resolve_asp() extracts soda_level, puts in ASPResult
    │
    ▼ coordinator.py
ASPParkingData.soda_level = result.soda_level
    │
    ▼ sensor.py
extra_state_attributes["soda_level"] = data.soda_level
```

### Pattern 3: graph.json Covers ALL Adjacency Segments (Current Design)

The current build writes graph.json with ALL segments that have adjacency entries — this is ~all vehicular segments. The comment in `build_index.py` (line 917) says:
```python
for pid, neighbors in adjacency.items():   # ALL adjacency entries
    pid_str = str(pid)
    graph_adjacency[pid_str] = sorted(neighbors)
```

**Why the graph covers all segments:** Level 4 BFS must traverse intermediate (non-ASP) segments to get from one ASP span endpoint to another. The BFS scores spans by graph distance; interior blocks along the route are non-ASP segments.

**The reduction opportunity:** The graph does not need entries for segments that could never be part of a Level 4 query. A segment is relevant to Level 4 if:
- It is adjacent to at least one ASP segment (can be traversed to reach one), OR
- It is an ASP segment itself (is a potential query target or span endpoint)

**Concrete approach:**
1. After building adjacency, compute `asp_pid_set` = all PIDs where `has_asp_left or has_asp_right` in segments metadata.
2. Expand with 1-hop neighbors: `relevant_pids = asp_pid_set | {n for pid in asp_pid_set for n in adjacency[pid]}`.
3. Filter graph.json to only `relevant_pids`.

This preserves full BFS capability for blocks adjacent to ASP streets while dropping purely non-ASP interior areas (parking lots, dead-end industrial segments, etc.).

**Expected size reduction:** From 7.9 MB toward ≤4 MB target. The exact reduction depends on what fraction of all segments are within 1 hop of an ASP segment. In dense NYC, this will be high in Manhattan/Brooklyn but there are large non-ASP areas (parks, airports, industrial zones) that can be pruned.

### Pattern 4: Queens Normalization — Three Candidate Failure Points

Queens street names have unique characteristics: numbered streets with borough-specific formatting (`"73 AVENUE"` vs `"73RD AVENUE"`), hyphenated addresses (`"147-23 STREET"`), and named streets that do not follow CSCL abbreviation conventions.

**Candidate failure point A: build_index.py `_normalize_street_name()`**

In `_compute_cross_streets()`, the cross street found by `_find_cross_street()` is the raw `full_street_name` from CSCL, which is stored directly into `cross_streets[pid]`. That raw name is later passed to `_check_has_asp()` which calls `_normalize_street_name()`. The `normalize_to_soda()` function handles standard abbreviations but has no Queens-specific ordinal handling (e.g., `"73 AVE"` → `"73 AVENUE"` works, but `"73 RD AVE"` → `"73 RD AVENUE"` not `"73RD AVENUE"`).

If SODA stores Queens cross streets as `"73 ROAD AVENUE"` or with ordinal suffixes, the lookup fails at build time → segment gets `has_asp=False` → Level 4 is never invoked at runtime.

**Candidate failure point B: runtime `retrieve_signs()` name_variants expansion**

`name_variants()` generates at most 2 variants (SODA format + original CSCL). For Queens streets with ordinal conventions (`"QUEENS BLVD"` vs `"QUEENS BOULEVARD"`) this may be insufficient. If SODA stores the name under a third variant not generated by `name_variants()`, Levels 1-3 all miss.

**Candidate failure point C: Level 4 BFS span_distance() cross-street PID lookup**

In `StreetGraph.span_distance()`, it calls `_pids_with_cross_street(block_from)` which scans `segment_cross_streets` for the normalized name. If graph.json was built with CSCL format names and runtime queries use SODA format names (or vice versa), the PID sets come back empty and all BFS distances are `float('inf')`.

The `StreetGraph.load()` normalizes names via `normalize_to_soda()` at load time — but if the names in graph.json are already in raw CSCL format and `normalize_to_soda()` doesn't fully handle Queens ordinals, the normalized forms still won't match SODA query terms.

**Diagnostic approach:** Add structured logging at each candidate point for borocode=4 segments:
```python
if seg_data.get("borocode") == "4":
    logger.debug("Queens L1 attempt: on=%r from=%r to=%r", ...)
```
This is a targeted log-and-compare, not a code change.

## Data Flow

### Request Flow (Current — post v1.1)

```
GPS coordinates (lat, lon)
    │
    ▼ pipeline.py: resolve_asp()
Stage 1: convert(lat, lon) → (x, y) State Plane
    │
    ▼ resolver/__init__.py: resolve_segment()
SpatialIndex.get() [lazy singleton]
    │   R-tree nearest(x, y, n=5, max=164ft) → [SegmentCandidate, ...]
    │   Side-of-street via perpendicular projection
    │
    ▼ pipeline.py
Stage 2: retrieve_signs(on_street, from_street, to_street, side)
    │
    ├── Level 1: exact SODA query (L1 soda_level=1)
    ├── Level 2: abbreviation variant combinations (soda_level=2)
    ├── Level 3: broad on_street+side, client-side cross-street filter (soda_level=3)
    └── Level 4: [only if Levels 1-3 return ZERO records]
                 StreetGraph.get() [lazy singleton, loads graph.json]
                 broad on_street+side query
                 _find_best_covering_span() via BFS span_distance()
                 soda_level=4
    │
    ▼ pipeline.py
Stage 3: compute_schedule(sign_result) → ScheduleResult
    │
    ▼ pipeline.py
ASPResult(schedule, resolution_failed, resolution_error)
   soda_level: NOT in ASPResult today (only in ASPDebugResult)
```

### Level 4 Observability Gap (Current State)

```
retrieve_signs() enters Level 4
    │
    ├── CASE A: Level 4 matches → logger.info("Level 4 matched...")
    │                              soda_level=4 on SignRetrievalSuccess
    │
    ├── CASE B: Level 4 entered, broad query returns records,
    │           _find_best_covering_span() returns None →
    │           falls through to NoMatchFound()
    │           NO STRUCTURED LOG emitted for this miss
    │
    └── CASE C: Level 4 entered, broad query returns zero records →
                falls through to NoMatchFound()
                NO STRUCTURED LOG emitted for this miss
```

Cases B and C are the gaps. Hit rate requires counting Case A vs (B + C). Currently only Case A is logged at INFO level. Cases B and C produce a generic `logger.info("No match found...")` that doesn't distinguish "Level 4 was attempted" from "Levels 1-3 failed before Level 4".

### Proposed Observability Data Flow (After v2.0)

```
retrieve_signs() enters Level 4
    │
    ├── NEW: logger.info("Level 4: entered for on_street=%r side=%r", ...)
    │                                    [structured: l4_entered=True]
    │
    ├── CASE A: match → logger.info("Level 4: matched, span_distance=%d", ...)
    │                   [structured: l4_result="match"]
    │
    ├── CASE B: no covering span → NEW logger.info("Level 4: no covering span found")
    │                              [structured: l4_result="no_span"]
    │
    └── CASE C: no SODA records → NEW logger.info("Level 4: no SODA records")
                                  [structured: l4_result="no_records"]
```

These three structured log entries are sufficient to compute hit rate from HA logs without changing the pipeline contract (`SignRetrievalResult` return type unchanged).

## Scaling Considerations

| Concern | Current | After v2.0 |
|---------|---------|------------|
| graph.json startup | 7.9 MB, loaded lazily on first L4 call | ≤4 MB target with ASP-reachable filter |
| Level 4 BFS correctness | Unchanged (full graph ensures no missing paths) | Preserved (1-hop neighbor expansion keeps all traversal paths) |
| Queens coverage | 36.8% (below 50% target) | Diagnostic logging reveals which failure point; fix applied after diagnosis |
| HA coordinator pipeline | Manual 3-stage call (tech debt) | Migrated to resolve_asp() — single call, cleaner error surface |

## Anti-Patterns

### Anti-Pattern 1: Filtering graph.json to ASP-Only Segments

**What it means:** Keeping only segments where `has_asp=True` in graph.json.

**Why it is wrong:** BFS traversal needs intermediate non-ASP segments as bridges. A block between two ASP spans may not be an ASP segment itself. Removing it breaks BFS connectivity and Level 4 returns `float('inf')` for spans that are actually reachable.

**Do this instead:** Keep ASP segments PLUS their 1-hop neighbors in graph.json. The 1-hop filter preserves all traversal paths while removing segments that are more than 1 hop from any ASP street (parks, airports, industrial dead-ends).

### Anti-Pattern 2: Instrumenting Level 4 Inside StreetGraph

**What people do:** Add hit-rate counters to `StreetGraph.span_distance()` or `_find_best_covering_span()`.

**Why it is wrong:** StreetGraph is a pure graph utility — it has no knowledge of whether it is being called from Level 4, from a test, or from a future caller. Mixing observability state into the graph breaks the separation between data structure and calling context.

**Do this instead:** All Level 4 observability lives in `retrieve_signs()` (signs/__init__.py), where the Level 4 block is explicitly demarcated with `# Level 4` comments. The entry, match, and miss cases are all visible there.

### Anti-Pattern 3: Adding soda_level as an Exception or Side Channel

**What people do:** Raise a custom exception carrying soda_level when Level 4 matches, or use a module-level counter.

**Why it is wrong:** The pipeline contract is `retrieve_signs()` → `SignRetrievalResult`. `SignRetrievalSuccess` already has `soda_level: int` — it is populated correctly for Levels 1-4. The problem is that `ASPResult` (the public pipeline output) doesn't carry it through to callers. The correct fix is to propagate the existing `soda_level` field through `pipeline.py` into `ASPResult`.

**Do this instead:** `pipeline.py` already extracts `soda_level` for the `ASPDebugResult` path (line 89: `soda_level = sign_result.soda_level if isinstance(sign_result, SignRetrievalSuccess) else 0`). Add `soda_level: int` to `ASPResult` and replicate that extraction for the non-debug path.

### Anti-Pattern 4: Queens-Specific Special Cases in normalize_to_soda()

**What people do:** Add Queens ordinal handling (`"73 AVE"` → `"73RD AVENUE"`) directly into `normalize_to_soda()`.

**Why it is wrong:** `normalize_to_soda()` is shared between build time and runtime. Queens ordinals in SODA are not consistent — SODA stores these as `"73 AVENUE"` (matching what normalize_to_soda already produces), not as `"73RD AVENUE"`. Adding ordinal logic would introduce wrong transformations. The Queens coverage problem is not in the normalization function — it is most likely in the cross-street computation at build time or in missing name variants.

**Do this instead:** Diagnose first via structured logging before changing normalization. The fix may be a new variant in `name_variants()` or a build-time cross-street computation fix, not a change to the core normalizer.

## Integration Points

### New vs Modified Components

| Component | Change Type | What Changes |
|-----------|-------------|--------------|
| `src/gps2asp/api_models.py` | **Modify** | Add `soda_level: int = 0` field to `ASPResult` dataclass |
| `src/gps2asp/pipeline.py` | **Modify** | Populate `soda_level` in `ASPResult` (same extraction already done for `ASPDebugResult`) |
| `src/gps2asp/signs/__init__.py` | **Modify** | Add structured INFO logs at Level 4 entry + miss cases (Cases B and C above) |
| `scripts/build_index.py` | **Modify** | Filter graph.json to ASP-reachable segments (ASP PIDs + 1-hop neighbors) |
| `custom_components/asp_parking/coordinator.py` | **Modify** | Migrate `_async_resolve_pipeline()` from 3-stage manual call to `resolve_asp()`; add `soda_level` to `ASPParkingData` |
| `custom_components/asp_parking/sensor.py` | **Modify** | Add `soda_level` to `extra_state_attributes` in `ASPNextMoveTimeSensor` |

No new files are needed. All changes are surgical modifications to existing components.

### Dependency Graph for Changes

```
api_models.py (add soda_level to ASPResult)
    │
    ▼ must happen first
pipeline.py (populate soda_level in non-debug path)
    │
    ▼ must happen after pipeline.py
coordinator.py (use resolve_asp(), read result.soda_level)
    │
    ▼ must happen after coordinator.py
sensor.py (read data.soda_level from coordinator)
```

```
signs/__init__.py (structured Level 4 logging)
    │ independent of the soda_level propagation chain above
    │ can be built in parallel
    ▼
(observability in HA logs)
```

```
build_index.py (graph.json filter)
    │ purely offline, no runtime code changes
    │ can be built in parallel with all runtime changes
    ▼
(re-run build_index.py, new graph.json deployed)
```

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| NYC Open Data SODA (`nfid-uabd`) | REST GET + SoQL `$where`, paginated JSON | No changes for v2.0; existing client handles L4 broad query |
| NYC Open Data SODA (`inkn-q76z`) | REST GeoJSON + pagination (build time only) | No changes; build_index.py downloads unchanged |

### Internal Boundaries

| Boundary | Communication | v2.0 Change |
|----------|---------------|-------------|
| `pipeline.py` → `ASPResult` | Frozen dataclass construction | Add `soda_level` field; zero-cost, backward-compat if callers use keyword args |
| `coordinator.py` → `pipeline.py` | `await resolve_asp(lat, lon)` | Coordinator currently bypasses `resolve_asp()` entirely; migration aligns HA with library public API |
| `coordinator.py` → `sensor.py` | `coordinator.data` (ASPParkingData dataclass) | Add `soda_level: int = 0` to `ASPParkingData`; sensor reads new field |
| `retrieve_signs()` → `StreetGraph` | `StreetGraph.get()` singleton call | No change; observability lives in `retrieve_signs()`, not in `StreetGraph` |

## Suggested Build Order

Build order is driven by the dependency chain above. Three workstreams are independent and can be sequenced or run in parallel:

**Workstream 1 — soda_level propagation (4 steps, strict order):**
1. `api_models.py`: Add `soda_level: int = 0` to `ASPResult`
2. `pipeline.py`: Populate `soda_level` in `ASPResult` construction (copy the existing `ASPDebugResult` extraction logic)
3. `coordinator.py`: Migrate to `resolve_asp()`, add `soda_level` to `ASPParkingData`, update data extraction
4. `sensor.py`: Add `soda_level` to `extra_state_attributes`

**Workstream 2 — Level 4 structured logging (1 step, independent):**
5. `signs/__init__.py`: Add INFO log at Level 4 entry; add INFO logs for miss Cases B and C

**Workstream 3 — graph.json size reduction (1 step, offline only):**
6. `build_index.py`: Add `relevant_pids` filter before writing graph.json; rebuild index; verify BFS correctness via tests

**Queens diagnosis (after Workstream 1 + 2 complete):**
7. Enable DEBUG logging for borocode=4 segments in a test resolve; compare logged CSCL cross-street names against SODA stored names; identify which candidate failure point (A, B, or C) is responsible; apply targeted fix

**Why this order:** Steps 1-4 unblock the HA sensor improvement and close the coordinator tech debt. Step 5 adds the observability needed to measure Level 4 hit rate in production. Step 6 is offline and has no runtime risk. Queens diagnosis must follow Steps 5 because the structured logs are what make the failure point identifiable.

## Sources

All findings are based on direct code inspection (confidence: HIGH):
- `src/gps2asp/pipeline.py` — soda_level extraction exists for debug path, absent from ASPResult
- `src/gps2asp/api_models.py` — ASPResult vs ASPDebugResult field comparison
- `src/gps2asp/signs/__init__.py` — Level 4 block, Cases A/B/C logging gap identified
- `src/gps2asp/signs/graph.py` — StreetGraph singleton, BFS logic, span_distance()
- `src/gps2asp/signs/normalize.py` — normalize_to_soda() suffix table, Queens ordinal gap
- `src/gps2asp/resolver/spatial_index.py` — SpatialIndex singleton pattern
- `custom_components/asp_parking/coordinator.py` — manual 3-stage call confirmed (lines 289-296)
- `custom_components/asp_parking/sensor.py` — extra_state_attributes missing soda_level confirmed
- `scripts/build_index.py` — graph.json write loop (lines 921-926), all-adjacency issue confirmed

---
*Architecture research for: GPS2ASP v2.0 — coverage improvements and observability*
*Researched: 2026-03-13*
