---
phase: 08-refactor-architecture-and-streamline-pipeline
plan: "02"
subsystem: resolver
tags: [python, refactor, confidence, spatial-index, soda, code-quality]

# Dependency graph
requires:
  - phase: 08-01
    provides: pipeline.py with thin __init__.py re-export
provides:
  - compute_confidence() with simplified effective_width_ft parameter (no rw_type)
  - resolve_segment() with public input_lat/input_lon parameters (no underscore prefix)
  - SegmentCandidate without dead l_blockfaceid/r_blockfaceid fields
  - _try_query() helper in signs/__init__.py eliminating repeated fetch-dedup-return pattern
  - ResolutionDebugInfo built exactly once in resolve_segment() success path
affects: [pipeline, confidence-scoring, spatial-index, sign-retrieval]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Caller resolves effective_width before passing to compute_confidence() — no internal re-computation"
    - "Fallback helper with optional prefetched_records for three-level SODA query abstraction"
    - "module-level import logging (not inside function bodies)"

key-files:
  created: []
  modified:
    - src/gps2asp/resolver/confidence.py
    - src/gps2asp/resolver/__init__.py
    - src/gps2asp/resolver/models.py
    - src/gps2asp/resolver/spatial_index.py
    - src/gps2asp/signs/__init__.py
    - src/gps2asp/pipeline.py
    - tests/test_confidence.py

key-decisions:
  - "compute_confidence() accepts effective_width_ft (already resolved) — caller is responsible for resolve_effective_width() call, eliminating double computation"
  - "_try_query() accepts optional prefetched_records to support Level 3 broad-query pattern without duplicating dedup+return logic"
  - "except Exception comment added to clarify intent (not converted to specific type — re-raise is already correct behavior)"

patterns-established:
  - "Resolve width once at call site; pass pre-resolved value to confidence scorer"

requirements-completed: [REFACTOR-QUALITY-MUST-FIX, REFACTOR-QUALITY-HIGH]

# Metrics
duration: 8min
completed: 2026-03-01
---

# Phase 8 Plan 02: Code Quality Cleanup Summary

**Seven code quality items fixed: compute_confidence simplified to effective_width_ft, module-level import logging, _input_lat/_input_lon renamed, dead blockfaceid fields removed, _try_query() helper extracted, ResolutionDebugInfo built once, bare except clarified**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-01T14:45:15Z
- **Completed:** 2026-03-01T14:53:23Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- Fixed `compute_confidence()` to accept `effective_width_ft` directly — removes duplicate `resolve_effective_width()` call and simplifies the signature (no `rw_type` param)
- Moved `import logging` from inside `resolve_effective_width()` function body to module top in `confidence.py`
- Renamed `_input_lat`/`_input_lon` to `input_lat`/`input_lon` in `resolve_segment()` signature and all call sites (resolver, pipeline)
- Removed dead `l_blockfaceid`/`r_blockfaceid` fields from `SegmentCandidate` dataclass and `SpatialIndex.nearest()` construction
- Extracted `_try_query()` async helper in `signs/__init__.py` with 3 call sites, eliminating repeated fetch-deduplicate-return pattern across Level 1, 2, and 3
- Built `ResolutionDebugInfo` exactly once in the success path (removed initial minimal construction at top of try block)
- Added clarifying comment to bare `except Exception` in `resolve_segment()`

## Task Commits

1. **Task 1: Fix compute_confidence signature and move import logging** - `0f895d1` (refactor)
2. **Task 2: Fix resolver/__init__.py, models.py, spatial_index.py, signs/__init__.py** - `3df4ca4` (refactor)

## Files Created/Modified
- `src/gps2asp/resolver/confidence.py` - import logging at module top; compute_confidence now takes effective_width_ft; rw_type param removed
- `src/gps2asp/resolver/__init__.py` - input_lat/input_lon params; effective_width_ft passed to compute_confidence; ResolutionDebugInfo built once; except comment
- `src/gps2asp/resolver/models.py` - SegmentCandidate without l_blockfaceid/r_blockfaceid
- `src/gps2asp/resolver/spatial_index.py` - SpatialIndex.nearest() construction without l_blockfaceid/r_blockfaceid
- `src/gps2asp/signs/__init__.py` - _try_query() helper extracted; used at 3 call sites
- `src/gps2asp/pipeline.py` - Updated resolve_segment() call to use input_lat=lat, input_lon=lon
- `tests/test_confidence.py` - Updated all compute_confidence calls to use effective_width_ft=; fallback tests restructured to call resolve_effective_width() first

## Decisions Made
- `_try_query()` accepts optional `prefetched_records` parameter — allows Level 3's broad-query+client-filter pattern to reuse the dedup+return logic without an extra network fetch
- `compute_confidence()` receives `effective_width_ft` (pre-resolved by caller) — makes the caller responsible for width resolution, consistent with "compute one thing at a time"
- Did not change Level 3 logging behavior — log before `_try_query`, same as before

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- The `test_sign_retrieval.py` integration tests (6 tests) attempt real network connections and fail with `SocketBlockedError` — confirmed pre-existing before this plan's changes, not introduced by this work. The 221 unit/mock tests all pass.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All 7 code quality items from plan 08-02 complete
- Phase 8 complete — architecture refactor and pipeline streamlining done
- Next: Phase 9 (Rebuild the spatial index) or Phase 10 (Update documentation)

---
*Phase: 08-refactor-architecture-and-streamline-pipeline*
*Completed: 2026-03-01*
