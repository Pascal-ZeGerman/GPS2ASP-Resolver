"""RED tests for caldav_sync (Phase 34) — locks the public API for Plan 02.

Covers the public API of caldav_sync.py that Plan 02 must implement:
  - derive_uid: deterministic UID derivation (CALDAV-04)
  - build_vevent_ical: tz-aware DTSTART preservation (Pitfall 9), UTC DTSTAMP, PRODID
  - validate_connection: AuthError / OSError → CalDAVAuthError mapping (CALDAV-01)
  - list_calendars: returns [(url, name), ...] tuples + missing-display-name fallback (CALDAV-02)
  - write_or_update_event: idempotent + delete-then-create on UID change (D-07)
  - delete_event: NotFoundError treated as success
  - render_title / render_description (D-04 / D-06)
  - No sync caldav.DAVClient is ever imported (CALDAV-08 / Pitfall 1 STATIC GUARD)

Pattern: SimpleNamespace stub + AsyncMock for AsyncDAVClient.
Same pattern as tests/test_coordinator_rebuild.py.

RED state proof: `caldav_sync` does not yet exist in `custom_components/asp_parking/`.
All tests are expected to fail with ImportError/AttributeError until Plan 02 lands.
"""

from __future__ import annotations

import inspect
import re
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

# Defer the real import: collection must succeed even before Plan 02 lands.
# Individual tests will fail with ModuleNotFoundError/AttributeError when
# they touch caldav_sync, which is the RED-state signal.
try:
    from custom_components.asp_parking import caldav_sync as _caldav_sync  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001 — collection must not crash
    _caldav_sync = None


def _require_caldav_sync():
    """Skip-style fail when caldav_sync isn't importable yet (Plan 02 hasn't landed)."""
    if _caldav_sync is None:
        pytest.fail(
            "caldav_sync module not importable — Plan 02 has not yet implemented "
            "custom_components/asp_parking/caldav_sync.py"
        )
    return _caldav_sync


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_cleaning_window(*, start: datetime, end: datetime | None = None):
    """Minimal CleaningWindow stub.

    Plan 02 will accept the real CleaningWindow dataclass from src.gps2asp.schedule.models;
    a SimpleNamespace with start_datetime/end_datetime is sufficient for the API contract.
    """
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
    summary: str = "Mon 8–9:30 AM, Thu 11:30 AM–1 PM",
    start: datetime | None = None,
):
    """Minimal ScheduleFound stub for render_title/render_description tests."""
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


# ---------------------------------------------------------------------------
# derive_uid — CALDAV-04 deterministic UID
# ---------------------------------------------------------------------------


def test_derive_uid_deterministic():
    """CALDAV-04: derive_uid is a pure function of (entry_id, window_start).

    Calling twice with the same args returns the same UID, and the shape is
    32 lowercase hex chars + @asp-parking.local (per RESEARCH Deterministic UID).
    """
    cs = _require_caldav_sync()
    start = datetime(2026, 5, 18, 8, 0, tzinfo=ZoneInfo("America/New_York"))
    w1 = _make_cleaning_window(start=start)
    w2 = _make_cleaning_window(start=start)

    uid1 = cs.derive_uid("entry_abc", w1.start_datetime)
    uid2 = cs.derive_uid("entry_abc", w2.start_datetime)

    assert uid1 == uid2
    assert re.match(r"^[0-9a-f]{32}@asp-parking\.local$", uid1), (
        f"UID shape mismatch: {uid1!r}"
    )


def test_derive_uid_changes_with_window_start():
    """CALDAV-04 / D-07: shifting window_start by 1s yields a different UID."""
    cs = _require_caldav_sync()
    base = datetime(2026, 5, 18, 8, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    shifted = datetime(2026, 5, 18, 8, 0, 1, tzinfo=ZoneInfo("America/New_York"))

    assert cs.derive_uid("entry_abc", base) != cs.derive_uid("entry_abc", shifted)


def test_derive_uid_changes_with_entry_id():
    """CALDAV-04: different entry_ids → different UIDs (collision avoidance)."""
    cs = _require_caldav_sync()
    start = datetime(2026, 5, 18, 8, 0, tzinfo=ZoneInfo("America/New_York"))

    assert cs.derive_uid("entry_abc", start) != cs.derive_uid("entry_xyz", start)


# ---------------------------------------------------------------------------
# build_vevent_ical — Pitfall 9 (tz-aware DTSTART), RFC 5545 PRODID, UTC DTSTAMP
# ---------------------------------------------------------------------------


def test_build_vevent_preserves_tz():
    """Pitfall 9: DTSTART MUST carry TZID=America/New_York (not floating-local).

    A floating DTSTART (DTSTART:20260518T080000) would be interpreted as the
    viewer's local time — disastrous for a parking-aware calendar.
    """
    cs = _require_caldav_sync()
    start = datetime(2026, 5, 18, 8, 0, tzinfo=ZoneInfo("America/New_York"))
    end = datetime(2026, 5, 18, 9, 30, tzinfo=ZoneInfo("America/New_York"))
    window = _make_cleaning_window(start=start, end=end)

    ical = cs.build_vevent_ical(
        uid="abc@asp-parking.local",
        window=window,
        title="ASP: VANDERBILT AVENUE",
        description="VANDERBILT AVENUE (N side)\nMon 8–9:30 AM",
    )

    # ical may be returned as bytes or str — normalize
    text = ical.decode() if isinstance(ical, (bytes, bytearray)) else ical

    assert "TZID=America/New_York" in text, (
        f"DTSTART must carry TZID=America/New_York; got:\n{text}"
    )
    # The "floating" form would be DTSTART:20260518T080000 (no TZID, no Z).
    assert "DTSTART:20260518T080000" not in text, (
        "DTSTART must NOT be floating-local (no TZID); Pitfall 9 regression"
    )
    assert "PRODID:-//ASP Parking//GPS2ASP//EN" in text, (
        f"PRODID line missing or mismatched; got:\n{text}"
    )


def test_build_vevent_dtstamp_is_utc():
    """RFC 5545: DTSTAMP must be in UTC (suffixed with 'Z')."""
    cs = _require_caldav_sync()
    start = datetime(2026, 5, 18, 8, 0, tzinfo=ZoneInfo("America/New_York"))
    end = datetime(2026, 5, 18, 9, 30, tzinfo=ZoneInfo("America/New_York"))
    window = _make_cleaning_window(start=start, end=end)

    ical = cs.build_vevent_ical(
        uid="abc@asp-parking.local",
        window=window,
        title="ASP: X",
        description="x",
    )
    text = ical.decode() if isinstance(ical, (bytes, bytearray)) else ical

    # DTSTAMP:YYYYMMDDTHHMMSSZ — 15 chars after the colon ending in Z
    assert re.search(r"DTSTAMP:\d{8}T\d{6}Z", text), (
        f"DTSTAMP must be UTC (ending in 'Z'); got:\n{text}"
    )


# ---------------------------------------------------------------------------
# render_title — D-04 (default template) + SafeDict (no KeyError on unknown placeholder)
# ---------------------------------------------------------------------------


def test_render_title_default_template():
    """D-04: 'ASP: {street}' resolves on_street to 'ASP: VANDERBILT AVENUE'."""
    cs = _require_caldav_sync()
    schedule = _make_schedule_found(on_street="VANDERBILT AVENUE")

    title = cs.render_title("ASP: {street}", schedule)

    assert title == "ASP: VANDERBILT AVENUE"


def test_render_title_unknown_placeholder_safedict():
    """Don't Hand-Roll row 7 / SafeDict: unknown placeholders must NOT raise KeyError.

    The unknown {nonexistent} must be preserved literally as '{nonexistent}'
    in the output (SafeDict-style format_map).
    """
    cs = _require_caldav_sync()
    schedule = _make_schedule_found(on_street="VANDERBILT AVENUE")

    # Must NOT raise
    title = cs.render_title("ASP: {street} {nonexistent}", schedule)

    # Unknown key is preserved literally
    assert "VANDERBILT AVENUE" in title
    assert "{nonexistent}" in title, (
        f"Unknown placeholder must be preserved literally; got {title!r}"
    )


# ---------------------------------------------------------------------------
# render_description — D-06 ("{street} ({side} side)\n{summary}")
# ---------------------------------------------------------------------------


def test_render_description_format():
    """D-06: description == f'{on_street} ({side_of_street} side)\\n{summary}'."""
    cs = _require_caldav_sync()
    schedule = _make_schedule_found(
        on_street="VANDERBILT AVENUE",
        side="N",
        summary="Mon 8–9:30 AM",
    )

    desc = cs.render_description(schedule)

    assert desc == "VANDERBILT AVENUE (N side)\nMon 8–9:30 AM"


# ---------------------------------------------------------------------------
# validate_connection — CALDAV-01 (any failure → CalDAVAuthError)
# ---------------------------------------------------------------------------


async def test_validate_connection_success():
    """CALDAV-01: a working principal call → no exception, get_principal awaited."""
    cs = _require_caldav_sync()
    fake_principal = SimpleNamespace()
    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.get_principal = AsyncMock(return_value=fake_principal)

    with patch(
        "custom_components.asp_parking.caldav_sync.caldav.aio.AsyncDAVClient",
        return_value=fake_client,
    ):
        await cs.validate_connection(
            url="https://example.com/dav/", username="user", password="pw"
        )

    fake_client.get_principal.assert_awaited_once()


async def test_validate_connection_auth_error_raises_caldav_auth_error():
    """CALDAV-01: AuthorizationError → CalDAVAuthError (re-mapped)."""
    cs = _require_caldav_sync()
    from caldav.lib import error as caldav_error

    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.get_principal = AsyncMock(
        side_effect=caldav_error.AuthorizationError("bad")
    )

    with patch(
        "custom_components.asp_parking.caldav_sync.caldav.aio.AsyncDAVClient",
        return_value=fake_client,
    ):
        with pytest.raises(cs.CalDAVAuthError):
            await cs.validate_connection(
                url="https://example.com/dav/", username="user", password="pw"
            )


async def test_validate_connection_network_error_raises_caldav_auth_error():
    """CALDAV-01 / D-03: any generic failure (e.g. OSError DNS) → CalDAVAuthError."""
    cs = _require_caldav_sync()
    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.get_principal = AsyncMock(side_effect=OSError("DNS"))

    with patch(
        "custom_components.asp_parking.caldav_sync.caldav.aio.AsyncDAVClient",
        return_value=fake_client,
    ):
        with pytest.raises(cs.CalDAVAuthError):
            await cs.validate_connection(
                url="https://example.com/dav/", username="user", password="pw"
            )


# ---------------------------------------------------------------------------
# list_calendars — CALDAV-02 (tuple list + display-name fallback)
# ---------------------------------------------------------------------------


async def test_list_calendars_returns_url_name_tuples():
    """CALDAV-02: returns [(url, name), ...] for every calendar on the principal."""
    cs = _require_caldav_sync()
    cal1 = SimpleNamespace(
        url="https://srv/cal/work/",
        get_display_name=AsyncMock(return_value="Work"),
    )
    cal2 = SimpleNamespace(
        url="https://srv/cal/personal/",
        get_display_name=AsyncMock(return_value="Personal"),
    )
    principal = SimpleNamespace(calendars=AsyncMock(return_value=[cal1, cal2]))
    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.get_principal = AsyncMock(return_value=principal)

    with patch(
        "custom_components.asp_parking.caldav_sync.caldav.aio.AsyncDAVClient",
        return_value=fake_client,
    ):
        cals = await cs.list_calendars(
            url="https://srv/dav/", username="u", password="p"
        )

    assert cals == [
        ("https://srv/cal/work/", "Work"),
        ("https://srv/cal/personal/", "Personal"),
    ]


async def test_list_calendars_handles_missing_display_name():
    """CALDAV-02: when get_display_name raises, fall back to str(url) (RESEARCH §list_calendars)."""
    cs = _require_caldav_sync()
    cal1 = SimpleNamespace(
        url="https://srv/cal/work/",
        get_display_name=AsyncMock(side_effect=RuntimeError("display name 500")),
    )
    principal = SimpleNamespace(calendars=AsyncMock(return_value=[cal1]))
    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.get_principal = AsyncMock(return_value=principal)

    with patch(
        "custom_components.asp_parking.caldav_sync.caldav.aio.AsyncDAVClient",
        return_value=fake_client,
    ):
        cals = await cs.list_calendars(
            url="https://srv/dav/", username="u", password="p"
        )

    assert len(cals) == 1
    url, name = cals[0]
    assert url == "https://srv/cal/work/"
    assert name == str(cal1.url), (
        f"Fallback name must be str(url); got name={name!r} url={cal1.url!r}"
    )


# ---------------------------------------------------------------------------
# write_or_update_event — D-07 (idempotent same-UID, delete-then-create on change)
# ---------------------------------------------------------------------------


async def test_write_or_update_event_idempotent_same_uid():
    """D-07 / CALDAV-04: when stored_uid == derive_uid(...), no delete, single add_event."""
    cs = _require_caldav_sync()

    entry_id = "entry_abc"
    start = datetime(2026, 5, 18, 8, 0, tzinfo=ZoneInfo("America/New_York"))
    window = _make_cleaning_window(start=start, end=start.replace(hour=9, minute=30))
    schedule = _make_schedule_found(start=start)
    object.__setattr__(schedule, "next_window", window)

    expected_uid = cs.derive_uid(entry_id, window.start_datetime)

    cal = AsyncMock()
    cal.add_event = AsyncMock()
    cal.event_by_uid = AsyncMock()  # should not be called
    principal = SimpleNamespace(
        calendar=AsyncMock(return_value=cal),
        calendars=AsyncMock(return_value=[]),
    )
    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.get_principal = AsyncMock(return_value=principal)

    config = cs.CalDAVConfig(
        url="https://srv/dav/",
        username="u",
        password="p",
        calendar_url="https://srv/cal/work/",
        title_template="ASP: {street}",
        safety_window_minutes=15,
    )

    with patch(
        "custom_components.asp_parking.caldav_sync.caldav.aio.AsyncDAVClient",
        return_value=fake_client,
    ):
        new_uid = await cs.write_or_update_event(
            config=config,
            entry_id=entry_id,
            schedule=schedule,
            stored_uid=expected_uid,
        )

    assert new_uid == expected_uid
    # event_by_uid (the delete-then-create path) MUST NOT have been called
    assert cal.event_by_uid.await_count == 0, (
        "Same-UID branch must NOT call event_by_uid (no delete needed)"
    )
    # add_event is called once with ical= kwarg containing the UID
    assert cal.add_event.await_count == 1
    add_kwargs = cal.add_event.await_args.kwargs
    add_args = cal.add_event.await_args.args
    ical_payload = add_kwargs.get("ical") or (add_args[0] if add_args else None)
    payload_text = (
        ical_payload.decode()
        if isinstance(ical_payload, (bytes, bytearray))
        else ical_payload
    )
    assert payload_text is not None and expected_uid in payload_text, (
        f"add_event ical payload must embed the new UID; got payload={payload_text!r}"
    )


async def test_write_or_update_event_first_write_no_stored_uid():
    """Finding 9: stored_uid=None (first write) — no delete call, one add_event call.

    This is the most common production path (first CalDAV write after setup)
    and must not attempt to delete any previous event.
    """
    cs = _require_caldav_sync()

    start = datetime(2026, 5, 18, 8, 0, tzinfo=ZoneInfo("America/New_York"))
    schedule = _make_schedule_found(start=start)

    mock_event = MagicMock()
    mock_event.delete = AsyncMock()
    mock_cal = AsyncMock()
    mock_cal.add_event = AsyncMock()
    mock_cal.event_by_uid = AsyncMock(return_value=mock_event)

    mock_principal = AsyncMock()
    mock_principal.calendar = AsyncMock(return_value=mock_cal)
    mock_client = AsyncMock()
    mock_client.get_principal = AsyncMock(return_value=mock_principal)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "custom_components.asp_parking.caldav_sync.caldav.aio.AsyncDAVClient",
        return_value=mock_client,
    ):
        config = SimpleNamespace(
            url="https://example.com/dav/",
            username="user",
            password="pw",
            calendar_url="https://example.com/dav/cal/",
            title_template="ASP: {street}",
            safety_window_minutes=15,
        )
        returned_uid = await cs.write_or_update_event(
            config=config,
            entry_id="entry_abc",
            schedule=schedule,
            stored_uid=None,  # first write — no prior event
        )

    # No delete call must be made (stored_uid is None → guard `if stored_uid and ...` is False)
    mock_event.delete.assert_not_called()
    mock_cal.event_by_uid.assert_not_called()

    # One add_event call must be made
    assert mock_cal.add_event.call_count == 1, (
        f"Expected 1 add_event call on first write; got {mock_cal.add_event.call_count}"
    )

    # Returned UID must be deterministic
    expected_uid = cs.derive_uid("entry_abc", start)
    assert returned_uid == expected_uid


async def test_write_or_update_event_deletes_old_then_creates_new():
    """D-07: stored_uid != new_uid → delete old, THEN create new (order matters)."""
    cs = _require_caldav_sync()

    entry_id = "entry_abc"
    start = datetime(2026, 5, 18, 8, 0, tzinfo=ZoneInfo("America/New_York"))
    window = _make_cleaning_window(start=start, end=start.replace(hour=9, minute=30))
    schedule = _make_schedule_found(start=start)
    object.__setattr__(schedule, "next_window", window)

    stored_uid = "stale_uid_from_last_week@asp-parking.local"
    new_uid = cs.derive_uid(entry_id, window.start_datetime)
    assert stored_uid != new_uid

    call_order: list[str] = []

    async def _record_event_by_uid(uid):
        call_order.append(f"event_by_uid:{uid}")
        old_event = AsyncMock()
        old_event.delete = AsyncMock(
            side_effect=lambda: call_order.append(f"delete:{uid}")
        )
        return old_event

    async def _record_add_event(*args, **kwargs):
        call_order.append("add_event")

    cal = AsyncMock()
    cal.event_by_uid = AsyncMock(side_effect=_record_event_by_uid)
    cal.add_event = AsyncMock(side_effect=_record_add_event)
    principal = SimpleNamespace(
        calendar=AsyncMock(return_value=cal),
        calendars=AsyncMock(return_value=[]),
    )
    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.get_principal = AsyncMock(return_value=principal)

    config = cs.CalDAVConfig(
        url="https://srv/dav/",
        username="u",
        password="p",
        calendar_url="https://srv/cal/work/",
        title_template="ASP: {street}",
        safety_window_minutes=15,
    )

    with patch(
        "custom_components.asp_parking.caldav_sync.caldav.aio.AsyncDAVClient",
        return_value=fake_client,
    ):
        result_uid = await cs.write_or_update_event(
            config=config,
            entry_id=entry_id,
            schedule=schedule,
            stored_uid=stored_uid,
        )

    assert result_uid == new_uid
    # Ordering check: the stored UID must be looked up (delete path) BEFORE add_event
    delete_idx = next(
        (i for i, ev in enumerate(call_order) if ev.startswith("event_by_uid")), -1
    )
    add_idx = next((i for i, ev in enumerate(call_order) if ev == "add_event"), -1)
    assert delete_idx >= 0 and add_idx >= 0, f"Both calls expected; got {call_order}"
    assert delete_idx < add_idx, (
        f"event_by_uid (delete path) must precede add_event; order: {call_order}"
    )
    # And the deleted UID was the stale one
    assert any(ev == f"event_by_uid:{stored_uid}" for ev in call_order), (
        f"Stale UID must be the lookup target; calls: {call_order}"
    )


# ---------------------------------------------------------------------------
# delete_event — NotFoundError treated as success
# ---------------------------------------------------------------------------


async def test_delete_event_treats_notfound_as_success():
    """Pitfall in deletes / RESEARCH _delete_uid_quiet: NotFoundError is a no-op, not a failure."""
    cs = _require_caldav_sync()
    from caldav.lib import error as caldav_error

    cal = AsyncMock()
    cal.event_by_uid = AsyncMock(side_effect=caldav_error.NotFoundError("gone"))
    principal = SimpleNamespace(
        calendar=AsyncMock(return_value=cal),
        calendars=AsyncMock(return_value=[]),
    )
    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.get_principal = AsyncMock(return_value=principal)

    with patch(
        "custom_components.asp_parking.caldav_sync.caldav.aio.AsyncDAVClient",
        return_value=fake_client,
    ):
        # Must NOT raise
        await cs.delete_event(
            url="https://srv/dav/",
            username="u",
            password="p",
            calendar_url="https://srv/cal/work/",
            uid="abc@asp-parking.local",
        )


# ---------------------------------------------------------------------------
# CALDAV-08 / Pitfall 1 — STATIC GUARD: no sync caldav.DAVClient anywhere
# ---------------------------------------------------------------------------


def test_no_sync_caldav_client_imported():
    """CALDAV-08 / Pitfall 1 STATIC GUARD: caldav_sync MUST NOT import caldav.DAVClient.

    The sync DAVClient blocks the asyncio event loop; the entire integration
    runs inside HA's event loop and any blocking call risks stalling sensors.
    """
    cs = _require_caldav_sync()

    src = inspect.getsource(cs)
    assert "from caldav import DAVClient" not in src, (
        "CALDAV-08 regression: sync `from caldav import DAVClient` found in caldav_sync"
    )
    assert "caldav.DAVClient(" not in src, (
        "CALDAV-08 regression: sync `caldav.DAVClient(...)` instantiation found in caldav_sync"
    )


# ---------------------------------------------------------------------------
# _sanitise — password masking (Fix 6)
# ---------------------------------------------------------------------------


def test_sanitise_empty_password_returns_message_unchanged():
    """_sanitise with empty password returns the message as-is (no replacement)."""
    from custom_components.asp_parking.caldav_sync import _sanitise

    msg = "Connection error: https://user:secret@example.com/dav/"
    assert _sanitise(msg, "") == msg


def test_sanitise_password_present_is_replaced():
    """_sanitise replaces the password with '***' when it appears in the message."""
    from custom_components.asp_parking.caldav_sync import _sanitise

    msg = "Authentication failed: bad password: mySecret"
    result = _sanitise(msg, "mySecret")
    assert "mySecret" not in result
    assert "***" in result


def test_sanitise_password_absent_returns_message_unchanged():
    """_sanitise leaves the message unchanged when the password is not in it."""
    from custom_components.asp_parking.caldav_sync import _sanitise

    msg = "Connection error: timeout"
    result = _sanitise(msg, "mySecret")
    assert result == msg


# ---------------------------------------------------------------------------
# CalDAVConfig.from_options — construction + defaults (Fix 7)
# ---------------------------------------------------------------------------


def test_caldav_config_from_options_happy_path():
    """from_options maps all option keys to the correct CalDAVConfig fields."""
    from custom_components.asp_parking.caldav_sync import CalDAVConfig
    from custom_components.asp_parking.const import (
        CONF_CALDAV_CALENDAR,
        CONF_CALDAV_EVENT_TITLE_TEMPLATE,
        CONF_CALDAV_PASSWORD,
        CONF_CALDAV_SAFETY_WINDOW,
        CONF_CALDAV_URL,
        CONF_CALDAV_USERNAME,
    )

    options = {
        CONF_CALDAV_URL: "https://example.com/dav/",
        CONF_CALDAV_USERNAME: "alice",
        CONF_CALDAV_PASSWORD: "s3cr3t",
        CONF_CALDAV_CALENDAR: "https://example.com/dav/personal/",
        CONF_CALDAV_SAFETY_WINDOW: 30,
        CONF_CALDAV_EVENT_TITLE_TEMPLATE: "Parking: {street}",
    }

    cfg = CalDAVConfig.from_options(options)

    assert cfg.url == "https://example.com/dav/"
    assert cfg.username == "alice"
    assert cfg.password == "s3cr3t"
    assert cfg.calendar_url == "https://example.com/dav/personal/"
    assert cfg.safety_window_minutes == 30
    assert cfg.title_template == "Parking: {street}"


def test_caldav_config_from_options_missing_url_raises_key_error():
    """from_options raises KeyError when CONF_CALDAV_URL is absent."""
    from custom_components.asp_parking.caldav_sync import CalDAVConfig

    with pytest.raises(KeyError):
        CalDAVConfig.from_options({})


def test_caldav_config_from_options_default_values():
    """from_options uses correct defaults for optional fields.

    A calendar_url is supplied so __post_init__ validation passes; the test
    focuses on the defaults for username, password, safety_window_minutes, and
    title_template which are all truly optional.
    """
    from custom_components.asp_parking.caldav_sync import CalDAVConfig
    from custom_components.asp_parking.const import (
        CONF_CALDAV_CALENDAR,
        CONF_CALDAV_URL,
        DEFAULT_CALDAV_EVENT_TITLE_TEMPLATE,
        DEFAULT_CALDAV_SAFETY_WINDOW,
    )

    cfg = CalDAVConfig.from_options(
        {
            CONF_CALDAV_URL: "https://example.com/dav/",
            CONF_CALDAV_CALENDAR: "https://example.com/dav/personal/",
        }
    )

    assert cfg.username == ""
    assert cfg.password == ""
    assert cfg.safety_window_minutes == DEFAULT_CALDAV_SAFETY_WINDOW
    assert cfg.title_template == DEFAULT_CALDAV_EVENT_TITLE_TEMPLATE


# ---------------------------------------------------------------------------
# _delete_uid_quiet — DAVError with status 404 treated as success (Fix 8)
# ---------------------------------------------------------------------------


async def test_delete_event_treats_dav_error_404_as_success():
    """_delete_uid_quiet treats a generic DAVError with status==404 as 'not found'.

    Some CalDAV servers return a plain DAVError (not the NotFoundError subclass)
    for a 404 status code. Both must be silenced.
    """
    cs = _require_caldav_sync()
    from caldav.lib import error as caldav_error

    dav_err = caldav_error.DAVError("404 Not Found")
    dav_err.status = 404

    cal = AsyncMock()
    cal.event_by_uid = AsyncMock(side_effect=dav_err)
    principal = SimpleNamespace(
        calendar=AsyncMock(return_value=cal),
        calendars=AsyncMock(return_value=[]),
    )
    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.get_principal = AsyncMock(return_value=principal)

    with patch(
        "custom_components.asp_parking.caldav_sync.caldav.aio.AsyncDAVClient",
        return_value=fake_client,
    ):
        # Must NOT raise — DAVError with status 404 is treated as "already gone"
        await cs.delete_event(
            url="https://srv/dav/",
            username="u",
            password="p",
            calendar_url="https://srv/cal/work/",
            uid="abc@asp-parking.local",
        )


# ---------------------------------------------------------------------------
# New edge-case tests (11 cases)
# ---------------------------------------------------------------------------


async def test_validate_connection_timeout_raises_caldav_auth_error():
    """Edge 1: asyncio.TimeoutError → CalDAVAuthError with 'Connection error:' prefix.

    TimeoutError is not an AuthorizationError or DAVError so it falls through to
    the generic Exception handler which prefixes 'Connection error:'.
    The password must NOT appear in the exception message (_sanitise defence).
    """
    cs = _require_caldav_sync()
    import asyncio

    password = "supersecret"
    fake_client = AsyncMock()
    fake_client.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError("timed out"))
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "custom_components.asp_parking.caldav_sync.caldav.aio.AsyncDAVClient",
        return_value=fake_client,
    ):
        with pytest.raises(cs.CalDAVAuthError) as exc_info:
            await cs.validate_connection(
                url="https://example.com/dav/", username="user", password=password
            )

    msg = str(exc_info.value)
    assert msg.startswith("Connection error:"), (
        f"Expected 'Connection error:' prefix; got {msg!r}"
    )
    assert password not in msg, (
        f"Password must be sanitised from error message; got {msg!r}"
    )


async def test_list_calendars_empty_list():
    """Edge 2: principal.calendars() returns [] → list_calendars returns [] without raising."""
    cs = _require_caldav_sync()

    principal = SimpleNamespace(calendars=AsyncMock(return_value=[]))
    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.get_principal = AsyncMock(return_value=principal)

    with patch(
        "custom_components.asp_parking.caldav_sync.caldav.aio.AsyncDAVClient",
        return_value=fake_client,
    ):
        result = await cs.list_calendars(
            url="https://srv/dav/", username="u", password="p"
        )

    assert result == [], f"Expected empty list; got {result!r}"


async def test_list_calendars_get_display_name_raises_generic_exception():
    """Edge 3: get_display_name() raises Exception → fallback to str(url), no propagation."""
    cs = _require_caldav_sync()

    cal = SimpleNamespace(
        url="https://srv/cal/broken/",
        get_display_name=AsyncMock(side_effect=Exception("server error")),
    )
    principal = SimpleNamespace(calendars=AsyncMock(return_value=[cal]))
    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.get_principal = AsyncMock(return_value=principal)

    with patch(
        "custom_components.asp_parking.caldav_sync.caldav.aio.AsyncDAVClient",
        return_value=fake_client,
    ):
        result = await cs.list_calendars(
            url="https://srv/dav/", username="u", password="p"
        )

    assert len(result) == 1, f"Expected 1 calendar entry; got {result!r}"
    url_out, name_out = result[0]
    assert url_out == "https://srv/cal/broken/"
    assert name_out == str(cal.url), (
        f"Fallback name must be str(url); got name={name_out!r}"
    )


async def test_write_or_update_event_add_event_raises_propagates():
    """Edge 4: delete succeeds (stored_uid differs) but add_event raises → CalDAVAuthError propagates.

    add_event failures are wrapped in CalDAVAuthError to ensure credentials
    are sanitised from any error message echoed back by the server.
    """
    cs = _require_caldav_sync()

    entry_id = "entry_abc"
    start = datetime(2026, 5, 18, 8, 0, tzinfo=ZoneInfo("America/New_York"))
    window = _make_cleaning_window(start=start, end=start.replace(hour=9, minute=30))
    schedule = _make_schedule_found(start=start)
    object.__setattr__(schedule, "next_window", window)

    stored_uid = "old-uid-that-differs@asp-parking.local"
    new_uid = cs.derive_uid(entry_id, window.start_datetime)
    assert stored_uid != new_uid

    # Delete path: event_by_uid returns an event whose delete() succeeds
    old_event = AsyncMock()
    old_event.delete = AsyncMock(return_value=None)

    cal = AsyncMock()
    cal.event_by_uid = AsyncMock(return_value=old_event)
    cal.add_event = AsyncMock(side_effect=Exception("quota exceeded"))

    principal = SimpleNamespace(
        calendar=AsyncMock(return_value=cal),
        calendars=AsyncMock(return_value=[]),
    )
    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.get_principal = AsyncMock(return_value=principal)

    config = cs.CalDAVConfig(
        url="https://srv/dav/",
        username="alice",
        password="s3cr3t",
        calendar_url="https://srv/cal/work/",
        title_template="ASP: {street}",
        safety_window_minutes=15,
    )

    with patch(
        "custom_components.asp_parking.caldav_sync.caldav.aio.AsyncDAVClient",
        return_value=fake_client,
    ):
        with pytest.raises(cs.CalDAVAuthError) as exc_info:
            await cs.write_or_update_event(
                config=config,
                entry_id=entry_id,
                schedule=schedule,
                stored_uid=stored_uid,
            )

    msg = str(exc_info.value)
    assert "quota exceeded" in msg, f"Error detail missing from CalDAVAuthError: {msg!r}"
    assert "s3cr3t" not in msg, f"Password must be sanitised from error: {msg!r}"


def test_build_vevent_ical_naive_datetime_no_tzid():
    """Edge 5: naive start_datetime (no tzinfo) → no raise, no TZID= in output (floating DTSTART)."""
    cs = _require_caldav_sync()

    naive_start = datetime(2026, 5, 18, 8, 0)  # no tzinfo
    naive_end = datetime(2026, 5, 18, 9, 30)  # no tzinfo
    window = _make_cleaning_window(start=naive_start, end=naive_end)

    ical = cs.build_vevent_ical(
        uid="test-uid@asp-parking.local",
        window=window,
        title="T",
        description="D",
    )
    text = ical.decode() if isinstance(ical, (bytes, bytearray)) else ical

    assert isinstance(text, str), f"Expected str output; got {type(ical)}"
    # Floating DTSTART documents the behavior: no TZID= for naive datetimes
    assert "TZID=" not in text, (
        "Naive datetime should produce a floating DTSTART (no TZID); got TZID= in output"
    )


def test_render_title_rfc5545_reserved_chars_in_street_name():
    """Edge 6: RFC 5545 reserved chars ';' and ',' in street name pass through literally."""
    cs = _require_caldav_sync()
    schedule = _make_schedule_found(on_street="PROSPECT; PARK, ST")

    # Must not raise
    title = cs.render_title("ASP: {street}", schedule)

    assert ";" in title, f"Semicolon must appear literally in title; got {title!r}"
    assert "," in title, f"Comma must appear literally in title; got {title!r}"
    assert "PROSPECT; PARK, ST" in title


def test_derive_uid_naive_datetime_no_raise():
    """Edge 7: naive window_start (no tzinfo) → no raise; .timestamp() works for naive datetimes."""
    cs = _require_caldav_sync()

    naive_start = datetime(2026, 5, 18, 8, 0)  # no tzinfo

    # Must not raise
    uid = cs.derive_uid("entry-123", naive_start)

    assert uid.endswith("@asp-parking.local"), (
        f"UID must end with '@asp-parking.local'; got {uid!r}"
    )
    assert re.match(r"^[0-9a-f]{32}@asp-parking\.local$", uid), (
        f"UID shape mismatch: {uid!r}"
    )


async def test_delete_uid_quiet_non_404_dav_error_reraises():
    """Edge 8: _delete_uid_quiet with DAVError status=403 → exception is re-raised (not swallowed)."""
    cs = _require_caldav_sync()
    from caldav.lib import error as caldav_error

    exc = caldav_error.DAVError("403 Forbidden")
    exc.status = 403

    cal = AsyncMock()
    cal.event_by_uid = AsyncMock(side_effect=exc)
    principal = SimpleNamespace(
        calendar=AsyncMock(return_value=cal),
        calendars=AsyncMock(return_value=[]),
    )
    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.get_principal = AsyncMock(return_value=principal)

    with patch(
        "custom_components.asp_parking.caldav_sync.caldav.aio.AsyncDAVClient",
        return_value=fake_client,
    ):
        with pytest.raises(caldav_error.DAVError):
            await cs.delete_event(
                url="https://srv/dav/",
                username="u",
                password="p",
                calendar_url="https://srv/cal/work/",
                uid="abc@asp-parking.local",
            )


def test_sanitise_password_with_regex_metacharacters():
    """Edge 9: password with regex metacharacters → str.replace is literal (not regex).

    '.' and '*' are regex metacharacters but _sanitise uses str.replace so they
    are matched literally, not as pattern wildcards.
    """
    from custom_components.asp_parking.caldav_sync import _sanitise

    password = "my.pass*word?"
    message = f"error: {password} is wrong"

    result = _sanitise(message, password)

    assert result == "error: *** is wrong", (
        f"Expected literal replacement; got {result!r}"
    )


def test_caldav_config_post_init_large_safety_window_no_raise():
    """Edge 10: safety_window_minutes=9999 → no exception (no upper-bound enforcement)."""
    from custom_components.asp_parking.caldav_sync import CalDAVConfig

    # Must not raise — CalDAVConfig only enforces >= 0, not an upper bound
    cfg = CalDAVConfig(
        url="http://x",
        username="u",
        password="p",
        calendar_url="http://x/cal/",
        title_template="T",
        safety_window_minutes=9999,
    )

    assert cfg.safety_window_minutes == 9999


def test_caldav_config_from_options_missing_url_key_error():
    """Edge 11: CalDAVConfig.from_options({}) → KeyError (bare subscript on missing CONF_CALDAV_URL)."""
    from custom_components.asp_parking.caldav_sync import CalDAVConfig

    with pytest.raises(KeyError):
        CalDAVConfig.from_options({})


# ---------------------------------------------------------------------------
# _CompatAsyncDAVClient shim tests
#
# The shim classes are always defined at module level (not inside the
# except block), so these tests run unconditionally regardless of the
# installed caldav version. On caldav 3.x the shim is never installed
# into caldav.aio, but the classes are always importable and testable.
# ---------------------------------------------------------------------------


def test_compat_shim_async_dav_client_exists_after_import():
    """caldav.aio.AsyncDAVClient is always callable after module import."""
    import caldav

    async_client_class = getattr(getattr(caldav, "aio", None), "AsyncDAVClient", None)
    assert async_client_class is not None, (
        "caldav.aio.AsyncDAVClient must exist after caldav_sync import"
    )
    instance = async_client_class(url="https://srv/", username="u", password="p")
    assert hasattr(instance, "__aenter__")
    assert hasattr(instance, "__aexit__")


async def test_compat_async_dav_client_aenter_uses_executor():
    """_CompatAsyncDAVClient.__aenter__ dispatches DAVClient() via run_in_executor."""
    from custom_components.asp_parking.caldav_sync import _CompatAsyncDAVClient
    import caldav

    mock_sync_client = MagicMock()
    mock_sync_client.close = MagicMock()
    SyncClass = MagicMock(return_value=mock_sync_client)

    with patch.object(caldav, "DAVClient", SyncClass, create=True):
        client = _CompatAsyncDAVClient(url="https://srv/", username="u", password="p")
        result = await client.__aenter__()

    assert result is client
    assert client._client is mock_sync_client
    SyncClass.assert_called_once_with(url="https://srv/", username="u", password="p")


async def test_compat_async_dav_client_aexit_closes_client_via_executor():
    """_CompatAsyncDAVClient.__aexit__ calls close() via executor and sets _client to None."""
    from custom_components.asp_parking.caldav_sync import _CompatAsyncDAVClient
    import caldav

    mock_sync_client = MagicMock()
    mock_sync_client.close = MagicMock()
    SyncClass = MagicMock(return_value=mock_sync_client)

    with patch.object(caldav, "DAVClient", SyncClass, create=True):
        client = _CompatAsyncDAVClient(url="https://srv/", username="u", password="p")
        async with client:
            pass

    mock_sync_client.close.assert_called_once()
    assert client._client is None


async def test_compat_aexit_with_none_client_does_not_raise():
    """_CompatAsyncDAVClient.__aexit__ is safe when _client is None (aenter failed)."""
    from custom_components.asp_parking.caldav_sync import _CompatAsyncDAVClient

    client = _CompatAsyncDAVClient(url="https://srv/", username="u", password="p")
    # Call __aexit__ without __aenter__ — _client stays None; must not raise
    await client.__aexit__(None, None, None)


async def test_compat_aexit_close_error_does_not_propagate():
    """__aexit__ suppresses close() errors so the original block exception is not replaced."""
    from custom_components.asp_parking.caldav_sync import _CompatAsyncDAVClient
    import caldav

    mock_sync_client = MagicMock()
    mock_sync_client.close = MagicMock(side_effect=OSError("socket gone"))
    SyncClass = MagicMock(return_value=mock_sync_client)

    class _OriginalError(Exception):
        pass

    with patch.object(caldav, "DAVClient", SyncClass, create=True):
        client = _CompatAsyncDAVClient(url="https://srv/", username="u", password="p")
        with pytest.raises(_OriginalError):
            async with client:
                raise _OriginalError("block failed")

    # close() raised OSError but it was suppressed; _OriginalError propagated


async def test_compat_event_delete_propagates_sync_exception():
    """_CompatEvent.delete() propagates exceptions from the underlying sync evt.delete()."""
    from custom_components.asp_parking.caldav_sync import _CompatEvent
    from caldav.lib import error as caldav_error

    sync_evt = MagicMock()
    sync_evt.delete = MagicMock(side_effect=caldav_error.NotFoundError("gone"))

    compat_evt = _CompatEvent(sync_evt)
    with pytest.raises(caldav_error.NotFoundError):
        await compat_evt.delete()


async def test_compat_principal_calendar_forwards_cal_url_kwarg():
    """_CompatPrincipal.calendar() passes cal_url as a keyword argument to the sync principal."""
    from custom_components.asp_parking.caldav_sync import _CompatCalendar, _CompatPrincipal

    mock_cal = MagicMock()
    sync_principal = MagicMock()
    sync_principal.calendar = MagicMock(return_value=mock_cal)

    compat_principal = _CompatPrincipal(sync_principal)
    result = await compat_principal.calendar("https://srv/cal/work/")

    sync_principal.calendar.assert_called_once_with(cal_url="https://srv/cal/work/")
    assert isinstance(result, _CompatCalendar)


async def test_compat_calendar_event_by_uid_wraps_result():
    """_CompatCalendar.event_by_uid() wraps the sync return value in _CompatEvent."""
    from custom_components.asp_parking.caldav_sync import _CompatCalendar, _CompatEvent

    sync_evt = MagicMock()
    sync_cal = MagicMock()
    sync_cal.event_by_uid = MagicMock(return_value=sync_evt)
    sync_cal.url = "https://srv/cal/"

    compat_cal = _CompatCalendar(sync_cal)
    result = await compat_cal.event_by_uid("abc@asp-parking.local")

    sync_cal.event_by_uid.assert_called_once_with("abc@asp-parking.local")
    assert isinstance(result, _CompatEvent)
    assert result._evt is sync_evt
