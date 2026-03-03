---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Bug Fixes
status: unknown
last_updated: "2026-03-03T14:36:59.376Z"
progress:
  total_phases: 7
  completed_phases: 6
  total_plans: 13
  completed_plans: 12
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-23)

**Core value:** Tell the user exactly when they need to move their car for ASP -- "next time to move is [datetime]"
**Current focus:** v1.1 bug fixes — Phase 11 in progress

## Current Position

Milestone: v1.1 Bug Fixes
Phase: 11-improve-asp-coverage-through-mid-span-coverage
Current Plan: 2 of 3 (complete)
Status: Phase 11 Plan 02 complete — StreetGraph class with BFS span_distance scoring; Level 4 wired into retrieve_signs(); 253 tests pass
Next: Phase 11 Plan 03 (if exists) or Phase 11 complete

Progress: [====================] 100% v1.0 | Phase 9: [====================] 100%

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
| 8 | 3/3 | 14 min | 5 min |
| 9 | 2/2 | 15 min | 8 min |

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
- [Phase 08-02]: compute_confidence() accepts effective_width_ft (pre-resolved by caller, no rw_type param)
- [Phase 08-02]: _try_query() accepts optional prefetched_records for Level 3 broad-query+client-filter pattern
- [Phase 08-02]: resolve_segment() params renamed input_lat/input_lon (removed underscore prefix)
- [Phase 08-03]: Per-file named constants for magic numbers (not shared constants.py) — keeps modules independently testable and self-contained
- [Phase 08-03]: _NEAR_INTERSECTION_THRESHOLD_FT duplicated in resolver/__init__.py and confidence.py with comment noting they must match — acceptable for two-file duplication
- [Phase 08-03]: Double normalization in _cross_streets_match() retained as-is — clarified by comments, no behavior change needed
- [Phase 09-01]: _normalize_street_name() delegates to normalize_to_soda() — eliminates duplication and ensures build-time parity with runtime sign queries
- [Phase 09-01]: Dead-end sentinel changed from "DEAD END" to "" (empty string) — SODA API uses empty strings for missing cross streets
- [Phase 09-01]: SODA filter changed to sign_design_voided_on_date IS NULL — record_type='Current' was a no-op (all records have that type)
- [Quick-4]: normalize_to_soda() directional prefix expansion widened from digit-only to any continuation — safe because startswith('abbrev + space') guard already prevents false positives
- [Quick-4]: Directional suffix expansion added as final step so W END AVE -> WEST END AVENUE (not WEST END AVE)
- [Quick-4]: Internal whitespace collapsed to single space in normalize_to_soda() to handle CSCL/SODA spacing inconsistencies
- [Quick-4]: Remaining Manhattan coverage gap (29.5% vs 40% target) is due to multi-block SODA spans vs single-block CSCL granularity — deferred to Phase 11
- [Phase 09-rebuild-the-spatial-index]: Remaining Manhattan coverage gap (29.5% vs 40% target) deferred to Phase 11 — multi-block SODA spans vs single-block CSCL granularity
- [Phase 09-rebuild-the-spatial-index]: Staten Island 0.0% coverage is a SODA data gap — deferred to Phase 11 triage
- [Phase 11-01]: _compute_cross_streets() accepts optional node_lookup to avoid double computation when caller also needs it for graph construction
- [Phase 11-01]: graph.json written for all segments with adjacency (not filtered to ASP-only) — Level 4 can navigate between any adjacent blocks
- [Phase 11-01]: BFS discards traversal if end_pids never reached — prevents false-positive has_asp flags (Pitfall 4)
- [Phase 11-01]: max_depth=30 for BFS prevents runaway on long avenues; propagation_stats added to build_info.json for observability
- [Phase Phase 11]: span_distance BFS returns 0 for adjacent spans sharing an endpoint cross street (correct behavior -- those segments cover the block)
- [Phase Phase 11]: Level 4 only fires when any_soda_results is False (no records from Levels 1-3) -- not when records exist but have no broom signs

### Roadmap Evolution

- Phase 5 added: Bug Fixes and Tech Debt (surfaced 2026-02-27 E2E test)
- Phase 6 added: Improve Confidence Scoring for NYC Street Widths (confidence=0.0 on 9.2ft centerline offset)
- Phase 7 added: Pipeline Stabilization — importable function with debug flag
- Phase 8 added: Refactor architecture and streamline pipeline
- Phase 9 added: Rebuild the spatial index
- Phase 10 added: Update documentation
- Phase 11 added: Improve ASP coverage through mid-span coverage

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 1 | Fix gps2asp module not installed so pipeline script runs | 2026-02-28 | f835dc5 | [1-fix-gps2asp-module-not-installed-so-pipe](./quick/1-fix-gps2asp-module-not-installed-so-pipe/) |
| 2 | Lower confidence threshold default from 0.60 to 0.33 for testing | 2026-02-28 | 8d655c0 | [2-lower-confidence-threshold-default-to-0-](./quick/2-lower-confidence-threshold-default-to-0-/) |
| 3 | Fix five code review issues: CLAUDE.md stale, missing future-import, wrong comments, dead fields | 2026-03-01 | 77f3ba4 | [3-fix-5-code-review-issues-claude-md-stale](./quick/3-fix-5-code-review-issues-claude-md-stale/) |
| 4 | Fix named directional normalization: expand W BROADWAY/CENTRAL PARK W, collapse whitespace, rebuild index | 2026-03-01 | 094a9f5 | [4-fix-named-directional-normalization-in-n](./quick/4-fix-named-directional-normalization-in-n/) |

### Blockers/Concerns

- nyc311calendar is alpha -- relevant for v2 suspension handling

## Session Continuity

Last session: 2026-03-03
Stopped at: Plan 11-02 complete — Level 4 mid-span fallback implemented; StreetGraph class in graph.py with BFS span_distance scoring and lazy singleton; Level 4 wired into retrieve_signs() after Level 3; soda_level=4 set on results; graceful degradation when graph.json absent; 253 tests pass.
Resume file: None
