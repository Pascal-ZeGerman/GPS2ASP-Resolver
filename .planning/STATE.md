# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-21)

**Core value:** Tell the user exactly when they need to move their car for ASP -- "next time to move is [datetime]"
**Current focus:** Phase 4: Home Assistant Integration

## Current Position

Phase: 4 of 4 (Home Assistant Integration)
Plan: 2 of 3 in current phase
Status: Executing Phase 4
Last activity: 2026-02-22 -- Completed 04-01-PLAN.md (foundation files and coordinator)

Progress: [================....] 80%

## Performance Metrics

**Velocity:**
- Total plans completed: 7
- Average duration: 10 min
- Total execution time: 1.18 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1 | 2/2 | 49 min | 25 min |
| 2 | 2/2 | 7 min | 4 min |
| 3 | 2/2 | 7 min | 4 min |
| 4 | 1/3 | 2 min | 2 min |

**Recent Trend:**
- Last 5 plans: 3min, 4min, 3min, 2min
- Trend: Consistently fast execution (established patterns accelerating development)

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
- [03-01]: ASPDay as IntEnum with Monday=0 matching datetime.weekday() for direct comparison
- [03-01]: v2 suspension hook via suspended=False field on ScheduleFound and ASPActiveNow
- [03-01]: Prefix-based rejection gate: signs must match standard NO PARKING prefix or return None
- [03-01]: Day extraction order: EXCEPT -> dash range -> individual names (prevents MONDAY-FRIDAY misparse)
- [03-02]: Conservative merge: earliest start, latest end when windows overlap (safer for tickets)
- [03-02]: Source signs joined with "; " in merged TimeWindow for traceability
- [03-02]: 8-day lookahead guarantees finding next weekly occurrence
- [03-02]: Same-meridiem simplification and consecutive-day dash notation in summary
- [03-02]: Start time inclusive, end time exclusive for active window detection
- [04-01]: Custom coordinator (not DataUpdateCoordinator) since GPS events are the data source
- [04-01]: ASPParkingData is mutable dataclass (not frozen) -- coordinator updates incrementally
- [04-01]: Debouncer with 5s cooldown and immediate=False to coalesce GPS jitter
- [04-01]: Pipeline errors retain last known schedule (fall back, not clear)
- [04-01]: OutsideNYC and NoSegmentFound produce distinct special_state sentinels

### Pending Todos

- Add env config for caching area range
- Parse non-ASP parking restrictions in future phase
- Add HA diagnostics endpoint to asp_parking integration (v2)

### Blockers/Concerns

- nyc311calendar is alpha -- relevant for v2 suspension handling but not v1

## Session Continuity

Last session: 2026-02-22
Stopped at: Completed 04-01-PLAN.md (foundation files and event-driven coordinator)
Resume file: None
