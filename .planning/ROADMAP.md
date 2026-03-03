# Roadmap: GPS2ASP Resolver

## Milestones

- ✅ **v1.0 MVP** — Phases 1-4 (shipped 2026-02-23)
- 🔄 **v1.1 Bug Fixes & Improvements** — Phases 5-7 (in progress)

## Phases

<details>
<summary>✅ v1.0 MVP (Phases 1-4) — SHIPPED 2026-02-23</summary>

- [x] Phase 1: GPS-to-Street Resolution (2/2 plans) — completed 2026-02-21
- [x] Phase 2: ASP Sign Retrieval (2/2 plans) — completed 2026-02-22
- [x] Phase 3: Schedule Parsing and Next-Move Computation (2/2 plans) — completed 2026-02-22
- [x] Phase 4: Home Assistant Integration (3/3 plans) — completed 2026-02-23

Full details: `.planning/milestones/v1.0-ROADMAP.md`

</details>

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. GPS-to-Street Resolution | v1.0 | 2/2 | Complete | 2026-02-21 |
| 2. ASP Sign Retrieval | v1.0 | 2/2 | Complete | 2026-02-22 |
| 3. Schedule Parsing & Next-Move | v1.0 | 2/2 | Complete | 2026-02-22 |
| 4. Home Assistant Integration | v1.0 | 3/3 | Complete | 2026-02-23 |

### v1.1 Bug Fixes

#### Phase 5: Bug Fixes and Tech Debt

**Goal:** Fix the `ScheduleFound.next_window` type mismatch and address venv path staleness after directory rename
**Requirements**: Surfaced during end-to-end pipeline test on 2026-02-27
**Depends on:** Phase 4
**Plans:** 1 plan

Plans:
- [x] 05-01-PLAN.md — Fix venv path staleness (BUG-01) and ScheduleFound.next_window type mismatch (BUG-02)

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 5. Bug Fixes and Tech Debt | v1.1 | 1/1 | Complete | 2026-02-27 |

#### Phase 6: Improve Confidence Scoring for NYC Street Widths

**Goal:** Improve the confidence scoring algorithm to use real NYC street width data so that the side-of-street determination is more accurate for wide vs narrow streets
**Requirements**: Observed confidence=0.0 for coordinates 9.2ft from centerline — threshold is too sensitive on narrow streets
**Depends on:** Phase 5
**Plans:** 1 plan

Plans:
- [x] 06-01-PLAN.md — Replace absolute near-centerline guard with width-relative formula; add rw_type fallback, NaN fix, and street_width_ft debug field

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 6. Improve Confidence Scoring | v1.1 | 1/1 | Complete | 2026-02-28 |

#### Phase 7: Pipeline Stabilization — Importable Function with Debug Flag

**Goal:** Expose the full GPS→schedule pipeline as a single importable `resolve_asp(lat, lon, debug=False)` function; when `debug=True` return rich intermediate state for inspection and testing
**Requirements**: Observed during 2026-02-27 E2E test — callers had to manually wire three pipeline stages together; a debug flag would have surfaced the confidence=0.0 and type mismatch issues immediately
**Depends on:** Phase 6
**Plans:** 2/2 plans complete

Plans:
- [x] TBD (run /gsd:plan-phase 7 to break down) (completed 2026-02-28)

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 7. Pipeline Stabilization | 2/2 | Complete   | 2026-02-28 | — |

### Phase 8: Refactor architecture and streamline pipeline

**Goal:** Clean up API surface, module layout, and code quality — move `resolve_asp()` to `pipeline.py`, thin `__init__.py`, relocate build tools to `scripts/`, and address all 22 identified rough edges
**Requirements**: Internal code quality and architecture improvement (no new capabilities)
**Depends on:** Phase 7
**Plans:** 3/3 plans complete

Plans:
- [ ] 08-01-PLAN.md — API surface + module layout: create `pipeline.py`, thin `__init__.py`, move `build/` to `scripts/`, add `ASPDebugResult` factory classmethods, update test imports
- [ ] 08-02-PLAN.md — Must-Fix + High Priority quality items: rename `_input_lat`/`_input_lon`, fix bare except, eliminate duplicate `resolve_effective_width()` call, `compute_confidence()` signature, module-level `import logging`, extract `_try_query()` helper, remove dead `SegmentCandidate` fields
- [ ] 08-03-PLAN.md — Medium + Nice-to-Have quality items: replace `assert isinstance`, name magic number constants, annotate `SpatialIndex` types, clarify double normalization in `_cross_streets_match()`

### Phase 9: Rebuild the spatial index

**Goal:** Fix three bugs in scripts/build_index.py that cause systematic false negatives in has_asp_left/has_asp_right flags, then rebuild the on-disk spatial index so the flags are correct
**Requirements**: Internal data quality fix — directional prefix normalization, voided sign filter, dead-end alignment with SODA format
**Depends on:** Phase 8
**Plans:** 1/2 plans executed

Plans:
- [ ] 09-01-PLAN.md — Fix all three bugs in build_index.py and add unit tests
- [ ] 09-02-PLAN.md — Run the spatial index rebuild and validate per-borough coverage

### Phase 10: Update documentation

**Goal:** [To be planned]
**Requirements**: TBD
**Depends on:** Phase 9
**Plans:** 1/1 plans complete

Plans:
- [x] TBD (run /gsd:plan-phase 10 to break down) (completed 2026-03-02)

### Phase 11: Improve ASP coverage through mid-span coverage

**Goal:** Increase ASP coverage by propagating has_asp flags to interior CSCL blocks via BFS graph traversal of multi-block SODA spans, and add a Level 4 runtime fallback to retrieve signs for mid-span blocks
**Requirements**: Manhattan 29.5% coverage (target 60-80%), Brooklyn 47.9% (target 50-65%) -- root cause is multi-block SODA spans vs single-block CSCL granularity
**Depends on:** Phase 10
**Plans:** 3 plans

Plans:
- [ ] 11-01-PLAN.md — Build-time graph construction and BFS propagation for mid-span ASP coverage
- [ ] 11-02-PLAN.md — Runtime Level 4 fallback with StreetGraph for mid-span sign retrieval
- [ ] 11-03-PLAN.md — Rebuild spatial index with graph propagation and validate coverage targets
