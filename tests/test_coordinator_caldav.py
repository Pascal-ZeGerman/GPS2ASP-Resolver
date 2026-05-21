"""RED tests for Phase 34 coordinator CalDAV hooks (CALDAV-03..05, D-08, D-09).

Covers the new coordinator methods Plan 04 must implement:
  - _async_caldav_hook_after_resolve — spawns asp_parking_caldav_write task
    after a successful resolve when CalDAV is configured AND not suspended.
  - _maybe_delete_caldav_on_move — safety-window gate (CALDAV-03 / CALDAV-05);
    inside 15-min window, no delete; outside, spawn asp_parking_caldav_delete_on_move.
  - _async_apply_suspension_state — D-08 / Pitfall 8 choke-point; on
    False→True transition (with a stored _caldav_uid) spawns
    asp_parking_caldav_delete_on_suspension. No-op on stable or True→False
    transitions.
  - _async_caldav_write_or_update — wraps caldav_sync.write_or_update_event;
    D-09 streak-aware persistent notification (single notify per error streak;
    dismiss + reset on success).

Pattern: SimpleNamespace stub + AsyncMock for the store, MagicMock for
entry.async_create_background_task. Same pattern as
tests/test_coordinator_rebuild.py.

RED state proof: ASPParkingCoordinator does not yet define
_async_caldav_hook_after_resolve / _maybe_delete_caldav_on_move /
_async_apply_suspension_state / _async_caldav_write_or_update. The _bind()
helper triggers AttributeError on the missing class method, which is the
RED signal Wave-2 Plan 04 must clear.

The notification IDs 'asp_parking_caldav_error' / 'asp_parking_caldav_delete_on_suspension'
are also locked here so Plan 04 cannot drift from VALIDATION row T-34-04.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time

from custom_components.asp_parking.coordinator import ASPParkingCoordinator

# Defer caldav_sync access (Plan 02) — only used in two notification-dedup
# tests. Tests that touch caldav_sync directly call _require_caldav_sync().
try:
    from custom_components.asp_parking import caldav_sync as _caldav_sync  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    _caldav_sync = None


# CONF_* names — also unimplemented in const.py until Plan 03. Use the
# string literals locked by the plan's <interfaces> block so tests can be
# collected without an ImportError on the const module.
CONF_CALDAV_URL = "caldav_url"
CONF_CALDAV_USERNAME = "caldav_username"
CONF_CALDAV_PASSWORD = "caldav_password"
CONF_CALDAV_CALENDAR = "caldav_calendar"
CONF_CALDAV_SAFETY_WINDOW = "caldav_safety_window"
CONF_CALDAV_EVENT_TITLE_TEMPLATE = "caldav_event_title_template"


def _require_caldav_sync():
    """Skip-fail when caldav_sync isn't importable (Plan 02 not yet landed)."""
    if _caldav_sync is None:
        pytest.fail(
            "caldav_sync not importable — Plan 02 has not yet implemented "
            "custom_components/asp_parking/caldav_sync.py"
        )
    return _caldav_sync


# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------


def _background_task_sink(hass, coro, *, name=""):
    """Consume the coroutine to suppress RuntimeWarning."""
    try:
        coro.close()
    except Exception:
        pass
    return MagicMock()


def _make_suspension_info(*, is_suspended: bool = False):
    """Build a SuspensionInfo. Falls back to SimpleNamespace if the real
    class isn't on sys.path yet (still useful for collection time)."""
    try:
        from custom_components.asp_parking.gps2asp.suspension import SuspensionInfo  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        try:
            from gps2asp.suspension import SuspensionInfo  # type: ignore[no-redef]
        except Exception:  # noqa: BLE001
            return SimpleNamespace(
                is_suspended=is_suspended, reason=None, source="none"
            )
    return SuspensionInfo(is_suspended=is_suspended, reason=None, source="none")


def _make_cleaning_window(*, start: datetime, end: datetime | None = None):
    """SimpleNamespace stand-in for CleaningWindow."""
    return SimpleNamespace(
        day=start.weekday(),
        start_time=start.time(),
        end_time=(end or start).time(),
        start_datetime=start,
        end_datetime=end or start,
        source_signs=["NO PARKING 8AM-9:30AM MON THURS"],
    )


def _make_schedule_found(
    *,
    on_street: str = "VANDERBILT AVENUE",
    side: str = "N",
    summary: str = "Mon 8–9:30 AM",
    start: datetime | None = None,
):
    if start is None:
        start = datetime(2026, 5, 18, 8, 0, tzinfo=ZoneInfo("America/New_York"))
    window = _make_cleaning_window(start=start, end=start.replace(hour=9, minute=30))
    return SimpleNamespace(
        status="schedule_found",
        next_window=window,
        weekly_schedule=None,
        on_street=on_street,
        from_street="FLATBUSH AVENUE",
        to_street="PARK PLACE",
        side_of_street=side,
        source_signs=["NO PARKING 8AM-9:30AM MON THURS"],
        summary=summary,
        parse_failures=[],
        suspended=False,
        suspension_reason=None,
        resolution_reason=None,
    )


def _make_coord_stub_caldav(
    *,
    caldav_uid: str | None = None,
    is_suspended: bool = False,
    options_overrides: dict | None = None,
    no_caldav_config: bool = False,
) -> SimpleNamespace:
    """Build a minimal coordinator stub mimicking the Phase 34 fields.

    Set ``no_caldav_config=True`` to mirror D-02 (CONF_CALDAV_URL absent ⇒
    entire CalDAV branch is a no-op).
    """
    options: dict = {}
    if not no_caldav_config:
        options = {
            CONF_CALDAV_URL: "https://example.com/dav/",
            CONF_CALDAV_USERNAME: "user",
            CONF_CALDAV_PASSWORD: "pw",
            CONF_CALDAV_CALENDAR: "https://example.com/dav/cal/",
            CONF_CALDAV_SAFETY_WINDOW: 15,
            CONF_CALDAV_EVENT_TITLE_TEMPLATE: "ASP: {street}",
        }
    if options_overrides:
        options.update(options_overrides)

    entry = SimpleNamespace(
        entry_id="test_entry_caldav",
        async_create_background_task=MagicMock(side_effect=_background_task_sink),
        options=options,
    )

    store = SimpleNamespace(
        async_load=AsyncMock(return_value={"uid": caldav_uid} if caldav_uid else None),
        async_save=AsyncMock(),
        async_remove=AsyncMock(),
    )

    schedule = _make_schedule_found()

    hass = SimpleNamespace(
        async_create_task=MagicMock(),
    )

    stub = SimpleNamespace(
        entry=entry,
        hass=hass,
        data=SimpleNamespace(
            suspension_state=_make_suspension_info(is_suspended=is_suspended),
            schedule_result=schedule,
            on_street=schedule.on_street,
            side_of_street=schedule.side_of_street,
            from_street=schedule.from_street,
            to_street=schedule.to_street,
        ),
        _caldav_store=None if no_caldav_config else store,
        _caldav_uid=caldav_uid,
        _caldav_write_error_notified=False,
        _caldav_delete_error_notified=False,
        _caldav_lock=asyncio.Lock(),
        _caldav_write_task=None,
        _caldav_delete_task=None,
        _last_suspension_state=is_suspended,
        _async_notify_entities=MagicMock(),
    )
    return stub


def _bind(stub: SimpleNamespace, method_name: str):
    """Bind ASPParkingCoordinator.method_name to ``stub`` for invocation.

    AttributeError on the class is the RED-state signal for missing methods.
    """
    method = getattr(ASPParkingCoordinator, method_name)
    return method.__get__(stub, ASPParkingCoordinator)


# ---------------------------------------------------------------------------
# CALDAV-04 — resolve-success spawns asp_parking_caldav_write
# ---------------------------------------------------------------------------


async def test_resolve_writes_event_when_caldav_configured():
    """CALDAV-04: a successful resolve with CalDAV config spawns one write task."""
    stub = _make_coord_stub_caldav()
    schedule = stub.data.schedule_result

    hook = _bind(stub, "_async_caldav_hook_after_resolve")
    await hook(schedule)

    assert stub.entry.async_create_background_task.call_count == 1
    name = stub.entry.async_create_background_task.call_args.kwargs.get("name")
    assert name == "asp_parking_caldav_write", (
        f"Expected name='asp_parking_caldav_write'; got {name!r}"
    )


async def test_resolve_skips_write_when_suspended():
    """CALDAV-04 / Pitfall 4: when suspension_state.is_suspended=True, NO write."""
    stub = _make_coord_stub_caldav(is_suspended=True)
    schedule = stub.data.schedule_result

    hook = _bind(stub, "_async_caldav_hook_after_resolve")
    await hook(schedule)

    assert stub.entry.async_create_background_task.call_count == 0, (
        "Suspended day must skip CalDAV write (raw suspension_state.is_suspended check)"
    )


async def test_resolve_skips_write_when_caldav_url_absent():
    """D-02: no CONF_CALDAV_URL → entire CalDAV branch is a no-op."""
    stub = _make_coord_stub_caldav(no_caldav_config=True)
    schedule = stub.data.schedule_result

    hook = _bind(stub, "_async_caldav_hook_after_resolve")
    await hook(schedule)

    assert stub.entry.async_create_background_task.call_count == 0, (
        "D-02: absent CONF_CALDAV_URL must spawn no background tasks"
    )


async def test_resolve_with_no_next_window_spawns_delete():
    """CALDAV-04: when schedule has no next_window (NoASPSchedule etc.), spawn delete task."""
    stub = _make_coord_stub_caldav(caldav_uid="abc@asp-parking.local")
    # Build a schedule-like object with no next_window
    no_window_schedule = SimpleNamespace(status="no_asp_schedule", next_window=None)

    hook = _bind(stub, "_async_caldav_hook_after_resolve")
    await hook(no_window_schedule)

    assert stub.entry.async_create_background_task.call_count == 1
    name = stub.entry.async_create_background_task.call_args.kwargs.get("name")
    assert name == "asp_parking_caldav_delete_on_move", (
        f"No active window must spawn delete task; got name={name!r}"
    )


# ---------------------------------------------------------------------------
# CALDAV-03 / CALDAV-05 — safety-window gate around next_window.start_datetime
# ---------------------------------------------------------------------------


def _start_nyc(year=2026, month=5, day=18, hour=8, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("America/New_York"))


@freeze_time("2026-05-18 11:50:00")  # UTC = NYC 07:50 → 10 min before 08:00 window
async def test_safety_window_inside_no_delete():
    """CALDAV-03: inside the 15-min safety window before next_window, NO delete spawned."""
    stub = _make_coord_stub_caldav(caldav_uid="abc@asp-parking.local")
    # next_window.start_datetime is already 2026-05-18 08:00 NYC by _make_schedule_found.

    hook = _bind(stub, "_maybe_delete_caldav_on_move")
    await hook()

    assert stub.entry.async_create_background_task.call_count == 0, (
        "Inside safety window: must NOT spawn a delete task (CALDAV-03)"
    )


@freeze_time("2026-05-18 11:30:00")  # UTC = NYC 07:30 → 30 min before 08:00 window
async def test_safety_window_outside_deletes():
    """CALDAV-05: outside the 15-min window, spawn asp_parking_caldav_delete_on_move."""
    stub = _make_coord_stub_caldav(caldav_uid="abc@asp-parking.local")

    hook = _bind(stub, "_maybe_delete_caldav_on_move")
    await hook()

    assert stub.entry.async_create_background_task.call_count == 1
    name = stub.entry.async_create_background_task.call_args.kwargs.get("name")
    assert name == "asp_parking_caldav_delete_on_move", (
        f"Expected name='asp_parking_caldav_delete_on_move'; got {name!r}"
    )


@freeze_time("2026-05-18 11:30:00")
async def test_safety_window_no_op_when_uid_absent():
    """CALDAV-05 guard: _caldav_uid is None → no delete even outside the window."""
    stub = _make_coord_stub_caldav(caldav_uid=None)

    hook = _bind(stub, "_maybe_delete_caldav_on_move")
    await hook()

    assert stub.entry.async_create_background_task.call_count == 0, (
        "No stored UID → nothing to delete (CALDAV-05 guard)"
    )


# ---------------------------------------------------------------------------
# D-08 / Pitfall 8 — suspension transition choke-point
# ---------------------------------------------------------------------------


async def test_suspension_transition_false_to_true_deletes():
    """D-08 / Pitfall 8: when _last_suspension_state=False and new is_suspended=True,
    spawn asp_parking_caldav_delete_on_suspension and update _last_suspension_state."""
    stub = _make_coord_stub_caldav(
        caldav_uid="abc@asp-parking.local", is_suspended=False
    )
    # _last_suspension_state is False by default

    new_info = _make_suspension_info(is_suspended=True)
    hook = _bind(stub, "_async_apply_suspension_state")
    hook(new_info)  # @callback synchronous

    assert stub.entry.async_create_background_task.call_count == 1
    name = stub.entry.async_create_background_task.call_args.kwargs.get("name")
    assert name == "asp_parking_caldav_delete_on_suspension", (
        f"Expected name='asp_parking_caldav_delete_on_suspension'; got {name!r}"
    )
    assert stub._last_suspension_state is True, (
        "After transition the stored flag must reflect the new state (D-08)"
    )


async def test_suspension_transition_true_to_true_no_op():
    """D-08: _last_suspension_state=True, new is_suspended=True → no transition, no task."""
    stub = _make_coord_stub_caldav(
        caldav_uid="abc@asp-parking.local", is_suspended=True
    )
    # _last_suspension_state initialized to True via is_suspended=True

    new_info = _make_suspension_info(is_suspended=True)
    hook = _bind(stub, "_async_apply_suspension_state")
    hook(new_info)

    assert stub.entry.async_create_background_task.call_count == 0, (
        "True→True is not a transition; must not spawn another delete task"
    )


async def test_suspension_transition_true_to_false_no_recreate():
    """D-08 / Anti-Patterns row 6: True→False MUST NOT re-create the event.

    The next normal resolve handles re-creation. The transition choke-point
    is delete-only on False→True.
    """
    stub = _make_coord_stub_caldav(caldav_uid=None, is_suspended=True)
    # _last_suspension_state initialized to True

    new_info = _make_suspension_info(is_suspended=False)
    hook = _bind(stub, "_async_apply_suspension_state")
    hook(new_info)

    assert stub.entry.async_create_background_task.call_count == 0, (
        "True→False must not spawn any CalDAV task (next resolve handles re-creation)"
    )
    # Bookkeeping: the flag is updated regardless
    assert stub._last_suspension_state is False


async def test_suspension_choke_point_no_uid_no_action():
    """Pitfall 8 / D-08 guard: False→True transition with NO stored UID is a no-op."""
    stub = _make_coord_stub_caldav(caldav_uid=None, is_suspended=False)

    new_info = _make_suspension_info(is_suspended=True)
    hook = _bind(stub, "_async_apply_suspension_state")
    hook(new_info)

    assert stub.entry.async_create_background_task.call_count == 0, (
        "No stored _caldav_uid → nothing to delete (Pitfall 8 guard)"
    )


# ---------------------------------------------------------------------------
# D-09 — failure notification dedup (one per streak)
# ---------------------------------------------------------------------------


async def test_caldav_failure_notifies_once_per_streak(monkeypatch):
    """D-09: two consecutive write failures → exactly ONE persistent_notification.create.

    The notification ID is locked to 'asp_parking_caldav_error' so Plan 04
    can dismiss it on success (test below).
    """
    _require_caldav_sync()
    stub = _make_coord_stub_caldav()
    schedule = stub.data.schedule_result

    pn_create = MagicMock()
    pn_dismiss = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.persistent_notification",
        SimpleNamespace(async_create=pn_create, async_dismiss=pn_dismiss),
    )

    with patch(
        "custom_components.asp_parking.caldav_sync.write_or_update_event",
        new_callable=AsyncMock,
        side_effect=RuntimeError("server down"),
    ):
        write = _bind(stub, "_async_caldav_write_or_update")
        await write(schedule)
        # Second call while the streak is unresolved
        await write(schedule)

    # The notification ID 'asp_parking_caldav_error' is locked here.
    assert pn_create.call_count == 1, (
        f"Expected exactly one persistent_notification.create call; got {pn_create.call_count}"
    )
    # The notification_id arg must be the locked literal
    called_kwargs = pn_create.call_args.kwargs
    called_args = pn_create.call_args.args
    notification_id = called_kwargs.get("notification_id") or (
        called_args[-1] if called_args else None
    )
    # Some HA versions accept notification_id as keyword only; accept either
    assert "asp_parking_caldav_error" in (
        str(notification_id),
        *[str(a) for a in called_args],
        *[str(v) for v in called_kwargs.values()],
    ), (
        f"notification_id must be 'asp_parking_caldav_error'; "
        f"got kwargs={called_kwargs} args={called_args}"
    )
    assert stub._caldav_write_error_notified is True


async def test_caldav_success_dismisses_notification_and_resets_flag(monkeypatch):
    """D-09: on the first successful write after a failure streak, dismiss the
    notification, reset _caldav_error_notified, update _caldav_uid, and persist
    via store.async_save({'uid': new_uid})."""
    _require_caldav_sync()
    stub = _make_coord_stub_caldav()
    stub._caldav_write_error_notified = True
    schedule = stub.data.schedule_result

    pn_create = MagicMock()
    pn_dismiss = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.persistent_notification",
        SimpleNamespace(async_create=pn_create, async_dismiss=pn_dismiss),
    )

    new_uid = "new-uid-from-write@asp-parking.local"
    with patch(
        "custom_components.asp_parking.caldav_sync.write_or_update_event",
        new_callable=AsyncMock,
        return_value=new_uid,
    ):
        write = _bind(stub, "_async_caldav_write_or_update")
        await write(schedule)

    # Dismiss the streak notification — id locked to 'asp_parking_caldav_error'
    assert pn_dismiss.call_count == 1, (
        f"Expected one dismiss call after first success; got {pn_dismiss.call_count}"
    )
    dismiss_kwargs = pn_dismiss.call_args.kwargs
    dismiss_args = pn_dismiss.call_args.args
    assert "asp_parking_caldav_error" in (
        *[str(a) for a in dismiss_args],
        *[str(v) for v in dismiss_kwargs.values()],
    ), (
        f"dismiss notification_id must be 'asp_parking_caldav_error'; "
        f"got kwargs={dismiss_kwargs} args={dismiss_args}"
    )
    assert stub._caldav_write_error_notified is False
    assert stub._caldav_uid == new_uid
    stub._caldav_store.async_save.assert_awaited_once_with({"uid": new_uid})


async def test_caldav_delete_failure_notifies_once_per_streak(monkeypatch):
    """D-09 (delete path): two consecutive delete failures → exactly ONE notification.

    The notification ID for delete failures is 'asp_parking_caldav_delete_error',
    separate from the write-path 'asp_parking_caldav_error'.
    """
    _require_caldav_sync()
    stub = _make_coord_stub_caldav(caldav_uid="abc@asp-parking.local")

    pn_create = MagicMock()
    pn_dismiss = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.persistent_notification",
        SimpleNamespace(async_create=pn_create, async_dismiss=pn_dismiss),
    )

    with patch(
        "custom_components.asp_parking.caldav_sync.delete_event",
        new_callable=AsyncMock,
        side_effect=RuntimeError("server down"),
    ):
        delete = _bind(stub, "_async_caldav_delete_current")
        await delete("abc@asp-parking.local")
        # Second call while the streak is unresolved
        await delete("abc@asp-parking.local")

    assert pn_create.call_count == 1, (
        f"Expected exactly one notification for delete failure streak; got {pn_create.call_count}"
    )
    notification_id = pn_create.call_args.kwargs.get("notification_id") or (
        pn_create.call_args.args[-1] if pn_create.call_args.args else None
    )
    assert notification_id == "asp_parking_caldav_delete_error", (
        f"Delete failures must use 'asp_parking_caldav_delete_error'; got {notification_id!r}"
    )
    assert stub._caldav_delete_error_notified is True


async def test_caldav_delete_success_clears_store_pop_not_wipe(monkeypatch):
    """Finding 8: successful delete uses pop-then-save, not async_save({}).

    Verifies that async_save is called with a dict that had 'uid' popped,
    rather than a bare empty dict (which would wipe any future store keys).
    """
    _require_caldav_sync()
    stub = _make_coord_stub_caldav(caldav_uid="abc@asp-parking.local")
    # Simulate a store that has uid + a hypothetical future key
    stub._caldav_store.async_load = AsyncMock(
        return_value={"uid": "abc@asp-parking.local", "future_key": "preserved"}
    )

    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.persistent_notification",
        SimpleNamespace(async_create=MagicMock(), async_dismiss=MagicMock()),
    )

    with patch(
        "custom_components.asp_parking.caldav_sync.delete_event",
        new_callable=AsyncMock,
    ):
        delete = _bind(stub, "_async_caldav_delete_current")
        await delete("abc@asp-parking.local")

    # async_save must have been called with uid removed but other keys intact
    stub._caldav_store.async_save.assert_awaited_once()
    saved_data = stub._caldav_store.async_save.call_args.args[0]
    assert "uid" not in saved_data, (
        "uid key must be removed from store on successful delete"
    )
    assert saved_data.get("future_key") == "preserved", (
        "Future store keys must be preserved (pop-then-save, not async_save({}))"
    )


# ---------------------------------------------------------------------------
# Edge-case tests (16 new tests)
# ---------------------------------------------------------------------------


# --- _async_apply_suspension_state edge cases ---


async def test_apply_suspension_true_to_false_no_delete_task():
    """True→False transition must NOT spawn a delete task.

    Only False→True spawns deletion; True→False is handled by the next
    normal resolve cycle. Regression guard for the mirrored-condition bug.
    """
    stub = _make_coord_stub_caldav(
        caldav_uid="abc@asp-parking.local", is_suspended=True
    )
    # _last_suspension_state is True, _caldav_uid is set, _caldav_store is set

    new_info = _make_suspension_info(is_suspended=False)
    hook = _bind(stub, "_async_apply_suspension_state")
    hook(new_info)  # @callback synchronous

    assert stub.entry.async_create_background_task.call_count == 0, (
        "True→False transition must NOT spawn any delete task — "
        "only False→True triggers deletion (D-08 / Pitfall 8)"
    )
    assert stub._last_suspension_state is False, (
        "Bookkeeping: _last_suspension_state must be updated to False"
    )


async def test_apply_suspension_uid_set_but_store_none_no_delete():
    """False→True with _caldav_uid set but _caldav_store=None: no delete task.

    Both _caldav_uid AND _caldav_store must be non-None for the delete
    branch to trigger (the `and self._caldav_store is not None` guard).
    """
    stub = _make_coord_stub_caldav(
        caldav_uid="abc@asp-parking.local", is_suspended=False
    )
    stub._caldav_store = None  # Wipe the store — UID present but store absent

    new_info = _make_suspension_info(is_suspended=True)
    hook = _bind(stub, "_async_apply_suspension_state")
    hook(new_info)

    assert stub.entry.async_create_background_task.call_count == 0, (
        "store=None must prevent the delete task even when _caldav_uid is set"
    )
    # State bookkeeping still occurs
    assert stub._last_suspension_state is True


async def test_apply_suspension_store_set_but_uid_none_no_delete():
    """False→True with _caldav_store set but _caldav_uid=None: no delete task.

    The uid=None guard fires first; no stored event means nothing to delete.
    """
    stub = _make_coord_stub_caldav(caldav_uid=None, is_suspended=False)
    # _caldav_store is the stub store (not None); _caldav_uid is None

    new_info = _make_suspension_info(is_suspended=True)
    hook = _bind(stub, "_async_apply_suspension_state")
    hook(new_info)

    assert stub.entry.async_create_background_task.call_count == 0, (
        "_caldav_uid=None must prevent the delete task even when store is set"
    )
    assert stub._last_suspension_state is True


# --- _async_caldav_write_or_update edge cases ---


async def test_write_or_update_skips_when_suspended_after_lock(monkeypatch):
    """Suspension flip True inside the lock aborts the write without calling caldav_sync.

    Simulates the race: caller was not suspended at schedule time, but
    suspension became active before the lock was acquired.
    """
    _require_caldav_sync()
    stub = _make_coord_stub_caldav(caldav_uid="uid123")
    # Flip suspension state so the inside-lock check fires
    stub.data.suspension_state = _make_suspension_info(is_suspended=True)

    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.persistent_notification",
        SimpleNamespace(async_create=MagicMock(), async_dismiss=MagicMock()),
    )

    write_mock = AsyncMock()
    with patch(
        "custom_components.asp_parking.caldav_sync.write_or_update_event",
        new=write_mock,
    ):
        write = _bind(stub, "_async_caldav_write_or_update")
        await write(stub.data.schedule_result)

    write_mock.assert_not_called()


async def test_write_or_update_success_dismisses_notification_and_resets_flag(
    monkeypatch,
):
    """Success after error streak: pn_dismiss called with correct id, flag reset to False.

    Distinct from the existing test: verifies the notification_id is
    'asp_parking_caldav_error' and that _caldav_write_error_notified is
    cleared in the same atomic success path.
    """
    _require_caldav_sync()
    stub = _make_coord_stub_caldav()
    stub._caldav_write_error_notified = True  # Simulate active error streak

    pn_dismiss = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.persistent_notification",
        SimpleNamespace(async_create=MagicMock(), async_dismiss=pn_dismiss),
    )

    new_uid = "fresh-uid@asp-parking.local"
    with patch(
        "custom_components.asp_parking.caldav_sync.write_or_update_event",
        new_callable=AsyncMock,
        return_value=new_uid,
    ):
        write = _bind(stub, "_async_caldav_write_or_update")
        await write(stub.data.schedule_result)

    assert pn_dismiss.call_count == 1, (
        f"Expected one pn_dismiss call on success; got {pn_dismiss.call_count}"
    )
    # The dismiss notification_id must be the locked literal
    all_strs = [str(a) for a in pn_dismiss.call_args.args] + [
        str(v) for v in pn_dismiss.call_args.kwargs.values()
    ]
    assert "asp_parking_caldav_error" in all_strs, (
        f"pn_dismiss must use 'asp_parking_caldav_error'; got args={pn_dismiss.call_args}"
    )
    assert stub._caldav_write_error_notified is False, (
        "_caldav_write_error_notified must be False after successful write"
    )


async def test_write_or_update_sanitises_username_in_error_notification(monkeypatch):
    """Error messages must not leak the CalDAV username into persistent notifications.

    The coordinator sanitises both username and password from the error
    string before creating the notification (T-34-01 / T-34-05).
    """
    _require_caldav_sync()
    stub = _make_coord_stub_caldav(
        options_overrides={
            CONF_CALDAV_USERNAME: "sensitiveuser",
        }
    )

    pn_create = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.persistent_notification",
        SimpleNamespace(async_create=pn_create, async_dismiss=MagicMock()),
    )

    with patch(
        "custom_components.asp_parking.caldav_sync.write_or_update_event",
        new_callable=AsyncMock,
        side_effect=Exception("auth error for sensitiveuser@host"),
    ):
        write = _bind(stub, "_async_caldav_write_or_update")
        await write(stub.data.schedule_result)

    assert pn_create.call_count >= 1, "Expected pn_create to be called on error"
    # Check that none of the notification arguments contain the raw username
    all_strs = " ".join(
        [str(a) for a in pn_create.call_args.args]
        + [str(v) for v in pn_create.call_args.kwargs.values()]
    )
    assert "sensitiveuser" not in all_strs, (
        f"Username must be scrubbed from notification; got: {all_strs!r}"
    )
    assert "***" in all_strs, "Redacted placeholder '***' must appear in notification"


# --- _async_caldav_delete_current edge cases ---


async def test_delete_current_returns_early_when_url_removed(monkeypatch):
    """If CONF_CALDAV_URL is absent from options at execution time, return silently.

    Covers the mid-flight deconfiguration race (Finding 4): the task was
    spawned while CalDAV was configured, but the option was removed before
    the task ran. The coordinator uses .get() to avoid a KeyError.
    """
    _require_caldav_sync()
    stub = _make_coord_stub_caldav(caldav_uid="abc@asp-parking.local")
    stub.entry.options = {}  # CalDAV URL removed between spawn and execution

    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.persistent_notification",
        SimpleNamespace(async_create=MagicMock(), async_dismiss=MagicMock()),
    )

    # Must not raise; must return silently
    delete = _bind(stub, "_async_caldav_delete_current")
    await delete("abc@asp-parking.local")  # Should not raise


async def test_delete_current_uid_guard_preserves_new_uid(monkeypatch):
    """UID guard: if _caldav_uid changed before the lock, do NOT clear it.

    Scenario: delete was spawned for "OLD-UID", but a concurrent write
    already stored a new event "NEW-UID". The guard `if self._caldav_uid == uid`
    prevents the delete from wiping the new UID (Finding 1 race fix).
    """
    _require_caldav_sync()
    stub = _make_coord_stub_caldav(caldav_uid="NEW-UID")
    # Simulate that the store returns data for the old uid
    stub._caldav_store.async_load = AsyncMock(return_value={"uid": "OLD-UID"})

    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.persistent_notification",
        SimpleNamespace(async_create=MagicMock(), async_dismiss=MagicMock()),
    )

    with patch(
        "custom_components.asp_parking.caldav_sync.delete_event",
        new_callable=AsyncMock,
    ):
        delete = _bind(stub, "_async_caldav_delete_current")
        await delete("OLD-UID")  # Spawned for OLD-UID

    assert stub._caldav_uid == "NEW-UID", (
        "UID guard must NOT clear _caldav_uid when it no longer matches the deleted UID"
    )


# --- _async_caldav_hook_after_resolve edge cases ---


async def test_hook_after_resolve_noop_when_store_none():
    """_caldav_store=None → the entire hook is a no-op (D-02 guard).

    This is the CalDAV-not-configured path; no background task must be spawned.
    """
    stub = _make_coord_stub_caldav(no_caldav_config=True)
    schedule = stub.data.schedule_result

    hook = _bind(stub, "_async_caldav_hook_after_resolve")
    await hook(schedule)

    assert stub.entry.async_create_background_task.call_count == 0, (
        "_caldav_store=None must make the hook a complete no-op"
    )


async def test_hook_after_resolve_noop_when_suspended():
    """suspension_state.is_suspended=True → hook no-ops even when store is set.

    Pitfall 4: the gate uses raw suspension_state.is_suspended, not
    schedule.suspended. Guards against a suspended-day write race.
    """
    stub = _make_coord_stub_caldav(is_suspended=True)
    schedule = stub.data.schedule_result

    hook = _bind(stub, "_async_caldav_hook_after_resolve")
    await hook(schedule)

    assert stub.entry.async_create_background_task.call_count == 0, (
        "Suspended state must prevent any CalDAV task from being spawned (Pitfall 4)"
    )


async def test_hook_after_resolve_no_next_window_spawns_delete():
    """Any schedule without next_window (e.g. ASPActiveNow) spawns a delete task.

    Documents that `active_window` present but `next_window` absent/None
    routes to the delete branch. The calendar event is removed because
    there is no *upcoming* window to display.
    """
    stub = _make_coord_stub_caldav(caldav_uid="abc@asp-parking.local")
    # Schedule with active_window but NO next_window (mirrors ASPActiveNow shape)
    active_now_schedule = SimpleNamespace(
        status="asp_active_now",
        active_window=_make_cleaning_window(
            start=datetime(2026, 5, 18, 8, 0, tzinfo=ZoneInfo("America/New_York"))
        ),
        next_window=None,
    )

    hook = _bind(stub, "_async_caldav_hook_after_resolve")
    await hook(active_now_schedule)

    assert stub.entry.async_create_background_task.call_count == 1
    name = stub.entry.async_create_background_task.call_args.kwargs.get("name")
    assert name == "asp_parking_caldav_delete_on_move", (
        f"ASPActiveNow (no next_window) must spawn delete task; got {name!r}"
    )


async def test_hook_not_called_on_outside_nyc_error():
    """OutsideNYCError in the pipeline must skip _async_caldav_hook_after_resolve.

    The hook is only reachable on the success path inside _async_resolve_pipeline.
    Verifies by spying on the stub method.
    """
    from custom_components.asp_parking.gps2asp.resolver.exceptions import (
        OutsideNYCError,
    )

    stub = _make_coord_stub_caldav()
    stub._caldav_hook_called = False

    # Spy: replace the hook with an AsyncMock on the stub instance
    hook_spy = AsyncMock()
    stub._async_caldav_hook_after_resolve = hook_spy

    # Build a minimal pipeline stub that raises OutsideNYCError at the resolve step
    stub._pending_lat = 40.0
    stub._pending_lon = -74.0
    stub._debug_enabled = False
    stub._debug_lat = None
    stub._debug_lon = None
    stub._sign_cache = {}
    stub.data.last_lat = None
    stub.data.last_lon = None
    stub.data.last_resolved = None
    stub.data.confidence_score = None
    stub.data.borough = None
    stub.data.distance_ft = None
    stub.data.street_width_ft = None
    stub.data.segment_id = None
    stub.data.sign_count = 0
    stub.data.soda_level = 0
    stub.data.parse_failures = 0
    stub.data.special_state = None
    stub.data.last_error = None
    stub.data.last_error_time = None
    stub._async_maybe_send_notification = AsyncMock()

    # Patch the resolve function to raise OutsideNYCError
    with patch(
        "custom_components.asp_parking.coordinator.resolve",
        new_callable=AsyncMock,
        side_effect=OutsideNYCError(40.0, -74.0),
    ):
        # Also patch dt_util.utcnow used by the pipeline
        with patch(
            "custom_components.asp_parking.coordinator.dt_util.utcnow",
            return_value=datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc),
        ):
            pipeline = _bind(stub, "_async_resolve_pipeline")
            await pipeline()

    hook_spy.assert_not_called()


async def test_hook_after_resolve_no_asp_schedule_spawns_delete():
    """NoASPSchedule-shaped object (next_window=None) routes to delete task.

    Complements the ASPActiveNow test: any schedule variant without
    next_window must trigger deletion of a stale calendar event.
    """
    stub = _make_coord_stub_caldav(caldav_uid="abc@asp-parking.local")
    no_asp = SimpleNamespace(status="no_asp_schedule", next_window=None)

    hook = _bind(stub, "_async_caldav_hook_after_resolve")
    await hook(no_asp)

    assert stub.entry.async_create_background_task.call_count == 1
    name = stub.entry.async_create_background_task.call_args.kwargs.get("name")
    assert "delete" in (name or ""), (
        f"NoASPSchedule must spawn a delete-named task; got {name!r}"
    )


# --- _maybe_delete_caldav_on_move boundary edge cases ---

# Boundary: boundary = start_datetime - 15min
#   start_datetime = 2026-05-18 08:00 NYC = 2026-05-18 12:00 UTC
#   boundary       = 2026-05-18 07:45 NYC = 2026-05-18 11:45 UTC
#
# Contract: now >= boundary → inside window → NO delete
#           now <  boundary → outside window → DELETE spawned


@freeze_time("2026-05-18 11:45:00")  # UTC = NYC 07:45 — exactly at boundary
async def test_safety_window_exactly_at_boundary_no_delete():
    """Exactly at the boundary (now == boundary): inside window → no delete.

    `now >= boundary` is True at the boundary, so the guard returns
    without spawning a delete task (car is considered to be moving).
    """
    stub = _make_coord_stub_caldav(caldav_uid="abc@asp-parking.local")

    hook = _bind(stub, "_maybe_delete_caldav_on_move")
    await hook()

    assert stub.entry.async_create_background_task.call_count == 0, (
        "At exactly the boundary (now == boundary), no delete must be spawned "
        "(CALDAV-03: now >= boundary means inside safety window)"
    )


@freeze_time("2026-05-18 11:44:59")  # UTC = NYC 07:44:59 — 1 second before boundary
async def test_safety_window_one_second_before_boundary_spawns_delete():
    """One second before the boundary (now < boundary): outside window → delete spawned.

    The car is moving more than 15 minutes early; the calendar event
    should be removed so the reminder doesn't appear at the wrong time.
    """
    stub = _make_coord_stub_caldav(caldav_uid="abc@asp-parking.local")

    hook = _bind(stub, "_maybe_delete_caldav_on_move")
    await hook()

    assert stub.entry.async_create_background_task.call_count == 1, (
        "1 second before the boundary must spawn a delete task (CALDAV-05)"
    )
    name = stub.entry.async_create_background_task.call_args.kwargs.get("name")
    assert name == "asp_parking_caldav_delete_on_move", (
        f"Expected 'asp_parking_caldav_delete_on_move'; got {name!r}"
    )


# --- _async_caldav_write_or_update store-save failure ---


async def test_write_or_update_store_save_raises_caught_and_notifies(monkeypatch):
    """async_save raising OSError is caught by the broad except handler.

    The `try` block in _async_caldav_write_or_update wraps both the
    caldav_sync call AND async_save, so an OSError from async_save is caught,
    logged, and surfaced as a persistent notification rather than propagating.
    This documents the actual behavior: storage failures are NOT silently
    swallowed — they trigger the error notification path.
    """
    _require_caldav_sync()
    stub = _make_coord_stub_caldav()
    stub._caldav_store.async_save = AsyncMock(side_effect=OSError("storage full"))

    pn_create = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.persistent_notification",
        SimpleNamespace(async_create=pn_create, async_dismiss=MagicMock()),
    )

    new_uid = "new-uid@asp-parking.local"
    with patch(
        "custom_components.asp_parking.caldav_sync.write_or_update_event",
        new_callable=AsyncMock,
        return_value=new_uid,
    ):
        write = _bind(stub, "_async_caldav_write_or_update")
        # Must NOT raise — the OSError is caught by the broad except block
        await write(stub.data.schedule_result)

    # The error notification must be created (first failure in streak)
    assert pn_create.call_count == 1, (
        f"OSError from async_save must trigger one error notification; "
        f"got {pn_create.call_count} calls"
    )
    assert stub._caldav_write_error_notified is True, (
        "_caldav_write_error_notified must be True after async_save failure"
    )


# ---------------------------------------------------------------------------
# Phase 35.1 Plan 06 — BUG-C-002 / BUG-C-003 / BUG-C-004 regression tests
# ---------------------------------------------------------------------------


async def test_caldav_write_re_checks_suspension_after_await(monkeypatch):
    """BUG-C-002: suspension flipping True DURING write_or_update_event must
    cause a delete-on-flip task to be spawned for the just-written UID.

    Race scenario:
      1. _async_caldav_write_or_update acquires the lock and confirms
         is_suspended=False before the await.
      2. caldav_sync.write_or_update_event() runs (network I/O);
         meanwhile the suspension state flips to True (holiday-fired or
         manual suspension during the same tick).
      3. After the await returns with a new UID, the coordinator MUST
         re-check suspension_state.is_suspended. If True, the event we
         just wrote is now stale — spawn a delete task for new_uid.

    RED expectation: no post-await re-check exists today; no delete task is
    spawned. The test asserts both the delete task AND that the task name
    contains 'delete_on_suspension_race', a literal Plan 06 must add.
    """
    _require_caldav_sync()
    stub = _make_coord_stub_caldav()
    schedule = stub.data.schedule_result

    pn_create = MagicMock()
    pn_dismiss = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.persistent_notification",
        SimpleNamespace(async_create=pn_create, async_dismiss=pn_dismiss),
    )

    new_uid = "race-uid@asp-parking.local"

    async def _flip_suspension_then_return(**kwargs):
        # Simulate the network call: while the await is in-flight, a
        # concurrent code path (a holiday calendar refresh, a manual
        # suspension service call, etc.) sets is_suspended=True.
        stub.data.suspension_state = _make_suspension_info(is_suspended=True)
        return new_uid

    with patch(
        "custom_components.asp_parking.caldav_sync.write_or_update_event",
        new=_flip_suspension_then_return,
    ):
        write = _bind(stub, "_async_caldav_write_or_update")
        await write(schedule)

    # The coordinator must have spawned a delete task for the just-written UID
    assert stub.entry.async_create_background_task.call_count == 1, (
        "BUG-C-002: post-await suspension re-check must spawn exactly one "
        f"delete-on-flip task; got {stub.entry.async_create_background_task.call_count}"
    )
    name = stub.entry.async_create_background_task.call_args.kwargs.get("name")
    assert name is not None and "delete_on_suspension_race" in name, (
        f"BUG-C-002: delete-on-flip task name must contain "
        f"'delete_on_suspension_race'; got {name!r}"
    )
    # The delete task handle must be stored on the coordinator (used by tests
    # and downstream lifecycle teardown).
    assert stub._caldav_delete_task is not None, (
        "BUG-C-002: _caldav_delete_task must reference the spawned delete task"
    )
