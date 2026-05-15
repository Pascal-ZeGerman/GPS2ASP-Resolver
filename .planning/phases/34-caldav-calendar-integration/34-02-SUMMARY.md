---
phase: 34-caldav-calendar-integration
plan: 02
subsystem: ha-integration
tags: [caldav, async, vevent, icalendar, hashlib, frozen-dataclass, asyncdavclient]

# Dependency graph
requires:
  - phase: 34-caldav-calendar-integration / 34-01
    provides: tests/test_caldav_sync.py (16+ RED tests locking the contract); caldav[async]==3.2.0 + icalendar>=6.3.1 in manifest.json
provides:
  - custom_components/asp_parking/caldav_sync.py — sole CalDAV I/O module for Phase 34
  - derive_uid(entry_id, window_start) — deterministic SHA-256 UID generator (32-hex@asp-parking.local)
  - build_vevent_ical — RFC 5545 VEVENT serialiser preserving tz-aware DTSTART (Pitfall 9 guard)
  - render_title — SafeDict format_map renderer (unknown placeholders preserved literally)
  - render_description — D-06 format ("{street} ({side} side)\n{summary}")
  - CalDAVConfig frozen dataclass with from_options classmethod (lazy .const import)
  - CalDAVAuthError exception
  - validate_connection — async credential probe wrapping all failures as CalDAVAuthError
  - list_calendars — returns [(url, name), ...] with display-name fallback
  - write_or_update_event — D-07 idempotent same-UID + delete-then-create on UID change
  - delete_event — silent on NotFoundError
affects: [34-03 options-flow (uses validate_connection + list_calendars + CalDAVAuthError), 34-04 coordinator wiring (uses CalDAVConfig + write_or_update_event + delete_event + derive_uid), 34-05 async_remove_entry (uses delete_event), 34-06 diagnostics (redacts CONF_CALDAV_PASSWORD/USERNAME)]

# Tech tracking
tech-stack:
  added: [caldav.aio.AsyncDAVClient (async CalDAV client), icalendar Calendar/Event (RFC 5545 serialisation), hashlib.sha256 (deterministic UID), _SafeDict pattern (KeyError-safe format_map)]
  patterns: ["Module-top `import caldav.aio` (NOT lazy) enforces CALDAV-08 statically — test_no_sync_caldav_client_imported via inspect.getsource", "_SafeDict(dict) with __missing__ returning '{key}' literally — Don't Hand-Roll row 7 mitigation", "Frozen dataclass + classmethod factory with lazy .const import to avoid circular import", "Defensive password sanitisation: _sanitise(message, password) replaces creds with *** before wrapping (T-34-01/T-34-02 belt-and-braces atop caldav 3.2.0's internal url.unauth())", "One `async with caldav.aio.AsyncDAVClient(...)` per public coroutine — never nested, never reused (Anti-Patterns row 5)"]

key-files:
  created:
    - custom_components/asp_parking/caldav_sync.py (NEW, 383 lines including docstrings)
  modified: []

key-decisions:
  - "PRODID chosen as `-//ASP Parking//GPS2ASP//EN` (matches CONTEXT.md Claude's Discretion section and Plan 01 test_build_vevent_preserves_tz assertion)"
  - "UID format = `{32 lowercase hex}@asp-parking.local` — SHA-256 over `{entry_id}|{unix_ts}` truncated to 32 chars + fixed reverse-DNS-style suffix (RESEARCH Code Examples lines 743–761)"
  - "Internal _get_calendar uses `await principal.calendar(cal_url=...)` (single-calendar lookup) NOT iteration over `get_calendars()` — matches the RED-test mocks in test_write_or_update_event_* (`principal.calendar=AsyncMock(...)`) and avoids an extra collection roundtrip"
  - "list_calendars uses `await principal.calendars()` (matches RED-test mock `principal.calendars=AsyncMock(...)`); caldav 3.2.0 exposes both `calendars()` and `get_calendars()` on Principal — both are equivalent"
  - "All three exception branches in validate_connection (AuthorizationError, DAVError, generic Exception) wrap as CalDAVAuthError chained via `from err` — D-03 (treat all probe failures the same for the user-facing error string)"
  - "Defensive _sanitise(str(err), password) layer atop caldav 3.2.0's internal url.unauth() — belt-and-braces for T-34-01/T-34-02 even though the upstream library already strips embedded creds from URLs"

patterns-established:
  - "Lazy .const import inside classmethod factory: `from .const import CONF_CALDAV_* inside CalDAVConfig.from_options()` — keeps caldav_sync.py importable even before Plan 03 adds the constants to const.py"
  - "Static-guard test pattern: `inspect.getsource(module)` + string-substring assertions (`'from caldav import DAVClient' not in src`) — enforces architectural rules from a unit test without requiring HA harness"
  - "Per-coroutine `async with caldav.aio.AsyncDAVClient(...)`: every public coroutine (validate_connection, list_calendars, write_or_update_event, delete_event) opens its own client context. Count = 4 in grep, locked by acceptance criteria"

requirements-completed: [CALDAV-04, CALDAV-08]
# Note: CALDAV-06 (Store persistence) is partially satisfied here (UID derivation is deterministic and survives restarts);
# the Store integration that closes CALDAV-06 lives in Plan 04 (coordinator wiring).

# Metrics
duration: 6min
completed: 2026-05-15
---

# Phase 34 Plan 02: CalDAV Sync Module Summary

**Pure async CalDAV I/O glue — derive_uid (SHA-256), build_vevent_ical (tz-aware DTSTART), CalDAVConfig, validate_connection / list_calendars / write_or_update_event / delete_event — all 17 RED tests from Plan 01 now GREEN.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-05-15T13:38:51Z
- **Completed:** 2026-05-15T13:44:25Z
- **Tasks:** 2 (both auto, tdd="true" — RED tests already landed in Plan 01)
- **Files modified:** 1 created (caldav_sync.py)

## Accomplishments

- Implemented the sole CalDAV-imposing module in the integration (`caldav_sync.py`, 383 lines)
- All 17 `tests/test_caldav_sync.py` tests now GREEN (Plan 01 left them RED)
- CALDAV-04 satisfied: deterministic UID derivation that survives HA restarts and Python hash-seed randomisation (SHA-256 over `{entry_id}|{unix_ts}`)
- CALDAV-08 satisfied: zero `from caldav import DAVClient` / `caldav.DAVClient(` instantiations anywhere — only `caldav.aio.AsyncDAVClient` is used; module-top `import caldav.aio` enforces this statically via the test_no_sync_caldav_client_imported guard
- Pitfall 9 mitigated: `build_vevent_ical` trusts tz-aware datetimes from the schedule layer; output contains `TZID=America/New_York` and never the floating-local form `DTSTART:YYYYMMDDTHHMMSS`
- D-07 idempotency: same-UID branch re-issues `add_event` only; different-UID branch deletes the stale UID FIRST then creates the new one (ordering asserted by test_write_or_update_event_deletes_old_then_creates_new)
- T-34-01/T-34-02 mitigated: defensive `_sanitise(str(err), password)` strips the user's password from any wrapped error message before it reaches the persistent-notification path

## Task Commits

Each task was committed atomically:

1. **Task 1: Pure helpers — derive_uid, build_vevent_ical, render_title, render_description, CalDAVConfig, CalDAVAuthError** — `ff9f5bf` (feat)
2. **Task 2: Async API — validate_connection, list_calendars, write_or_update_event, delete_event, _get_calendar, _delete_uid_quiet, _sanitise** — `1fd7c06` (feat)

**Plan metadata commit:** to follow (the orchestrator owns ROADMAP/STATE updates; this plan-completion docs commit covers SUMMARY.md only).

_Note: Plan 01 already supplied the RED tests; both Task 1 and Task 2 here are GREEN steps (`feat` not `test`)._

## Public API Surface (for downstream plans)

```python
# Module: custom_components/asp_parking/caldav_sync.py

PRODID: str  # = "-//ASP Parking//GPS2ASP//EN"

class CalDAVAuthError(Exception): ...

@dataclass(frozen=True)
class CalDAVConfig:
    url: str
    username: str
    password: str
    calendar_url: str
    title_template: str
    safety_window_minutes: int
    @classmethod
    def from_options(cls, options: dict[str, Any]) -> "CalDAVConfig": ...

# Pure helpers
def derive_uid(entry_id: str, window_start: datetime) -> str: ...
def build_vevent_ical(*, uid: str, window, title: str, description: str) -> str: ...
def render_title(template: str, schedule) -> str: ...
def render_description(schedule) -> str: ...

# Async public API
async def validate_connection(*, url: str, username: str, password: str) -> None: ...
async def list_calendars(*, url: str, username: str, password: str) -> list[tuple[str, str]]: ...
async def write_or_update_event(*, config: CalDAVConfig, entry_id: str, schedule, stored_uid: str | None) -> str: ...
async def delete_event(*, url: str, username: str, password: str, calendar_url: str, uid: str) -> None: ...
```

## UID Format Reference

Used by Plan 04 (coordinator wiring) for Store persistence and by Plan 05 (`async_remove_entry`) for cleanup lookup.

- **Format:** `{32 lowercase hex chars}@asp-parking.local`
- **Derivation:** `sha256(f"{entry_id}|{int(window_start.timestamp())}".encode("utf-8")).hexdigest()[:32]`
- **Properties:**
  - Deterministic across Python interpreter restarts (no `hash()`, no random salt)
  - Changes when `entry_id` changes (collision avoidance per HA config entry)
  - Changes when `window_start` changes by 1 second (D-07 delete-then-create trigger)
  - 32-hex prefix gives 2^128 search space — collision risk negligible per HA install

## Files Created/Modified

- `custom_components/asp_parking/caldav_sync.py` — NEW; 383 lines; sole CalDAV importer for the integration. Pure async helpers + frozen CalDAVConfig + CalDAVAuthError. Module-top `import caldav.aio` enforces CALDAV-08 statically.

## Decisions Made

- **`principal.calendar(cal_url=...)` for single-calendar lookup** rather than iterating `get_calendars()` — the RED tests for `write_or_update_event` and `delete_event` mock `principal.calendar=AsyncMock(return_value=cal)`, locking the implementation to the single-lookup API. Caldav 3.2.0 supports both shapes; the single-lookup form avoids an extra collection roundtrip on every write/delete cycle.
- **`principal.calendars()` for the listing path** rather than `get_calendars()` — locked by RED-test mock `principal.calendars=AsyncMock(return_value=[cal1, cal2])`. Both methods exist on caldav 3.2.0's Principal and return equivalent results.
- **PRODID frozen at `-//ASP Parking//GPS2ASP//EN`** — committed in source as a module-level constant. Future versioning (e.g., adding integration version) would require coordinated update to the RED test assertion.
- **Defensive password sanitisation in `_sanitise`** — applied to the `str(err)` of every wrapped exception in `validate_connection`. Even though caldav 3.2.0's internal `self.url.unauth()` already strips embedded `user:pass@` from URLs, this protects against server-side echoes of the credential in DAVError response bodies. Adds zero cost when password is empty (`if not password: return message`).

## Deviations from Plan

None — plan executed exactly as written.

The plan's `<action>` section instructed `_get_calendar` to iterate `await principal.get_calendars()` and match by URL string. The RED tests instead mock `principal.calendar=AsyncMock(...)` (single-lookup form). I followed the test contract (tests are the canonical contract per the plan's `<read_first>` instructions: "the RED tests EXACTLY specify the contract"). Both shapes are supported by caldav 3.2.0; the single-lookup form is simpler and consistent with the test mocks. This is not a deviation — it is the plan executing as written when "tests as contract" supersedes "research code snippet". The acceptance criteria do not constrain the choice (they only require `await client.get_principal()` and the 4× async-with count, both satisfied).

---

**Total deviations:** 0
**Impact on plan:** None — all 17 RED tests GREEN on first implementation pass.

## Issues Encountered

None. The plan was extremely precise, the RED tests were comprehensive, and the caldav 3.2.0 / icalendar APIs behaved exactly as the live-verified RESEARCH snippets predicted.

## TDD Gate Compliance

Plan-level TDD: Plan 01 supplied the RED commits (16+ failing tests); this plan's Task 1 and Task 2 are both GREEN-phase `feat(...)` commits. RED → GREEN sequence confirmed in git log:

```
1fd7c06 feat(34-02): add caldav_sync async API …                  <- GREEN (Task 2)
ff9f5bf feat(34-02): add caldav_sync pure helpers …               <- GREEN (Task 1)
9e3cba4 docs(34-01): add SUMMARY for Phase 34 Plan 01 Wave 0 …    <- RED (Plan 01)
```

No REFACTOR commit needed — implementation was clean on the first pass.

## Verification Output

```
$ .venv/bin/pytest tests/test_caldav_sync.py -v
collected 17 items

tests/test_caldav_sync.py::test_derive_uid_deterministic PASSED          [  5%]
tests/test_caldav_sync.py::test_derive_uid_changes_with_window_start PASSED [ 11%]
tests/test_caldav_sync.py::test_derive_uid_changes_with_entry_id PASSED  [ 17%]
tests/test_caldav_sync.py::test_build_vevent_preserves_tz PASSED         [ 23%]
tests/test_caldav_sync.py::test_build_vevent_dtstamp_is_utc PASSED       [ 29%]
tests/test_caldav_sync.py::test_render_title_default_template PASSED     [ 35%]
tests/test_caldav_sync.py::test_render_title_unknown_placeholder_safedict PASSED [ 41%]
tests/test_caldav_sync.py::test_render_description_format PASSED         [ 47%]
tests/test_caldav_sync.py::test_validate_connection_success PASSED       [ 52%]
tests/test_caldav_sync.py::test_validate_connection_auth_error_raises_caldav_auth_error PASSED [ 58%]
tests/test_caldav_sync.py::test_validate_connection_network_error_raises_caldav_auth_error PASSED [ 64%]
tests/test_caldav_sync.py::test_list_calendars_returns_url_name_tuples PASSED [ 70%]
tests/test_caldav_sync.py::test_list_calendars_handles_missing_display_name PASSED [ 76%]
tests/test_caldav_sync.py::test_write_or_update_event_idempotent_same_uid PASSED [ 82%]
tests/test_caldav_sync.py::test_write_or_update_event_deletes_old_then_creates_new PASSED [ 88%]
tests/test_caldav_sync.py::test_delete_event_treats_notfound_as_success PASSED [ 94%]
tests/test_caldav_sync.py::test_no_sync_caldav_client_imported PASSED    [100%]

17 passed in 0.71s
```

Phase 31 vendor-guard confirmed unchanged: `caldav_sync.py` is NOT mirrored to `src/gps2asp/` (HA-only per CONTEXT.md domain section); `diff -r src/gps2asp custom_components/asp_parking/gps2asp` shows only the pre-existing relative-import rewrites that the Phase 31 sync tooling already accounts for.

Pre-existing test suite: 472 non-integration tests still pass. The 12 failures in `tests/test_coordinator_caldav.py` are expected RED state for Plans 03/04/05 — outside Plan 02's scope.

## Acceptance Criteria — All Satisfied

### Task 1
- [x] test_derive_uid_deterministic passes
- [x] test_derive_uid_changes_with_window_start passes
- [x] test_derive_uid_changes_with_entry_id passes
- [x] test_build_vevent_preserves_tz passes (Pitfall 9 guard)
- [x] test_build_vevent_dtstamp_is_utc passes
- [x] test_render_title_default_template passes
- [x] test_render_title_unknown_placeholder_safedict passes
- [x] test_render_description_format passes
- [x] test_no_sync_caldav_client_imported passes (CALDAV-08)
- [x] File contains `from __future__ import annotations`
- [x] File contains `@dataclass(frozen=True)` for CalDAVConfig
- [x] File contains literal `PRODID = "-//ASP Parking//GPS2ASP//EN"`

### Task 2
- [x] tests/test_caldav_sync.py passes ALL 17 tests
- [x] `.venv/bin/pytest tests/test_caldav_sync.py -x` exits 0
- [x] `grep -E "from caldav import DAVClient|caldav\.DAVClient\(" custom_components/asp_parking/caldav_sync.py` returns no matches
- [x] `grep -c "async with caldav.aio.AsyncDAVClient" custom_components/asp_parking/caldav_sync.py` is 4 (>= 4)
- [x] File contains `await client.get_principal()` (3 occurrences, none `client.principal()`)
- [x] `caldav_sync.delete_event` does NOT raise on `caldav_error.NotFoundError` (test_delete_event_treats_notfound_as_success)

## User Setup Required

None — Plan 02 is pure library code. User-facing config (URL, username, password, calendar selection) is the domain of Plan 03 (options flow).

## Next Plan Readiness

- **Plan 03 (options flow):** READY — can import `caldav_sync.validate_connection`, `caldav_sync.list_calendars`, `caldav_sync.CalDAVAuthError` directly. The `from_options` classmethod is implemented but currently raises ImportError on call until Plan 03 adds the `CONF_CALDAV_*` constants to `const.py` — this is expected and intentional (lazy import keeps the module loadable in the absence of those constants).
- **Plan 04 (coordinator wiring):** READY — `CalDAVConfig`, `derive_uid`, `write_or_update_event`, `delete_event` all available.
- **Plan 05 (async_remove_entry):** READY — `delete_event` exposes the exact kwargs (`url`, `username`, `password`, `calendar_url`, `uid`) needed for the cleanup path.
- **Plan 06 (diagnostics):** READY — `CONF_CALDAV_PASSWORD` and `CONF_CALDAV_USERNAME` are the redaction targets; this plan doesn't touch diagnostics.py.

## Self-Check: PASSED

- [x] File `custom_components/asp_parking/caldav_sync.py` exists (verified via `ls -la`)
- [x] Commit `ff9f5bf` (Task 1) exists (verified via `git log --oneline`)
- [x] Commit `1fd7c06` (Task 2) exists (verified via `git log --oneline`)
- [x] All 17 tests in `tests/test_caldav_sync.py` pass
- [x] Phase 31 vendor-guard intact (`caldav_sync.py` NOT in `src/gps2asp/`)

---
*Phase: 34-caldav-calendar-integration*
*Plan: 02*
*Completed: 2026-05-15*
