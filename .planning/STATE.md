---
gsd_state_version: 1.0
milestone: v3.0
milestone_name: Suspension Handling
status: Executing Phase 23
stopped_at: Phase 23 context gathered
last_updated: "2026-04-05T00:32:57.496Z"
progress:
  total_phases: 5
  completed_phases: 4
  total_plans: 9
  completed_plans: 7
  percent: 78
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-30)

**Core value:** Tell the user exactly when they need to move their car for ASP — or that they don't need to move because ASP is suspended.
**Current focus:** Phase 23 — ha-nyc311-bridge

## Current Position

Phase: 23 (ha-nyc311-bridge) — EXECUTING
Plan: 1 of 2

## Phase Summary (v3.0)

| Phase | Goal | Requirements | Status |
|-------|------|--------------|--------|
| 19. Suspension Package Foundation | Users see holiday suspensions with no network call | SUSP-01 | Not started |
| 20. Suspension Merge Layer and Pipeline Wiring | Single authoritative answer combining schedule + suspension | SUSP-03 (library) | Not started |
| 21. Direct 311 API Poller | Weather/emergency suspension via 311 API; fail-open | SUSP-02 | Not started |
| 22. HA Coordinator and Sensor Integration | Live suspension status in HA sensor and binary sensor | SUSP-03 (HA) | Not started |
| 23. ha-nyc311 Bridge | Auto-detect ha-nyc311; no duplicate API calls | SUSP-04 | Not started |

## Performance Metrics

**v1.0 Velocity:**

- Total plans completed: 9
- Average duration: 8 min
- Total execution time: 1.26 hours
- Timeline: 2 days (2026-02-21 → 2026-02-22)

**By Phase (v1.0 + v1.1):**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1 | 2/2 | 49 min | 25 min |
| 2 | 2/2 | 7 min | 4 min |
| 3 | 2/2 | 7 min | 4 min |
| 4 | 3/3 | 7 min | 2 min |
| 5 | 1/1 | 10 min | 10 min |
| 6 | 1/1 | 8 min | 8 min |
| 7 | 2/2 | 6 min | 3 min |
| 8 | 3/3 | 14 min | 5 min |
| 9 | 2/2 | 15 min | 8 min |
| 10 | 1/1 | — | — |
| 11 | 3/3 | — | — |
| Phase 12-structured-level-4-logging P01 | 7 | 2 tasks | 2 files |
| Phase 13-soda-level-propagation P01 | 5 | 3 tasks | 2 files |
| Phase 13 P02 | 7 | 3 tasks | 9 files |
| Phase 14-graph-json-size-reduction P01 | 8 | 2 tasks | 2 files |
| Phase 14 P02 | 5 | 2 tasks | 4 files |
| Phase 15-queens-and-manhattan-coverage-fix P01 | 4 | 2 tasks | 4 files |
| Phase 16 P01 | 5 | 2 tasks | 3 files |
| Phase 16 P02 | 5 | 1 tasks | 0 files |
| Phase 17 P01 | 9 | 2 tasks | 2 files |
| Phase 17 P02 | 13 | 2 tasks | 3 files |
| Phase 15 P02 | 152 | 3 tasks | 2 files |
| Phase 18 P01 | 5 | 2 tasks | 2 files |
| Phase 19 P01 | 7 | 3 tasks | 6 files |
| Phase 20-suspension-merge-layer-and-pipeline-wiring P01 | 15 | 2 tasks | 4 files |
| Phase 20 P02 | 10 | 2 tasks | 4 files |
| Phase 21 P01 | 4 | 2 tasks | 2 files |
| Phase 21 P02 | 2 | 3 tasks | 3 files |

## Accumulated Context

### Key Decisions (v3.0 Roadmap)

- SUSP-03 split across Phase 20 (pure library: apply_suspension(), merge rules, schema changes) and Phase 22 (HA layer: coordinator, sensor, binary_sensor) — merge layer must be stable before HA wiring
- Phase 21 (311 poller) depends on Phase 19 (SuspensionStatus model) but not on Phase 20 (merge layer) — can be planned in parallel with Phase 20 if desired; Phase 22 needs both
- Phase 23 (ha-nyc311 bridge) is optional optimization — adds no correctness, only eliminates duplicate API polling; can be deferred to v3.1 without user-visible loss
- nyc311calendar PyPI package must NOT be added — aiohttp conflict + alpha quality; call 311 API directly via existing httpx client
- SuspensionStatus must use typed enum/Literal source field, never a raw bool — prevents NOT_IN_EFFECT conflation with SUSPENDED (research Pitfall 2)
- Lazy merge in sensor native_value property, not coordinator — prevents race condition between GPS events and suspension poll (research Pitfall 3)
- Date derivation must always use datetime.now(NYC_TZ).date() — never date.today() which returns UTC on HA servers (research Pitfall 4)
- Vendored copy sync (custom_components/asp_parking/gps2asp/suspension/) must happen alongside Phases 19-21; do not defer
- suspended: bool = False hooks already present on ScheduleFound and ASPActiveNow from v2.0 — confirmed by research

### Key Architecture Decisions (from research)

- Suspension is a post-pipeline annotation (Stage 4), not a replacement for any pipeline stage
- apply_suspension() is a pure function: ScheduleFound/ASPActiveNow + SuspensionStatus -> ScheduleResult
- Coordinator holds schedule_result and suspension_state as separate fields — merged lazily at sensor read time
- Three new coordinator data flow paths: suspension timer → re-apply to cached schedule; midnight reset → fetch new day; ha-nyc311 state change → immediate re-apply
- resolution_reason attribute distinguishes all six meaningful states: suspended_holiday, suspended_emergency, no_asp_on_block, no_data_for_block, active, unknown
- 311 API endpoint: https://api.nyc.gov/public/api/GetCalendar; auth header: Ocp-Apim-Subscription-Key; four status strings: IN_EFFECT, NOT_IN_EFFECT, SUSPENDED, NO_INFORMATION

### Key Decisions (v2.0 Roadmap — retained for context)

- Phase 12 before Phase 15: structured logs are the diagnostic tool for identifying Queens failure point
- Phase 13 and Phase 12 are independent (different files); can be planned in parallel if desired
- Phase 14 (graph.json filter) is fully offline; its rebuild is scheduled to combine with Phase 15's index rebuild
- COV-03 coordinator migration explicitly deferred to v2.x; soda_level achievable without it
- Queens failure point unknown until Phase 12 logs are analyzed — three candidates: build-time cross-street normalization, runtime name_variants() coverage, BFS cross-street PID lookup
- zstandard compression is conditional: add only if ASP + 1-hop neighbor filter alone exceeds 4 MB
- Coverage target is runtime Level 1/2 success rate (GPS spot-check fixtures), not build_info.json segment counts

### Pending Todos (from v1.1 and v2.0)

- Add env config for caching area range (v2.x CACHE-02) — deferred
- Parse non-ASP parking restrictions in future phase (v3+) — deferred
- Add HA diagnostics endpoint to asp_parking integration (v2.x) — deferred
- Schedule monthly spatial index rebuild in HA integration — deferred
- COV-03: Migrate HA coordinator to use resolve_asp() — deferred past v3.0

### Blockers/Concerns

- 311 API response field names: exact JSON keys should be confirmed by reading nyc311calendar services.py before Phase 21 implementation (10-minute code read; not blocking roadmap)
- NYC DOT ICS URL exact path: inferred from PDF URL pattern; not validated by live download; hardcoded-dates fallback available
- NYC 311 API rate limits: not published; 60-minute default is a conservative assumption consistent with aspnyc.info's confirmed operation

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260424-urm | Make the repo HACS ready so it can be added as a custom repo | 2026-04-25 | 21d1525 | [260424-urm-make-the-repo-hacs-ready-so-it-can-be-ad](./quick/260424-urm-make-the-repo-hacs-ready-so-it-can-be-ad/) |

## Session Continuity

Last session: 2026-04-04T19:02:50.677Z
Stopped at: Phase 23 context gathered
Resume file: .planning/phases/23-ha-nyc311-bridge/23-CONTEXT.md
