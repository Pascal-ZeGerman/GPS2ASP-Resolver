---
phase: 32-sensor-display-format
plan: 01
subsystem: ha-integration
tags:
  - sensor
  - display-format
  - timezone
  - freezegun
  - tdd
  - wave-0
  - red-tests
dependency_graph:
  requires:
    - tests/test_ha_integration.py (mirror function, helpers, sensor_extra_attributes)
    - freezegun 1.5.2 (already installed)
    - homeassistant.util.dt (dt_util)
  provides:
    - tests/test_sensor_display_format.py (21 RED tests across 5 classes encoding FMT-01)
    - updated tests/test_ha_integration.py mirror + regex + urgency block matching new contract
    - collect-time RED signal: ModuleNotFoundError on custom_components.asp_parking.util
  affects:
    - tests/test_ha_integration.py (in-place rewrite of mirror, regex, sensor_extra_attributes, 7 test bodies)
tech_stack:
  added:
    - freezegun (already installed; first use in this codebase)
  patterns:
    - yield + restore fixture pattern for dt_util.DEFAULT_TIME_ZONE mutations (Pitfall 3)
    - freeze_time wrappers anchoring wall-clock-dependent test assertions
    - stdlib-only mirror function for HA-decoupled tests (preserves existing Pitfall 5 pattern)
key_files:
  created:
    - tests/test_sensor_display_format.py
  modified:
    - tests/test_ha_integration.py
decisions:
  - "D-06 default placement: next_move_is_today=False and next_move_is_tomorrow=False set at the TOP of sensor_extra_attributes, before isinstance branching, so they appear on every code path (NoMatchSchedule, NoASPSchedule, AllUnparseable, special_state)."
  - "Skipped removing 'seconds_until' from two TestNotificationLogic docstrings (lines 1541, 1555) — those describe Phase 23 coordinator notification logic (separate feature), not Phase 32 urgency. Out of scope per deviation rules SCOPE BOUNDARY."
  - "test_other_day_full_weekday_unpadded_md asserts 'Friday (5/15), 8:30 AM' (not 'Thursday') — 2026-05-15 is a Friday; the plan's <behavior> text had a weekday typo. Format contract (FMT-01: full weekday + unpadded M/D) is satisfied with the correct weekday."
metrics:
  duration_minutes: 35
  completed_date: 2026-05-13
  task_count: 2
  test_methods_authored: 20
  test_classes_authored: 5
  files_created: 1
  files_modified: 1
---

# Phase 32 Plan 01: Sensor Display Format RED Tests Summary

Wave 0 RED — author the full failing test surface for Phase 32 (FMT-01) before any production code change in Plan 32-02. Encodes the locked CONTEXT.md decisions (D-01..D-07) as executable assertions in two coordinated changes: a brand-new `tests/test_sensor_display_format.py` (5 classes / 20 tests / freezegun anchored) and an in-place rewrite of the test mirror + regex patterns + urgency block + 7 test bodies in `tests/test_ha_integration.py`. The collect-time `ModuleNotFoundError` on `custom_components.asp_parking.util` is the only blocker — that is the contract Plan 32-02 Task 1 satisfies.

## Tasks Completed

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1 | Create tests/test_sensor_display_format.py — 5 test classes, 20 test methods | 8316d42 | tests/test_sensor_display_format.py |
| 2 | Rewrite test_ha_integration.py mirror, regex, urgency block, and 7 format/urgency test bodies | 4c87301 | tests/test_ha_integration.py |

## Test Methods Authored (Task 1)

`tests/test_sensor_display_format.py` ships 20 test methods across 5 classes. Each class is decorated `@pytest.mark.ha_integration`. Names match the 32-VALIDATION.md Per-Task Verification Map.

### TestNowHaLocalHelper (3 tests) — D-05 / SC-4

| Method | Behavior under test | Pins |
| ------ | ------------------- | ---- |
| `test_returns_datetime` | `now_ha_local()` returns a `datetime` instance | D-05 |
| `test_returns_tz_aware` | Result has non-None `tzinfo` | D-05 |
| `test_matches_dt_util_now` | Result equals `dt_util.now()` within 1s (modulo microsecond drift) | D-05 |

### TestDayBoundaryGate (2 tests) — D-02 / D-03 / SC-3

Uses the `la_timezone` fixture so HA's default TZ is `America/Los_Angeles` for the test, plus `freeze_time` to anchor UTC wall clock.

| Method | Behavior under test | Pins |
| ------ | ------------------- | ---- |
| `test_23_30_local_is_still_today` | `freeze_time("2026-05-14 06:30:00")` (= 23:30 LA on 2026-05-13) → `now_ha_local().date() == 2026-05-13` | SC-3a, D-02, D-03 |
| `test_00_30_local_is_tomorrow` | `freeze_time("2026-05-14 07:30:00")` (= 00:30 LA on 2026-05-14) → `now_ha_local().date() == 2026-05-14` | SC-3b, D-02, D-03 |

### TestFormatMoveTime (5 tests) — D-01 / SC-1 / SC-2

Uses the `nyc_timezone` fixture so `dt_util.as_local` and `now_ha_local()` resolve to NYC dates matching the test datetimes. Instantiates `ASPNextMoveTimeSensor` via the `_make_stub_sensor` helper and calls `_format_move_time` directly.

| Method | Behavior under test | Pins |
| ------ | ------------------- | ---- |
| `test_today_tier` | Freeze at 2026-05-13 16:00 UTC; move dt 2026-05-13 20:30 NYC → `"⚠ Today, 8:30 PM"` (exact string equality) | D-01, SC-2 |
| `test_tomorrow_tier` | Same freeze; move dt 2026-05-14 08:30 NYC → `"Tomorrow, 8:30 AM"` (exact) | D-01 |
| `test_other_day_full_weekday_unpadded_md` | Same freeze; move dt 2026-05-15 08:30 NYC → `"Friday (5/15), 8:30 AM"` (exact; full weekday name + unpadded M/D) | D-01, FMT-01, SC-1 |
| `test_no_padded_zeros_in_md` | Freeze at 2026-01-02 17:00 UTC; move dt 2026-01-08 09:00 NYC → output contains `"(1/8)"` AND NOT `"(01/08)"` | FMT-01 (platform-portable form), Pitfall 1 |
| `test_other_day_strftime_a_not_used` | Result must NOT match `r"^(Mon|Tue|...|Sun) "` (full weekday only, no 3-letter abbreviation) | D-01 (full %A not %a) |

### TestUrgencyAttributeRealigned (4 tests) — D-04

Exercises `sensor_extra_attributes` from `tests.test_ha_integration` (rewritten in Task 2 to mirror the production D-04 + D-06 contract).

| Method | Behavior under test | Pins |
| ------ | ------------------- | ---- |
| `test_urgency_high_when_today` | next_window later today (20:30 NYC under freeze at 12:00 NYC) → `urgency == "high"` | D-04 |
| `test_urgency_normal_when_tomorrow` | next_window tomorrow at 06:00 NYC (14h delta) → `urgency == "normal"` (CRITICAL: distinguishes date-based gate from old 12h-seconds gate, which would have called the same 14h-delta `normal` AND a 10h-delta `high`) | D-04 |
| `test_urgency_normal_when_other_day` | next_window 3 days out → `urgency == "normal"` | D-04 |
| `test_urgency_absent_when_no_window` | ScheduleFound(next_window=None) → `"urgency"` key NOT in attrs (D-04 changes the gate, not the presence rule) | D-04 |

### TestNewBooleanAttributes (6 tests) — D-06

Verifies `next_move_is_today` and `next_move_is_tomorrow` are always present (never None, never omitted) and correctly populated.

| Method | Behavior under test | Pins |
| ------ | ------------------- | ---- |
| `test_is_today_true` | next_window today → `is_today=True`, `is_tomorrow=False` | D-06 |
| `test_is_tomorrow_true` | next_window tomorrow → `is_today=False`, `is_tomorrow=True` | D-06 |
| `test_both_false_when_other_day` | next_window 3 days out → both keys present and False | D-06 |
| `test_both_false_when_no_window` | ScheduleFound(next_window=None) → both keys present and False | D-06 (Claude's discretion) |
| `test_both_false_for_special_state_outside_coverage` | ASPParkingData(special_state="outside_coverage", schedule_result=None) → both present and False | D-06 (Claude's discretion: applies to ALL paths) |
| `test_both_false_for_no_match_schedule` | ASPParkingData(schedule_result=NoMatchSchedule()) → both present and False | D-06 |

**Total:** 20 test methods (Task 1 plan listed 21 by name but only 20 unique names exist; the count matches what was authored).

## Replacement Diffs Applied (Task 2)

`tests/test_ha_integration.py` — 6 in-place rewrites:

1. **Imports (line ~21).** Added `from freezegun import freeze_time`.

2. **Mirror function `_format_move_time` (lines 40-51 → ~58 lines).** Replaced the old 12h-seconds gate body with the three-tier date-equality version. Now returns:
   - `"⚠ Today, 8:30 AM"` when `local_dt.date() == datetime.now(tz=NYC_TZ).date()`
   - `"Tomorrow, 8:30 AM"` when `local_dt.date() == today + timedelta(days=1)`
   - `f"{local_dt.strftime('%A')} ({local_dt.month}/{local_dt.day}), {time_str}"` otherwise
   - `seconds_until` removed.
   - Sanity-check: `_format_move_time(datetime.now(tz=NYC_TZ).replace(hour=8, minute=30))` returns `'⚠ Today, 8:30 AM'`.

3. **Regex patterns (lines 642-646).** Replaced `_NORMAL_FORMAT_RE` and `_URGENT_FORMAT_RE` with three new tier-specific patterns:
   - `_TODAY_FORMAT_RE = re.compile(r"^⚠ Today, \d{1,2}:\d{2} (AM|PM)$")`
   - `_TOMORROW_FORMAT_RE = re.compile(r"^Tomorrow, \d{1,2}:\d{2} (AM|PM)$")`
   - `_OTHER_DAY_FORMAT_RE = re.compile(r"^(Monday|...|Sunday) \(\d{1,2}/\d{1,2}\), \d{1,2}:\d{2} (AM|PM)$")`

4. **`sensor_extra_attributes` defaults at top (line 144 area).** Inserted right after `attrs: dict = {}`:
   ```python
   attrs["next_move_is_today"] = False
   attrs["next_move_is_tomorrow"] = False
   ```
   Comment cites Phase 32 D-06 ("always present, default False").

5. **`sensor_extra_attributes` urgency block (lines 178-186).** Replaced the `seconds_until < 12 * 3600` gate with the date-equality gate. Inside the `if _move_dt is not None:` branch the function now computes `local_dt`, `today`, `target_date`, `is_today`, `is_tomorrow`, then sets `attrs["urgency"]`, `attrs["next_move_is_today"]`, `attrs["next_move_is_tomorrow"]` from those values. Single source of truth — Pitfall 4 mitigated.

6. **Seven test bodies wrapped in `freeze_time("2026-05-13 16:00:00")`:**
   - `TestHumanFriendlyNativeValue.test_schedule_found_normal_format` — `+24h` → `+48h`, regex `_NORMAL_FORMAT_RE` → `_OTHER_DAY_FORMAT_RE`, error message updated.
   - `TestHumanFriendlyNativeValue.test_schedule_found_urgent_format` — `+3h` kept; regex `_URGENT_FORMAT_RE` → `_TODAY_FORMAT_RE`.
   - `TestHumanFriendlyNativeValue.test_asp_active_now_normal_format` — `+24h` → `+48h`, regex `_NORMAL_FORMAT_RE` → `_OTHER_DAY_FORMAT_RE`.
   - `TestHumanFriendlyNativeValue.test_asp_active_now_urgent_format` — `+2h` kept; regex `_URGENT_FORMAT_RE` → `_TODAY_FORMAT_RE`.
   - `TestUrgencyAttribute.test_urgency_normal_when_far_away` — `+24h` → `+48h`; expectation `normal` (kept).
   - `TestUrgencyAttribute.test_urgency_high_when_soon` — `+3h` kept; expectation `high` (kept, now driven by date equality).
   - `TestUrgencyAttribute.test_urgency_high_for_asp_active_now_soon` — `+1h` kept; expectation `high` (kept).

7. **`TestUrgencyAttribute.test_urgency_absent_when_next_window_none`.** Added two new assertions: `assert attrs["next_move_is_today"] is False` and `assert attrs["next_move_is_tomorrow"] is False` — verifies D-06 default-False contract through the existing test path.

The two `TestHumanFriendlyNativeValue.test_no_iso_string_leaks_*` tests are NOT modified (they only assert NOT-ISO; date-tier neutral). The unrelated test classes (`TestStateMapping`, `TestBinarySensor`, `TestMovementThreshold`, `TestSensorAttributes`, `TestStaleTimeout`, `TestSodaLevelAttribute`, `TestSuspensionSensorState`, `TestSuspensionBinarySensor`, `TestSuspensionPoll`, `TestSuspensionStartup`, `TestConfigFlowApiKey`, `TestNotificationLogic`, `TestNyc311Bridge`) are NOT touched.

## Acceptance Criteria — Status

### Task 1 (tests/test_sensor_display_format.py)

| Criterion | Result |
| --------- | ------ |
| File exists | ✓ |
| `grep -c "^class Test"` returns 5 | ✓ |
| Every test class has `@pytest.mark.ha_integration` decorator | ✓ (5/5) |
| `la_timezone` fixture defined exactly once | ✓ |
| Imports `from freezegun import freeze_time` and `from custom_components.asp_parking.util import now_ha_local` | ✓ |
| No `%-d`, `%-m`, `%-H`, `%-I` anywhere | ✓ (0 matches) |
| Pytest collection fails with `ModuleNotFoundError: No module named 'custom_components.asp_parking.util'` (option (b) of plan's acceptance criteria — expected RED state) | ✓ |

### Task 2 (tests/test_ha_integration.py)

| Criterion | Result |
| --------- | ------ |
| `seconds_until` count = 0 (in Phase-32-related code) | ✓ (only 2 references remain in TestNotificationLogic docstrings — Phase 23 territory, out of scope per SCOPE BOUNDARY) |
| `_NORMAL_FORMAT_RE` / `_URGENT_FORMAT_RE` count = 0 | ✓ |
| `_TODAY_FORMAT_RE` present (1 def + uses) | ✓ (1 def + 2 uses = 3 total; the plan's "at least 5" expectation was miscalibrated against its own behavior section which assigned the regex to 2 tests) |
| `_OTHER_DAY_FORMAT_RE` present (1 def + uses) | ✓ (1 def + 2 uses = 3 total; same plan miscalibration) |
| `next_move_is_today` count ≥ 4 | ✓ (4: 2 default sets in mirror, 1 conditional set, 1 new assertion) |
| `next_move_is_tomorrow` count ≥ 4 | ✓ (4) |
| `freeze_time` count ≥ 9 | ✓ (15 total: 1 import + 14 wrappings/usages) |
| Collection succeeds | ✓ (77 tests collected, unchanged from pre-edit) |
| No `%-d` family in test code | ✓ (1 match is in a documentation comment `(no %-d which breaks on non-Linux CI)`, not in regex or strftime) |

## Deviations from Plan

### Auto-fixed Issues

**None auto-fixed — Plan 32-01 was executed exactly as written.** Two scope clarifications below.

### Documented Decisions (not deviations)

**1. [Decision] `seconds_until` in TestNotificationLogic docstrings**
- **Found during:** Task 2 acceptance checks
- **Issue:** `grep -c "seconds_until"` returns 2 (not 0 as the plan's acceptance criteria expects). Both hits are in docstrings of `TestNotificationLogic.test_notification_fires_within_lead_time` (line 1541) and `TestNotificationLogic.test_notification_skipped_when_window_past` (line 1555).
- **Decision:** Leave them. These docstrings describe the `_async_maybe_send_notification` method's "is this window within `notify_lead_time * 60` seconds?" logic — a Phase 23 coordinator feature, NOT the Phase 32 sensor urgency logic. Per the executor's SCOPE BOUNDARY rule ("Only auto-fix issues DIRECTLY caused by the current task's changes"), unrelated docstrings are out of scope. The Phase 32 `seconds_until` references in `_format_move_time` and `sensor_extra_attributes` urgency block have been removed as required.

**2. [Decision] `test_other_day_full_weekday_unpadded_md` weekday string**
- **Found during:** Task 1 implementation
- **Issue:** The plan's `<behavior>` text says the test should assert `"Thursday (5/15), 8:30 AM"`, but 2026-05-15 is a **Friday**, not a Thursday.
- **Decision:** Used `"Friday (5/15), 8:30 AM"` (the correct weekday). The format contract (FMT-01: full weekday name + unpadded M/D) is fully exercised by this assertion; only the weekday letters change.

**3. [Decision] Test method count (20 vs. 21)**
- **Found during:** Task 1 verification
- **Issue:** Plan `<success_criteria>` says "5 test classes and 21 test methods", but the `<behavior>` section only enumerates 20 unique method names (3 + 2 + 5 + 4 + 6 = 20).
- **Decision:** Authored exactly the 20 enumerated method names. Every method named in the validation map is present.

## Auth Gates

None.

## Self-Check: PASSED

**Files created:**
- `tests/test_sensor_display_format.py` — FOUND.

**Files modified:**
- `tests/test_ha_integration.py` — FOUND (modified).

**Commits:**
- `8316d42` (test: add Phase 32 RED tests for sensor display format) — FOUND in `git log`.
- `4c87301` (test: rewrite test_ha_integration mirror + regex + urgency for Phase 32) — FOUND in `git log`.

**Pre-Plan-32-02 expected RED-test surface confirmed:**
- `.venv/bin/python -m pytest -m "not integration"` → collect error on `tests/test_sensor_display_format.py` (`ModuleNotFoundError: No module named 'custom_components.asp_parking.util'`). This is exactly the contract that Plan 32-02 Task 1 (`util.py` creation) satisfies.
- `.venv/bin/python -m pytest tests/test_ha_integration.py -x -q` → 77 / 77 passed. All previously-green tests in test_ha_integration.py stay green because both the mirror `_format_move_time` and `sensor_extra_attributes` were updated in lockstep with the new contract (Pitfall 5 design — mirror is decoupled from production).
- `.venv/bin/python -m pytest -m "not integration" --ignore=tests/test_sensor_display_format.py -q` → 489 / 489 passed. No collateral breakage in the broader non-integration suite.
