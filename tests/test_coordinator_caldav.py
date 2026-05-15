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
from datetime import datetime, timedelta, timezone
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
    window = _make_cleaning_window(
        start=start, end=start.replace(hour=9, minute=30)
    )
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
        async_create_background_task=MagicMock(),
        options=options,
    )

    store = SimpleNamespace(
        async_load=AsyncMock(
            return_value={"uid": caldav_uid} if caldav_uid else None
        ),
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
        _caldav_error_notified=False,
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
    stub = _make_coord_stub_caldav(
        caldav_uid=None, is_suspended=True
    )
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
    assert stub._caldav_error_notified is True


async def test_caldav_success_dismisses_notification_and_resets_flag(monkeypatch):
    """D-09: on the first successful write after a failure streak, dismiss the
    notification, reset _caldav_error_notified, update _caldav_uid, and persist
    via store.async_save({'uid': new_uid})."""
    _require_caldav_sync()
    stub = _make_coord_stub_caldav()
    stub._caldav_error_notified = True
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
    assert stub._caldav_error_notified is False
    assert stub._caldav_uid == new_uid
    stub._caldav_store.async_save.assert_awaited_once_with({"uid": new_uid})
