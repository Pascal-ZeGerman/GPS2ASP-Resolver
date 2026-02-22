---
phase: 03-schedule-parsing-and-next-move-computation
plan: 01
subsystem: schedule
tags: [regex, parser, enum, dataclass, frozen, asp-signs]

# Dependency graph
requires:
  - phase: 02-asp-sign-retrieval
    provides: SignRetrievalResult union, SignRecord with sign_description text
provides:
  - ASPDay enum (Monday=0 through Sunday=6) matching datetime.weekday()
  - TimeWindow, CleaningWindow, WeeklySchedule frozen dataclasses
  - ParseFailure model for tracking unparseable signs
  - 5-variant ScheduleResult discriminated union
  - parse_sign() regex-based parser handling all 447 SODA sign formats
  - parse_time_token() and extract_days() utility functions
affects: [03-02-PLAN, schedule-merge, next-move-computation, home-assistant-integration]

# Tech tracking
tech-stack:
  added: []  # All stdlib: re, enum, datetime, dataclasses
  patterns: [regex-token-extraction, discriminated-union-result, frozen-dataclass-models]

key-files:
  created:
    - src/gps2asp/schedule/__init__.py
    - src/gps2asp/schedule/models.py
    - src/gps2asp/schedule/parser.py
    - tests/test_parser.py
  modified: []

key-decisions:
  - "ASPDay as IntEnum with Monday=0 matching datetime.weekday() for direct comparison"
  - "v2 suspension hook via optional suspended=False field on ScheduleFound and ASPActiveNow"
  - "Prefix-based rejection: signs must match NO PARKING (SANITATION BROOM SYMBOL) prefix or return None"
  - "Parse order: EXCEPT clause -> dash range -> individual day names (prevents MONDAY-FRIDAY returning only 2 days)"

patterns-established:
  - "Regex token extraction: strip prefix/suffix, extract time, extract days from remainder"
  - "ScheduleResult discriminated union: 5 variants with Literal status field, following Phase 2 pattern"
  - "source_sign tracking: every TimeWindow carries the raw sign text it was parsed from"

requirements-completed: [SCHED-01, SCHED-02, SCHED-03]

# Metrics
duration: 4min
completed: 2026-02-22
---

# Phase 3 Plan 01: Schedule Data Models and Sign Parser Summary

**ASPDay enum, 5-variant ScheduleResult union, and regex-based sign description parser handling all 447 observed SODA sign formats with 56 unit tests**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-22T17:24:39Z
- **Completed:** 2026-02-22T17:28:16Z
- **Tasks:** 2
- **Files created:** 4

## Accomplishments
- ASPDay IntEnum (Monday=0 through Sunday=6) with .name and .value accessors matching datetime.weekday()
- Complete ScheduleResult discriminated union: ScheduleFound, ASPActiveNow, NoASPSchedule, NoMatchSchedule, AllUnparseable -- all frozen dataclasses with v2 suspension hooks
- Regex-based parser covering 100% of observed SODA sign formats: standard day+time, MOON & STARS night signs, EXCEPT SUNDAY, MONDAY-FRIDAY dash ranges, NOON/MIDNIGHT tokens, arrow/SUPERSEDES stripping
- 56 comprehensive unit tests: 18 for parse_time_token, 12 for extract_days, 26 for parse_sign (including top-10 most common patterns, failure cases, and source tracking)

## Task Commits

Each task was committed atomically:

1. **Task 1: Data models and ASPDay enum** - `3b503e3` (feat)
2. **Task 2: Sign description parser with comprehensive tests** - `ba98daf` (feat)

## Files Created/Modified
- `src/gps2asp/schedule/__init__.py` - Package init with public API re-exports and TODO for Plan 02 compute_schedule
- `src/gps2asp/schedule/models.py` - ASPDay enum, TimeWindow, CleaningWindow, WeeklySchedule, ParseFailure, and 5-variant ScheduleResult union
- `src/gps2asp/schedule/parser.py` - parse_sign(), parse_time_token(), extract_days() with compiled regex patterns
- `tests/test_parser.py` - 56 unit tests across TestParseTimeToken, TestExtractDays, TestParseSign classes

## Decisions Made
- ASPDay as IntEnum (not plain Enum) so values can be used directly in datetime.weekday() comparisons without conversion
- v2 suspension hook as `suspended: bool = False` field on ScheduleFound and ASPActiveNow -- lightweight, no breaking changes when Phase 4 or v2 needs it
- Prefix-matching as the primary rejection gate: any sign that does not start with the standard "NO PARKING (SANITATION BROOM SYMBOL)" prefix is immediately rejected (catches template sign, random text)
- Day extraction order (EXCEPT -> dash range -> individual names) prevents MONDAY-FRIDAY from being parsed as just Monday + Friday
- end_time > start_time validation: all observed SODA windows are same-day, so cross-midnight windows are treated as unparseable per research recommendation

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Models and parser ready for Plan 02: window merging, next-move datetime computation, human-readable summary, and compute_schedule() public API
- WeeklySchedule.windows_for_day() method ready for next-move algorithm to iterate by day
- ParseFailure model ready for aggregate failure tracking across multiple signs
- ScheduleResult union complete -- Plan 02 only needs to wire up the compute_schedule() function that produces these results

## Self-Check: PASSED

- All 4 created files verified on disk
- Commit 3b503e3 (Task 1) verified in git log
- Commit ba98daf (Task 2) verified in git log
- 153/153 tests passing (56 new + 97 existing, zero regressions)

---
*Phase: 03-schedule-parsing-and-next-move-computation*
*Completed: 2026-02-22*
