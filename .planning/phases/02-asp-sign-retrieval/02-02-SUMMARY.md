---
phase: 02-asp-sign-retrieval
plan: 02
subsystem: api
tags: [soda-api, async, three-level-fallback, integration-tests, street-normalization]

# Dependency graph
requires:
  - phase: 02-asp-sign-retrieval
    plan: 01
    provides: "SODAClient, SignRecord, SignRetrievalSuccess/NoASPSigns/NoMatchFound models, normalize_to_soda/name_variants functions, exception hierarchy"
provides:
  - "retrieve_signs() public API with three-level fallback (exact -> variants -> broad+client-filter)"
  - "31 unit tests for street name normalization (suffix, directional, escaping)"
  - "6 integration tests against live SODA API (known ASP block, dedup, no voided signs)"
  - "Complete Phase 2 sign retrieval pipeline: CSCL input -> SODA query -> deduplicated SignRetrievalResult"
affects: [03-schedule-parsing]

# Tech tracking
tech-stack:
  added: []
  patterns: [three-level-fallback-query, client-side-cross-street-filtering, itertools-product-variant-combos]

key-files:
  created:
    - tests/test_normalize.py
    - tests/test_sign_retrieval.py
  modified:
    - src/gps2asp/signs/__init__.py
    - pyproject.toml

key-decisions:
  - "Level 1 uses SODA-normalized names (first variant) for highest-probability match"
  - "Level 2 iterates remaining variant combos via itertools.product, short-circuits on first hit"
  - "Level 3 client-side cross-street matching tries both from/to directions (SODA may have opposite directionality)"
  - "Registered custom pytest integration marker to eliminate warnings"

patterns-established:
  - "Three-level fallback: exact -> variant combos -> broad+client-filter with short-circuit"
  - "Integration test pattern: skip_no_network decorator + socket connectivity check"
  - "Result uses input CSCL names throughout, never SODA-converted names"

requirements-completed: [SIGN-01, SIGN-02, SIGN-03]

# Metrics
duration: 3min
completed: 2026-02-22
---

# Phase 2 Plan 2: Sign Retrieval Public API and Tests Summary

**Three-level fallback retrieve_signs() API with 31 normalization unit tests and 6 SODA integration tests, completing Phase 2 sign retrieval pipeline**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-22T05:12:29Z
- **Completed:** 2026-02-22T05:15:52Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- retrieve_signs() public API implementing three-level fallback strategy: exact SODA-normalized match, abbreviation variant combinations, and broad on_street+side query with client-side cross-street filtering
- 31 unit tests for normalize_to_soda (suffix expansion, directional expansion with digit guard, passthrough, whitespace), name_variants (ordering, dedup), and escape_soql (single quote escaping)
- 6 integration tests against live SODA API validating SIGN-01 (query works), SIGN-02 (no voided signs), SIGN-03 (deduplication), name normalization fallback, and input name preservation
- All 97 tests pass (60 Phase 1 + 37 Phase 2) with zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Three-level fallback retrieve_signs() public API** - `ec35e1b` (feat)
2. **Task 2: Unit tests for normalization and integration tests for sign retrieval** - `e52b729` (test)

## Files Created/Modified
- `src/gps2asp/signs/__init__.py` - Public API: retrieve_signs() with three-level fallback, deduplication, and all re-exports
- `tests/test_normalize.py` - 31 unit tests for normalize_to_soda, name_variants, escape_soql
- `tests/test_sign_retrieval.py` - 6 integration tests against live SODA API (skip if unreachable)
- `pyproject.toml` - Registered integration pytest marker

## Decisions Made
- Level 1 queries with SODA-normalized names (first variant from name_variants) since these are the format used in the parking signs dataset, giving highest probability of immediate match
- Level 2 uses itertools.product to generate all remaining variant combinations and short-circuits on first hit, avoiding unnecessary API calls
- Level 3 client-side cross-street matching normalizes both SODA record names and expected names, and tries from/to swapped since SODA may have opposite directionality than CSCL
- Registered custom `integration` pytest marker in pyproject.toml to eliminate PytestUnknownMarkWarning

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Registered integration pytest marker**
- **Found during:** Task 2 (integration test creation)
- **Issue:** pytest raised PytestUnknownMarkWarning for unregistered `@pytest.mark.integration`
- **Fix:** Added `markers` config to `[tool.pytest.ini_options]` in pyproject.toml
- **Files modified:** pyproject.toml
- **Verification:** Warning no longer appears in test output
- **Committed in:** e52b729 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Minor config addition for clean test output. No scope creep.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required. The optional NYC_OPEN_DATA_APP_TOKEN environment variable is supported but not required (same as Plan 01).

## Next Phase Readiness
- Phase 2 is complete: retrieve_signs() can be called with any CSCL street segment tuple from Phase 1
- Phase 3 (Schedule Parsing) can import `from gps2asp.signs import retrieve_signs, SignRetrievalSuccess` and parse sign_description strings into structured schedule objects
- All 97 tests pass with zero regressions across both phases

## Self-Check: PASSED

All 4 created/modified files verified on disk. Both task commits (ec35e1b, e52b729) verified in git log.

---
*Phase: 02-asp-sign-retrieval*
*Completed: 2026-02-22*
