---
phase: "08"
plan: "01"
subsystem: gps2asp-pipeline
tags: [refactor, api-surface, module-layout, build-tools]
dependency_graph:
  requires: []
  provides: [gps2asp.pipeline.resolve_asp, scripts/build_index.py, scripts/update_checker.py]
  affects: [gps2asp.__init__, gps2asp.api_models, tests/test_resolve_asp.py]
tech_stack:
  added: []
  patterns: [thin-re-export, factory-classmethod, script-directory]
key_files:
  created:
    - src/gps2asp/pipeline.py
    - scripts/build_index.py
    - scripts/update_checker.py
  modified:
    - src/gps2asp/__init__.py
    - src/gps2asp/api_models.py
    - tests/test_resolver.py
    - tests/test_edge_cases.py
    - tests/test_resolve_asp.py
    - tests/conftest.py
  deleted:
    - src/gps2asp/build/__init__.py
    - src/gps2asp/build/build_index.py
    - src/gps2asp/build/update_checker.py
decisions:
  - resolve_asp() implementation moved to pipeline.py; __init__.py is a thin re-export (~22 lines)
  - ASPDebugResult gains from_resolution() and from_error() classmethods replacing 13-field manual construction
  - Build tools moved to scripts/ at project root; src/gps2asp/build/ subpackage removed
  - Logger name gps2asp.build kept in scripts for backward log compatibility
  - resolve/convert/resolve_segment removed from __all__ but remain importable via gps2asp.resolver.*
metrics:
  duration_seconds: 148
  completed_date: "2026-03-01"
  tasks_completed: 2
  files_changed: 9
---

# Phase 08 Plan 01: Restructure Public API Surface and Module Layout Summary

**One-liner:** Moved resolve_asp() to pipeline.py with factory classmethods, thinned __init__.py to a 22-line re-export, and relocated build tools from src/gps2asp/build/ to scripts/.

## What Was Built

### Task 1: Create pipeline.py and factory classmethods (38ffdcb)

Created `src/gps2asp/pipeline.py` as the new home for the full `resolve_asp()` implementation. Added two factory classmethods to `ASPDebugResult`:
- `from_resolution()` — builds the debug result for a successful pipeline run
- `from_error()` — builds the debug result when `AmbiguousResolutionError` is caught

The pipeline.py implementation uses these factory methods instead of the previous 13-field manual dataclass construction, making the control flow cleaner.

### Task 2: Thin __init__.py, move build tools, update tests (39d1806)

Replaced the 143-line `__init__.py` (which contained the full resolve_asp body) with a 22-line thin re-export. The new `__all__` contains only `resolve_asp`, result types (`ASPResult`, `ASPDebugResult`), and error types — not the internal pipeline functions.

Moved the offline build tools from `src/gps2asp/build/` (an importable subpackage) to `scripts/` at the project root:
- `scripts/build_index.py` — CSCL download and R-tree index builder
- `scripts/update_checker.py` — monthly update check against NYC Open Data

Updated 4 test files to use the correct import paths and mock targets after the refactor.

## Verification Results

All 221 target tests pass. (1 pre-existing network-blocked test in test_sign_retrieval.py was already failing before this plan.)

```
['resolve_asp', 'ASPResult', 'ASPDebugResult', 'ResolutionError', 'OutsideNYCError', 'NoSegmentFoundError', 'AmbiguousResolutionError']
```

Public contract satisfied:
- `from gps2asp import resolve_asp` works
- `from gps2asp.resolver import resolve, convert, resolve_segment` works
- `src/gps2asp/build/` directory is gone
- `scripts/build_index.py` and `scripts/update_checker.py` exist
- `ASPDebugResult.from_resolution()` and `.from_error()` exist

## Decisions Made

- `resolve_asp()` implementation lives in `pipeline.py`; `__init__.py` is purely a re-export
- Factory classmethods on `ASPDebugResult` replace inline construction to avoid repeating 13 positional fields
- Build tools are in `scripts/` (not importable package) — reduces the installable wheel size
- Logger name `gps2asp.build` kept in scripts for backward log compatibility (per RESEARCH.md)
- Pre-existing socket-blocked test (`test_retrieve_signs_known_asp_block`) is out of scope — it was failing before this plan

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED

All created files exist on disk. Both task commits (38ffdcb, 39d1806) exist in git history. build/ subpackage confirmed removed.
