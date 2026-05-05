# Phase 30 — Deferred Items

Out-of-scope discoveries surfaced during execution; not fixed in this phase.

## Pre-existing test failures

### `tests/test_suspension.py::test_is_suspended_holiday`

- **Surfaced by:** Plan 30-01 (regression run)
- **Reproducible without 30-01 changes:** Yes — verified by stashing 30-01 edits and re-running the same test (still fails with the same `AssertionError: source: 'holiday' != 'none'`)
- **Symptom:** `HolidayCalendar.is_suspended()` returns `SuspensionInfo(source='none')` while the test expects `source='holiday'`. Also emits `WARNING ... HolidayCalendar.is_suspended() called before load() -- returning not suspended`.
- **Root cause (suspected):** Test fixture either does not call `load()` or relies on a state file that was not seeded. Phase 19/20 territory.
- **Out-of-scope rationale:** The `HolidayCalendar` lives in `src/gps2asp/suspension/` — Plan 30-01 only modified `resolver/models.py` and `resolver/__init__.py` plus their vendored mirrors. There is no plausible coupling.
- **Action:** Tracked here for a future phase; not within Plan 30-01 scope.

### `tests/test_ha_integration.py::TestSuspensionPoll::test_suspension_poll_does_not_require_gps_coordinates`

- **Surfaced by:** Plan 30-04 (full HA integration suite run)
- **Reproducible without 30-04 changes:** Yes — verified by `git stash -u` of 30-04 edits and re-running the same test (still fails with same `AssertionError: 'datetime.now(NYC_TZ).date()' in src` substring missing)
- **Symptom:** Test asserts the literal substring `datetime.now(NYC_TZ).date()` exists in `coordinator.py`, but Phase 24 introduced `_get_now()` indirection so the coordinator now uses `self._get_now().date()` instead.
- **Root cause:** Phase 22 string-based test was never updated when Phase 24 added the `_get_now()` time abstraction. The behavioural intent (suspension poll uses today's date, not GPS) is still satisfied via `_get_now()`.
- **Out-of-scope rationale:** Plan 30-04 only touches `sensor.py` and the test helper / 2 new tests in `test_ha_integration.py`. No `coordinator.py` change in this plan would affect this string check.
- **Action:** Tracked here for a future phase to refresh the assertion to `self._get_now().date()`; not within Plan 30-04 scope.
