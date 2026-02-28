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
**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd:plan-phase 7 to break down)

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 7. Pipeline Stabilization | v1.1 | 0/? | Not started | — |
