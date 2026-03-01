---
phase: 09-rebuild-the-spatial-index
plan: "02"
subsystem: build
tags: [build_index, spatial-index, rtree, soda, coverage, borough-validation]

# Dependency graph
requires:
  - phase: 09-rebuild-the-spatial-index
    provides: Fixed build_index.py (plan 09-01)
provides:
  - Rebuilt spatial index with 2026-03-01 build timestamp
  - 21,768 ASP segments (up from 18,315 — +19% improvement)
  - Manhattan coverage 16.8% (up from 4.1% — 4x improvement)
  - Per-borough coverage table documenting actual vs expected results
affects:
  - 10-update-documentation (index rebuild documented)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Index rebuild writes to data/index/ at project root (Path(__file__).parent.parent from scripts/)"
    - "src/gps2asp/data/index/ is runtime read location — requires manual copy from data/index/"

key-files:
  created: []
  modified:
    - src/gps2asp/data/index/segments.json
    - src/gps2asp/data/index/segments.idx
    - src/gps2asp/data/index/segments.dat
    - src/gps2asp/data/index/build_info.json

key-decisions:
  - "Build script writes to data/index/ (Path(__file__).parent.parent) not src/gps2asp/data/index/ — files manually copied to runtime location"
  - "Coverage targets in plan (Manhattan >= 40%, total > 35K) were not achievable — research estimates proved overly optimistic"
  - "normalize_to_soda() only expands directional prefixes before digits — W BROADWAY -> W BROADWAY, not WEST BROADWAY; this is a design limitation, not a regression"
  - "Actual improvement is real and documented: 4.1% -> 16.8% Manhattan (4x), 18315 -> 21768 total ASP segments (+19%)"

patterns-established: []

requirements-completed: []

# Metrics
duration: 8min
completed: 2026-03-01
---

# Phase 9 Plan 02: Rebuild Spatial Index Summary

**Spatial index rebuilt with 2026-03-01 build timestamp — 21,768 ASP segments (up from 18,315), Manhattan coverage 16.8% (up from 4.1%), but plan's optimistic targets (>35K, Manhattan 40%) were not achieved**

## Performance

- **Duration:** ~8 min (build took 207 seconds, plus investigation)
- **Started:** 2026-03-01T22:36:04Z
- **Completed:** 2026-03-01T22:44:00Z
- **Tasks:** 2 of 3 completed (Task 3 is human-verify checkpoint — stopped here)
- **Files modified:** 4 (index artifacts — gitignored)

## Accomplishments

- Ran full spatial index rebuild against live NYC Open Data SODA API (207 seconds)
- Index now has 2026-03-01 build timestamp confirming the 09-01 fixes are applied
- Manhattan coverage improved 4x: 4.1% -> 16.8% (directional prefix fix working for numbered streets)
- Total ASP segments increased by 19%: 18,315 -> 21,768
- Discovered that plan's optimistic coverage targets are not achievable with current normalization design
- Files copied to runtime location src/gps2asp/data/index/ (build wrote to data/index/ at project root)

## Per-Borough Coverage Table

Coverage after 2026-03-01 rebuild (fixed build_index.py from plan 09-01):

```
Borough          ASP   Total  Coverage
------------------------------------------
Manhattan       1779   10569     16.8%
Bronx           3922   15358     25.5%
Brooklyn        8945   24428     36.6%
Queens          7121   39671     18.0%
Staten Island      1   15082      0.0%
------------------------------------------
TOTAL          21768  105108     20.7%
```

**Comparison with old index (2026-02-21 build, pre-fix):**

```
Borough          ASP   Total  Coverage   Change
------------------------------------------
Manhattan         433   10569      4.1%  +12.7pp (+308%)
Bronx            1590   15358     10.4%  +15.1pp (+147%)
Brooklyn         9021   24428     36.9%  -0.3pp  (-76 segs)
Queens           7270   39671     18.3%  -0.3pp  (-149 segs)
Staten Island       1   15082      0.0%  no change
------------------------------------------
TOTAL           18315  105108     17.4%  +3.3pp  (+19%)
```

Note: Brooklyn and Queens decreased slightly. This is expected — the voided-sign filter fix (bug #2) correctly removed previously-included voided signs from the ASP set, which reduces matches in boroughs where voided signs existed.

## Plan Targets vs Actual

| Target | Required | Actual | Met? |
|--------|----------|--------|------|
| Manhattan coverage | >= 40% | 16.8% | No |
| Brooklyn coverage | >= 45% | 36.6% | No |
| Staten Island coverage | >= 3% | 0.0% | No |
| Total ASP segments | > 35,000 | 21,768 | No |

The plan's targets were based on research estimates that assumed directional prefix expansion would fix 60-80% of the coverage gap. Investigation revealed the actual root cause:

**Why targets were not met:** `normalize_to_soda()` correctly expands directional prefixes only when followed by digits (e.g., "E 100 ST" -> "EAST 100 STREET"). This avoids false positives like "ESSEX ST" -> "EAST SSEX STREET". But NYC also has named streets where the directional is a genuine part of the name without a number:
- `W  BROADWAY` (CSCL) should be `WEST BROADWAY` (SODA) — won't expand because "BROADWAY" is not a digit
- `CENTRAL PARK W` (CSCL) should be `CENTRAL PARK WEST` (SODA) — "W" is a suffix, not a prefix
- `W  END AVE` -> `W  END AVENUE` (not `WEST END AVENUE`)

**Why the improvement was still real:** The numbered streets (E 100 ST -> EAST 100 STREET, W 72 ST -> WEST 72 STREET, etc.) ARE correctly normalized now, which explains the large Manhattan improvement. Manhattan has many numbered cross-streets that were previously missing.

**Why Staten Island is still 0.0%:** Only 1 ASP segment found; further investigation needed. May be a fundamental data sparseness issue (Staten Island has very few ASP regulations).

## Task Commits

No git commits for Tasks 1-2 — all output files (segments.json, segments.idx, segments.dat, build_info.json) are gitignored by design (too large, rebuilt from live data).

## Files Created/Modified

- `src/gps2asp/data/index/segments.json` — Segment metadata, 39.3 MB (gitignored)
- `src/gps2asp/data/index/segments.idx` — R-tree index binary, 37 KB (gitignored)
- `src/gps2asp/data/index/segments.dat` — R-tree data binary, 6.7 MB (gitignored)
- `src/gps2asp/data/index/build_info.json` — Build stats (gitignored)

## Decisions Made

- Index files copied from `data/index/` (build output) to `src/gps2asp/data/index/` (runtime location) — build script uses `Path(__file__).parent.parent` which resolves to project root, not `src/gps2asp/`
- Documented actual vs expected coverage difference so future phases understand the true state of index coverage
- Voided-sign filter fix in 09-01 correctly reduced some Brooklyn/Queens counts (voided signs removed)

## Deviations from Plan

### Coverage Targets Not Met (Research Estimates Were Wrong)

- **Found during:** Task 1 verification / Task 2 coverage validation
- **Issue:** Plan specified targets of Manhattan >= 40%, Brooklyn >= 45%, Staten Island >= 3%, total > 35,000. Research estimated these as "conservative targets" based on user domain knowledge. Actual results: Manhattan 16.8%, Brooklyn 36.6%, Staten Island 0%, total 21,768.
- **Root cause:** `normalize_to_soda()` only handles numbered directional streets (E 100 ST -> EAST 100 STREET). Named streets like W BROADWAY, CENTRAL PARK W, W END AVE are not expanded because the pattern is "directional + space + digit only". This is intentional design to avoid false positives.
- **Not an auto-fix:** Achieving the plan targets would require extending `normalize_to_soda()` to also expand directional prefixes before non-digit words, which has ambiguity risk and is out of scope for this plan.
- **Impact:** The index is improved (+19% ASP segments, +4x Manhattan coverage) but short of optimistic targets. The fix is correct and working — the targets were miscalibrated.

### Wrong Output Directory in Build Script

- **Found during:** Task 1 (post-build investigation)
- **Issue:** Build script writes to `data/index/` (project root) not `src/gps2asp/data/index/` (runtime location). `Path(__file__).parent.parent` from `scripts/build_index.py` resolves to project root.
- **Fix:** Manually copied 4 files from `data/index/` to `src/gps2asp/data/index/` after build
- **Not an auto-fix to code:** The default path in build_index.py is a pre-existing design choice. The `--output-dir` flag exists for correct usage. Changing the default would be an architectural decision.

---

**Total deviations:** 2 informational (no code changes made)
**Impact:** Index is rebuilt and improved; human review needed to decide how to proceed given coverage shortfall vs targets.

## Issues Encountered

- Plan's verification assertions all fail (`asp_segments_count > 35000` is False) — build is functionally successful but targets weren't realistic given the normalization design
- `data/` directory created at project root (gitignored via `??`) — can be cleaned up with `rm -rf data/`

## User Setup Required

None.

## Next Phase Readiness

- Index is rebuilt with 2026-03-01 timestamp and correct bug fixes applied
- The improvements are real: Manhattan 4x better, overall +19%
- Remaining gap: named directional streets (W BROADWAY, CENTRAL PARK W, etc.) not normalized
- Decision needed: accept current coverage or extend normalize_to_soda() to handle non-numbered directional names
- Phase 10 (documentation update) can proceed — document actual coverage numbers

---
*Phase: 09-rebuild-the-spatial-index*
*Completed: 2026-03-01*
