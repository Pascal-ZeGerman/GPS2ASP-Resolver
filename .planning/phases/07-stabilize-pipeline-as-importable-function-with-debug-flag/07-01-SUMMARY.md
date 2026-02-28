---
phase: 07-stabilize-pipeline-as-importable-function-with-debug-flag
plan: 1
subsystem: api-models
tags: [tdd, data-models, pipeline, debug]
dependency_graph:
  requires:
    - src/gps2asp/signs/models.py
    - src/gps2asp/resolver/models.py
    - src/gps2asp/schedule/models.py
  provides:
    - src/gps2asp/api_models.py (ASPResult, ASPDebugResult)
    - src/gps2asp/signs/models.py (SignRetrievalSuccess.soda_level)
    - tests/test_resolve_asp.py (failing test suite)
  affects:
    - src/gps2asp/signs/__init__.py (soda_level at all three return sites)
tech_stack:
  added: []
  patterns:
    - frozen dataclasses with full docstrings (project convention)
    - TDD RED phase — tests fail at import, not syntax
    - soda_level default=1 for backwards compatibility
key_files:
  created:
    - src/gps2asp/api_models.py
    - tests/test_resolve_asp.py
  modified:
    - src/gps2asp/signs/models.py
    - src/gps2asp/signs/__init__.py
decisions:
  - "soda_level: int = 1 as last field of SignRetrievalSuccess preserves backwards compatibility for existing call sites"
  - "Test mocking targets gps2asp.convert, gps2asp.resolve_segment, gps2asp.retrieve_signs, gps2asp.compute_schedule — these will be imported into gps2asp.__init__ by Plan 07-02"
  - "ASPDebugResult carries 13 fields exactly as locked in CONTEXT.md — no parking_lane_fraction exposed per spec"
metrics:
  duration_minutes: 4
  completed_date: "2026-02-28"
  tasks_completed: 3
  files_changed: 4
---

# Phase 7 Plan 1: Data model foundation and failing tests for resolve_asp() (TDD RED)

**One-liner:** Frozen ASPResult/ASPDebugResult dataclasses and soda_level-augmented SignRetrievalSuccess, with 8 failing async tests specifying the resolve_asp() contract.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Add soda_level field to SignRetrievalSuccess | 3a7a508 | signs/models.py, signs/__init__.py |
| 2 | Create api_models.py with ASPResult and ASPDebugResult | 4355afe | src/gps2asp/api_models.py |
| 3 | Write failing tests for resolve_asp() | c26d1d6 | tests/test_resolve_asp.py |

## What Was Built

**Task 1 — SignRetrievalSuccess.soda_level:**
- Added `soda_level: int = 1` as the last field of `SignRetrievalSuccess` in `signs/models.py`
- Updated all three `SignRetrievalSuccess(...)` return sites in `signs/__init__.py` to set `soda_level` explicitly: Level 1 → `soda_level=1`, Level 2 → `soda_level=2`, Level 3 → `soda_level=3`
- Default of `1` preserves backwards compatibility; no existing call sites break

**Task 2 — api_models.py:**
- `ASPResult` (3 fields): `schedule: ScheduleResult | None`, `resolution_failed: bool`, `resolution_error: str | None`
- `ASPDebugResult` (13 fields): all fields from locked CONTEXT.md spec — schedule, resolution_failed, resolution_error, on_street, from_street, to_street, side_of_street, resolution, sign_result, confidence, state_plane_x, state_plane_y, soda_level
- Both are `@dataclass(frozen=True)` with `from __future__ import annotations` and full docstrings
- Imports: `ResolutionResult` from resolver, `ScheduleResult` from schedule, `SignRetrievalResult` from signs

**Task 3 — Failing test suite (RED):**
- 8 async tests in `tests/test_resolve_asp.py`
- Tests cover: return type narrowing (debug=False/True), AmbiguousResolutionError caught, OutsideNYCError propagates, successful pipeline fields (confidence, soda_level, state_plane coordinates), soda_level=0 for NoMatchFound
- All tests use `unittest.mock.patch` and `AsyncMock` — no real network/index calls
- Tests fail at import: `ImportError: cannot import name 'resolve_asp' from 'gps2asp'` — expected RED state

## Verification

```
# Task 1: field present
python -c "from gps2asp.signs.models import SignRetrievalSuccess; import dataclasses; print([f.name for f in dataclasses.fields(SignRetrievalSuccess)])"
# → ['status', 'signs', 'on_street', 'from_street', 'to_street', 'side_of_street', 'soda_level']

# Task 2: import succeeds
python -c "from gps2asp.api_models import ASPResult, ASPDebugResult; print('OK')"
# → OK

# Task 3: fails with ImportError (correct RED)
python -m pytest tests/test_resolve_asp.py --collect-only
# → ImportError: cannot import name 'resolve_asp' from 'gps2asp'

# Full suite (excluding new failing file and pre-existing socket-blocked tests): 213 passed
python -m pytest --ignore=tests/test_resolve_asp.py --ignore=tests/test_sign_retrieval.py -x -q
# → 213 passed in 10.33s
```

## Deviations from Plan

None — plan executed exactly as written.

**Note on test_sign_retrieval.py:** These 6 tests were already failing before this plan (integration tests that make real network calls, blocked by pytest-socket). Pre-existing, out of scope. Not introduced by this plan.

## Decisions Made

1. `soda_level: int = 1` default on `SignRetrievalSuccess` — field added at end to avoid disrupting positional construction; default=1 because Level 1 was the original implicit behavior
2. Test mock targets: patching at `gps2asp.*` namespace (e.g., `gps2asp.convert`) because Plan 07-02 will import these names into `gps2asp/__init__.py`; this is the correct patch target for Plan 07-02's implementation
3. `ASPDebugResult` has exactly 13 fields per CONTEXT.md lock — `parking_lane_fraction` explicitly excluded

## Self-Check: PASSED

Files created/modified:
- FOUND: src/gps2asp/api_models.py
- FOUND: src/gps2asp/signs/models.py (soda_level field)
- FOUND: src/gps2asp/signs/__init__.py (3 soda_level return sites)
- FOUND: tests/test_resolve_asp.py (8 async tests)

Commits:
- FOUND: 3a7a508 feat(07-01): add soda_level field to SignRetrievalSuccess
- FOUND: 4355afe feat(07-01): create api_models.py with ASPResult and ASPDebugResult
- FOUND: c26d1d6 test(07-01): add failing tests for resolve_asp() contract (RED phase)
