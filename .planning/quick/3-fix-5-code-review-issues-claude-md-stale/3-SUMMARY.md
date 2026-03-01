---
phase: quick-3
plan: 01
subsystem: docs-and-code-quality
tags: [code-quality, comments, conventions, dead-code]
dependency_graph:
  requires: []
  provides: [accurate-docs, convention-compliance, clean-metadata]
  affects: [CLAUDE.md, tests/test_confidence.py, scripts/build_index.py, src/gps2asp/signs/__init__.py, src/gps2asp/resolver/confidence.py]
tech_stack:
  added: []
  patterns: [from __future__ import annotations convention]
key_files:
  created: []
  modified:
    - CLAUDE.md
    - tests/test_confidence.py
    - scripts/build_index.py
    - src/gps2asp/signs/__init__.py
    - src/gps2asp/resolver/confidence.py
decisions:
  - CLAUDE.md now shows scripts/ as a top-level sibling of src/ and tests/ (not nested under src/gps2asp/)
  - Dead l/r_blockfaceid fields removed from segments.json generation (never read by spatial_index.py after Phase 8)
metrics:
  duration: ~8 min
  completed: 2026-03-01
  tasks_completed: 2
  files_modified: 5
---

# Quick Task 3: Fix Five Code Review Issues (CLAUDE.md Stale) Summary

**One-liner:** Five targeted single-line fixes removing stale docs, a missing future-import, two wrong comments, and two dead dict fields from build_index.py.

## What Was Done

Fixed five post-Phase-8 code review issues found after the architecture refactor:

1. **CLAUDE.md stale structure** — `build/` was listed as a sub-directory of `src/gps2asp/` but Phase 8 moved build scripts to `scripts/` at project root. Updated to show `scripts/` as a top-level entry alongside `src/gps2asp/` and `tests/`.

2. **Missing `from __future__ import annotations`** — `tests/test_confidence.py` lacked the project-wide annotation import convention. Added after the module docstring, before `import pytest`.

3. **Wrong "lowercase" comment in signs/__init__.py** — Line 88 said `# Normalize ... (lowercase, strip, no punctuation)` but `_normalize_street()` calls `.upper()` then `normalize_to_soda`. Corrected to `(uppercase, strip, expand abbreviations)`.

4. **Misleading "scales from 0" comment in confidence.py** — Line 125 said `scales from 0 at _NEAR_INTERSECTION_THRESHOLD_FT` but the early-return guard at line 117 already handles d < 30ft with return 0.0. The formula `min(1.0, d / 100.0)` is only reached when d >= 30ft, so the minimum reachable value is 30/100 = 0.3. Corrected to `scales from 0.3 at _NEAR_INTERSECTION_THRESHOLD_FT (30ft)`.

5. **Dead l/r_blockfaceid fields in build_index.py** — `SegmentCandidate` no longer has these fields (removed in Phase 8). Removed two lines writing them into segments.json; they were never read by `spatial_index.py`.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Fix four comment/annotation issues | 4170ee0 | CLAUDE.md, tests/test_confidence.py, src/gps2asp/signs/__init__.py, src/gps2asp/resolver/confidence.py |
| 2 | Remove dead l/r_blockfaceid fields from build_index.py | 77f3ba4 | scripts/build_index.py |

## Verification Results

- `grep -n "blockfaceid" scripts/build_index.py` — no results (CLEAN)
- `grep -n "from __future__" tests/test_confidence.py` — line 3: `from __future__ import annotations`
- `grep -n "build/" CLAUDE.md` — no results (CLEAN)
- `grep -n "scripts/" CLAUDE.md` — line 10 shows top-level entry
- `grep -n "lowercase" src/gps2asp/signs/__init__.py` — no results (CLEAN)
- `grep -n "scales from 0.3" src/gps2asp/resolver/confidence.py` — line 125 match
- `python -m pytest -q` — 221 passed

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED

- CLAUDE.md updated: FOUND
- tests/test_confidence.py updated: FOUND
- src/gps2asp/signs/__init__.py updated: FOUND
- src/gps2asp/resolver/confidence.py updated: FOUND
- scripts/build_index.py updated: FOUND
- Commit 4170ee0: FOUND
- Commit 77f3ba4: FOUND
- 221 tests pass: CONFIRMED
