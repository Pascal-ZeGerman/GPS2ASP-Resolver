---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Full Borough Coverage
status: in_progress
stopped_at: Completed 14-02-PLAN.md
last_updated: "2026-03-17T02:12:49.294Z"
last_activity: 2026-03-17 — Phase 14 complete (graph.json filter + zstandard compression)
progress:
  total_phases: 4
  completed_phases: 3
  total_plans: 5
  completed_plans: 5
  percent: 50
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-13)

**Core value:** Tell the user exactly when they need to move their car for ASP — "next time to move is [datetime]"
**Current focus:** v2.0 Full Borough Coverage — Phase 12 next

## Current Position

Milestone: v2.0 Full Borough Coverage
Phase: 14-graph-json-size-reduction (Plan 2 of 2 complete)
Plan: 02 complete
Status: Complete
Last activity: 2026-03-17 — Phase 14 Plan 02 runtime zstandard decompression complete

Progress: [##########] 100% (2/2 plans complete in Phase 14)

## Phase Summary (v2.0)

| Phase | Goal | Requirements | Status |
|-------|------|--------------|--------|
| 12. Structured Level 4 Logging | Level 4 behavior visible in HA logs | OBS-02 | Not started |
| 13. soda_level Propagation | soda_level in HA sensor attributes | OBS-01 | Complete (2/2 plans) |
| 14. graph.json Size Reduction | graph.json ≤4 MB at build time | PERF-01 | Complete (2/2 plans) |
| 15. Queens and Manhattan Coverage Fix | Queens ≥50%, Manhattan ≥60% | COV-02, COV-04 | Not started |

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

## Accumulated Context

### Key Decisions (v2.0 Roadmap)

- Phase 12 before Phase 15: structured logs are the diagnostic tool for identifying Queens failure point
- Phase 13 and Phase 12 are independent (different files); can be planned in parallel if desired
- Phase 14 (graph.json filter) is fully offline; its rebuild is scheduled to combine with Phase 15's index rebuild
- COV-03 coordinator migration explicitly deferred to v2.x; soda_level achievable without it
- Queens failure point unknown until Phase 12 logs are analyzed — three candidates: build-time cross-street normalization, runtime name_variants() coverage, BFS cross-street PID lookup
- zstandard compression is conditional: add only if ASP + 1-hop neighbor filter alone exceeds 4 MB
- Coverage target is runtime Level 1/2 success rate (GPS spot-check fixtures), not build_info.json segment counts

### Pending Todos (from v1.1)

- Add env config for caching area range (v2.x CACHE-02)
- Parse non-ASP parking restrictions in future phase (v3+)
- Add HA diagnostics endpoint to asp_parking integration (v2.x)
- Schedule monthly spatial index rebuild in HA integration
- Write scripts/audit_queens_coverage.py to drive Phase 15 diagnosis

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
- [Phase 11-03]: Manhattan 58.2% accepted as close enough to 60-80% target (was 29.5% — near-double improvement)
- [Phase 11-03]: Brooklyn 74.1% accepted above 50-65% ceiling — user approved, no action required
- [Phase 11-03]: 6 pre-existing socket-blocked integration tests not counted as regressions from this phase
- [Phase 12-01]: l4_entry fires before on_variants loop (once per Level 4 activation, not once per variant)
- [Phase 12-01]: l4_match replaces old unstructured 'Level 4 matched' log — no duplicate logs
- [Phase 12-01]: l4_no_records omits span_candidates to distinguish empty-SODA case (C) from unreachable-span case (B)
- [Phase 12-01]: Tests use _CapturingHandler (custom logging.Handler) instead of caplog fixture for async test compatibility
- [Quick-260316-cvs]: _format_move_time() uses %-I:%M %p strftime (no-leading-zero 12h, Linux) with 12h urgency threshold
- [Quick-260316-cvs]: ISO datetime attributes (next_window_start/end) deliberately unchanged — raw ISO retained for programmatic/automation use
- [Quick-260316-cvs]: urgency key absent when next_window is None — avoids misleading urgency with no concrete move datetime
- [Phase 13-01]: TestSodaLevelAttribute tests pass immediately (test-local mirror, not production code) — TDD contract verified by Plan 02 integration
- [Phase 13-01]: TestASPResultSodaLevel tests intentionally RED (AttributeError on ASPResult.soda_level) — Plan 02 makes them GREEN
- [Phase 13]: NoMatchFound test fixture corrected: removed invalid kwargs that NoMatchFound does not accept
- [Phase 13]: Generic except Exception in coordinator retains last soda_level (same pattern as sign_count)
- [Phase 14-01]: Filter function defined as reference impl in test file since scripts/ is not importable; identical copy in build_index.py
- [Phase 14-01]: 2-hop BFS from ASP seeds: hop0=seeds, hop1=neighbors of seeds, hop2=neighbors of hop1; compact JSON separators before zstd compression
- [Phase 14]: zstandard stream_reader with TextIOWrapper for memory-efficient decompression of graph.json.zst

### Roadmap Evolution

- Phase 5 added: Bug Fixes and Tech Debt (surfaced 2026-02-27 E2E test)
- Phase 6 added: Improve Confidence Scoring for NYC Street Widths (confidence=0.0 on 9.2ft centerline offset)
- Phase 7 added: Pipeline Stabilization — importable function with debug flag
- Phase 8 added: Refactor architecture and streamline pipeline
- Phase 9 added: Rebuild the spatial index
- Phase 10 added: Update documentation
- Phase 11 added: Improve ASP coverage through mid-span coverage
- Phases 12-15 added: v2.0 Full Borough Coverage roadmap (2026-03-13)

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 1 | Fix gps2asp module not installed so pipeline script runs | 2026-02-28 | f835dc5 | [1-fix-gps2asp-module-not-installed-so-pipe](./quick/1-fix-gps2asp-module-not-installed-so-pipe/) |
| 2 | Lower confidence threshold default from 0.60 to 0.33 for testing | 2026-02-28 | 8d655c0 | [2-lower-confidence-threshold-default-to-0-](./quick/2-lower-confidence-threshold-default-to-0-/) |
| 3 | Fix five code review issues: CLAUDE.md stale, missing future-import, wrong comments, dead fields | 2026-03-01 | 77f3ba4 | [3-fix-5-code-review-issues-claude-md-stale](./quick/3-fix-5-code-review-issues-claude-md-stale/) |
| 4 | Fix named directional normalization: expand W BROADWAY/CENTRAL PARK W, collapse whitespace, rebuild index | 2026-03-01 | 094a9f5 | [4-fix-named-directional-normalization-in-n](./quick/4-fix-named-directional-normalization-in-n/) |
| 260316-cvs | Format datetime string in HA sensor: human-friendly native_value + urgency attribute | 2026-03-16 | 88f580d | [260316-cvs-format-datetime-string-in-ha-sensor-for-](./quick/260316-cvs-format-datetime-string-in-ha-sensor-for-/) |

### Blockers/Concerns

- nyc311calendar is alpha -- relevant for v2 suspension handling
- Queens failure point identity unknown — will be diagnosed in Phase 15 using Phase 12 logs

## Session Continuity

Last session: 2026-03-17T02:12:49.285Z
Stopped at: Completed 14-02-PLAN.md
Resume file: None
