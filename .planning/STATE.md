---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Bug Fixes
status: unknown
last_updated: "2026-03-01T14:43:43.273Z"
progress:
  total_phases: 6
  completed_phases: 3
  total_plans: 7
  completed_plans: 5
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-23)

**Core value:** Tell the user exactly when they need to move their car for ASP -- "next time to move is [datetime]"
**Current focus:** v1.1 bug fixes — Phase 7 complete

## Current Position

Milestone: v1.1 Bug Fixes
Phase: 08-refactor-architecture-and-streamline-pipeline
Current Plan: 1 of 2
Status: Plan 08-01 complete — pipeline.py created, __init__.py thinned, build/ moved to scripts/, 221 tests pass
Next: Plan 08-02 — rename _input_lat/_input_lon parameters and further pipeline cleanup

Progress: [====================] 100% v1.0 | Phase 8: [==========          ] 50%

## Performance Metrics

**v1.0 Velocity:**
- Total plans completed: 9
- Average duration: 8 min
- Total execution time: 1.26 hours
- Timeline: 2 days (2026-02-21 → 2026-02-22)

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1 | 2/2 | 49 min | 25 min |
| 2 | 2/2 | 7 min | 4 min |
| 3 | 2/2 | 7 min | 4 min |
| 4 | 3/3 | 7 min | 2 min |
| 5 | 1/1 | 10 min | 10 min |
| 6 | 1/1 | 8 min | 8 min |
| 7 | 2/2 | 6 min | 3 min |
| 8 | 1/2 | 2 min | 2 min |

## Accumulated Context

### Pending Todos

- Add env config for caching area range (v2)
- Parse non-ASP parking restrictions in future phase (v2+)
- Add HA diagnostics endpoint to asp_parking integration (v2)

### Completed in Phase 5

- Fixed ScheduleFound.next_window type mismatch (BUG-02) — widened to CleaningWindow | None
- Fixed venv pip wrapper shebangs stale after project directory rename (BUG-01)

### Completed in Phase 6

- Fixed PROSPECT PL case: 9.2ft from centerline on 30ft street now returns confidence=0.6133 (>= 0.6)
- Replaced absolute 10ft near-centerline guard with width-relative threshold (parking_lane_fraction * width / 2)
- Added _NYC_DEFAULT_WIDTHS dict for rw_type fallback when CSCL streetwidth is missing
- Added resolve_effective_width() public helper in confidence.py
- Added parking_lane_fraction=0.33 parameter to resolve(), resolve_segment(), and compute_confidence()
- Added street_width_ft field to ResolutionDebugInfo (post-fallback effective width)
- Enriched AmbiguousResolutionError messages with street_width, perp_dist, endpoint_dist
- Fixed NaN streetwidth in build_index.py (now stores 0.0 to trigger rw_type fallback)

### Completed in Phase 7

- Added soda_level: int = 1 field to SignRetrievalSuccess (all three return sites set explicitly)
- Created src/gps2asp/api_models.py with ASPResult (3 fields) and ASPDebugResult (13 fields)
- Wrote 8 failing async tests in tests/test_resolve_asp.py (TDD RED — Plan 07-01)
- Implemented resolve_asp() with @overload stubs wiring all three pipeline stages (Plan 07-02)
- AmbiguousResolutionError caught internally; OutsideNYCError/NoSegmentFoundError propagate
- Created examples/run_pipeline.py CLI live demo (PROSPECT PL default coordinates)
- All 8 resolve_asp tests pass GREEN; full suite 221 passed

### Decisions Made

- _classify_ambiguity() retains 10ft absolute heuristic for debug log labels only (not confidence algorithm)
- _NYC_DEFAULT_WIDTHS is a code constant, not runtime-configurable (per user decision)
- Fallback width is logged at DEBUG level only, not surfaced in error messages
- soda_level: int = 1 default on SignRetrievalSuccess preserves backwards compatibility
- Test mocking targets gps2asp.* namespace for Plan 07-02's implementation
- ASPDebugResult has exactly 13 fields per CONTEXT.md — parking_lane_fraction not exposed
- resolve_segment(x, y, ...) used instead of resolve(lat, lon) to avoid double coordinate conversion
- soda_level=0 in debug result when sign_result is not SignRetrievalSuccess
- [Phase 08]: resolve_asp() moved to pipeline.py; __init__.py is a 22-line thin re-export
- [Phase 08]: ASPDebugResult gains from_resolution() and from_error() classmethods
- [Phase 08]: Build tools moved from src/gps2asp/build/ to scripts/ at project root

### Roadmap Evolution

- Phase 5 added: Bug Fixes and Tech Debt (surfaced 2026-02-27 E2E test)
- Phase 6 added: Improve Confidence Scoring for NYC Street Widths (confidence=0.0 on 9.2ft centerline offset)
- Phase 7 added: Pipeline Stabilization — importable function with debug flag
- Phase 8 added: Refactor architecture and streamline pipeline
- Phase 9 added: Rebuild the spatial index
- Phase 10 added: Update documentation

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 1 | Fix gps2asp module not installed so pipeline script runs | 2026-02-28 | f835dc5 | [1-fix-gps2asp-module-not-installed-so-pipe](./quick/1-fix-gps2asp-module-not-installed-so-pipe/) |
| 2 | Lower confidence threshold default from 0.60 to 0.33 for testing | 2026-02-28 | 8d655c0 | [2-lower-confidence-threshold-default-to-0-](./quick/2-lower-confidence-threshold-default-to-0-/) |

### Blockers/Concerns

- nyc311calendar is alpha -- relevant for v2 suspension handling

## Session Continuity

Last session: 2026-03-01
Stopped at: Completed 08-01-PLAN.md — pipeline.py, thin __init__.py, scripts/, 221 tests pass
Resume file: None
