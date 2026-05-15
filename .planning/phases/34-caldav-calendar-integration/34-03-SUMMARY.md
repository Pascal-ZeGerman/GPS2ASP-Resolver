---
phase: 34-caldav-calendar-integration
plan: 03
subsystem: ha-integration
tags: [caldav, options-flow, i18n, config, ha-config-flow, voluptuous, selector, async]

# Dependency graph
requires:
  - phase: 34-01
    provides: "RED tests in tests/test_options_flow_caldav.py (8 tests locking the contract for async_step_caldav + async_step_caldav_calendar)"
  - phase: 34-02
    provides: "caldav_sync module (validate_connection, list_calendars, CalDAVAuthError) — imported at module level by config_flow.py"
provides:
  - "6 CONF_CALDAV_* constants in const.py (url, username, password, calendar, safety_window, event_title_template)"
  - "2 DEFAULT_CALDAV_* defaults (safety_window=15 min, event_title_template='ASP: {street}')"
  - "ASPParkingOptionsFlow.async_step_caldav: credential probe + D-02 empty-URL no-op + D-03 unified caldav_auth_failed error"
  - "ASPParkingOptionsFlow.async_step_caldav_calendar: dropdown populated from caldav_sync.list_calendars"
  - "Updated chain: init → parking_area → caldav → caldav_calendar → CREATE_ENTRY"
  - "i18n: options.step.caldav + options.step.caldav_calendar + options.error.caldav_auth_failed (mirrored in strings.json AND translations/en.json)"
affects: [34-04, 34-05, 34-06, future-phases-touching-options-flow]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Parallel-wave module-level import with try/except fallback stub (caldav_sync) — registered in sys.modules so unittest.mock.patch resolves the dotted path even before the sibling worktree merges"
    - "Empty-URL-is-no-op pattern (D-02): inserts a step into the chain that can be fully bypassed by a single field, preserving the unconditional CREATE_ENTRY guarantee for users who don't want the optional feature"
    - "Translated unified error key for credential probes (D-03): all probe failures — auth, network, DNS, TLS — surface as the SAME caldav_auth_failed key to avoid leaking server-internal details to the UI"
    - "Form-render password hardcoding (T-34-01): when re-rendering after a validation error, the password field's default is HARDCODED to '' rather than echoing user-submitted or stored value"

key-files:
  created: []
  modified:
    - "custom_components/asp_parking/const.py (6 CONF_CALDAV_* + 6 DEFAULT_CALDAV_*)"
    - "custom_components/asp_parking/config_flow.py (try/except caldav_sync import, async_step_caldav, async_step_caldav_calendar, parking_area→caldav routing)"
    - "custom_components/asp_parking/strings.json (caldav + caldav_calendar blocks + caldav_auth_failed error)"
    - "custom_components/asp_parking/translations/en.json (byte-equivalent mirror per Phase 31 CI guard)"
    - "tests/test_options_flow.py (3 pre-existing tests updated to advance through new caldav step)"

key-decisions:
  - "Module-level caldav_sync import with try/except fallback stub registered in sys.modules — enables both production correctness (real module imported when present) AND parallel-wave isolation (this worktree's tests pass before Plan 02 merges)"
  - "Updated 3 pre-existing options_flow tests (Rule 3 deviation): the new caldav step sits between parking_area and CREATE_ENTRY, so the legacy tests' final assertion needed an empty-URL caldav submission to reach CREATE_ENTRY"
  - "Password form default hardcoded to '' (T-34-01) — never echo submitted/stored value back to the visible form even after validation error"

patterns-established:
  - "Pattern: parallel-wave fallback import (try/except + sys.modules registration). Code remains importable when sibling plan has not yet merged; mock.patch dotted-path resolution still works"
  - "Pattern: D-02 empty-trigger no-op step. A single field acts as the on/off switch for an entire optional configuration block; empty value strips ALL related keys from options"

requirements-completed: [CALDAV-01, CALDAV-02, CALDAV-03]

# Metrics
duration: 14 min
completed: 2026-05-15
---

# Phase 34 Plan 03: CalDAV Options-Flow Surface Summary

**Two new chained options-flow steps (async_step_caldav + async_step_caldav_calendar) with credential validation, calendar-selection dropdown, mirrored i18n entries, and security-first form rendering (T-34-01/02 mitigations).**

## Performance

- **Duration:** 14 min (819 seconds)
- **Started:** 2026-05-15T13:36:01Z
- **Completed:** 2026-05-15T13:49:40Z
- **Tasks:** 3
- **Files modified:** 5 (const.py, config_flow.py, strings.json, translations/en.json, tests/test_options_flow.py)

## Accomplishments

- Added six CONF_CALDAV_* string keys + two DEFAULT_CALDAV_* defaults to const.py (CALDAV-01..08 surface)
- Implemented async_step_caldav with credential probe, D-02 empty-URL no-op, D-03 unified error mapping, T-34-01 password-default hardcoding, and T-34-02 fail-closed write gating
- Implemented async_step_caldav_calendar with dropdown populated by `caldav_sync.list_calendars` and Pitfall 6 defensive fallback to the credentials form on listing failure
- Rewired parking_area → caldav (previously parking_area was the terminal CREATE_ENTRY step)
- Mirrored full caldav + caldav_calendar i18n blocks across strings.json AND translations/en.json (Phase 31 vendor-guard CI requirement / T-34-10 mitigation)
- All 8 RED tests in tests/test_options_flow_caldav.py turn GREEN; all 4 pre-existing tests in tests/test_options_flow.py also GREEN after a minor chain-update fix

## Task Commits

Each task was committed atomically:

1. **Task 1: Add CONF_CALDAV_* constants + defaults to const.py** — `ad5241f` (feat)
2. **Task 2: Implement async_step_caldav + async_step_caldav_calendar + route parking_area→caldav** — `b1b6266` (feat)
3. **Task 3: Add caldav + caldav_calendar i18n blocks to strings.json AND translations/en.json** — `ed8b373` (feat)

## Files Created/Modified

- `custom_components/asp_parking/const.py` — Added 6 CONF_CALDAV_* keys (caldav_url, caldav_username, caldav_password, caldav_calendar, caldav_safety_window, caldav_event_title_template) and 6 DEFAULT_CALDAV_* defaults under a new "# CalDAV calendar sync (Phase 34) — CALDAV-01..08" section. DEFAULT_CALDAV_SAFETY_WINDOW=15, DEFAULT_CALDAV_EVENT_TITLE_TEMPLATE="ASP: {street}".
- `custom_components/asp_parking/config_flow.py` — Added try/except `from . import caldav_sync` with sys.modules-registered fallback stub; imported 6 CONF_CALDAV_* + 2 DEFAULT_CALDAV_* from const; rewired `async_step_parking_area` to call `await self.async_step_caldav()` instead of `async_create_entry`; added 200+ lines for `async_step_caldav` (credentials form, D-02 no-op, D-03 error mapping, T-34-01 password default, T-34-02 fail-closed gating) and `async_step_caldav_calendar` (dropdown form, Pitfall 6 fallback).
- `custom_components/asp_parking/strings.json` — Added options.step.caldav (title + description + 5 data labels + 5 data_description tooltips), options.step.caldav_calendar (title + description + 1 data label), and options.error.caldav_auth_failed.
- `custom_components/asp_parking/translations/en.json` — Identical mirror per Phase 31 byte-equivalence CI guard.
- `tests/test_options_flow.py` — Updated three pre-existing parking_area tests to advance through the new caldav step with an empty URL (D-02 no-op) to reach CREATE_ENTRY. The chain change in Plan 03 (parking_area no longer terminal) made the original assertions incompatible without this fix.

## Updated Chained-Step Order

```
init  →  parking_area  →  caldav  →  caldav_calendar  →  CREATE_ENTRY
                              │
                              └─ (empty URL) ──────────►  CREATE_ENTRY  (D-02 no-op)
```

## CONF_CALDAV_* Constants

| Constant                              | String value                    | Default                                       |
| ------------------------------------- | ------------------------------- | --------------------------------------------- |
| `CONF_CALDAV_URL`                     | `"caldav_url"`                  | `None`                                        |
| `CONF_CALDAV_USERNAME`                | `"caldav_username"`             | `""`                                          |
| `CONF_CALDAV_PASSWORD`                | `"caldav_password"`             | `""`                                          |
| `CONF_CALDAV_CALENDAR`                | `"caldav_calendar"`             | `""`                                          |
| `CONF_CALDAV_SAFETY_WINDOW`           | `"caldav_safety_window"`        | `15` (minutes — D-04/CALDAV-03)               |
| `CONF_CALDAV_EVENT_TITLE_TEMPLATE`    | `"caldav_event_title_template"` | `"ASP: {street}"` (D-04)                      |

## Translation Key Namespace

- `options.step.caldav.{title, description, data.*, data_description.*}` — credentials form i18n
- `options.step.caldav_calendar.{title, description, data.caldav_calendar}` — dropdown form i18n
- `options.error.caldav_auth_failed` — single unified probe-failure error (D-03)

All five data keys are present and match the CONF_CALDAV_* names: `caldav_url`, `caldav_username`, `caldav_password`, `caldav_safety_window`, `caldav_event_title_template`.

## Test Pass Count

- **tests/test_options_flow_caldav.py**: 8/8 passing (all RED tests from Plan 01 turn GREEN)
- **tests/test_options_flow.py**: 4/4 passing (3 updated for the new chain, 1 unchanged)
- **Combined**: 12/12 passing
- **Full non-network suite (worktree-local)**: 567 passing, 33 failing — every failure is in tests for `caldav_sync` (Plan 02), coordinator caldav hooks (Plan 04), or async_remove_entry (Plan 05); none touched files under Plan 03 ownership. Zero non-caldav regressions.

## Decisions Made

- **Module-level caldav_sync import with try/except + sys.modules fallback**: the test contract uses `unittest.mock.patch("custom_components.asp_parking.config_flow.caldav_sync.validate_connection")`, which requires `caldav_sync` to be an attribute on the `config_flow` module. With Plan 02 producing the real `caldav_sync.py` in a sibling worktree (parallel wave), this worktree fell back to a sentinel `types.ModuleType` registered in `sys.modules` under the canonical dotted path. The fallback is `pragma: no cover` and disappears the moment Plan 02 merges, because the `try: from . import caldav_sync` succeeds first.
- **Password form default hardcoded to `""` (T-34-01)**: re-rendering after a validation error must NOT echo back submitted/stored credentials. The four other form fields default to their stored values; only password is special-cased.
- **Single unified `caldav_auth_failed` error key (D-03)**: probes catch `CalDAVAuthError` AND generic `Exception` and map both to the same translated string — no leaking of DNS/TLS/timeout details to the UI surface.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated three pre-existing options_flow tests for the new chain order**

- **Found during:** Task 2 (running `tests/test_options_flow.py` after wiring parking_area → caldav)
- **Issue:** The three pre-existing tests (`test_parking_area_empty_submission_saves_without_parking_keys`, `test_parking_area_round_trip_persists_values`, `test_init_step_preserves_parking_keys_when_unchanged`) all asserted that submitting the parking_area form returns `FlowResultType.CREATE_ENTRY`. After Plan 03 routed parking_area into the new caldav step, that assertion would always see `FlowResultType.FORM` (step=caldav) instead. Plan 03's explicit acceptance criterion is "All pre-existing options-flow tests still pass: `.venv/bin/pytest tests/test_options_flow.py -x` exits 0", so updating those tests was required for the plan to converge.
- **Fix:** Added an extra `async_configure(result["flow_id"], {"caldav_url": ""})` step to each of the three tests so they advance through the new caldav step's D-02 empty-URL no-op path and reach CREATE_ENTRY. Added a docstring note in each test explaining the Phase 34 chain insertion.
- **Files modified:** `tests/test_options_flow.py`
- **Verification:** All 4 tests in tests/test_options_flow.py pass; the parking-area contract (no parking keys persisted on empty submission, correct round-trip of lat/lon/radius, preservation of pre-existing parking keys) is unchanged.
- **Committed in:** `b1b6266` (Task 2 commit — bundled with the config_flow changes that made this fix necessary, since the test update is meaningless without the corresponding chain change)

**2. [Rule 2 - Missing Critical] Module-level caldav_sync import with try/except fallback + sys.modules registration**

- **Found during:** Task 2 (after wiring module-level `from . import caldav_sync`, the entire integration failed to load because the file doesn't exist in this worktree until Plan 02 merges)
- **Issue:** The plan's `<interfaces>` block declares Plan 02 provides `caldav_sync`, but Plan 02 runs in parallel and its file is not yet in this worktree. A naked `from . import caldav_sync` at module level made config_flow.py un-importable, which broke ALL options-flow tests (including the pre-existing four). At the same time, the test contract relies on `mock.patch("...config_flow.caldav_sync.validate_connection")` resolving, which requires `caldav_sync` to be a module-level attribute — a lazy import inside the methods would not satisfy this.
- **Fix:** Wrapped the import in `try: from . import caldav_sync; except ImportError:` and, in the fallback branch, built a `types.ModuleType` stub with `validate_connection`, `list_calendars`, and `CalDAVAuthError` symbols, registered it under `sys.modules["custom_components.asp_parking.caldav_sync"]` so subsequent `from custom_components.asp_parking.caldav_sync import CalDAVAuthError` calls (used by the test file at line 141) resolve to the stub. The fallback branch is `pragma: no cover` because it disappears the moment Plan 02 merges and the real module is found by the `try` branch.
- **Files modified:** `custom_components/asp_parking/config_flow.py`
- **Verification:** `from custom_components.asp_parking import config_flow` succeeds in this worktree without Plan 02; `config_flow.caldav_sync` is a real module-attribute; `unittest.mock.patch("...config_flow.caldav_sync.validate_connection")` resolves and all 8 CalDAV options-flow tests pass.
- **Committed in:** `b1b6266` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 Rule 3 — blocking chain change; 1 Rule 2 — parallel-wave import safety)
**Impact on plan:** Both auto-fixes were required for the plan's own verify and acceptance criteria. No scope creep — both are tightly scoped to satisfying the plan's stated invariants.

## Issues Encountered

- None requiring user intervention. The two deviations above were anticipated parallel-wave artifacts and resolved automatically.

## Threat Model Compliance

Per the plan's `<threat_model>`:

- **T-34-01 (Information Disclosure — password form default)**: ✅ Mitigated. Password schema entry hardcodes `default=""`, never `opts.get(CONF_CALDAV_PASSWORD)`. Verifiable by grep: `default=""` appears immediately above `selector.TextSelectorType.PASSWORD` in the caldav step.
- **T-34-02 (Information Disclosure — bad creds persisting)**: ✅ Mitigated. The `if not errors:` gate is the only code path that writes `self._options[CONF_CALDAV_*]`. Test `test_caldav_step_invalid_credentials_shows_error` (Plan 01) asserts `entry.options` is unchanged after a CalDAVAuthError, and `test_caldav_step_network_error_shows_same_error` asserts the same for a generic OSError.
- **T-34-09 (Tampering — title template injection)**: Out of scope for Plan 03. Mitigation is in Plan 02's `render_title` (`format_map(_SafeDict)`) per the threat register row's disposition.
- **T-34-10 (Spoofing — strings/translations mismatch)**: ✅ Mitigated. Task 3's automated verify asserts byte-equivalence of all three new blocks across strings.json and translations/en.json.
- **T-34-05 (Information Disclosure — diagnostics)**: Transferred to Plan 06.

## User Setup Required

None - no external service configuration required for this plan. End-user configuration (entering CalDAV URL/username/password via Settings → Integrations → ASP Parking → Configure) is documented in `34-CONTEXT.md` `user_setup` and is performed at runtime, not at code-time.

## Next Phase Readiness

- **Plans 04, 05, 06 (this phase, downstream waves)**: All six CONF_CALDAV_* constants are available for import. The options-flow surface is complete, so the coordinator (Plan 04) and async_remove_entry (Plan 05) can read `entry.options[CONF_CALDAV_URL]` to gate their behavior.
- **Plan 02 (this phase, parallel wave)**: The module-level `caldav_sync` import will silently switch from the fallback stub to the real Plan 02 module on merge. No code changes needed in config_flow.py.
- **Plan 06 (diagnostics redaction — this phase, downstream)**: Will need to extend Phase 27's TO_REDACT set with `CONF_CALDAV_PASSWORD` and `CONF_CALDAV_USERNAME` (T-34-05 mitigation).

## Self-Check: PASSED

- ✅ `custom_components/asp_parking/const.py` exists with all 6 CONF_CALDAV_* + 2 DEFAULT_CALDAV_* constants
- ✅ `custom_components/asp_parking/config_flow.py` contains `async def async_step_caldav` (×2 — caldav + caldav_calendar)
- ✅ `custom_components/asp_parking/strings.json` contains `caldav`, `caldav_calendar`, and `caldav_auth_failed` keys
- ✅ `custom_components/asp_parking/translations/en.json` byte-equivalent for the new blocks
- ✅ Commit `ad5241f` (Task 1) found in `git log`
- ✅ Commit `b1b6266` (Task 2) found in `git log`
- ✅ Commit `ed8b373` (Task 3) found in `git log`
- ✅ 12/12 plan tests pass (4 pre-existing options_flow + 8 new caldav)

---
*Phase: 34-caldav-calendar-integration*
*Plan: 03*
*Completed: 2026-05-15*
