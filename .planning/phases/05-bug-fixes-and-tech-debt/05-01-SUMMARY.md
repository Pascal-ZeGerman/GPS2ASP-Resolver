---
phase: 05-bug-fixes-and-tech-debt
plan: 01
subsystem: schedule-models, ha-sensor, dev-tooling
tags: [bug-fix, type-safety, mypy, venv, sensor]
requirements: [BUG-01, BUG-02]

dependency_graph:
  requires: []
  provides:
    - ScheduleFound.next_window typed as CleaningWindow | None
    - mypy-clean schedule module
    - sensor None-safe next_window access
    - correct venv pip shebang for renamed directory
  affects:
    - src/gps2asp/schedule/models.py
    - src/gps2asp/schedule/__init__.py
    - custom_components/asp_parking/sensor.py
    - tests/test_ha_integration.py

tech_stack:
  added: [mypy]
  patterns:
    - Discriminated union field widened to Optional via CleaningWindow | None
    - Sensor None guard pattern for optional dataclass fields

key_files:
  created: []
  modified:
    - pyproject.toml
    - CLAUDE.md
    - src/gps2asp/schedule/models.py
    - src/gps2asp/schedule/__init__.py
    - custom_components/asp_parking/sensor.py
    - tests/test_ha_integration.py

decisions:
  - Update pip itself (pip upgrade) rather than reinstall gps2asp to regenerate pip wrapper shebangs
  - Omit next_window_* keys entirely from extra_state_attributes when next_window is None (callers check key existence)
  - Update test helper functions in test_ha_integration.py to mirror sensor.py None guard logic

metrics:
  duration: 10 min
  completed: 2026-02-28
  tasks: 2
  files_modified: 6
---

# Phase 05 Plan 01: Bug Fixes — Venv Path and Type Annotation Summary

Fixed two bugs surfaced during the 2026-02-27 end-to-end pipeline test: stale venv pip shebangs after project directory rename, and ScheduleFound.next_window typed as non-optional while find_next_window() returns CleaningWindow | None.

## What Was Built

**BUG-01 (venv path staleness):**
- Added `mypy` to `[project.optional-dependencies] dev` in `pyproject.toml`
- Ran `python -m pip install -e ".[dev]"` to install mypy and regenerate `.pth` files
- Upgraded pip itself via `python -m pip install --upgrade pip` to regenerate `.venv/bin/pip*` wrapper scripts with the correct `VW-CarNet` (dash) shebang
- Added pip/venv convention note to `CLAUDE.md`: always use `python -m pip`; after directory rename, re-run `python -m pip install -e ".[dev]"`

**BUG-02 (ScheduleFound.next_window type mismatch):**
- Changed `next_window: CleaningWindow` to `next_window: CleaningWindow | None` in `ScheduleFound` dataclass
- Updated docstring: "The next upcoming ASP cleaning window, or None if no upcoming window found within 7 days."
- Added explanatory comment in `__init__.py` replacing placeholder (no `# type: ignore` existed in file)
- Added None guard in `sensor.py native_value`: returns `None` instead of AttributeError when next_window is None
- Added None guard in `sensor.py extra_state_attributes`: omits `next_window_*` keys when next_window is None
- Added new test `test_schedule_found_none_next_window_returns_none` in `TestSensorStateMapping`
- Updated `sensor_native_value()` and `sensor_extra_attributes()` test helpers to match None guard logic

## Decisions Made

1. **pip upgrade to regenerate shebangs:** `pip install -e .` regenerates the `.pth` file but not the pip wrapper scripts themselves. Upgrading pip via `python -m pip install --upgrade pip` causes pip to reinstall itself with a fresh shebang pointing to the current Python executable path.

2. **Omit next_window_* keys when None:** When `next_window is None`, the three window attributes (`next_window_start`, `next_window_end`, `next_window_day`) are omitted entirely from `extra_state_attributes`. Callers check key existence rather than expecting None values.

3. **Test helpers updated to mirror sensor:** The test file uses standalone helper functions (`sensor_native_value`, `sensor_extra_attributes`) that replicate sensor logic. Both were updated to include the None guard to keep tests accurate representations of production behavior.

## Verification Results

- `.venv/bin/pip` shebang: `#!/home/pascal/Vibe-Coding/VW-CarNet/GSP2ASP-Resolver/.venv/bin/python` (dash, correct)
- `from gps2asp.resolver import resolve` succeeds via `.venv/bin/python`
- `mypy src/gps2asp/schedule/` — no errors on schedule module
- 208 tests pass (excluding pre-existing network socket tests in test_sign_retrieval.py)
- 25 HA integration tests pass (24 pre-existing + 1 new)
- New test `test_schedule_found_none_next_window_returns_none` passes

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] pip upgrade needed to regenerate wrapper shebangs**
- **Found during:** Task 1
- **Issue:** `pip install -e ".[dev]"` regenerates the `.pth` file but not the pip wrapper scripts (`pip`, `pip3`, `pip3.13`). The wrappers remained dated Feb 21 with old "VW CarNet" space shebang.
- **Fix:** Ran `python -m pip install --upgrade pip` which caused pip to reinstall itself, generating new wrapper scripts with the correct dash-path shebang.
- **Files modified:** `.venv/bin/pip`, `.venv/bin/pip3`, `.venv/bin/pip3.13` (binary, not committed)
- **Commit:** 7d00e00

**2. [Rule 2 - Missing functionality] Test helpers also needed None guards**
- **Found during:** Task 2
- **Issue:** The test file's `sensor_native_value()` and `sensor_extra_attributes()` helper functions replicate sensor.py logic but lacked the None guards. The new test would pass trivially without them (it only calls helpers, not real sensor), but the helpers would be incorrect representations of production behavior.
- **Fix:** Updated both test helpers to include the same None guard logic added to sensor.py.
- **Files modified:** `tests/test_ha_integration.py`
- **Commit:** 599ccfb

## Self-Check: PASSED

Files created/modified:
- FOUND: pyproject.toml (mypy in dev deps)
- FOUND: CLAUDE.md (pip convention note)
- FOUND: src/gps2asp/schedule/models.py (CleaningWindow | None)
- FOUND: src/gps2asp/schedule/__init__.py (comment updated)
- FOUND: custom_components/asp_parking/sensor.py (None guards)
- FOUND: tests/test_ha_integration.py (new test + helper updates)

Commits:
- FOUND: 7d00e00 (Task 1: BUG-01)
- FOUND: 599ccfb (Task 2: BUG-02)
