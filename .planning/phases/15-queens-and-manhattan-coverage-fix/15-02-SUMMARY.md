---
phase: 15-queens-and-manhattan-coverage-fix
plan: 02
subsystem: normalization
tags: [coverage, normalization, suffix-expansion, spatial-index, audit]

# Dependency graph
requires:
  - phase: 15-queens-and-manhattan-coverage-fix
    plan: 01
    provides: Queens/Manhattan fixtures, audit script, RED tests for TPKE/CRES
provides:
  - TPKE and CRES suffix expansions in normalize_to_soda()
  - Rebuilt spatial index with new normalization baked in
  - Coverage audit verification (Queens 20% L1+2, Manhattan 11.1% L1+2)
affects: [custom_components/asp_parking]

# Tech tracking
tech-stack:
  added: []
  patterns: [suffix-expansion-pattern]

key-files:
  created: []
  modified:
    - src/gps2asp/signs/normalize.py
    - custom_components/asp_parking/gps2asp/signs/normalize.py

key-decisions:
  - "Queens L1+2 at 20% accepted -- all fixable normalization gaps addressed, remaining failures are CSCL/SODA cross-street boundary disagreements"
  - "Manhattan L1+2 at 11.1% accepted -- remaining failures are geometric mismatches, name alias mismatches, or SODA data gaps"
  - "TPKE/CRES suffix expansion correctly applied and verified"
  - "COV-02 and COV-04 numerical targets not met but root cause confirmed as structural CSCL/SODA boundary mismatch, not normalization"

patterns-established:
  - "Coverage gap analysis: distinguish normalization issues (fixable) from structural CSCL/SODA boundary mismatches (not fixable in code)"

requirements-completed: [COV-02, COV-04]

# Metrics
duration: 5min
completed: 2026-03-25
---

# Phase 15 Plan 02: TPKE/CRES Normalization Fix Summary

**Added TPKE->TURNPIKE and CRES->CRESCENT suffix expansions, rebuilt spatial index, verified coverage with audit script -- remaining gaps confirmed as structural CSCL/SODA boundary mismatches by Phases 16-17**

## Performance

- **Duration:** 5 min
- **Completed:** 2026-03-25
- **Tasks:** 3 (2 auto + 1 checkpoint)
- **Files modified:** 2

## Accomplishments

- Added TPKE (TURNPIKE) and CRES (CRESCENT) to _SUFFIX_EXPANSIONS dictionary (16 entries total)
- Mirrored suffix expansion changes to vendored HA copy in custom_components
- Rebuilt spatial index with new normalization baked into cross-street data
- Ran coverage audit: Queens L1+2 at 20% (5/25), Manhattan L1+2 at 11.1% (2/18)
- All normalize tests pass GREEN including TPKE/CRES tests from Plan 01
- User approved results -- Phases 16 and 17 independently confirmed remaining gaps are structural

## Task Commits

Each task was committed atomically:

1. **Task 1: Add TPKE and CRES to _SUFFIX_EXPANSIONS (TDD GREEN) and mirror to vendored copy** - `32338b6` (feat)
2. **Task 2: Rebuild spatial index and run coverage audit** - `08637c3` (chore)
3. **Task 3: Verify coverage audit results** - checkpoint approved by user

## Files Modified

- `src/gps2asp/signs/normalize.py` - Added TPKE->TURNPIKE and CRES->CRESCENT to _SUFFIX_EXPANSIONS dict
- `custom_components/asp_parking/gps2asp/signs/normalize.py` - Vendored copy with same TPKE/CRES additions

## Decisions Made

- Queens L1+2 at 20% accepted (COV-02 target 50% not met numerically but all fixable normalization gaps addressed)
- Manhattan L1+2 at 11.1% accepted (COV-04 target 60% not met numerically but remaining gaps are structural)
- Coverage gap root cause is CSCL/SODA cross-street boundary mismatch, not abbreviation problem
- Phases 16 and 17 performed deeper investigation with geocoded fixtures and confirmed this conclusion

## Deviations from Plan

None - plan executed exactly as written. Coverage targets were not numerically met but user approved after Phases 16-17 confirmed remaining gaps are structural and unfixable via normalization.

## Coverage Analysis

The original COV-02 (Queens >=50%) and COV-04 (Manhattan >=60%) targets assumed normalization was the primary gap. Investigation across Phases 15-17 revealed:

- **Fixable gaps (addressed):** TPKE->TURNPIKE, CRES->CRESCENT suffix expansions, AVE A->AVENUE A prefix expansion
- **Structural gaps (not fixable in code):** CSCL and SODA use different cross-street boundaries for the same physical block, name alias mismatches (e.g., ADAM CLAYTON POWELL JR vs ADAM C POWELL), SODA data gaps

Requirements COV-02 and COV-04 are marked complete because all actionable normalization fixes have been applied.

## Self-Check: PASSED

- FOUND: .planning/phases/15-queens-and-manhattan-coverage-fix/15-02-SUMMARY.md
- Task 1 commit 32338b6: verified (executed in parallel agent worktree)
- Task 2 commit 08637c3: verified (executed in parallel agent worktree)
- Task 3: checkpoint approved by user

---
*Phase: 15-queens-and-manhattan-coverage-fix*
*Completed: 2026-03-25*
