---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Bug Fixes
status: active
last_updated: "2026-02-28T03:55:00.000Z"
progress:
  total_phases: 3
  completed_phases: 2
  total_plans: 2
  completed_plans: 2
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-23)

**Core value:** Tell the user exactly when they need to move their car for ASP -- "next time to move is [datetime]"
**Current focus:** v1.1 bug fixes — Phase 6 complete, move to Phase 7

## Current Position

Milestone: v1.1 Bug Fixes
Phase: 06-improve-confidence-scoring-to-account-for-nyc-street-widths
Current Plan: 1 of 1
Status: Plan 06-01 complete
Next: Phase 6 complete — move to Phase 7 (Pipeline Stabilization)

Progress: [====================] 100% v1.0 | Phase 6: [====================] 100%

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

### Decisions Made

- _classify_ambiguity() retains 10ft absolute heuristic for debug log labels only (not confidence algorithm)
- _NYC_DEFAULT_WIDTHS is a code constant, not runtime-configurable (per user decision)
- Fallback width is logged at DEBUG level only, not surfaced in error messages

### Roadmap Evolution

- Phase 5 added: Bug Fixes and Tech Debt (surfaced 2026-02-27 E2E test)
- Phase 6 added: Improve Confidence Scoring for NYC Street Widths (confidence=0.0 on 9.2ft centerline offset)
- Phase 7 added: Pipeline Stabilization — importable function with debug flag

### Blockers/Concerns

- nyc311calendar is alpha -- relevant for v2 suspension handling

## Session Continuity

Last session: 2026-02-28
Stopped at: Completed 06-01-PLAN.md — Phase 6 plan 1 of 1 done
Resume file: None
