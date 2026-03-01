---
phase: 08-refactor-architecture-and-streamline-pipeline
plan: "03"
subsystem: resolver
tags: [python, type-annotations, code-quality, refactor]

# Dependency graph
requires:
  - phase: 08-02
    provides: compute_confidence simplified, _try_query extracted, 221 tests pass
provides:
  - assert replaced with explicit TypeError in schedule/__init__.py
  - _MAX_SNAP_DISTANCE_FT and _NEAR_INTERSECTION_THRESHOLD_FT named constants
  - SpatialIndex._segments typed as dict[str, Any] | None
  - _cross_streets_match() with clarifying dual-normalization comments
affects: [09-rebuild-spatial-index, 10-update-documentation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Prefer explicit if/raise TypeError over assert for runtime type contracts"
    - "Module-level named constants for magic numbers — per-file, not shared constants.py"
    - "ClassVar vs instance var separation with inline comment block in class body"

key-files:
  created: []
  modified:
    - src/gps2asp/schedule/__init__.py
    - src/gps2asp/resolver/__init__.py
    - src/gps2asp/resolver/confidence.py
    - src/gps2asp/resolver/spatial_index.py
    - src/gps2asp/signs/__init__.py

key-decisions:
  - "Per-file named constants (not a shared constants.py) — keeps modules self-contained and testable in isolation"
  - "_NEAR_INTERSECTION_THRESHOLD_FT duplicated in resolver/__init__.py and confidence.py with explicit comment that they must match"
  - "Double normalization in _cross_streets_match() retained as-is — two distinct purposes clarified by comments, no behavior change"

patterns-established:
  - "Named constant with comment explaining semantic meaning and equivalence (e.g., '~50m: maximum snap radius')"

requirements-completed: [REFACTOR-QUALITY-MEDIUM, REFACTOR-QUALITY-NICE]

# Metrics
duration: 4min
completed: 2026-03-01
---

# Phase 8 Plan 3: Code Quality Sweep — Final Rough Edges Summary

**assert-to-TypeError replacement, magic number extraction as named constants, SpatialIndex dict[str, Any] annotation, and dual-normalization comment clarification across schedule/resolver/signs modules**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-01T14:55:58Z
- **Completed:** 2026-03-01T15:00:00Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Replaced `assert isinstance(sign_result, SignRetrievalSuccess)` with explicit `if not isinstance(...): raise TypeError(...)` in `schedule/__init__.py` — prevents `-O` optimization stripping the runtime guard
- Extracted `_MAX_SNAP_DISTANCE_FT = 164.0` and `_NEAR_INTERSECTION_THRESHOLD_FT = 30.0` as module-level named constants in `resolver/__init__.py` and `confidence.py`; replaced `30.0` usage-site literals
- Annotated `SpatialIndex._segments` as `dict[str, Any] | None` (added `Any` to typing imports); added comment block separating ClassVar from instance vars; fixed 95-char line length violation
- Added clarifying comments to `_cross_streets_match()` explaining that `_normalize_street()` cleans SODA record fields while `name_variants()` generates CSCL abbreviation variants — two distinct purposes, no behavior change
- All 221 tests pass (pre-existing `test_sign_retrieval.py` socket failures confirmed pre-existing, unrelated to this plan)

## Task Commits

Each task was committed atomically:

1. **Task 1: Replace assert, name magic numbers, annotate SpatialIndex types** - `97f3f95` (refactor)
2. **Task 2: Clarify double normalization in signs/__init__.py** - `e94db4c` (refactor)

**Plan metadata:** (docs commit below)

## Files Created/Modified

- `src/gps2asp/schedule/__init__.py` - assert replaced with explicit TypeError raise (item 9)
- `src/gps2asp/resolver/__init__.py` - _MAX_SNAP_DISTANCE_FT and _NEAR_INTERSECTION_THRESHOLD_FT constants added; 30.0 literal replaced (item 11)
- `src/gps2asp/resolver/confidence.py` - _NEAR_INTERSECTION_THRESHOLD_FT constant added; 30.0 literal replaced in compute_confidence()
- `src/gps2asp/resolver/spatial_index.py` - _segments typed as dict[str, Any] | None; Any added to imports; ClassVar comment added; RuntimeError line length fixed (item 3)
- `src/gps2asp/signs/__init__.py` - Clarifying comments added to _cross_streets_match(); long comment line fixed (item 13)

## Decisions Made

- Per-file named constants rather than shared `constants.py` — consistent with RESEARCH.md decision, keeps modules independently testable
- `_NEAR_INTERSECTION_THRESHOLD_FT` duplicated in both `resolver/__init__.py` and `confidence.py` with a comment noting they must match — acceptable for two-file duplication vs coupling via import
- Retained `_normalize_street()` + `name_variants()` dual approach in `_cross_streets_match()` without behavior changes — comments alone resolve the ambiguity

## Deviations from Plan

None - plan executed exactly as written. The `_NEAR_INTERSECTION_THRESHOLD_FT` constant was also added to `confidence.py` as the plan specified in its description (the plan explicitly instructs to check `confidence.py` and add the constant there too).

## Issues Encountered

Pre-existing `test_sign_retrieval.py` test failures (SocketBlockedError from `pytest-socket`) confirmed pre-existing before this plan's changes via `git stash` verification. These 6 failures were already present in commit `65db713` and are unrelated to plan 08-03 changes. All 221 non-socket tests pass.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All 22 rough edges from CONTEXT.md are now addressed across Plans 01-03
- Phase 8 (refactor architecture) is complete
- Phase 9 (Rebuild spatial index) and Phase 10 (Update documentation) can proceed

---
*Phase: 08-refactor-architecture-and-streamline-pipeline*
*Completed: 2026-03-01*
