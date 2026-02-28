---
phase: 07-stabilize-pipeline-as-importable-function-with-debug-flag
plan: 2
subsystem: pipeline-integration
tags: [tdd, green-phase, pipeline, importable-api, debug-flag]
dependency_graph:
  requires:
    - src/gps2asp/api_models.py
    - src/gps2asp/signs/models.py (soda_level field)
    - tests/test_resolve_asp.py (failing RED suite from Plan 07-01)
    - src/gps2asp/resolver/__init__.py
    - src/gps2asp/signs/__init__.py
    - src/gps2asp/schedule/__init__.py
  provides:
    - src/gps2asp/__init__.py (resolve_asp, @overload stubs, updated __all__)
    - examples/run_pipeline.py (CLI live demo)
  affects:
    - Any caller of gps2asp package (now has resolve_asp in top-level namespace)
tech_stack:
  added: []
  patterns:
    - typing.overload stubs for debug: Literal[False] -> ASPResult, debug: Literal[True] -> ASPDebugResult
    - AmbiguousResolutionError caught internally; OutsideNYCError/NoSegmentFoundError propagate
    - convert() called once before resolve_segment() to avoid double coordinate conversion
    - asyncio.run() entry point in example script
key_files:
  created:
    - examples/run_pipeline.py
  modified:
    - src/gps2asp/__init__.py
decisions:
  - "resolve_segment(x, y, ...) used instead of resolve(lat, lon) to avoid double coordinate conversion — x,y from convert() reused for state_plane fields"
  - "AmbiguousResolutionError only is caught; OutsideNYCError and NoSegmentFoundError propagate per spec"
  - "soda_level=0 in debug result when sign_result is not SignRetrievalSuccess (NoMatchFound, NoASPSigns)"
metrics:
  duration_minutes: 2
  completed_date: "2026-02-28"
  tasks_completed: 2
  files_changed: 2
---

# Phase 7 Plan 2: Implement resolve_asp() — TDD GREEN phase

**One-liner:** resolve_asp() async function with @overload stubs wiring GPS -> segment -> SODA -> schedule into a single importable call, making all 8 RED tests pass.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Implement resolve_asp() in __init__.py with @overload stubs | c61cf70 | src/gps2asp/__init__.py |
| 2 | Create examples/run_pipeline.py CLI demo | d1aa2e8 | examples/run_pipeline.py |

## What Was Built

**Task 1 — resolve_asp() implementation:**
- Added `from __future__ import annotations` (missing from original __init__.py)
- Added imports: `Literal`, `overload`, `ASPResult`, `ASPDebugResult`, `retrieve_signs`, `SignRetrievalSuccess`, `compute_schedule`
- Extended `__all__` with `"resolve_asp"`, `"ASPResult"`, `"ASPDebugResult"`
- Two `@overload` stubs narrowing return type: `debug: Literal[False]` -> `ASPResult`, `debug: Literal[True]` -> `ASPDebugResult`
- Runtime implementation with three pipeline stages:
  - Stage 1: `convert(lat, lon)` -> `(x, y)`, then `resolve_segment(x, y, _input_lat=lat, _input_lon=lon)`
  - Stage 2: `retrieve_signs(on_street, from_street, to_street, side_of_street)`
  - Stage 3: `compute_schedule(sign_result)`
- `AmbiguousResolutionError` caught, returns `resolution_failed=True` result (debug or non-debug)
- `OutsideNYCError`, `NoSegmentFoundError` propagate to caller
- `soda_level=0` in debug result when `sign_result` is not `SignRetrievalSuccess`
- All 8 tests in `tests/test_resolve_asp.py` pass (GREEN)

**Task 2 — examples/run_pipeline.py:**
- Standalone script (no `__init__.py` in examples/)
- `argparse` for optional positional `lat` and `lon` (defaults to PROSPECT PL, Brooklyn)
- `DEFAULT_LAT = 40.677629`, `DEFAULT_LON = -73.968527`
- Runs both `debug=False` and `debug=True` in sequence, prints both results
- `asyncio.run(run())` async entry point
- Documents `pip install -e "[dev]"` and `build_index` requirements in docstring

## Verification

```
# All 8 resolve_asp tests pass (GREEN)
.venv/bin/python -m pytest tests/test_resolve_asp.py -v
# -> 8 passed in 0.25s

# Full suite (221 passed, excluding pre-existing socket-blocked test_sign_retrieval.py)
.venv/bin/python -m pytest -x -q --ignore=tests/test_sign_retrieval.py
# -> 221 passed in 11.08s

# Imports OK
.venv/bin/python -c "from gps2asp import resolve_asp, ASPResult, ASPDebugResult; print('imports OK')"
# -> imports OK

# __all__ OK
.venv/bin/python -c "from gps2asp import __all__; assert all(x in __all__ for x in ['resolve_asp','ASPResult','ASPDebugResult']); print('__all__ OK')"
# -> __all__ OK

# Example script help
.venv/bin/python examples/run_pipeline.py --help
# -> usage: run_pipeline.py [-h] [lat] [lon] ...
```

## Deviations from Plan

None — plan executed exactly as written.

**Note on mypy:** One pre-existing error in `src/gps2asp/signs/client.py` (unrelated incompatible type assignment). This file was not modified by this plan and the error predates it. Out of scope per deviation rules.

**Note on test_sign_retrieval.py:** 6 pre-existing integration tests that make real network calls remain blocked by pytest-socket. Pre-existing, out of scope.

## Decisions Made

1. `resolve_segment(x, y, ...)` used instead of `resolve(lat, lon)` — avoids double coordinate conversion; coordinates from `convert()` are reused for `state_plane_x`/`state_plane_y` debug fields
2. Only `AmbiguousResolutionError` is caught — per spec, `OutsideNYCError` and `NoSegmentFoundError` propagate
3. `soda_level=0` when sign_result is not `SignRetrievalSuccess` — covers `NoMatchFound` and `NoASPSigns` cases

## Self-Check: PASSED

Files created/modified:
- FOUND: src/gps2asp/__init__.py (resolve_asp + overloads + imports + __all__ update)
- FOUND: examples/run_pipeline.py (CLI demo with DEFAULT_LAT = 40.677629)

Commits:
- FOUND: c61cf70 feat(07-02): implement resolve_asp() in __init__.py with @overload stubs
- FOUND: d1aa2e8 feat(07-02): create examples/run_pipeline.py CLI demo
