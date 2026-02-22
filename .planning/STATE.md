# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-21)

**Core value:** Tell the user exactly when they need to move their car for ASP -- "next time to move is [datetime]"
**Current focus:** Phase 3: Schedule Parsing

## Current Position

Phase: 3 of 4 (Schedule Parsing)
Plan: 1 of ? in current phase
Status: Ready
Last activity: 2026-02-22 -- Completed 02-02-PLAN.md (public API, tests, Phase 2 complete)

Progress: [============........] 50%

## Performance Metrics

**Velocity:**
- Total plans completed: 4
- Average duration: 15 min
- Total execution time: 1.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1 | 2/2 | 49 min | 25 min |
| 2 | 2/2 | 7 min | 4 min |

**Recent Trend:**
- Last 5 plans: 6min, 43min, 4min, 3min
- Trend: Phase 2 fast execution (building on established patterns)

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: 4-phase linear pipeline (GPS -> Signs -> Schedule -> HA) derived from requirement dependencies
- [Roadmap]: Suspensions, caching, and notifications deferred to v2 per REQUIREMENTS.md scoping
- [01-01]: Used exceptions (not Result objects) for error handling -- cleaner for async pipeline
- [01-01]: Confidence threshold default 0.6 based on GPS accuracy math
- [01-01]: Hard cutoff at <10ft (centerline) and <30ft (intersection) returning 0.0 confidence
- [01-01]: has_asp defaults to False, will be pre-computed by build script in Plan 02
- [01-02]: R-tree built with index.insert() loop (not generator) -- generator produces empty files
- [01-02]: Cross streets derived via 5ft-tolerance node-to-segment spatial lookup
- [01-02]: has_asp pre-computed from SODA API parking signs with pagination
- [01-02]: Integration tests use session-scoped fixtures, skip when index not built
- [02-01]: Suffix expansion uses rsplit word-boundary matching to avoid false matches
- [02-01]: Directional prefix expansion guards on next-char-is-digit (ESSEX != EAST+SSEX)
- [02-01]: httpx.AsyncClient created fresh per fetch_signs call (not stored as instance state)
- [02-01]: Per-page retry with IncompleteResultsError for partial pagination failures
- [02-02]: Level 1 uses SODA-normalized names for highest-probability match
- [02-02]: Level 2 iterates variant combos via itertools.product, short-circuits on first hit
- [02-02]: Level 3 client-side cross-street matching tries from/to swapped (SODA directionality may differ)
- [02-02]: Registered custom pytest integration marker for clean test output

### Pending Todos

None yet.

### Blockers/Concerns

- Research flags sign description parser as needing empirical format catalog from live SODA dataset before writing parser (Phase 3 pre-task)
- nyc311calendar is alpha -- relevant for v2 suspension handling but not v1

## Session Continuity

Last session: 2026-02-22
Stopped at: Completed 02-02-PLAN.md (Phase 2 complete)
Resume file: None
