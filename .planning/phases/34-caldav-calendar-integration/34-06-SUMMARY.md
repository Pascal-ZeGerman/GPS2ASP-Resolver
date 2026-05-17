---
phase: 34-caldav-calendar-integration
plan: 06
subsystem: security
tags: [caldav, ha-integration, diagnostics, redaction, security, t-34-05]

# Dependency graph
requires:
  - phase: 27-diagnostics
    provides: TO_REDACT set + async_get_config_entry_diagnostics structure
  - phase: 34-caldav-calendar-integration (plan 03)
    provides: CONF_CALDAV_USERNAME + CONF_CALDAV_PASSWORD constants in const.py
provides:
  - "TO_REDACT set extended with CalDAV credential fields"
  - "Regression test asserting CONF_CALDAV_PASSWORD never appears in diagnostics JSON output"
  - "Mitigation for T-34-05 (Information Disclosure via diagnostics export)"
affects: [diagnostics, future-caldav-options, support-bundles]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Anti-leak regression test via json.dumps(result) substring assertion"

key-files:
  created: []
  modified:
    - custom_components/asp_parking/diagnostics.py
    - tests/test_diagnostics.py

key-decisions:
  - "Anti-leak assertion uses json.dumps + substring scan rather than per-key inspection — catches accidental leakage anywhere in the nested structure (state, last_resolve, last_error sections), not just the config section"
  - "URL + calendar URL are explicitly NOT redacted — they identify the server/calendar (often shared as documentation) and a passthrough sanity assertion guards against false-positive redaction tests"

patterns-established:
  - "Anti-leak substring assertion: serialise full result with json.dumps and assert literal secret string `not in serialised` — robust against future structural changes to the diagnostics shape"
  - "Phase 34 additions in TO_REDACT marked with `# Phase 34: CalDAV credentials (T-34-05 mitigation)` comment so future maintainers can trace each redaction back to its threat ID"

requirements-completed: [CALDAV-01]

# Metrics
duration: 4 min
completed: 2026-05-15
---

# Phase 34 Plan 06: Diagnostics Redaction for CalDAV Credentials Summary

**Extended Phase 27's TO_REDACT set with CONF_CALDAV_USERNAME + CONF_CALDAV_PASSWORD and added a regression test that asserts the literal password string never appears in the JSON-serialised diagnostics output.**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-05-15T13:57:44Z
- **Completed:** 2026-05-15T14:01:30Z
- **Tasks:** 1 (TDD: RED + GREEN; no REFACTOR needed for a 2-line set extension)
- **Files modified:** 2

## Accomplishments

- T-34-05 (Information Disclosure via diagnostics export) is mitigated: HA's `async_redact_data` now replaces both `CONF_CALDAV_USERNAME` and `CONF_CALDAV_PASSWORD` values with the standard `"**REDACTED**"` sentinel before the JSON serialises.
- Regression test `test_diagnostics_redacts_caldav_credentials` locks the mitigation against future accidental removal — the test fails immediately if any future code change drops either key from `TO_REDACT`.
- Zero regression on the pre-existing 6 redaction entries (`CONF_PARKING_LAT`, `CONF_PARKING_LON`, `CONF_DEBUG_LAT`, `CONF_DEBUG_LON`, `CONF_NYC311_API_KEY`, `CONF_NOTIFY_SERVICE`).
- All 5 tests in `tests/test_diagnostics.py` pass (4 pre-existing + 1 new).

## Task Commits

Each task was committed atomically following the TDD cycle:

1. **Task 1 (RED): Failing regression test** — `53fe426` (test)
2. **Task 1 (GREEN): Extend TO_REDACT with CalDAV credentials** — `4b0f24a` (feat)

_REFACTOR not needed — the implementation is a 2-line set extension._

## Files Created/Modified

- `custom_components/asp_parking/diagnostics.py` — Added `CONF_CALDAV_PASSWORD` + `CONF_CALDAV_USERNAME` to the `.const` import block and to the `TO_REDACT` set under a `# Phase 34: CalDAV credentials (T-34-05 mitigation)` comment. Pre-existing entries unchanged.
- `tests/test_diagnostics.py` — Added `json` stdlib import + `CONF_CALDAV_URL`, `CONF_CALDAV_USERNAME`, `CONF_CALDAV_PASSWORD`, `CONF_CALDAV_CALENDAR` to the const import block; appended a new `test_diagnostics_redacts_caldav_credentials` async test using the existing `_make_entry` helper and the same `_FakeData` stub pattern as the four pre-existing Phase 27 tests.

## Final TO_REDACT Set Membership

After this plan, `TO_REDACT` contains exactly 8 entries (verified via runtime assertion):

```
{
    'caldav_password',     # ← Phase 34 addition (this plan)
    'caldav_username',     # ← Phase 34 addition (this plan)
    'debug_lat',           # ← Phase 27 (preserved)
    'debug_lon',           # ← Phase 27 (preserved)
    'notify_service',      # ← Phase 27 (preserved)
    'nyc311_api_key',      # ← Phase 27 (preserved)
    'parking_lat',         # ← Phase 27 (preserved)
    'parking_lon',         # ← Phase 27 (preserved)
}
```

## Anti-Leak Assertion (canonical regression guard)

The new test's anti-leak assertion is the exact text:

```python
assert "supersecret123" not in serialised, "Password leaked into diagnostics"
assert "alice@example.com" not in serialised, "Username leaked into diagnostics"
```

These assertions catch leakage anywhere in the nested diagnostics structure (config / state / last_resolve / last_error) because `serialised = json.dumps(result)` flattens the entire export into a single searchable string. Per-key inspection on `result["config"][CONF_CALDAV_PASSWORD] == "**REDACTED**"` is also asserted as a positive sentinel check.

## Decisions Made

- **Substring anti-leak assertion over per-key inspection:** `json.dumps + "secret" not in serialised` catches leakage in any nested section, not just `config`. Per-key `==` checks for the redaction sentinel are added separately as positive guards. Combined the two patterns get the best of both worlds.
- **URL + calendar URL are NOT credentials:** Both are identifiers (server endpoint, calendar collection URL) that users commonly share as documentation when asking for help. Redacting them would harm support workflows without improving security. The new test explicitly asserts they pass through unredacted, defending against an over-eager future maintainer adding them to TO_REDACT.

## Deviations from Plan

None — plan executed exactly as written.

The plan called for ONE new test, TWO new TO_REDACT entries, ONE comment in `diagnostics.py`, and ONE non-empty `_FakeData` runtime_data stub pattern. All four happened verbatim.

## Issues Encountered

- The `.venv/bin/pytest` shebang line points at `GSP2ASP-Resolver` (typo: `GSP` vs `GPS`) so direct invocation fails with `cannot execute: required file not found`. Worked around by invoking via `/home/pascal/Vibe-Coding/VW-CarNet/GPS2ASP-Resolver/.venv/bin/python -m pytest`. Not introduced by this plan; pre-existing environment issue logged here for visibility.

## Pre-existing test failures outside scope (logged to deferred-items.md)

The full non-network suite (`pytest -m "not integration"`) reports 16 failing tests in `tests/test_coordinator_caldav.py` (12) and `tests/test_init_caldav_remove.py` (4). All raise `AttributeError: type object 'ASPParkingCoordinator' has no attribute '_async_caldav_hook_after_resolve'` — these are RED tests waiting for Plans 34-04 (coordinator hook) and 34-05 (entry removal cleanup). They are NOT touched by this plan and pre-date 34-06 changes. Recorded in `.planning/phases/34-caldav-calendar-integration/deferred-items.md` for tracking. The 34-06 scope itself is fully green: `pytest tests/test_diagnostics.py` reports 5 passed, 0 failed.

## Verification Output

```
$ .venv/bin/python -m pytest tests/test_diagnostics.py -x
============================== 5 passed in 0.44s ===============================

$ python -c "from custom_components.asp_parking.diagnostics import TO_REDACT; ..."
OK — TO_REDACT preserved + extended with Phase 34 creds
TO_REDACT size: 8
```

## Next Phase Readiness

- T-34-05 mitigation in place — diagnostics exports are safe to share with support helpers and on GitHub issues.
- Plan 34-06 was the final Wave 2 plan in Phase 34. With this plan complete, Phase 34's threat model has been fully addressed at the diagnostics surface.
- Future CalDAV options (e.g., `verify_ssl` cert path, `VALARM` minutes from Open Questions 2 and 4 in 34-RESEARCH.md) should be re-evaluated against `TO_REDACT` if/when added — the regression test only guards against removal of CURRENT entries, not absence of FUTURE entries (T-34-14 accepted residual risk).

## Self-Check: PASSED

Verified:
- `custom_components/asp_parking/diagnostics.py` modified — `CONF_CALDAV_USERNAME` + `CONF_CALDAV_PASSWORD` present in `TO_REDACT` (runtime assert passed).
- `tests/test_diagnostics.py` modified — `test_diagnostics_redacts_caldav_credentials` runs and passes (1 new test).
- Commit `53fe426` (RED): `test(34-06): add failing regression test for CalDAV credential redaction` — present in `git log`.
- Commit `4b0f24a` (GREEN): `feat(34-06): redact CONF_CALDAV_USERNAME + CONF_CALDAV_PASSWORD in diagnostics` — present in `git log`.

---
*Phase: 34-caldav-calendar-integration*
*Completed: 2026-05-15*
