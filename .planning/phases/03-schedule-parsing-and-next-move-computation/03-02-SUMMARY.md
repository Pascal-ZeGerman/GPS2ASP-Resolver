---
phase: 03-schedule-parsing-and-next-move-computation
plan: 02
subsystem: schedule
tags: [merge, next-move, timezone, zoneinfo, summary, compute-schedule, pipeline]

# Dependency graph
requires:
  - phase: 03-schedule-parsing-and-next-move-computation
    provides: ASPDay enum, TimeWindow, WeeklySchedule, ParseFailure, ScheduleResult union, parse_sign() parser
  - phase: 02-asp-sign-retrieval
    provides: SignRetrievalResult union (SignRetrievalSuccess, NoASPSigns, NoMatchFound)
provides:
  - merge_windows() for combining overlapping/adjacent windows per day
  - find_next_window() and find_active_window() with NYC timezone awareness
  - format_summary() for human-readable schedule strings
  - compute_schedule() public API accepting SignRetrievalResult and returning ScheduleResult
affects: [04-home-assistant-integration, v2-suspensions]

# Tech tracking
tech-stack:
  added: [zoneinfo]
  patterns: [conservative-window-merge, timezone-aware-datetime, same-meridiem-simplification]

key-files:
  created:
    - src/gps2asp/schedule/merge.py
    - src/gps2asp/schedule/next_move.py
    - src/gps2asp/schedule/summary.py
    - tests/test_schedule.py
  modified:
    - src/gps2asp/schedule/__init__.py

key-decisions:
  - "Conservative merge: earliest start, latest end when windows overlap (safer for avoiding tickets)"
  - "Source signs concatenated via semicolon join in merged TimeWindow.source_sign field"
  - "8-day lookahead (today + 7) to guarantee finding next weekly occurrence"
  - "Same-meridiem simplification in summary: '8:30 - 10 AM' not '8:30 AM - 10 AM'"
  - "Consecutive day ranges of 3+ use dash notation (MON-FRI), 2 days use ampersand (TUE & FRI)"

patterns-established:
  - "Window merge: groupby day, sort by start, extend on overlap (conservative)"
  - "Timezone-aware computation: all datetime.combine calls use tzinfo=NYC_TZ parameter"
  - "Summary generation: group by (start_time, end_time) tuple for compact multi-day display"

requirements-completed: [SCHED-04]

# Metrics
duration: 3min
completed: 2026-02-22
---

# Phase 3 Plan 02: Window Merge, Next-Move Computation, and compute_schedule() API Summary

**Conservative window merging, NYC-timezone-aware next-move computation, human-readable summary, and compute_schedule() pipeline entry point with 36 unit tests**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-22T17:31:12Z
- **Completed:** 2026-02-22T17:34:55Z
- **Tasks:** 2
- **Files created:** 4
- **Files modified:** 1

## Accomplishments
- merge_windows() combines overlapping/adjacent TimeWindows per day using conservative logic (earliest start, latest end) to avoid missed street cleaning
- find_next_window() and find_active_window() with full America/New_York timezone awareness, 8-day lookahead, and start-inclusive/end-exclusive semantics
- format_summary() generates compact human-readable strings like "TUE & FRI 11:30 AM - 1 PM" with same-meridiem simplification and consecutive-day dash notation
- compute_schedule() public API routes SignRetrievalResult variants, parses signs, merges windows, detects active windows, and computes next move datetime
- 36 comprehensive unit tests covering merge (6), next-window (6), active-window (6), summary (6), and full pipeline integration (12)

## Task Commits

Each task was committed atomically:

1. **Task 1: Window merging, next-move computation, and summary generation** - `fe64c2a` (feat)
2. **Task 2: Public API compute_schedule() and comprehensive tests** - `21c4f4b` (feat)

## Files Created/Modified
- `src/gps2asp/schedule/merge.py` - merge_windows() for combining overlapping/adjacent windows per day
- `src/gps2asp/schedule/next_move.py` - find_next_window() and find_active_window() with NYC timezone awareness
- `src/gps2asp/schedule/summary.py` - format_summary() for human-readable schedule strings
- `src/gps2asp/schedule/__init__.py` - Updated with compute_schedule() public API entry point and full re-exports
- `tests/test_schedule.py` - 36 unit tests for merge, next-move, summary, and compute_schedule integration

## Decisions Made
- Conservative merge strategy (earliest start, latest end) locked per user decision -- safer for avoiding parking tickets
- Source signs joined with "; " in merged TimeWindow for traceability
- 8-day lookahead in find_next_window (today through 7 days out) guarantees weekly cycle coverage
- Same-meridiem simplification: "8:30 - 10 AM" instead of "8:30 AM - 10 AM" for cleaner display
- Consecutive-day ranges (3+) use dash notation (MON-FRI), two days use ampersand (TUE & FRI)
- Start time is inclusive, end time is exclusive for active window detection

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Phase 3 complete: full pipeline from sign descriptions to next-move datetimes
- compute_schedule() ready for Phase 4 Home Assistant integration
- All 189 tests passing (36 new + 153 existing, zero regressions)
- End-to-end verified: SignRetrievalSuccess with known sign produces ScheduleFound with correct Tuesday 11:30AM datetime

## Self-Check: PASSED

- All 5 created/modified files verified on disk
- Commit fe64c2a (Task 1) verified in git log
- Commit 21c4f4b (Task 2) verified in git log
- 189/189 tests passing (36 new + 153 existing, zero regressions)

---
*Phase: 03-schedule-parsing-and-next-move-computation*
*Completed: 2026-02-22*
