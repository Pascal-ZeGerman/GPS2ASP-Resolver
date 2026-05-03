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
