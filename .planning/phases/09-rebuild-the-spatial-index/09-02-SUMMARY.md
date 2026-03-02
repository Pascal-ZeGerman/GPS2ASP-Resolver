---
phase: 09-rebuild-the-spatial-index
plan: "02"
subsystem: build
tags: [build_index, spatial-index, rtree, soda, coverage, borough-validation]

# Dependency graph
requires:
  - phase: 09-rebuild-the-spatial-index
    provides: Fixed build_index.py (plan 09-01) and normalize_to_soda improvements (quick-task-4)
provides:
  - Rebuilt spatial index with 2026-03-01T23:22:59Z build timestamp
  - 26,374 ASP segments (up from 18,315 — +44% improvement)
  - Per-borough coverage table with human approval
  - Confirmation that remaining coverage gap is a structural SODA span mismatch (deferred to Phase 11)
affects:
  - 10-update-documentation
  - 11-improve-asp-coverage

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Index rebuild is fully automated: python scripts/build_index.py writes to src/gps2asp/data/index/"
    - "build_info.json stores asp_segments_count and build_timestamp as canonical build metadata"

key-files:
  created: []
  modified:
    - src/gps2asp/data/index/segments.json
    - src/gps2asp/data/index/segments.idx
    - src/gps2asp/data/index/segments.dat
    - src/gps2asp/data/index/build_info.json

key-decisions:
  - "Remaining Manhattan coverage gap (29.5% vs 40% target) deferred to Phase 11 — root cause is multi-block SODA spans vs single-block CSCL granularity, not normalization"
  - "Staten Island 0.0% coverage is a SODA data gap (only 1 sign record for all 15,082 segments) — deferred to Phase 11 triage"
  - "Index files are gitignored (too large); rebuild is the authoritative source, not version-controlled artifacts"
  - "Human approved coverage results despite Manhattan/SI not meeting plan targets — improvements are real, remaining gaps have known root causes"

patterns-established: []

requirements-completed: []

# Metrics
duration: 15min
completed: 2026-03-01
---

# Phase 9 Plan 02: Rebuild Spatial Index Summary

**Spatial index rebuilt to 26,374 ASP segments (+44% from 18,315) using all 09-01 bug fixes plus quick-task-4 normalize_to_soda improvements; human-approved per-borough coverage report with remaining gap deferred to Phase 11**

## Performance

- **Duration:** ~15 min (build took 199s, plus coverage validation and checkpoint review)
- **Started:** 2026-03-01T23:07:00Z
- **Completed:** 2026-03-01T23:30:00Z
- **Tasks:** 3 (including human-verify checkpoint, approved)
- **Files modified:** 4 (index artifacts — all gitignored)

## Accomplishments

- Ran full spatial index rebuild against live NYC Open Data SODA API (199 seconds)
- Index incorporates all Plan 09-01 bug fixes (directional prefix expansion, voided-sign filter, dead-end sentinel)
- Index also incorporates quick-task-4 normalize_to_soda improvements (directional suffix expansion, internal whitespace collapse)
- ASP segment count: 18,315 → 26,374 (+44%)
- Per-borough coverage validated and human-approved at Task 3 checkpoint
- Root cause of remaining gap identified (multi-block SODA spans) and deferred to Phase 11

## Per-Borough Coverage Table

Coverage after final 2026-03-01T23:22:59Z rebuild (09-01 fixes + quick-task-4 normalize_to_soda):

```
Borough            ASP   Total  Coverage
------------------------------------------
Manhattan         3117   10569     29.5%
Bronx             4395   15358     28.6%
Brooklyn         11697   24428     47.9%
Queens            7164   39671     18.1%
Staten Island        1   15082      0.0%
------------------------------------------
TOTAL            26374  105108     25.1%
```

**Build metadata:**
- `build_timestamp`: `2026-03-01T23:22:59Z`
- `asp_segments_count`: 26,374
- `build_duration_seconds`: 199.3
- `cscl_row_count`: 122,251
- `filtered_count` (vehicular segments): 105,112

**Comparison with original pre-fix index (2026-02-21 build):**

| Borough | Before (4.1%) | After | Change |
|---------|---------------|-------|--------|
| Manhattan | 433 (4.1%) | 3,117 (29.5%) | +2,684 segs, +7x |
| Bronx | 1,590 (10.4%) | 4,395 (28.6%) | +2,805 segs, +2.8x |
| Brooklyn | 9,021 (36.9%) | 11,697 (47.9%) | +2,676 segs, +30% |
| Queens | 7,270 (18.3%) | 7,164 (18.1%) | -106 segs (voided signs removed) |
| Staten Island | 1 (0.0%) | 1 (0.0%) | no change |
| **TOTAL** | **18,315 (17.4%)** | **26,374 (25.1%)** | **+8,059 segs, +44%** |

Note: Queens decreased slightly — the voided-sign filter fix (bug #2 in plan 09-01) correctly removed previously-included voided signs.

## Plan Targets vs Actual

| Target | Required | Actual | Met? |
|--------|----------|--------|------|
| Manhattan coverage | >= 40% | 29.5% | No — gap deferred to Phase 11 |
| Brooklyn coverage | >= 45% | 47.9% | Yes |
| Staten Island coverage | >= 3% | 0.0% | No — SODA data gap |
| Total ASP segments | > 35,000 | 26,374 | No — gap deferred to Phase 11 |

The plan's targets were based on research estimates that proved overly optimistic. Brooklyn met its target. The remaining gaps have identified root causes:

**Why Manhattan is at 29.5% not 40%+:** Many SODA parking sign records span multiple CSCL block segments. A sign entered for "WEST 72 ST between Broadway and Columbus Ave" covers 3–4 CSCL segments, but the SODA record has a single on_street/from_cross/to_cross tuple. Only the from_cross segment end gets matched; mid-span segments are missed. This is an architectural matching limitation, not a normalization issue.

**Why Staten Island is 0.0%:** SODA parking signs API has effectively zero ASP sign records for Staten Island. This is a real data gap in the source, not a code issue.

## Task Commits

No git commits for Tasks 1-3 — all output files (segments.json, segments.idx, segments.dat, build_info.json) are gitignored by design (too large, rebuilt from live data). Task 3 was a human-verify checkpoint, approved by user.

## Files Created/Modified

- `src/gps2asp/data/index/build_info.json` — Build stats: 26,374 ASP segments, timestamp 2026-03-01T23:22:59Z (gitignored)
- `src/gps2asp/data/index/segments.json` — 38MB segment metadata with corrected has_asp_left/has_asp_right flags (gitignored)
- `src/gps2asp/data/index/segments.idx` — 109KB R-tree index binary (gitignored)
- `src/gps2asp/data/index/segments.dat` — 21MB R-tree data binary (gitignored)

## Decisions Made

- Manhattan/SI coverage gap deferred to Phase 11 (mid-span coverage) with explicit root cause documentation
- Human approval received for coverage results despite two targets not met — improvements are real and substantial
- Index rebuild incorporated quick-task-4 improvements that were not in the original plan scope, but were applied before this plan's verification ran

## Deviations from Plan

### Coverage Targets Partially Not Met (Root Cause Identified)

- **Found during:** Task 2 (coverage validation)
- **Issue:** Plan specified targets of Manhattan >= 40%, Brooklyn >= 45%, Staten Island >= 3%, total > 35,000. Actual results: Manhattan 29.5%, Brooklyn 47.9%, Staten Island 0%, total 26,374.
- **Root cause:** Multi-block SODA span matching limitation (architectural) and SODA data gap for Staten Island.
- **Action:** Documented root cause, deferred to Phase 11. Human approved results at checkpoint.
- **Not an auto-fix:** This is an architectural gap requiring a different matching strategy, not a code bug.

---

**Total deviations:** 1 informational (no code changes)
**Impact:** Index is rebuilt with all current fixes applied. Coverage improvement is real (+44% ASP segments). Remaining gap has clear root cause tracked in Phase 11.

## Issues Encountered

None during execution. The build completed successfully on first attempt.

## User Setup Required

None.

## Next Phase Readiness

- Index is rebuilt with 2026-03-01 timestamp and all current bug fixes applied
- Phase 10 (documentation update) can proceed — document actual coverage numbers (29.5% Manhattan, 47.9% Brooklyn)
- Phase 11 (mid-span coverage) has clear scope: implement matching for mid-span CSCL segments to close the remaining Manhattan coverage gap

---
*Phase: 09-rebuild-the-spatial-index*
*Completed: 2026-03-01*
