---
phase: 30-add-richer-debug-sensor-pipeline-attributes
plan: 02
subsystem: api
tags: [python, dataclass, api, tdd, frozen-dataclass, optional-fields, vendored-mirror]

# Dependency graph
requires:
  - phase: 30-add-richer-debug-sensor-pipeline-attributes
    plan: 01
    provides: ResolutionResult.borocode / .perpendicular_distance_ft / .street_width_ft / .segment_id (consumed by ASPDebugResult.from_resolution)
provides:
  - "ASPDebugResult.borocode (str | None) — CSCL borough code surfaced as top-level debug field"
  - "ASPDebugResult.perpendicular_distance_ft (float | None) — rounded GPS-to-centerline distance"
  - "ASPDebugResult.street_width_ft (float | None) — post-fallback effective width"
  - "ASPDebugResult.segment_id (int | None) — CSCL physical segment ID"
  - "ASPDebugResult.from_resolution() threads all 4 fields from the ResolutionResult argument"
  - "ASPDebugResult.from_error() sets all 4 fields to None on the failure path"
  - "Vendored mirror under custom_components/asp_parking/gps2asp/api_models.py stays byte-for-byte identical with src"
affects:
  - 30-03 (coordinator ASPParkingData — will populate borough/distance_ft/etc. by reading the new ASPDebugResult top-level fields)
  - 30-04 (sensor extra_state_attributes — will read coordinator.data.borough etc. once 30-03 wires it through)

# Tech tracking
tech-stack:
  added: []  # No new deps; uses existing dataclasses + pytest
  patterns:
    - "Optional-field extension on frozen dataclass with None defaults (parallels Plan 30-01 pattern)"
    - "TDD RED → GREEN cycle as two atomic commits with shared test module"
    - "Vendored-mirror parity enforced by post-edit cp + diff (byte-for-byte identical, D-15)"

key-files:
  created:
    - tests/test_asp_debug_result_extended_fields.py
  modified:
    - src/gps2asp/api_models.py
    - custom_components/asp_parking/gps2asp/api_models.py

key-decisions:
  - "D-04 (closed): New ASPDebugResult fields are Optional/None with None defaults — backwards-compatible (no existing constructor call site outside the two classmethods needs updating)"
  - "D-07 (closed): ASPDebugResult exposes the 4 fields at the TOP level, separate from the nested resolution field — coordinator/sensor callers read directly without unwrapping; from_resolution threads from resolution; from_error sets all None"
  - "D-08 (closed): ASPResult (the lean variant) does NOT gain these fields — they remain debug-only, lean path stays minimal"
  - "D-15 (closed): Vendored mirror byte-identical to src — enforced by post-edit cp + diff check"

patterns-established:
  - "Diagnostic-field extension on frozen ASPDebugResult: append optional fields with str|None / float|None / int|None typing and None defaults; thread in from_resolution; set None in from_error"
  - "When the editable gps2asp install points at the project root but execution happens inside a Claude Code worktree, set PYTHONPATH=<worktree>/src so pytest imports the worktree's src/gps2asp/ instead of the project-root copy. Mirror imports (custom_components.asp_parking.gps2asp.*) are path-based from cwd and need no override."

requirements-completed: [DIAG-04]

# Metrics
duration: ~6min
completed: 2026-05-03
---

# Phase 30 Plan 02: ASPDebugResult diagnostic fields Summary

**ASPDebugResult exposes four new top-level optional diagnostic fields (borocode, perpendicular_distance_ft, street_width_ft, segment_id) threaded through both classmethods — API surface ready for the Phase 30 coordinator/sensor consumers.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-05-03T15:32:44Z
- **Completed:** 2026-05-03T15:38:37Z
- **Tasks:** 2 (RED + GREEN)
- **Files modified:** 2 source
- **Files created:** 1 test

## Accomplishments

- Extended `ASPDebugResult` from 13 to 17 fields — four new optional diagnostic fields (`borocode`, `perpendicular_distance_ft`, `street_width_ft`, `segment_id`) all default `None` so the only constructor call sites that exist (the two classmethods in this same file) keep working unchanged. ASPDebugResult is also constructed nowhere else in the codebase, so the additive change is fully backwards-compatible.
- `ASPDebugResult.from_resolution()` now threads all 4 fields straight off the `ResolutionResult` argument: `borocode=resolution.borocode`, `perpendicular_distance_ft=resolution.perpendicular_distance_ft`, `street_width_ft=resolution.street_width_ft`, `segment_id=resolution.segment_id`. No extra computation; values come from Plan 30-01's resolver work.
- `ASPDebugResult.from_error()` sets all 4 new fields to `None` on the resolution-failure path — matches the existing pattern of all-None for already-existing optional fields (`on_street`, `from_street`, etc.) on the same code path.
- `ASPResult` (the lean variant) is **untouched** per D-08 — the negative test in this plan asserts ASPResult still has exactly its original 4 fields (`schedule`, `resolution_failed`, `resolution_error`, `soda_level`) and none of the new four field names.
- Vendored mirror under `custom_components/asp_parking/gps2asp/api_models.py` updated identically — `diff src/... custom_components/...` returns no output (D-15 byte-for-byte parity).
- 6 new unit tests covering: top-level field exposure, from_resolution threading with populated values, from_resolution threading with None values, from_error all-None reset, ASPResult negative (lean variant unchanged), and vendored-mirror field-name parity.
- Foundation in place for Plan 30-03 (`coordinator.ASPParkingData`) to populate `borough`/`distance_ft`/`street_width_ft`/`segment_id` directly off `ASPDebugResult` top-level attributes without nested unwrapping.

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): failing tests for ASPDebugResult diagnostic field threading** — `25f197e` (test)
2. **Task 2 (GREEN): add diagnostic fields to ASPDebugResult and thread through classmethods** — `133b743` (feat)

_Note: This is a TDD plan; the test commit precedes the implementation commit. No REFACTOR commit was needed — the GREEN edits are pure additive extensions._

## Files Created/Modified

- `tests/test_asp_debug_result_extended_fields.py` — **created** (239 lines) — 6 tests covering top-level field exposure, from_resolution threading (populated + None paths), from_error reset, ASPResult negative (D-08), and vendored-mirror parity.
- `src/gps2asp/api_models.py` — **modified** — `ASPDebugResult` gains 4 optional fields with docstring entries; `from_resolution()` cls(...) call body extended with 4 lines reading from `resolution.*`; `from_error()` cls(...) call body extended with 4 lines setting `=None`.
- `custom_components/asp_parking/gps2asp/api_models.py` — **modified** — byte-for-byte identical to `src/` version (verified via `diff` returning no output).

## ASPDebugResult Signature Change

| Item | Before | After |
|------|--------|-------|
| Field count | 13 | 17 (+4) |
| `borocode: str \| None` | absent | added (default `None`) |
| `perpendicular_distance_ft: float \| None` | absent | added (default `None`) |
| `street_width_ft: float \| None` | absent | added (default `None`) |
| `segment_id: int \| None` | absent | added (default `None`) |

## Classmethod Signature Change

| Method | Parameters | Return-cls call body |
|--------|-----------|----------------------|
| `from_resolution()` | unchanged (resolution, sign_result, schedule, state_plane_x, state_plane_y, soda_level) | +4 lines reading from `resolution.borocode/.perpendicular_distance_ft/.street_width_ft/.segment_id` |
| `from_error()` | unchanged (error, state_plane_x, state_plane_y) | +4 lines setting all 4 new fields to `None` |

## ASPResult Confirmation (D-08)

`ASPResult` field count: 4 (unchanged) — `{schedule, resolution_failed, resolution_error, soda_level}`. Verified by `dataclasses.fields(ASPResult)` in `test_aspresult_does_not_gain_new_fields`.

## Mirror Diff Confirmation (D-15)

```bash
$ diff src/gps2asp/api_models.py custom_components/asp_parking/gps2asp/api_models.py
$ echo $?
0
```

No output, exit 0 — byte-for-byte identical.

## Test Count Delta

- New module: `tests/test_asp_debug_result_extended_fields.py` — 6 tests
- Net delta: **+6 tests** (no existing tests modified or deleted)
- Pre-RED state: 0 of 6 fail at import (negative test passes), 5 fail at runtime → confirmed ≥4 failures for RED gate
- Post-GREEN state: 6 of 6 pass

## Decisions Made

Followed plan as specified — all decisions D-04, D-07, D-08, D-15 implemented exactly as defined in the plan frontmatter. No new decisions required.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] PYTHONPATH override required for pytest to import the worktree's src/gps2asp/**
- **Found during:** Task 2 (GREEN run)
- **Issue:** `python -m pytest tests/test_asp_debug_result_extended_fields.py` initially showed 4 of 6 tests still failing with `AttributeError: 'ASPDebugResult' object has no attribute 'borocode'` even after the api_models.py edits were applied to the worktree. Investigation showed the editable install (`pip install -e .`) points the `gps2asp` package at the project root (`/home/pascal/.../GPS2ASP-Resolver/src/gps2asp/api_models.py`), NOT at the worktree's `src/gps2asp/api_models.py`. The vendored-mirror test passed because that import is path-based from cwd (`custom_components.asp_parking.gps2asp.api_models`).
- **Fix:** Run pytest with `PYTHONPATH=<worktree>/src` prepended so the worktree's edited `src/gps2asp/` shadows the editable install. No source change required.
- **Files modified:** None (test invocation only).
- **Verification:** With the override, all 6 new tests + all 12 `test_resolve_asp.py` tests pass.
- **Documented in:** This SUMMARY's `patterns-established` so future worktree-executed TDD plans avoid the same false-negative.

### Out-of-scope discoveries (logged, not fixed)

- **Pre-existing failure in `tests/test_suspension.py::test_is_suspended_holiday`** — same failure that Plan 30-01 logged to `deferred-items.md`. Confirmed not caused by Plan 30-02: this plan only touches `api_models.py`; `HolidayCalendar` lives in `src/gps2asp/suspension/` with no plausible coupling. No new deferred-items entry needed — already tracked.

---

**Total deviations:** 1 auto-fixed (1 blocking) + 0 new deferred items
**Impact on plan:** Test invocation change only. No production code, no test code, no contract change. Pattern documented under `patterns-established` so future worktree TDD authors avoid the same import shadowing trap.

## Issues Encountered

- **Import shadowing under Claude Code worktree** (resolved above) — surfaced because the editable `gps2asp` install points at the project root, not the worktree. Now documented in `patterns-established` for future worktree-executed plans.

## User Setup Required

None — all changes are internal-library / dataclass-shape changes that flow through automatically once Phase 30 plans 03–04 wire the downstream consumers (coordinator + sensor extra-state-attributes).

## Next Phase Readiness

- **Plan 30-03** can now read `result.borocode`, `result.perpendicular_distance_ft`, `result.street_width_ft`, and `result.segment_id` directly off the `ASPDebugResult` returned by `resolve_asp(debug=True)` — no nested-resolution unwrapping needed (D-07 fulfilled).
- Both `ASPDebugResult` mirrors are in lock-step — no further mirror sync required for the api_models layer in this phase.
- Fast test suite is green for the 6 new tests + zero new regressions in the 343 other tests; only the pre-existing `test_suspension::test_is_suspended_holiday` failure remains (already deferred).
- TDD gate compliance: RED commit `25f197e` precedes GREEN commit `133b743`; no REFACTOR commit needed.

## TDD Gate Compliance

- **RED gate:** `25f197e` (`test(30-02): add failing tests for ASPDebugResult diagnostic field threading`) — confirmed failing with `AttributeError: 'ASPDebugResult' object has no attribute 'borocode'` (5 of 6 tests; the negative ASPResult test passed correctly).
- **GREEN gate:** `133b743` (`feat(30-02): add diagnostic fields to ASPDebugResult and thread through classmethods`) — all 6 new tests pass; full fast suite green except the pre-existing deferred suspension failure.
- **REFACTOR gate:** Not exercised — pure extension required no follow-up cleanup.

## Self-Check: PASSED

- `tests/test_asp_debug_result_extended_fields.py` exists ✓ (FOUND)
- `src/gps2asp/api_models.py` modified ✓ (FOUND)
- `custom_components/asp_parking/gps2asp/api_models.py` modified ✓ (FOUND)
- Commit `25f197e` (RED) exists in git log ✓ (FOUND)
- Commit `133b743` (GREEN) exists in git log ✓ (FOUND)
- Mirror byte-identical (`diff` returns no output) ✓
- All 6 new tests pass ✓
- All 12 `test_resolve_asp.py` tests pass (backwards-compat) ✓
- ASPResult unchanged (D-08) ✓ — `dataclasses.fields(ASPResult)` returns 4 entries
- ASPDebugResult has 17 fields (13 + 4) ✓

---
*Phase: 30-add-richer-debug-sensor-pipeline-attributes*
*Completed: 2026-05-03*
