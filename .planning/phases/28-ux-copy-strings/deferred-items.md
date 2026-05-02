# Phase 28 Deferred Items

Out-of-scope discoveries observed during execution of plan `28-01`. Logged but
NOT fixed — they are unrelated to the strings/translations work this phase is
scoped to.

## Pre-existing test failure: `tests/test_suspension.py::test_is_suspended_holiday`

- **First observed:** plan 28-01 verification, 2026-05-02
- **Reproduces on plan base** (`fa6a151`, before any strings.json/translations changes): yes — verified via `git stash` + run.
- **Failure summary:**
  - `SuspensionInfo.source` is `'none'` when test expects `'holiday'`.
  - Captured warning: `HolidayCalendar.is_suspended() called before load() -- returning not suspended`.
  - Located in `gps2asp.suspension` (or `src/gps2asp/__init__.py:223`).
- **Why deferred:** Phase 28 only edits HA strings/translations JSON. The failure
  is in a completely unrelated module (suspension/holiday calendar). Per
  executor scope-boundary rule, "only auto-fix issues directly caused by the
  current task's changes."
- **Suggested follow-up:** open a small bug-fix plan (or repair issue) targeting
  the holiday-calendar test fixture or `HolidayCalendar.is_suspended` short-circuit.

All other 301 tests pass (`pytest -m "not integration and not ha_integration"`).
