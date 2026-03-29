# Roadmap: GPS2ASP Resolver

## Milestones

- ✅ **v1.0 MVP** — Phases 1-4 (shipped 2026-02-23)
- ✅ **v1.1 Bug Fixes** — Phases 5-11 (shipped 2026-03-07)
- 🔄 **v2.0 Full Borough Coverage** — Phases 12-18 (active)

## Phases

<details>
<summary>✅ v1.0 MVP (Phases 1-4) — SHIPPED 2026-02-23</summary>

- [x] Phase 1: GPS-to-Street Resolution (2/2 plans) — completed 2026-02-21
- [x] Phase 2: ASP Sign Retrieval (2/2 plans) — completed 2026-02-22
- [x] Phase 3: Schedule Parsing and Next-Move Computation (2/2 plans) — completed 2026-02-22
- [x] Phase 4: Home Assistant Integration (3/3 plans) — completed 2026-02-23

Full details: `.planning/milestones/v1.0-ROADMAP.md`

</details>

<details>
<summary>✅ v1.1 Bug Fixes (Phases 5-11) — SHIPPED 2026-03-07</summary>

- [x] Phase 5: Bug Fixes and Tech Debt (1/1 plans) — completed 2026-02-27
- [x] Phase 6: Improve Confidence Scoring for NYC Street Widths (1/1 plans) — completed 2026-02-28
- [x] Phase 7: Pipeline Stabilization — Importable Function with Debug Flag (2/2 plans) — completed 2026-02-28
- [x] Phase 8: Refactor Architecture and Streamline Pipeline (3/3 plans) — completed 2026-03-01
- [x] Phase 9: Rebuild the Spatial Index (2/2 plans) — completed 2026-03-01
- [x] Phase 10: Update Documentation (1/1 plans) — completed 2026-03-02
- [x] Phase 11: Improve ASP Coverage Through Mid-Span Coverage (3/3 plans) — completed 2026-03-03

Full details: `.planning/milestones/v1.1-ROADMAP.md`

</details>

### v2.0 Full Borough Coverage (Phases 12-18) — Active

- [x] **Phase 12: Structured Level 4 Logging** — Emit grep-friendly INFO logs at Level 4 entry and all miss cases in signs/__init__.py (completed 2026-03-15)
- [x] **Phase 13: soda_level Propagation to HA Sensor** — Surface soda_level from ASPResult through coordinator to HA sensor extra_state_attributes (completed 2026-03-16)
- [x] **Phase 14: graph.json Size Reduction** — Filter graph.json to ASP-reachable segments at build time, reducing file from 7.9 MB to ≤4 MB (completed 2026-03-17)
- [x] **Phase 15: Queens and Manhattan Coverage Fix** — Diagnose Queens normalization failure point using Phase 12 logs and fix; rebuild index (completed 2026-03-25)
- [x] **Phase 16: Queens Coverage Fix — Geocoded Fixtures + L3 Diagnosis** — Regenerate Queens fixtures from real addresses, extend audit with L3 diagnostics, fix normalization gaps, verify ≥50% (completed 2026-03-19)
- [x] **Phase 17: Manhattan Coverage Fix — Geocoded Fixtures + L3 Diagnosis** — Same approach for Manhattan, target ≥60% (completed 2026-03-19)
- [x] **Phase 18: Vendored Signs Sync + Docs Cleanup** — Sync Phase 12 structured Level 4 logging to vendored HA copy; update REQUIREMENTS.md traceability (completed 2026-03-29)

## Phase Details

### Phase 12: Structured Level 4 Logging
**Goal**: Level 4 fallback behavior is fully observable from HA logs, enabling failure diagnosis
**Depends on**: Nothing (independent single-file change)
**Requirements**: OBS-02
**Success Criteria** (what must be TRUE):
  1. HA log shows an INFO entry at Level 4 entry that includes borough, segment ID, and span being queried
  2. HA log shows an INFO entry for Case A (covering span matched) with the matching span identifiers
  3. HA log shows an INFO entry for Case B (no covering span found) that is distinct from Case C
  4. HA log shows an INFO entry for Case C (SODA returned no records) that is distinct from Case B
  5. All four log entries use consistent field names searchable with a single grep pattern
**Plans**: 1 plan

Plans:
- [ ] 12-01-PLAN.md — Add four structured l4_event INFO log calls to retrieve_signs() Level 4 block (TDD)

### Phase 13: soda_level Propagation to HA Sensor
**Goal**: The HA sensor's extra_state_attributes exposes which fallback level (1-4) resolved the parking data
**Depends on**: Nothing (independent of Phase 12; touches different files)
**Requirements**: OBS-01
**Success Criteria** (what must be TRUE):
  1. HA sensor's extra_state_attributes contains a soda_level key with an integer value 1-4
  2. soda_level shows 1 or 2 for a location with a direct SODA match at the queried block
  3. soda_level shows 4 for a location that required the graph BFS fallback to find a covering span
  4. soda_level shows 0 when resolution fails before reaching the SODA query stage
  5. resolve_asp() ASPResult.soda_level is populated for non-debug callers (not just ASPDebugResult)
**Plans**: 2 plans

Plans:
- [ ] 13-01-PLAN.md — TDD Wave 0: write failing tests (test-local mirror + TestSodaLevelAttribute + TestASPResultSodaLevel)
- [ ] 13-02-PLAN.md — Implementation: thread soda_level through models, pipeline, coordinator, sensor, and vendored copies

### Phase 14: graph.json Size Reduction
**Goal**: graph.json is ≤4 MB so HA startup memory and cold-start latency are reduced
**Depends on**: Nothing (offline build-time change only; runtime code unchanged)
**Requirements**: PERF-01
**Success Criteria** (what must be TRUE):
  1. Running build_index.py produces a graph.json file that is ≤4 MB on disk
  2. Level 4 mid-span match rate against the existing set of known mid-span test blocks is unchanged after the rebuild
  3. BFS traversal through non-ASP intermediate segments still works (non-ASP 1-hop neighbors retained in graph)
**Plans**: 2 plans

Plans:
- [ ] 14-01-PLAN.md — TDD tests + 2-hop BFS filter + zstd write in build_index.py
- [ ] 14-02-PLAN.md — StreetGraph.load() .zst support + zstandard dependency + vendored mirror

### Phase 15: Queens and Manhattan Coverage Fix
**Goal**: Users in Queens get ASP results at >=50% success rate and Manhattan reaches >=60%
**Depends on**: Phase 12 (structured logs required to identify Queens failure point before writing normalization code)
**Requirements**: COV-02, COV-04
**Success Criteria** (what must be TRUE):
  1. GPS spot-check fixture set for Queens returns a Level 1 or Level 2 SODA match at >=50% of locations
  2. GPS spot-check fixture set for Manhattan returns a Level 1 or Level 2 SODA match at >=60% of locations
  3. Existing Brooklyn and Bronx spot-check fixtures show no regression after normalization changes
  4. Phase 12 logs from the audit script identify which of the three candidate failure points (build-time cross-street normalization, runtime name_variants expansion, or BFS cross-street PID lookup) causes the Queens gap
  5. The index rebuild for the fix also incorporates the Phase 14 graph.json size reduction in the same invocation
**Plans**: 2 plans

Plans:
- [x] 15-01-PLAN.md — Create GPS fixture files (Queens 25 locations, Manhattan 18 locations), audit script, and TDD RED tests for TPKE/CRES
- [x] 15-02-PLAN.md — Apply TPKE/CRES normalization fix, rebuild index, verify coverage thresholds via audit

### Phase 16: Queens Coverage Fix — Geocoded Fixtures + L3 Diagnosis
**Goal**: Queens address-geocoded fixture set achieves >=50% Level 1+2 SODA match rate after regenerating fixtures from real street addresses and fixing all safely fixable normalization gaps
**Depends on**: Phase 15 (TPKE/CRES normalization code already applied; this phase replaces the bad fixture set and goes deeper on remaining L3 failures)
**Requirements**: COV-02
**Success Criteria** (what must be TRUE):
  1. Queens fixture set of 25 GPS locations is regenerated from real street addresses via NYC GeoSearch geocoding (no random offsets)
  2. Fixtures are biased toward residential side streets where ASP is common (not wide avenues or commercial corridors)
  3. Audit script extended to show, for Level 3 failures, what CSCL from/to was sent vs what SODA from/to was in the response
  4. All L3 failures categorized: missing suffix, geometric mismatch, or SODA data gap
  5. All safely fixable L3 failures fixed (suffix table additions and/or `_cross_streets_match()` logic if warranted)
  6. Spatial index rebuilt with any new normalization changes
  7. Queens fixture set achieves Level 1+2 >=50% after rebuild
  8. Brooklyn and Bronx spot-check fixtures show no regression
**Plans**: 2 plans

Plans:
- [ ] 16-01-PLAN.md — Create geocoding script, regenerate Queens fixtures from real addresses, extend audit with L3 diagnostics
- [ ] 16-02-PLAN.md — Run L3 diagnostic audit, fix normalization gaps, rebuild index, human-verify Queens >=50%

### Phase 17: Manhattan Coverage Fix — Geocoded Fixtures + L3 Diagnosis
**Goal**: Manhattan address-geocoded fixture set achieves >=60% Level 1+2 SODA match rate using same approach as Phase 16
**Depends on**: Phase 16 (reuses geocoding script, extended audit script, and any normalization fixes discovered for Queens)
**Requirements**: COV-04
**Success Criteria** (what must be TRUE):
  1. Manhattan fixture set of 18 GPS locations regenerated from real street addresses via NYC GeoSearch
  2. Fixtures biased toward residential side streets (UWS, Harlem, East Village, Midtown side streets)
  3. Extended audit run against Manhattan fixtures using L3 diagnostic output from Phase 16
  4. Manhattan-specific normalization gaps discovered and fixed
  5. Spatial index rebuilt with Manhattan normalization additions
  6. Manhattan fixture set achieves Level 1+2 >=60% after rebuild
  7. Queens, Brooklyn, and Bronx spot-check fixtures show no regression
**Plans**: 2 plans

Plans:
- [ ] 17-01-PLAN.md — Populate Manhattan addresses in geocoding script, geocode fixtures, run L3 diagnostic audit
- [ ] 17-02-PLAN.md — Analyze L3 diagnostics, fix normalization gaps, rebuild index, human-verify Manhattan >=60%

### Phase 18: Vendored Signs Sync + Docs Cleanup
**Goal**: Close integration gap: structured Level 4 logging works in HA deployment path; REQUIREMENTS.md traceability is accurate
**Depends on**: Phase 12 (source of structured log entries to sync)
**Requirements**: OBS-02
**Gap Closure**: Closes OBS-02 vendored sync gap and Level 4 HA logging flow gap from v2.0-MILESTONE-AUDIT.md
**Success Criteria** (what must be TRUE):
  1. `custom_components/asp_parking/gps2asp/signs/__init__.py` Level 4 block matches `src/gps2asp/signs/__init__.py` (structured l4_event= INFO logs present)
  2. REQUIREMENTS.md traceability table shows OBS-01 as Complete, COV-02 mapped to Phases 15+16, COV-04 mapped to Phases 15+17
  3. All existing tests pass (no regressions)
**Plans**: 1 plan

Plans:
- [x] 18-01-PLAN.md — Sync Level 4 structured logging to vendored copy + fix REQUIREMENTS.md traceability

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. GPS-to-Street Resolution | v1.0 | 2/2 | Complete | 2026-02-21 |
| 2. ASP Sign Retrieval | v1.0 | 2/2 | Complete | 2026-02-22 |
| 3. Schedule Parsing & Next-Move | v1.0 | 2/2 | Complete | 2026-02-22 |
| 4. Home Assistant Integration | v1.0 | 3/3 | Complete | 2026-02-23 |
| 5. Bug Fixes and Tech Debt | v1.1 | 1/1 | Complete | 2026-02-27 |
| 6. Improve Confidence Scoring | v1.1 | 1/1 | Complete | 2026-02-28 |
| 7. Pipeline Stabilization | v1.1 | 2/2 | Complete | 2026-02-28 |
| 8. Refactor Architecture | v1.1 | 3/3 | Complete | 2026-03-01 |
| 9. Rebuild Spatial Index | v1.1 | 2/2 | Complete | 2026-03-01 |
| 10. Update Documentation | v1.1 | 1/1 | Complete | 2026-03-02 |
| 11. Improve ASP Coverage | v1.1 | 3/3 | Complete | 2026-03-03 |
| 12. Structured Level 4 Logging | v2.0 | 1/1 | Complete | 2026-03-15 |
| 13. soda_level Propagation | v2.0 | 2/2 | Complete | 2026-03-16 |
| 14. graph.json Size Reduction | v2.0 | 2/2 | Complete | 2026-03-17 |
| 15. Queens and Manhattan Coverage Fix | v2.0 | 2/2 | Complete    | 2026-03-26 |
| 16. Queens Coverage Fix — Geocoded Fixtures | 2/2 | Complete   | Complete    | 2026-03-26 |
| 17. Manhattan Coverage Fix — Geocoded Fixtures | 2/2 | Complete   | 2026-03-19 | — |
