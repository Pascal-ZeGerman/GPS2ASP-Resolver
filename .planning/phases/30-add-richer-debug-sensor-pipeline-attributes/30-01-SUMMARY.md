---
phase: 30-add-richer-debug-sensor-pipeline-attributes
plan: 01
subsystem: resolver
tags: [python, dataclass, resolver, tdd, frozen-dataclass, optional-fields]

# Dependency graph
requires:
  - phase: 11-bfs-graph-propagation
    provides: SegmentCandidate.borocode and SegmentCandidate.segment_id (already on the candidate dataclass; plan 30-01 simply surfaces them on the result)
provides:
  - "ResolutionResult.borocode (str | None) — CSCL borough code surfaced on resolver output"
  - "ResolutionResult.perpendicular_distance_ft (float | None) — rounded GPS-to-centerline distance"
  - "ResolutionResult.street_width_ft (float | None) — post-fallback effective width"
  - "ResolutionResult.segment_id (int | None) — CSCL physical segment ID"
  - "resolve_segment() populates all four from values already in scope (best, perp_distance, effective_width)"
  - "Vendored mirror under custom_components/asp_parking/gps2asp/resolver/ stays byte-for-byte identical for models.py and structurally identical for __init__.py"
affects:
  - 30-02 (ASPDebugResult — will read from resolution.borocode/.segment_id/etc.)
  - 30-03 (coordinator ASPParkingData — will populate borough/distance_ft/etc. from ResolutionResult)
  - 30-04 (sensor extra_state_attributes — will read coordinator.data.borough etc.)

# Tech tracking
tech-stack:
  added: []  # No new deps; uses existing shapely/pytest/unittest.mock
  patterns:
    - "Optional-field extension on frozen dataclass with None defaults (per ResolutionDebugInfo precedent)"
    - "TDD RED → GREEN cycle as two atomic commits with shared test module"

key-files:
  created:
    - tests/test_resolver_extended_fields.py
    - .planning/phases/30-add-richer-debug-sensor-pipeline-attributes/deferred-items.md
  modified:
    - src/gps2asp/resolver/models.py
    - src/gps2asp/resolver/__init__.py
    - custom_components/asp_parking/gps2asp/resolver/models.py
    - custom_components/asp_parking/gps2asp/resolver/__init__.py

key-decisions:
  - "D-04: New fields are Optional with None defaults — preserves backwards compatibility for existing callers and 18+ test fixtures"
  - "D-05: ResolutionResult signature grows from 6 to 10 fields; appended after has_asp"
  - "D-06: resolve_segment() populates all four fields from values already in scope at the success-branch ResolutionResult constructor (no extra computation, no new imports)"
  - "D-15: Vendored mirror models.py kept byte-for-byte identical; mirror __init__.py extends call body identically while preserving relative imports"

patterns-established:
  - "Diagnostic-field extension on frozen dataclass: append optional fields with str|None / float|None / int|None typing and None defaults (parallels ResolutionDebugInfo lines 92-97)"
  - "When a TDD test exercises resolve_segment via SpatialIndex mocking, geometry must be long enough (>~60ft) and query point must be off-center enough to escape the near-intersection (<30ft) and near-centerline (<width*0.165 ft) ambiguity guards"

requirements-completed: [DIAG-04]

# Metrics
duration: ~7min
completed: 2026-05-03
---

# Phase 30 Plan 01: ResolutionResult diagnostic fields Summary

**ResolutionResult exposes four new optional diagnostic fields (borocode, perpendicular_distance_ft, street_width_ft, segment_id) populated by resolve_segment from values already in scope — backwards-compatible foundation for Phase 30 sensor attribute pipeline.**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-05-03T15:22:00Z
- **Completed:** 2026-05-03T15:29:00Z
- **Tasks:** 2 (RED + GREEN)
- **Files modified:** 4 source + 1 test = 5
- **Files created:** 1 test + 1 deferred-items log

## Accomplishments

- Extended `ResolutionResult` from 6 to 10 fields — four new optional diagnostic fields (`borocode`, `perpendicular_distance_ft`, `street_width_ft`, `segment_id`) all default `None` so every existing caller keeps working unchanged.
- `resolve_segment()` now threads all four fields onto the result using values that were already in scope at the success-branch constructor call (`best.borocode`, `round(perp_distance, 2)`, `effective_width`, `best.segment_id`) — no extra computation, no new imports.
- Vendored mirror under `custom_components/asp_parking/gps2asp/resolver/` updated identically: `models.py` is byte-for-byte identical with `src/`; `__init__.py` extends the constructor call body the same way while preserving its existing relative-import block (`from .confidence import ...`).
- 4 new unit tests covering: default `None` values, explicit value round-trip, `resolve_segment` field population (mocked `SpatialIndex.get`), and vendored-mirror parity.
- Foundation in place for Phase 30 plans 02–04 (ASPDebugResult / ASPParkingData / sensor attributes can now thread these four values straight through to HA dashboards).

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): failing tests for ResolutionResult diagnostic fields** — `fec9c2d` (test)
2. **Task 2 (GREEN): add diagnostic fields and populate in resolve_segment** — `5ee344f` (feat)

_Note: This is a TDD plan; the test commit precedes the implementation commit. No REFACTOR commit was needed — the GREEN edit is a pure extension._

## Files Created/Modified

- `tests/test_resolver_extended_fields.py` — **created** — 4 tests covering field defaults, explicit values, resolver population (with `SpatialIndex.get` patched via `AsyncMock`), and vendored-mirror parity.
- `src/gps2asp/resolver/models.py` — **modified** — `ResolutionResult` gains 4 optional fields with docstring entries; field order: `on_street, from_street, to_street, side_of_street, confidence, has_asp` (existing) then `borocode, perpendicular_distance_ft, street_width_ft, segment_id` (new).
- `src/gps2asp/resolver/__init__.py` — **modified** — `resolve_segment()` success-branch constructor call extended with `borocode=best.borocode, perpendicular_distance_ft=round(perp_distance, 2), street_width_ft=effective_width, segment_id=best.segment_id`.
- `custom_components/asp_parking/gps2asp/resolver/models.py` — **modified** — byte-for-byte identical to `src/` version (verified via `diff` returning no output).
- `custom_components/asp_parking/gps2asp/resolver/__init__.py` — **modified** — same constructor extension; relative-import block preserved unchanged.
- `.planning/phases/30-add-richer-debug-sensor-pipeline-attributes/deferred-items.md` — **created** — logs one pre-existing `test_suspension.py` failure that is out-of-scope for Plan 30-01.

## Decisions Made

Followed plan as specified — all decisions D-04, D-05, D-06, D-15 implemented exactly as defined in the plan frontmatter.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] Test fixture geometry adjusted so resolve_segment hits the success branch**
- **Found during:** Task 2 (GREEN run of `test_resolve_segment_populates_new_fields_from_best_candidate`)
- **Issue:** The plan's suggested test geometry (a 100ft horizontal segment from `(987600, 178432)` to `(987700, 178432)` with query point at `(987654, 178432)`) put the query point exactly on the segment centerline (perp_distance = 0.0). `compute_confidence()` returned 0.0 (near-centerline guard at `width * 0.33 / 2 = 4.95ft` for width=30ft), `resolve_segment` raised `AmbiguousResolutionError` instead of returning a `ResolutionResult`, and the test could not assert on the new fields.
- **Fix:** Lengthened the segment to 200ft (`(987600, 178432)` → `(987800, 178432)`) and moved the query point to the midpoint with a 10ft perpendicular offset (`(987700, 178442)`). This places it at perp_distance=10ft (above the 4.95ft near-centerline guard) with endpoint distance ~100ft (above the 30ft near-intersection guard), yielding confidence ~0.67 — well above the 0.33 threshold.
- **Files modified:** `tests/test_resolver_extended_fields.py` (`_make_segment_candidate` default geometry + `query_x, query_y` in the resolver test)
- **Verification:** All 4 tests pass after the geometry adjustment; `compute_perpendicular_distance` is still called dynamically so no hard-coded distance assumption was introduced.
- **Committed in:** `5ee344f` (Task 2 GREEN commit — fixture tweak shipped alongside the implementation since the broken fixture would have made the GREEN gate unverifiable).

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Test-only fix to make the resolver-integration assertion reachable. No production code or contract change. The pattern is documented under `patterns-established` so future TDD authors writing `resolve_segment` tests with mocked `SpatialIndex` know the geometry constraints up front.

## Issues Encountered

- **Pre-existing failure in `tests/test_suspension.py::test_is_suspended_holiday`** (out of scope) — surfaced when running the full fast suite for regression check. Verified via `git stash` that the same failure occurs without Plan 30-01 edits, with the same `AssertionError: source: 'holiday' != 'none'` message and the same `WARNING ... HolidayCalendar.is_suspended() called before load() -- returning not suspended`. Not caused by this plan; logged to `deferred-items.md` for a future phase. Plan 30-01 does not touch `src/gps2asp/suspension/` and there is no plausible coupling.

## User Setup Required

None — all changes are internal-library / dataclass-shape changes that flow through automatically once Phase 30 plans 02–04 wire the downstream consumers.

## Next Phase Readiness

- **Plan 30-02** can now consume `resolution.borocode`, `resolution.perpendicular_distance_ft`, `resolution.street_width_ft`, and `resolution.segment_id` directly when extending `ASPDebugResult.from_resolution()` (per D-07).
- Both `ResolutionResult` mirrors are in lock-step — no further mirror sync is required for the resolver layer in this phase.
- Fast test suite is green for the new 4 tests and showed zero new regressions (only the pre-existing `test_suspension` failure remains).
- TDD gate compliance: RED commit `fec9c2d` precedes GREEN commit `5ee344f`; no REFACTOR commit needed.

## TDD Gate Compliance

- **RED gate:** `fec9c2d` (`test(30-01): add failing tests for ResolutionResult diagnostic fields`) — confirmed failing with `AttributeError: 'ResolutionResult' object has no attribute 'borocode'` before any implementation.
- **GREEN gate:** `5ee344f` (`feat(30-01): add diagnostic fields to ResolutionResult and populate in resolve_segment`) — all 4 tests pass.
- **REFACTOR gate:** Not exercised — pure extension required no follow-up cleanup.

## Self-Check: PASSED

- `tests/test_resolver_extended_fields.py` exists ✓
- `src/gps2asp/resolver/models.py` modified ✓
- `src/gps2asp/resolver/__init__.py` modified ✓
- `custom_components/asp_parking/gps2asp/resolver/models.py` modified ✓
- `custom_components/asp_parking/gps2asp/resolver/__init__.py` modified ✓
- Commit `fec9c2d` (RED) exists in git log ✓
- Commit `5ee344f` (GREEN) exists in git log ✓
- Mirror `models.py` byte-identical (`diff` returns no output) ✓
- Mirror `__init__.py` `ResolutionResult(...)` call body identical ✓
- All 4 new tests pass ✓

---
*Phase: 30-add-richer-debug-sensor-pipeline-attributes*
*Completed: 2026-05-03*
