---
phase: 32-sensor-display-format
plan: 02
subsystem: ha-integration
tags:
  - sensor
  - display-format
  - timezone
  - tdd-green
  - wave-1
  - fmt-01
dependency_graph:
  requires:
    - tests/test_sensor_display_format.py (RED test surface from Plan 32-01)
    - tests/test_ha_integration.py (mirror + regex + urgency rewritten in Plan 32-01)
    - homeassistant.util.dt (dt_util)
  provides:
    - custom_components/asp_parking/util.py (new module exporting now_ha_local)
    - ASPNextMoveTimeSensor._format_move_time three-tier date-aware output
    - ASPNextMoveTimeSensor.extra_state_attributes — next_move_is_today / next_move_is_tomorrow (always present) + urgency realigned to date-equality gate
    - README.md "## Upgrade Notes" section documenting the v3.2 breaking change
    - Stable import surface for Phase 34 CalDAV: `from custom_components.asp_parking.util import now_ha_local`
  affects:
    - custom_components/asp_parking/sensor.py (imports + _format_move_time + native_value docstring + extra_state_attributes)
    - README.md (insertion before "## Known Limitations")
tech_stack:
  added: []
  patterns:
    - "Thin HA-utility module pattern (Pattern 1): pure-function helper wrapping dt_util.now()"
    - "Date-equality tiering for day-boundary labels (Pattern 2): compare local_dt.date() to today / today+1, no seconds-until heuristic"
    - "Single source-of-truth derivation (Pitfall 4): is_today / is_tomorrow drive both urgency and the new boolean attributes — no duplicate calls to dt_util.as_local or now_ha_local"
key_files:
  created:
    - custom_components/asp_parking/util.py
  modified:
    - custom_components/asp_parking/sensor.py
    - README.md
decisions:
  - "D-01..D-07 implemented exactly as locked in CONTEXT.md. No deviations."
  - "Boolean defaults (next_move_is_today / next_move_is_tomorrow) placed at the TOP of extra_state_attributes, immediately after `attrs = {}` and before suspension merge / isinstance branching. This guarantees they appear on every code path (special_state, NoASPSchedule, NoMatchSchedule, AllUnparseable, suspended, no-window) per Open Question #2 and Pitfall 6."
  - "native_value docstring updated with the new three-tier examples (Today / Tomorrow / Other) — was referencing the obsolete `'Mon 8:00 AM', '⚠ Today 8:00 AM'` format. Kept the rest of the docstring unchanged."
  - "_format_move_time kept as instance method on ASPNextMoveTimeSensor (RESEARCH.md Open Question #1). Not refactored to module-level."
metrics:
  duration_minutes: 12
  completed_date: 2026-05-13
  task_count: 3
  files_created: 1
  files_modified: 2
  tests_passing_after_change: 509
  newly_green_tests: 20
---

# Phase 32 Plan 02: Sensor Display Format GREEN Implementation Summary

Wave 1 GREEN — implements FMT-01 by adding the `now_ha_local()` helper in a new `util.py` module, rewriting `ASPNextMoveTimeSensor._format_move_time` to the locked three-tier date-aware format ("⚠ Today, 8:30 AM" / "Tomorrow, 8:30 AM" / "Thursday (5/3), 8:30 AM"), realigning the urgency attribute to a date-equality gate, adding the always-present `next_move_is_today` / `next_move_is_tomorrow` boolean attributes, and shipping a README breaking-change note pointing template authors at the new attributes and the preserved `next_window_start` ISO attribute. Closes Plan 32-01's 20 RED tests in `tests/test_sensor_display_format.py` and the 7 rewritten tests in `tests/test_ha_integration.py`; full non-integration suite is 509 / 509 green.

## Tasks Completed

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1 | Create `custom_components/asp_parking/util.py` with `now_ha_local()` helper (D-05) | `d5645a6` | `custom_components/asp_parking/util.py` |
| 2 | Rewrite `ASPNextMoveTimeSensor._format_move_time` and the urgency / booleans block in `extra_state_attributes` | `59c8dc2` | `custom_components/asp_parking/sensor.py` |
| 3 | Add the v3.2 breaking-change note to `README.md` | `7d69f41` | `README.md` |

## New File — `custom_components/asp_parking/util.py`

Cited line-by-line for downstream reuse (Phase 34 CalDAV will import `now_ha_local` from this module without further refactoring):

```python
"""Shared utilities for the ASP Parking integration.

Pure-function helpers wrapping Home Assistant primitives. No state, no
class — every function is safe to import from any other module in this
integration without circular-import risk.
"""

from __future__ import annotations

from datetime import datetime

from homeassistant.util import dt as dt_util


def now_ha_local() -> datetime:
    """Return the current datetime in Home Assistant's configured local timezone.

    Thin wrapper over ``homeassistant.util.dt.now()`` so callers do not need
    to import ``dt_util`` directly. Used by Phase 32 (sensor display format)
    and Phase 34 (CalDAV calendar integration).
    """
    return dt_util.now()
```

Total length: 22 lines (well under the 35-line ceiling in the acceptance criteria). No class, no global state, no logging. Module is exempt from the Phase 31 vendor guard by design — it lives at `custom_components/asp_parking/util.py`, not under `gps2asp/`, so `scripts/sync_vendored.py` does not require a matching `src/gps2asp/util.py` mirror.

## Diff Applied to `custom_components/asp_parking/sensor.py`

Six in-place edits, all on `ASPNextMoveTimeSensor` (no other sensor class touched):

1. **Imports (line 20).** `from datetime import datetime` → `from datetime import datetime, timedelta`.

2. **Imports (line 41 area).** Added `from .util import now_ha_local` right after `from .coordinator import ASPParkingCoordinator`. Uses the leading-dot relative-import style matching `.const` and `.coordinator`.

3. **`_format_move_time` (was lines 108–118, ~10 lines → ~22 lines after edit).** Body fully replaced:
   - Binds `local_dt = dt_util.as_local(dt)` (unchanged).
   - Binds `today = now_ha_local().date()` and `target_date = local_dt.date()` — replaces the old `seconds_until = (dt_util.as_utc(dt) - dt_util.utcnow()).total_seconds()` line.
   - Binds `time_str = local_dt.strftime("%I:%M %p").lstrip("0")` (unchanged, simplified to one line).
   - Branches:
     - `if target_date == today: return f"⚠ Today, {time_str}"` — note the new comma between "Today" and the time (D-01).
     - `if target_date == today + timedelta(days=1): return f"Tomorrow, {time_str}"` — new Tomorrow tier (D-01).
     - Otherwise: `weekday = local_dt.strftime("%A")` and `md = f"{local_dt.month}/{local_dt.day}"`, then `return f"{weekday} ({md}), {time_str}"`.
   - Docstring rewritten to cite FMT-01 / D-01 / D-02 and document the three tiers.
   - `seconds_until` and `day_str = local_dt.strftime("%a")` fully removed.

4. **`native_value` docstring (around line 124).** Replaced the obsolete line
   `Normal: "Mon 8:00 AM", Urgent (<12h): "⚠ Today 8:00 AM"`
   with three lines, one per tier:
   ```
   Today: "⚠ Today, 8:30 AM"
   Tomorrow: "Tomorrow, 8:30 AM"
   Other: "Thursday (5/3), 8:30 AM"
   ```
   Other lines of the docstring stay unchanged.

5. **`extra_state_attributes` defaults at top (right after `attrs: dict[...] = {}`).** Inserted six lines:
   ```python
   # Date-relationship booleans (D-06: always present, default False)
   # Set defaults BEFORE branching so attributes are present even when no
   # concrete _move_dt exists (Claude's discretion: never None, never omitted).
   attrs["next_move_is_today"] = False
   attrs["next_move_is_tomorrow"] = False
   ```
   This placement (BEFORE `schedule = data.schedule_result`, the suspension merge, and the `isinstance(schedule, (ScheduleFound, ASPActiveNow))` branch) guarantees the booleans appear on every code path: special_state, NoASPSchedule, NoMatchSchedule, AllUnparseable, suspended, no-window, even initial / loading. The 20 RED tests in `TestNewBooleanAttributes` and `tests/test_ha_integration.py::TestUrgencyAttribute::test_urgency_absent_when_next_window_none` all confirm this.

6. **`extra_state_attributes` urgency block (was lines 243–253).** Replaced the `seconds_until < 12 * 3600` gate with:
   ```python
   # Urgency + date-relationship booleans — only when a concrete move
   # datetime exists. Single source-of-truth derivation (Pitfall 4):
   # is_today / is_tomorrow drive both urgency and the new booleans.
   _move_dt: datetime | None = None
   if isinstance(schedule, ScheduleFound) and schedule.next_window is not None:
       _move_dt = schedule.next_window.start_datetime
   elif isinstance(schedule, ASPActiveNow):
       _move_dt = schedule.active_window.end_datetime
   if _move_dt is not None:
       local_dt = dt_util.as_local(_move_dt)
       today = now_ha_local().date()
       target_date = local_dt.date()
       is_today = target_date == today
       is_tomorrow = target_date == today + timedelta(days=1)
       attrs["urgency"] = "high" if is_today else "normal"
       attrs["next_move_is_today"] = is_today
       attrs["next_move_is_tomorrow"] = is_tomorrow
   ```
   `is_today` and `is_tomorrow` are bound once and drive all three attributes — no duplicate calls to `dt_util.as_local`, `now_ha_local`, or the date-equality comparison (Pitfall 4 mitigated).

Pre-existing attribute keys (`cleaning_days`, `time_window_start`, `time_window_end`, `schedule_summary`, `street_name`, `cross_streets`, `side_of_street`, `next_window_start`, `next_window_end`, `next_window_day`, `current_window_start`, `current_window_end`, `suspension_reason`, `resolution_reason`, `last_resolved`, `confidence_score`, `borough`, `sign_count`, `parse_failures`, `soda_level`, `last_error`, `last_error_time`) are NOT touched (D-07).

## README Section Added

Heading exactly: `## Upgrade Notes`, with sub-heading `### v3.2 — Sensor Display Format (Breaking change)`.

Inserted immediately BEFORE `## Known Limitations` (README line 74 in the worktree after the edit).

Bullet count:
- "Templates affected" — 2 bullets (two `startswith` / `in` template examples that break).
- "Migration" — 2 bullets (boolean attributes pointer; preserved `next_window_start` pointer).

Required-string presence (verified by `grep -c`):

| String | Count |
| ------ | ----- |
| `Breaking change` | 1 |
| `Thursday (5/3), 8:30 AM` | 1 |
| `next_move_is_today` | 1 |
| `next_move_is_tomorrow` | 1 |
| `next_window_start` | 1 |
| `^## Upgrade Notes` | 1 |

Ordering verified via awk: `## Upgrade Notes` is at line 74, `## Known Limitations` is at line 100 — Upgrade Notes appears first.

Code-fence balance: `python -c` check returned `OK` (balanced fenced blocks).

## Test Results

| Suite | Before | After | Newly green |
| ----- | ------ | ----- | ----------- |
| `tests/test_sensor_display_format.py` | 0 / 20 (collect-time `ModuleNotFoundError` on `custom_components.asp_parking.util`) | **20 / 20 passed** in 1.45 s | 20 (every test from Plan 32-01) |
| `tests/test_ha_integration.py` | 77 / 77 passed (mirror was rewritten in Plan 32-01 to match the new contract) | **77 / 77 passed** in 1.41 s | 7 of the 77 are the format/urgency tests that exercise the new behavior (`TestHumanFriendlyNativeValue.test_schedule_found_normal_format`, `test_schedule_found_urgent_format`, `test_asp_active_now_normal_format`, `test_asp_active_now_urgent_format`, `TestUrgencyAttribute.test_urgency_normal_when_far_away`, `test_urgency_high_when_soon`, `test_urgency_high_for_asp_active_now_soon`); all green. |
| Full non-integration suite (`.venv/bin/pytest -m "not integration"`) | 489 / 489 (pre-32-01 baseline) | **509 / 509 passed**, 32 deselected | +20 from the new `test_sensor_display_format.py` |

No flakes. No regressions. The 32 deselected tests are the `integration`-marked tests that require live network access to the NYC Open Data SODA API — not exercised by this phase.

## Behavior Sanity Checks (live `ASPNextMoveTimeSensor._format_move_time`)

Run interactively against the GREEN sensor.py:

| Input (NYC-local datetime) | Expected start | Actual return |
| -------------------------- | -------------- | ------------- |
| today at 08:30 | `"⚠ Today, "` | `'⚠ Today, 12:30 PM'` ✓ (12:30 PM because the live run was at 12:30 PM NYC) |
| today + 1 day at 08:30 | `"Tomorrow, "` | `'Tomorrow, 12:30 PM'` ✓ |
| today + 3 days at 08:30 | `<weekday> (M/D), ` | `'Saturday (5/16), 12:30 PM'` ✓ (today is 2026-05-13 Wed; +3d = Saturday 5/16) |

All three behavioral acceptance criteria from Task 2 pass.

## Verification — Plan-Level Gates

| Gate | Result |
| ---- | ------ |
| `.venv/bin/pytest tests/test_sensor_display_format.py -x -q` | 20 / 20 passed ✓ |
| `.venv/bin/pytest tests/test_ha_integration.py -x -q` | 77 / 77 passed ✓ |
| `.venv/bin/pytest -m "not integration"` | 509 / 509 passed, 32 deselected ✓ |
| `! grep -n "seconds_until" custom_components/asp_parking/sensor.py` | 0 references (Pitfall 7 satisfied) ✓ |
| `! grep -E "%-[dmHI]" custom_components/asp_parking/sensor.py` | 0 GNU strftime tokens in sensor.py (Pitfall 1 satisfied) ✓ |
| `! grep -rn "NYC_TZ" custom_components/asp_parking/sensor.py` | 0 — display path never hardcodes NYC TZ (D-02, D-03) ✓ |
| `! test -f custom_components/asp_parking/gps2asp/util.py` | True — Phase 31 vendor guard preserved ✓ |
| Manual: README.md "Breaking change" note visible | ✓ — section title `## Upgrade Notes` → `### v3.2 — Sensor Display Format (Breaking change)` placed before `## Known Limitations` |

## Threat Surface

No new trust boundaries introduced (matches threat_model in 32-02-PLAN.md). All four threats (T-32-04..T-32-07) are `accept` or `mitigate` with mitigation in place:

- **T-32-06 (D / strftime platform portability):** Mitigated. `f"{dt.month}/{dt.day}"` used in both `_format_move_time` and (via the rewritten mirror in Plan 32-01) the test helper. `grep -E "%-[dmHI]" custom_components/asp_parking/sensor.py` returns zero matches. The only remaining `%-d` reference in the tree is a documentation comment in `tests/test_ha_integration.py` explaining the choice not to use it — not actual strftime usage.
- **T-32-04 (I / display string disclosure):** Accepted. String contains only public NYC ASP schedule date/time — no PII or secrets.
- **T-32-05 (T / `dt_util.DEFAULT_TIME_ZONE` global):** Accepted. Production code does not mutate the global; only test fixtures do, and they always restore (Pitfall 3 mitigated in the Plan 32-01 test fixture).
- **T-32-07 (E / util.py import surface):** Accepted. Module exports a single pure function returning a public datetime. No coordinator coupling, no hass state access.

No new security-relevant surface beyond what's documented in `<threat_model>`. No threat flags.

## Deviations from Plan

### Auto-fixed Issues

**None.** The plan was executed exactly as written. No Rule 1 / 2 / 3 deviations required.

### Documented Decisions (not deviations)

**1. [Decision] Pitfall 1 grep on tests/ shows one match in a comment.**
- **Found during:** Plan-level verification gate `! grep -rE "%-[dmHI]" custom_components/asp_parking/sensor.py tests/`.
- **Match:** `tests/test_ha_integration.py:# Full weekday name + unpadded M/D (no %-d which breaks on non-Linux CI).`
- **Decision:** Leave it. This is a documentation comment explaining the rationale for using `f"{dt.month}/{dt.day}"` over `strftime("%-d")` — it is not actual GNU strftime usage. The Plan 32-01 SUMMARY already documented and accepted this same hit under the same rationale. The production sensor.py grep (`! grep -E "%-[dmHI]" custom_components/asp_parking/sensor.py`) is clean (zero hits).

## Pointer for Phase 34 (CalDAV)

Stable import surface:

```python
from custom_components.asp_parking.util import now_ha_local
```

- Signature: `now_ha_local() -> datetime`
- Returns: tz-aware datetime in HA's configured local timezone (calls `dt_util.now()`).
- Safe to import from any module in `custom_components/asp_parking/` — no circular-import risk, no class state, no coordinator coupling.
- The module is NOT vendored (does not live under `gps2asp/`), so changes to `util.py` do NOT trigger the Phase 31 vendor-guard CI.

## Auth Gates

None.

## Self-Check: PASSED

**Files created:**
- `custom_components/asp_parking/util.py` — FOUND (22 lines, exports `now_ha_local`).

**Files modified:**
- `custom_components/asp_parking/sensor.py` — FOUND (modified: imports + `_format_move_time` + `native_value` docstring + `extra_state_attributes` defaults + urgency block).
- `README.md` — FOUND (modified: new `## Upgrade Notes` section).

**Commits:**
- `d5645a6` (feat(32-02): add util.py with now_ha_local() helper (D-05)) — FOUND in `git log`.
- `59c8dc2` (feat(32-02): rewrite _format_move_time and urgency block for date-aware tiers) — FOUND in `git log`.
- `7d69f41` (docs(32-02): add breaking-change note for v3.2 sensor display format) — FOUND in `git log`.

**Phase 32 plan-level success criteria (from 32-02-PLAN.md `<success_criteria>`):**
- `util.py` exists with `now_ha_local()` returning `dt_util.now()` ✓
- `_format_move_time` produces three-tier format via date equality + `now_ha_local()` ✓
- `extra_state_attributes` always includes `next_move_is_today` / `next_move_is_tomorrow` (default False, overwritten when `_move_dt is not None`) and urgency derived from `is_today` ✓
- Existing keys (`next_window_start`, `next_window_day`, `time_window_start`, `time_window_end`, `next_window_end`) preserved unchanged ✓
- `seconds_until` count in `sensor.py` = 0 ✓
- README breaking-change note added with migration path ✓
- Full non-integration suite green: 509 / 509 ✓
- Phase 31 vendor guard still passes — no `util.py` mirror under `gps2asp/` ✓
