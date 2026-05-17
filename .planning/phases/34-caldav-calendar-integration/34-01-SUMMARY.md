---
phase: 34
plan: 01
subsystem: caldav-calendar-integration
tags: [caldav, ha-integration, test-scaffolding, options-flow, storage, wave-0]
requires: []
provides:
  - "manifest.json: caldav[async]==3.2.0 + icalendar>=6.3.1 declared"
  - "tests/test_caldav_sync.py: 17 RED tests locking caldav_sync public API (Plan 02 target)"
  - "tests/test_coordinator_caldav.py: 12 RED tests locking ASPParkingCoordinator hooks (Plan 04 target)"
  - "tests/test_options_flow_caldav.py: 8 RED tests locking options-flow steps (Plan 03 target)"
  - "tests/test_init_caldav_remove.py: 4 RED tests locking async_remove_entry (Plan 05 target)"
affects:
  - "custom_components/asp_parking/manifest.json"
  - "tests/"
tech_stack_added:
  - "caldav[async]==3.2.0 (no [async] extra exists in caldav 3.2.0; bare pin pulled in regardless)"
  - "icalendar>=6.3.1 (bumped from >=6.1.0)"
tech_stack_patterns:
  - "Deferred caldav_sync import via try/except at module top + pytest.fail() in test bodies — RED-state scaffolding that lets pytest collection succeed before Plan 02 lands"
  - "SimpleNamespace + AsyncMock stub coordinator (pattern matches tests/test_coordinator_rebuild.py)"
  - "freezegun.freeze_time decorators anchoring the safety-window safety-band tests"
  - "PHACC hass_storage fixture for in-memory Store inspection in async_remove_entry tests"
  - "Patch target convention: 'custom_components.asp_parking.config_flow.caldav_sync.*' (Plan 03 will import caldav_sync into config_flow.py)"
key_files_created:
  - "tests/test_caldav_sync.py"
  - "tests/test_coordinator_caldav.py"
  - "tests/test_options_flow_caldav.py"
  - "tests/test_init_caldav_remove.py"
key_files_modified:
  - "custom_components/asp_parking/manifest.json"
decisions:
  - "caldav[async]==3.2.0 pin emits a benign 'extra not provided' pip warning (no [async] extra exists in caldav 3.2.0). Bare module + caldav.aio.AsyncDAVClient + caldav.lib.error pull in regardless. RESEARCH §Standard Stack note 1 + actual install validate."
  - "Phase 34 CONF_CALDAV_* names inlined as literal strings in the new test files instead of importing from const.py (Plan 03 will land the constants). This lets the test files collect cleanly before Plan 03 ships."
  - "Test bodies defer the caldav_sync / async_remove_entry import to inside _require_*() helpers using try/except at module top — pytest collection succeeds even though the symbols don't exist yet. Each test body that touches the missing symbol fails with a precise 'Plan N has not yet implemented X' message via pytest.fail()."
  - "Test for write_or_update_event ordering uses a call-order recorder (list[str]) to assert event_by_uid (delete path) precedes add_event — the only AsyncMock-friendly way to test ordering for two methods on the same mock."
metrics:
  duration_min: 13
  completed: 2026-05-15
  tasks_total: 5
  tasks_done: 5
  files_modified: 1
  files_created: 4
  red_tests_collected: 41
  red_tests_passing: 0
  pre_existing_tests_status: "559 passed, 0 regressions"
---

# Phase 34 Plan 01: Wave 0 Test Surface + Dependency Install Summary

Authored RED test scaffolding for the entire Phase 34 CalDAV calendar integration, locking the public API contracts that Waves 1–2 (Plans 02–06) must implement. Installed `caldav[async]==3.2.0` and bumped `icalendar>=6.3.1` in the integration manifest so HA and the test `.venv/` agree on the runtime stack.

## What Landed

### Dependency Pins (Task 1)

`custom_components/asp_parking/manifest.json` now declares:

```json
"requirements": [
  "pyproj>=3.7.0",
  "rtree>=1.4.0",
  "shapely>=2.1.0",
  "numpy",
  "httpx>=0.28.0",
  "zstandard>=0.21.0",
  "icalendar>=6.3.1",
  "caldav[async]==3.2.0"
]
```

The `[async]` extra triggers a benign `WARNING: caldav 3.2.0 does not provide the extra 'async'` from pip — there is no such extra defined in caldav 3.2.0, but the bare module ships `caldav.aio.AsyncDAVClient` and `caldav.lib.error.{AuthorizationError, NotFoundError}` regardless. `icalendar` was already 7.0.3 in the test env so the `>=6.3.1` bump is satisfied without reinstall.

Verified:

```bash
$ .venv/bin/python -c "from caldav.aio import AsyncDAVClient; from caldav.lib import error as e; print(AsyncDAVClient.__name__, e.AuthorizationError.__name__, e.NotFoundError.__name__)"
AsyncDAVClient AuthorizationError NotFoundError
```

### RED Test Files

| Test file                                    | Tests | Target plan | Locks                                                                                                                                                                                                                                       |
| -------------------------------------------- | ----- | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tests/test_caldav_sync.py` (NEW)             | 17    | Plan 02     | `derive_uid` (CALDAV-04), `build_vevent_ical` w/ tz-aware DTSTART + UTC DTSTAMP (Pitfall 9), `render_title` SafeDict + `render_description` D-06, `validate_connection`/`list_calendars`/`write_or_update_event`/`delete_event` semantics + CALDAV-08 STATIC GUARD (no sync `caldav.DAVClient`) |
| `tests/test_coordinator_caldav.py` (NEW)      | 12    | Plan 04     | `_async_caldav_hook_after_resolve`, `_maybe_delete_caldav_on_move` (CALDAV-03/05 safety-window), `_async_apply_suspension_state` (D-08/Pitfall 8 choke-point), `_async_caldav_write_or_update` (D-09 streak-aware notification w/ notification_id `asp_parking_caldav_error`) |
| `tests/test_options_flow_caldav.py` (NEW)     | 8     | Plan 03     | `async_step_caldav` (CALDAV-01 auth probe + D-03 error key `caldav_auth_failed`), `async_step_caldav_calendar` (CALDAV-02 dropdown), D-02 absent-URL no-op, D-04 default title template, T-34-02 mitigation (failed probe must NOT persist) |
| `tests/test_init_caldav_remove.py` (NEW)      | 4     | Plan 05     | `async_remove_entry` (CALDAV-07 happy path, D-02 no-op, Pitfall 5 absent-UID graceful, T-34-04 best-effort delete + Store cleanup), storage-key contract `f"{DOMAIN}_caldav_{entry.entry_id}"`                                              |
| **Total**                                     | **41** | —           | All four module-level imports of caldav-related symbols are deferred to inside test bodies via `try/except` + `_require_*()` helpers so pytest collection succeeds today; each test that touches the missing symbol fails with a precise locator message naming which plan still owes that symbol. |

### `pytest --collect-only` output snippet

```
tests/test_caldav_sync.py::test_derive_uid_deterministic
tests/test_caldav_sync.py::test_derive_uid_changes_with_window_start
tests/test_caldav_sync.py::test_derive_uid_changes_with_entry_id
tests/test_caldav_sync.py::test_build_vevent_preserves_tz
tests/test_caldav_sync.py::test_build_vevent_dtstamp_is_utc
tests/test_caldav_sync.py::test_render_title_default_template
tests/test_caldav_sync.py::test_render_title_unknown_placeholder_safedict
tests/test_caldav_sync.py::test_render_description_format
tests/test_caldav_sync.py::test_validate_connection_success
tests/test_caldav_sync.py::test_validate_connection_auth_error_raises_caldav_auth_error
tests/test_caldav_sync.py::test_validate_connection_network_error_raises_caldav_auth_error
tests/test_caldav_sync.py::test_list_calendars_returns_url_name_tuples
tests/test_caldav_sync.py::test_list_calendars_handles_missing_display_name
tests/test_caldav_sync.py::test_write_or_update_event_idempotent_same_uid
tests/test_caldav_sync.py::test_write_or_update_event_deletes_old_then_creates_new
tests/test_caldav_sync.py::test_delete_event_treats_notfound_as_success
tests/test_caldav_sync.py::test_no_sync_caldav_client_imported
tests/test_coordinator_caldav.py::test_resolve_writes_event_when_caldav_configured
tests/test_coordinator_caldav.py::test_resolve_skips_write_when_suspended
tests/test_coordinator_caldav.py::test_resolve_skips_write_when_caldav_url_absent
tests/test_coordinator_caldav.py::test_safety_window_inside_no_delete
tests/test_coordinator_caldav.py::test_safety_window_outside_deletes
tests/test_coordinator_caldav.py::test_safety_window_no_op_when_uid_absent
tests/test_coordinator_caldav.py::test_suspension_transition_false_to_true_deletes
tests/test_coordinator_caldav.py::test_suspension_transition_true_to_true_no_op
tests/test_coordinator_caldav.py::test_suspension_transition_true_to_false_no_recreate
tests/test_coordinator_caldav.py::test_suspension_choke_point_no_uid_no_action
tests/test_coordinator_caldav.py::test_caldav_failure_notifies_once_per_streak
tests/test_coordinator_caldav.py::test_caldav_success_dismisses_notification_and_resets_flag
tests/test_options_flow_caldav.py::test_caldav_step_empty_url_creates_entry_no_op
tests/test_options_flow_caldav.py::test_caldav_step_invalid_credentials_shows_error
tests/test_options_flow_caldav.py::test_caldav_step_network_error_shows_same_error
tests/test_options_flow_caldav.py::test_caldav_step_success_chains_to_calendar_step
tests/test_options_flow_caldav.py::test_caldav_calendar_step_persists_selection
tests/test_options_flow_caldav.py::test_caldav_calendar_step_safety_window_persisted
tests/test_options_flow_caldav.py::test_caldav_calendar_step_default_template_used_when_blank
tests/test_options_flow_caldav.py::test_caldav_step_validate_connection_called_with_submitted_creds
tests/test_init_caldav_remove.py::test_async_remove_entry_deletes_event_and_store_when_uid_present
tests/test_init_caldav_remove.py::test_async_remove_entry_noop_when_caldav_url_absent
tests/test_init_caldav_remove.py::test_async_remove_entry_noop_when_no_stored_uid
tests/test_init_caldav_remove.py::test_async_remove_entry_continues_when_delete_fails

41 tests collected in 0.18s
```

## Commits

| Task | Description                                                       | Commit    |
| ---- | ----------------------------------------------------------------- | --------- |
| 1    | `feat`: add caldav[async]==3.2.0 + bump icalendar>=6.3.1          | `5ccb1da` |
| 2    | `test`: RED tests for caldav_sync public API (Plan 02 target)     | `61a5483` |
| 3    | `test`: RED tests for coordinator CalDAV hooks (Plan 04 target)   | `26e5f9c` |
| 4    | `test`: RED tests for CalDAV options-flow steps (Plan 03 target)  | `ee404c6` |
| 5    | `test`: RED tests for async_remove_entry teardown (Plan 05 target) | `8ac1694` |

## Verification

| Check                                                                                  | Status |
| -------------------------------------------------------------------------------------- | :----: |
| `from caldav.aio import AsyncDAVClient` succeeds                                       | ✅      |
| `from caldav.lib import error` exposes `AuthorizationError, NotFoundError`             | ✅      |
| `manifest.json` requirements contains `caldav[async]==3.2.0`                            | ✅      |
| `manifest.json` requirements contains `icalendar>=6.3.1`                                | ✅      |
| 4 new test files exist and are pytest-collectable                                       | ✅      |
| Total Phase 34 tests collected: **41** (>= 39 required)                                 | ✅      |
| All 41 new tests FAIL with locator-style errors naming the missing Plan-X symbols      | ✅      |
| Pre-existing test suite (`-m "not integration"`) — **559 passed**, 0 regressions        | ✅      |

```
$ .venv/bin/python -m pytest tests/test_caldav_sync.py tests/test_coordinator_caldav.py tests/test_options_flow_caldav.py tests/test_init_caldav_remove.py
============================== 41 failed in 2.30s ==============================

$ .venv/bin/python -m pytest -m "not integration" --ignore=tests/test_caldav_sync.py --ignore=tests/test_coordinator_caldav.py --ignore=tests/test_options_flow_caldav.py --ignore=tests/test_init_caldav_remove.py
================ 559 passed, 32 deselected, 1 warning in 13.10s ================
```

## Interface Contracts Locked

Each contract below is asserted by name in at least one test, so any future plan that names a method differently will trigger an AttributeError/ImportError in CI:

**`caldav_sync` (Plan 02):**
- `CalDAVAuthError`, `CalDAVConfig` (url/username/password/calendar_url/title_template/safety_window_minutes)
- `derive_uid(entry_id, window_start) -> "<32-hex>@asp-parking.local"`
- `render_title(template, schedule)` (SafeDict; unknown placeholders preserved)
- `render_description(schedule) -> "{on_street} ({side_of_street} side)\n{summary}"`
- `build_vevent_ical(*, uid, window, title, description)` (TZID-bearing DTSTART, UTC DTSTAMP, PRODID `-//ASP Parking//GPS2ASP//EN`)
- `async validate_connection(*, url, username, password)` (raises `CalDAVAuthError` on any failure — auth + network)
- `async list_calendars(*, url, username, password) -> [(url, name), ...]` (fallback `name = str(url)` if `get_display_name` raises)
- `async write_or_update_event(*, config, entry_id, schedule, stored_uid) -> new_uid` (delete-then-create on UID change; idempotent on same UID)
- `async delete_event(*, url, username, password, calendar_url, uid)` (silent on `caldav.lib.error.NotFoundError`)

**`ASPParkingCoordinator` (Plan 04):**
- `_async_caldav_hook_after_resolve(schedule)` (spawns task `asp_parking_caldav_write` when `CONF_CALDAV_URL` configured AND `data.suspension_state.is_suspended is False` — raw flag, NOT `schedule.suspended`)
- `_maybe_delete_caldav_on_move()` (safety-window gate; inside 15 min → no-op; outside → task `asp_parking_caldav_delete_on_move`; UID-absent → no-op)
- `@callback _async_apply_suspension_state(SuspensionInfo)` (False→True with UID → task `asp_parking_caldav_delete_on_suspension`; True→True / True→False / False→True w/o UID → no-op; always updates `_last_suspension_state`)
- `_async_caldav_write_or_update(schedule)` (failure streak → ONE `persistent_notification.async_create(notification_id="asp_parking_caldav_error")`; first success → `async_dismiss(notification_id="asp_parking_caldav_error")` + reset `_caldav_error_notified=False` + update `_caldav_uid` + `store.async_save({"uid": new_uid})`)

**`custom_components.asp_parking` (Plan 05):**
- `async def async_remove_entry(hass, entry)` (D-02 no-op when no URL; CALDAV-07 happy path = delete event + remove Store; Pitfall 5 absent-UID = no delete + no exception; T-34-04 robustness = catch RuntimeError + still remove Store)

**`const.py` (Plan 03):**
- `CONF_CALDAV_URL = "caldav_url"`, `CONF_CALDAV_USERNAME = "caldav_username"`, `CONF_CALDAV_PASSWORD = "caldav_password"`, `CONF_CALDAV_CALENDAR = "caldav_calendar"`, `CONF_CALDAV_SAFETY_WINDOW = "caldav_safety_window"`, `CONF_CALDAV_EVENT_TITLE_TEMPLATE = "caldav_event_title_template"`
- `DEFAULT_CALDAV_SAFETY_WINDOW = 15`, `DEFAULT_CALDAV_EVENT_TITLE_TEMPLATE = "ASP: {street}"`

**Storage-key contract (Plan 04 + Plan 05 must agree):** `f"{DOMAIN}_caldav_{entry.entry_id}"`.

**Notification-ID contract:** `asp_parking_caldav_error` (used by `_async_caldav_write_or_update`); the per-task names `asp_parking_caldav_write`, `asp_parking_caldav_delete_on_move`, `asp_parking_caldav_delete_on_suspension` are distinct per Pitfall 7.

## Deviations from Plan

None. Plan executed exactly as written. The plan acknowledged ahead of time that the `caldav[async]` pin emits a pip warning and the `[async]` extra is a no-op — that's the observed behavior at install time.

## Known Stubs

The four new test files all use a `_require_*()` helper pattern that calls `pytest.fail("Plan N has not yet implemented X")` when the target symbol is missing. **These are not stubs** — they are intentional Wave 0 RED scaffolding required by GSD methodology: the test files commit in failing state and become green as Wave 1/2 plans land. Each `pytest.fail` message names the specific downstream plan that owes the symbol, so the failure is self-documenting.

The Phase 34 CONF_CALDAV_* constants are inlined as literal strings (`"caldav_url"`, etc.) in `tests/test_coordinator_caldav.py`, `tests/test_options_flow_caldav.py`, and `tests/test_init_caldav_remove.py` rather than imported from `const.py`. This is also intentional Wave 0 scaffolding — Plan 03 will add the constants and at that point the test files will still pass without needing modification (the string literals match the plan-locked values).

## Threat Flags

None. Wave 0 introduces no new production-side surface. The single production change (`manifest.json` adding `caldav[async]==3.2.0`) is mitigated by T-34-08 (exact pin → pip wheel SHA256 verification is the supply-chain trust boundary; caldav 3.2.0 is the current latest per RESEARCH A5 with no known regressions). All other changes are test-only.

## Self-Check: PASSED

- `[FOUND]` `custom_components/asp_parking/manifest.json` (modified)
- `[FOUND]` `tests/test_caldav_sync.py` (new, 17 tests)
- `[FOUND]` `tests/test_coordinator_caldav.py` (new, 12 tests)
- `[FOUND]` `tests/test_options_flow_caldav.py` (new, 8 tests)
- `[FOUND]` `tests/test_init_caldav_remove.py` (new, 4 tests)
- `[FOUND]` commit `5ccb1da` — manifest.json
- `[FOUND]` commit `61a5483` — tests/test_caldav_sync.py
- `[FOUND]` commit `26e5f9c` — tests/test_coordinator_caldav.py
- `[FOUND]` commit `ee404c6` — tests/test_options_flow_caldav.py
- `[FOUND]` commit `8ac1694` — tests/test_init_caldav_remove.py
- 41 RED tests collected; pre-existing 559 tests still pass.
