# Project Research Summary

**Project:** GPS2ASP Resolver v2.0 — coverage and observability additions
**Domain:** Spatial GPS-to-parking-regulation resolver (NYC Alternate Side Parking)
**Researched:** 2026-03-13
**Confidence:** HIGH

## Executive Summary

GPS2ASP Resolver v1.1 is an operational system with a four-level SODA API fallback pipeline (GPS coordinates to State Plane to street segment to SODA signs to parsed schedule to HA sensor). The v2.0 milestone is a focused improvement cycle with three concrete goals: raise Queens coverage from 36.8% to >=50% (the largest borough gap by 13.2 points), reduce graph.json from 7.9 MB to <=4 MB for low-memory HA hardware, and surface the `soda_level` field (already tracked internally) in the HA sensor's `extra_state_attributes`. This is an incremental improvement cycle on an already-working system, not a new build.

The recommended approach is to work three independent workstreams in parallel: (1) soda_level propagation through the API result type to coordinator to sensor (four sequential file edits), (2) structured Level 4 logging added to `signs/__init__.py`, and (3) graph.json size reduction via ASP-reachable segment filtering in `build_index.py`. Queens normalization diagnosis should follow workstreams 1 and 2, because the structured logging produced by workstream 2 is the primary diagnostic tool for identifying which of the three candidate failure points (build-time cross-street normalization, runtime name variant expansion, or BFS cross-street PID lookup) causes the Queens coverage gap. No new runtime dependencies are required except `zstandard` as a conditional addition if ASP-segment filtering alone does not reach the <=4 MB target.

The key risk is subtle regressions: graph.json filtering that breaks BFS traversal by removing non-ASP intermediate blocks (the correct filter is ASP segments plus 1-hop neighbors, not ASP-only), Queens normalization changes that silently reduce Brooklyn or Manhattan coverage, and soda_level always showing 0 because the coordinator plumbing was not updated alongside the sensor attribute. All three risks have well-understood prevention strategies grounded in the existing codebase patterns (SpatialIndex.reset() precedent for singleton management, per-borough coverage snapshots before normalization changes, mandatory ASPParkingData field addition alongside sensor attribute addition).

## Key Findings

### Recommended Stack

The v1.x stack (Python 3.11+, pyproj, shapely, rtree, httpx, numpy) is unchanged and validated. For v2.0, no new runtime dependencies are required for Queens coverage improvement or observability. Both use existing stdlib (`logging` with `extra={}` dicts) and existing data structures. The only conditional addition is `zstandard>=0.23.0` for graph.json compression — needed only if filtering graph.json to ASP-reachable segments alone yields a file larger than 4 MB.

**Core technologies (unchanged from v1.x):**
- Python 3.11+ with frozen dataclasses and type hints throughout
- pyproj / shapely — GPS to State Plane coordinate conversion and side-of-street geometry
- rtree — R-tree spatial index for nearest-segment lookup
- httpx (async) — SODA API client for sign retrieval
- stdlib `logging` with `extra={}` dicts — structured observability without adding structlog (incompatible with HA's logging model)

**Conditional new dependency:**
- zstandard 0.25.0 — compress graph.json if ASP-segment filter alone exceeds 4 MB; self-contained wheel, Python >=3.9 compatible, ~30-40% additional size reduction on top of filtering

**Explicitly avoid:** structlog (bypasses HA's logger configuration UI), orjson (graph load is already in asyncio.to_thread; no bottleneck), msgpack (string-heavy data shows no meaningful size advantage over JSON + compression), pandas as a runtime dependency (already available via geopandas in build extras).

### Expected Features

All four v2.0 features are improvements to an operational system. "Table stakes" here means the minimum to close the v2.0 milestone.

**Must have (table stakes — v2.0 launch criteria):**
- Queens normalization audit + rule additions — diagnose format mismatches, add patterns to normalize_to_soda(), rebuild index, confirm runtime Level 1/2 success rate >=50% for Queens (not just build-time has_asp segment count)
- Manhattan coverage >=60% — 1.8-point gap; expected side effect of Queens normalization fix; verify after rebuild as an explicit target
- graph.json <=4 MB — ASP-reachable segment filter (ASP PIDs + 1-hop neighbors) in build_index.py; preserves full BFS correctness; zero runtime code changes required
- soda_level in HA sensor extra_state_attributes — one field added to ASPParkingData + one assignment in coordinator + one line in sensor; soda_level already flows through SignRetrievalSuccess

**Should have (P2 — add during v2.0 cycle before close):**
- Structured Level 4 logging — add INFO log at Level 4 entry and miss cases (B: no covering span, C: no SODA records) in signs/__init__.py; grep-friendly format; low complexity; directly enables Queens diagnosis

**Defer to v2.x:**
- COV-03: Coordinator migration to resolve_asp() — correct tech debt fix, but soda_level can be captured without it; risk of behavioral regressions if rushed into v2.0
- CACHE-01: SQLite sign data cache — not needed to meet coverage goals
- HA diagnostics endpoint — blocked on HA diagnostics API familiarity

**Defer to v3+:**
- SUSP-01/02/03: NYC holiday and weather suspension — separate 311 API data source, separate milestone
- NOTIF-01/02: HA actionable notifications — requires stable schedule data first

### Architecture Approach

v2.0 requires no new files or new modules. All work is surgical modifications to six existing files, organized into three independent workstreams. The two-singleton lazy-load pattern (SpatialIndex and StreetGraph each have a class-level _instance with a get() classmethod) is unchanged. graph.json size reduction is a purely build-time change; StreetGraph.load() reads whatever is in graph.json with no runtime code changes. The coordinator tech debt (manually calling three pipeline stages instead of resolve_asp()) is mitigated for soda_level without requiring the full COV-03 migration.

**Files modified in v2.0:**
1. `src/gps2asp/api_models.py` — add soda_level: int = 0 to ASPResult (enables non-debug callers to see it)
2. `src/gps2asp/pipeline.py` — populate soda_level in ASPResult (copy existing ASPDebugResult extraction logic)
3. `custom_components/asp_parking/coordinator.py` — add soda_level to ASPParkingData; set from sign_result; optionally migrate to resolve_asp()
4. `custom_components/asp_parking/sensor.py` — expose soda_level in extra_state_attributes
5. `src/gps2asp/signs/__init__.py` — structured INFO logs at Level 4 entry and all miss cases
6. `scripts/build_index.py` — filter graph.json to ASP-reachable segments (ASP PIDs + 1-hop neighbors)

**Level 4 data flow for soda_level (after v2.0):**
```
SignRetrievalSuccess.soda_level
  -> pipeline.py: ASPResult.soda_level
  -> coordinator.py: ASPParkingData.soda_level
  -> sensor.py: extra_state_attributes["soda_level"]
```

### Critical Pitfalls

1. **Filtering graph.json to ASP-only segments severs BFS traversal** — The correct filter is ASP segments PLUS their 1-hop neighbors. Non-ASP intermediate blocks between two ASP spans must remain in the adjacency graph for BFS to traverse them. Validate by running Level 4 match rate against known mid-span blocks before and after compression — rate must be unchanged, not just file size reduced.

2. **Queens normalization fix regresses other boroughs** — normalize_to_soda() is shared across all boroughs. Before any normalization change, record current outputs for 20+ known-working blocks per borough as regression fixtures and assert they are unchanged after the fix. If a Queens-specific rule is needed, add a borough parameter rather than a global mutation.

3. **Coverage declared done from build-time index stats alone** — has_asp segment counts in build_info.json are a proxy metric. A segment tagged has_asp=True via BFS can still return NoMatchFound at runtime if SODA queries fail. The acceptance criterion for Queens must be runtime Level 1/2 success rate from a GPS coordinate spot-check fixture set, not the build_info.json segment count.

4. **soda_level plumbing incomplete — attribute always shows 0** — If soda_level is added to sensor.py without also adding the field to ASPParkingData and setting it from sign_result in the coordinator, the attribute exists but always returns 0. Both changes (coordinator assignment and sensor exposure) must be in the same commit.

5. **StreetGraph singleton not invalidated after graph.json rebuild** — During development, rebuilding graph.json while a pytest session is running leaves the stale in-memory singleton active. StreetGraph needs a reset() class method mirroring SpatialIndex.reset(), called in test teardown for any test supplying a custom graph.json.

## Implications for Roadmap

Based on research, three independent workstreams can be developed in parallel, with Queens diagnosis gated on the structured logging workstream completing first.

### Phase 1: soda_level Propagation

**Rationale:** Lowest complexity (four file edits, strictly ordered), highest user visibility impact, and unblocks Queens diagnosis by making Level 4 hit rates visible in production. Should be done first to establish the observability foundation.
**Delivers:** soda_level visible in HA sensor attributes; non-debug callers of resolve_asp() can read soda_level from ASPResult; coordinator optionally migrated to resolve_asp().
**Addresses:** "soda_level in HA sensor attributes" (P1 table stakes), partial COV-03 tech debt.
**Avoids:** Pitfall 4 (always-0 attribute) — requires ASPParkingData field + coordinator assignment + sensor attribute in same commit.

Strict file order within this phase: api_models.py -> pipeline.py -> coordinator.py -> sensor.py.

### Phase 2: Structured Level 4 Logging

**Rationale:** Independent of Phase 1 (can be developed in parallel), but must complete before Queens diagnosis begins. Cases B (no covering span) and C (no SODA records) are currently both logged as generic "No match found" with no indication that Level 4 was attempted. Without this, Queens failure point identification is guesswork.
**Delivers:** Structured INFO log at Level 4 entry + match + both miss cases in signs/__init__.py. Grep-friendly format with consistent field names. Hit-rate computation possible from HA logs.
**Addresses:** "Structured Level 4 logging" (P2), enables Queens normalization diagnosis.
**Avoids:** Pitfall 6 (blocking I/O) — use only stdlib logging with extra= dicts; no file handlers or push clients in async pipeline.

### Phase 3: graph.json Size Reduction

**Rationale:** Purely offline (build_index.py only), zero runtime code changes, fully independent of all runtime workstreams. Can be developed in parallel with Phases 1 and 2. Expected to reach 3-4 MB with ASP + 1-hop neighbor filter; add zstandard compression only if filtered result exceeds 4 MB.
**Delivers:** graph.json <=4 MB; reduced HA startup memory and cold-start latency; new graph.json deployed with same build_index.py rebuild used for Queens normalization fix.
**Addresses:** "graph.json <=4 MB" (P1 table stakes).
**Avoids:** Pitfall 1 (ASP-only filter breaks BFS) — filter must include 1-hop neighbors. Pitfall 5 (stale singleton) — add StreetGraph.reset() and call in test teardown.

### Phase 4: Queens Normalization Diagnosis and Fix

**Rationale:** Must follow Phase 2 (structured logging) to be diagnosable. Three candidate failure points exist (build-time cross-street normalization, runtime name_variants() coverage, BFS cross-street PID lookup) and structured logs are required to identify which one applies. Fix is applied after diagnosis — changing normalization without understanding the failure point risks introducing the wrong rules or regressing other boroughs.
**Delivers:** Queens runtime Level 1/2 success rate >=50% verified by GPS spot-check fixtures. Manhattan coverage >=60% as expected side effect. New normalize.py rules targeting the confirmed failure point. Build-index rebuilt (same invocation also produces the Phase 3 graph.json).
**Addresses:** "Queens normalization audit + fix" (P1), "Manhattan coverage >=60%" (P1).
**Avoids:** Pitfall 2 (regression to other boroughs) — per-borough coverage snapshot before/after; regression fixture suite passes. Pitfall 3 (Level 4 fires on non-broom records) — any control flow changes in retrieve_signs() must preserve any_soda_results guard. Pitfall 7 (coverage declared done from build stats) — GPS spot-check fixture set required as acceptance criterion.

### Phase Ordering Rationale

- Phases 1 and 2 can be developed in parallel since they touch different files (api_models.py/pipeline.py/coordinator.py/sensor.py vs signs/__init__.py).
- Phase 3 is fully independent of all runtime work and can run in parallel with Phases 1-2. The build_index.py rebuild for Phase 3 can be combined with the Phase 4 rebuild to avoid running the full CSCL download twice.
- Phase 4 must follow Phase 2 because the structured logging is the diagnostic tool. Phase 1 completing before Phase 4 is also preferred so that soda_level production visibility confirms the fix worked from the user's perspective.
- The Queens normalization fix (Phase 4) triggers a build_index.py rebuild — schedule this to also incorporate the Phase 3 graph.json size reduction in the same run.

### Research Flags

Phases with well-documented patterns (no additional research needed):
- **Phase 1 (soda_level propagation):** Pattern is clearly documented in ARCHITECTURE.md — copy existing ASPDebugResult extraction logic; all four target files and exact line numbers are known.
- **Phase 2 (structured logging):** Standard stdlib logging with extra= dicts; implementation pattern shown in STACK.md; no external library research needed.
- **Phase 3 (graph.json reduction):** Filter algorithm is specified in ARCHITECTURE.md (ASP PIDs + 1-hop neighbors); build_index.py lines 921-926 are the exact insertion point; conditional zstandard dependency is fully specified.

Phases needing investigation during execution:
- **Phase 4 (Queens normalization):** The specific failure point (A: build-time cross-street computation, B: runtime name_variants() coverage, or C: BFS cross-street PID lookup) is unknown until structured logs are analyzed. An audit script (scripts/audit_queens_coverage.py) needs to be written and run against the live SODA API before any normalization code change is made.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All findings based on direct codebase inspection and PyPI package verification; zstandard is the only conditional new dependency and is well-documented; structlog rejection confirmed against HA logging docs |
| Features | HIGH | All feature analysis sourced directly from codebase — field locations, line numbers, and data flow paths confirmed by code inspection, not inference; feature scope is grounded in PROJECT.md milestone targets |
| Architecture | HIGH | All architectural findings based on direct code inspection of the live system; component boundaries, singleton patterns, data flow, and exact file-change list are confirmed by reading the actual source |
| Pitfalls | HIGH | Pitfalls grounded in existing code patterns (SpatialIndex.reset() precedent, any_soda_results guard, ASPParkingData field plumbing pattern) and v1.1 known issues; not speculative |

**Overall confidence:** HIGH

### Gaps to Address

- **Queens failure point identity:** The exact cause of 36.8% Queens coverage is unknown. Three candidate failure points are documented (ARCHITECTURE.md Pattern 4), but the specific one affecting Queens requires live SODA API diagnostic logging to identify. Resolution: Write audit_queens_coverage.py and enable DEBUG logging for borocode=4 segments before writing any normalization code.

- **graph.json post-filter size:** The exact size after ASP + 1-hop neighbor filtering is estimated at 3.5-4.5 MB but not confirmed without running the filter. If the filtered size exceeds 4 MB, zstandard compression must be added as a dependency. Resolution: Run the filter in Phase 3 and measure before deciding on compression.

- **COV-03 migration scope in Phase 1:** Whether to migrate the coordinator to resolve_asp() as part of Phase 1 or defer it is a planning decision. The research confirms soda_level can be captured without the migration, but the migration closes tech debt that makes future pipeline output additions require two-place changes. Resolution: Treat coordinator migration as optional in Phase 1 scope; confirm during planning.

## Sources

### Primary (HIGH confidence — direct codebase inspection)

- `src/gps2asp/signs/__init__.py` — Level 4 fallback chain, soda_level tracking, any_soda_results guard, Cases A/B/C logging gap
- `src/gps2asp/signs/graph.py` — StreetGraph singleton, BFS span_distance(), _find_best_covering_span()
- `src/gps2asp/signs/normalize.py` — normalize_to_soda(), _SUFFIX_EXPANSIONS, _DIRECTIONAL_EXPANSIONS, Queens ordinal gap
- `src/gps2asp/api_models.py` — ASPResult vs ASPDebugResult field comparison; soda_level present in debug path only
- `src/gps2asp/pipeline.py` — soda_level extraction exists for debug path; ASPResult construction
- `src/gps2asp/resolver/spatial_index.py` — SpatialIndex singleton with reset(); precedent for StreetGraph.reset()
- `custom_components/asp_parking/coordinator.py` — manual 3-stage call confirmed; ASPParkingData fields; sign_result extraction
- `custom_components/asp_parking/sensor.py` — extra_state_attributes; soda_level absence confirmed
- `scripts/build_index.py` — graph.json write loop (lines 921-926); all-adjacency confirmed; BFS propagation logic

### Primary (HIGH confidence — official documentation)

- [Home Assistant Logger integration docs](https://www.home-assistant.io/integrations/logger/) — HA logging model; why structlog is incompatible with custom components
- [zstandard on PyPI](https://pypi.org/project/zstandard/) — Version 0.25.0; Python >=3.9; self-contained wheels confirmed

### Secondary (MEDIUM confidence)

- [NYC Queens address format — StreetEasy](https://streeteasy.com/blog/queens-addresses-hyphenated-confusing-street-names/) — Queens street naming conventions; ordinal suffix usage rationale
- [msgpack vs JSON compression benchmark](https://www.peterbe.com/plog/msgpack-vs-json-with-gzip) — Compressed JSON comparable to compressed msgpack for string-heavy data

---
*Research completed: 2026-03-13*
*Ready for roadmap: yes*
