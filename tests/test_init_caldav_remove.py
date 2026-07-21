"""RED tests for async_remove_entry CalDAV teardown (CALDAV-07).

Verifies the new async_remove_entry function Plan 05 must add to
custom_components/asp_parking/__init__.py:
  - Skip when CONF_CALDAV_URL absent (D-02)
  - On removal with stored UID, call caldav_sync.delete_event AND
    remove the Store file (best-effort cleanup)
  - On Store empty (no stored UID), no delete attempt and no exception
    (Pitfall 5 — graceful handling of fresh / never-written entries)
  - On caldav_sync.delete_event failure, no exception propagates AND
    the Store is still removed (T-34-04 mitigation — best-effort delete;
    we still need to clean up local state at teardown).

Pattern: PHACC's `hass_storage` fixture pre-seeds the Store; AsyncMock
patches caldav_sync.delete_event so no real network calls are made.

RED state proof: async_remove_entry is not yet defined in
custom_components/asp_parking/__init__.py — the import at the top of
each test body raises ImportError until Plan 05 lands.

Storage-key contract: f'{DOMAIN}_caldav_{entry.entry_id}' — locked here
so Plan 04 / Plan 05 cannot diverge.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.asp_parking.const import (
    CONF_DEVICE_TRACKER,
    DOMAIN,
)

# Phase 34 const names — Plan 03 adds them to const.py. Until then,
# use the literal strings locked by the plan's <interfaces>.
CONF_CALDAV_URL = "caldav_url"
CONF_CALDAV_USERNAME = "caldav_username"
CONF_CALDAV_PASSWORD = "caldav_password"
CONF_CALDAV_CALENDAR = "caldav_calendar"

pytestmark = pytest.mark.ha_integration


def _make_entry(hass, options: dict | None = None):
    """Create + add a MockConfigEntry for the asp_parking integration."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={CONF_DEVICE_TRACKER: "device_tracker.car"},
        options=options or {},
        title="ASP Parking Monitor",
    )
    entry.add_to_hass(hass)
    return entry


def _full_caldav_options() -> dict:
    return {
        CONF_CALDAV_URL: "https://example.com/dav/",
        CONF_CALDAV_USERNAME: "u",
        CONF_CALDAV_PASSWORD: "p",
        CONF_CALDAV_CALENDAR: "https://example.com/dav/cal/",
    }


def _require_async_remove_entry():
    """Skip-fail when async_remove_entry is not yet defined (Plan 05 not landed)."""
    try:
        from custom_components.asp_parking import async_remove_entry  # type: ignore[attr-defined]

        return async_remove_entry
    except ImportError:
        pytest.fail(
            "async_remove_entry not importable — Plan 05 has not yet added it to "
            "custom_components/asp_parking/__init__.py"
        )
        return None  # unreachable: pytest.fail() always raises


# ---------------------------------------------------------------------------
# CALDAV-07 — happy path: delete event then remove Store
# ---------------------------------------------------------------------------


async def test_async_remove_entry_deletes_event_and_store_when_uid_present(
    hass, enable_custom_integrations
):
    """CALDAV-07 happy path: stored UID → caldav_sync.delete_event called with that UID;
    Store.async_remove() called afterwards.

    Mocks Store.async_load() directly rather than using hass_storage pre-seeding so
    the test is robust across PHACC versions (hass_storage format changed in 0.13.333).
    """
    async_remove_entry = _require_async_remove_entry()

    entry = _make_entry(hass, options=_full_caldav_options())

    mock_store = MagicMock()
    mock_store.async_load = AsyncMock(return_value={"uid": "abc123@asp-parking.local"})
    mock_store.async_remove = AsyncMock()

    with (
        patch("homeassistant.helpers.storage.Store", return_value=mock_store),
        patch(
            "custom_components.asp_parking.caldav_sync.delete_event",
            new_callable=AsyncMock,
        ) as mock_delete,
    ):
        await async_remove_entry(hass, entry)

    mock_delete.assert_awaited_once()
    call_kwargs = mock_delete.await_args.kwargs
    # The delete call MUST use the stored UID (not derive a new one)
    assert call_kwargs.get("uid") == "abc123@asp-parking.local", (
        f"delete_event must be called with the stored UID; got {call_kwargs}"
    )
    # Store.async_remove() MUST be called to clean up persisted state
    mock_store.async_remove.assert_awaited_once()


# ---------------------------------------------------------------------------
# D-02 — no-op when CalDAV not configured
# ---------------------------------------------------------------------------


async def test_async_remove_entry_noop_when_caldav_url_absent(
    hass, enable_custom_integrations, hass_storage
):
    """D-02: when CONF_CALDAV_URL is absent, the entire CalDAV teardown branch
    is a no-op — no Store I/O, no delete attempt, no exception."""
    async_remove_entry = _require_async_remove_entry()

    entry = _make_entry(hass, options={})  # NO CalDAV options at all

    with patch(
        "custom_components.asp_parking.caldav_sync.delete_event",
        new_callable=AsyncMock,
    ) as mock_delete:
        await async_remove_entry(hass, entry)

    mock_delete.assert_not_called()


# ---------------------------------------------------------------------------
# Pitfall 5 — graceful no-op when Store has no UID
# ---------------------------------------------------------------------------


async def test_async_remove_entry_noop_when_no_stored_uid(
    hass, enable_custom_integrations, hass_storage
):
    """CALDAV-07 edge / Pitfall 5: CalDAV is configured but the Store has no
    stored UID (fresh / never-written entry). Must NOT call delete_event
    and MUST NOT raise."""
    async_remove_entry = _require_async_remove_entry()

    entry = _make_entry(hass, options=_full_caldav_options())
    # Do NOT pre-seed hass_storage — Store is empty

    with patch(
        "custom_components.asp_parking.caldav_sync.delete_event",
        new_callable=AsyncMock,
    ) as mock_delete:
        # Must NOT raise
        await async_remove_entry(hass, entry)

    mock_delete.assert_not_called()


# ---------------------------------------------------------------------------
# CALDAV-07 robustness (T-34-04 mitigation) — Store cleanup is best-effort
# ---------------------------------------------------------------------------


async def test_async_remove_entry_continues_when_delete_fails(
    hass, enable_custom_integrations
):
    """CALDAV-07 robustness: when caldav_sync.delete_event raises
    RuntimeError('server unreachable'), the exception is caught + logged,
    no exception propagates from async_remove_entry, AND Store.async_remove()
    is still called (best-effort cleanup — RESEARCH Pattern 6 lines 619-624).

    Mocks Store.async_load() directly rather than using hass_storage pre-seeding so
    the test is robust across PHACC versions (hass_storage format changed in 0.13.333).
    """
    async_remove_entry = _require_async_remove_entry()

    entry = _make_entry(hass, options=_full_caldav_options())

    mock_store = MagicMock()
    mock_store.async_load = AsyncMock(return_value={"uid": "abc123@asp-parking.local"})
    mock_store.async_remove = AsyncMock()

    with (
        patch("homeassistant.helpers.storage.Store", return_value=mock_store),
        patch(
            "custom_components.asp_parking.caldav_sync.delete_event",
            new_callable=AsyncMock,
            side_effect=RuntimeError("server unreachable"),
        ),
    ):
        # Must NOT raise — failure is caught + logged
        await async_remove_entry(hass, entry)

    # Best-effort cleanup: Store.async_remove() called even on delete failure
    mock_store.async_remove.assert_awaited_once()


# ---------------------------------------------------------------------------
# Decision #2 — strip-on-disable: GPS stripped from live event when the user
# turns off caldav_include_location while CalDAV sync stays configured
# ---------------------------------------------------------------------------


async def test_async_options_updated_strips_location_when_include_location_disabled(
    hass, enable_custom_integrations
):
    """When include_location flips True -> False (CalDAV URL still set),
    _async_options_updated rewrites the live event with lat=None, lon=None
    BEFORE reload — even when the coordinator's cached last_lat is None
    (quiet tracker; options reload has not yet reset it)."""
    from types import SimpleNamespace

    from custom_components.asp_parking import (
        _CALDAV_OPTIONS_CACHE_KEY_TPL,
        _async_options_updated,
    )
    from custom_components.asp_parking.const import CONF_CALDAV_INCLUDE_LOCATION

    new_options = {**_full_caldav_options(), CONF_CALDAV_INCLUDE_LOCATION: False}
    entry = _make_entry(hass, options=new_options)

    stub_schedule = SimpleNamespace(next_window=SimpleNamespace(start_datetime=None))
    stub_coordinator = SimpleNamespace(
        _caldav_uid="uid@asp-parking.local",
        data=SimpleNamespace(schedule_result=stub_schedule, last_lat=None),
    )
    entry.runtime_data = stub_coordinator

    old_options = {**_full_caldav_options(), CONF_CALDAV_INCLUDE_LOCATION: True}
    cache_key = _CALDAV_OPTIONS_CACHE_KEY_TPL.format(entry_id=entry.entry_id)
    hass.data[cache_key] = old_options

    with (
        patch(
            "custom_components.asp_parking.caldav_sync.write_or_update_event",
            new_callable=AsyncMock,
            return_value="uid@asp-parking.local",
        ) as mock_write,
        patch.object(hass.config_entries, "async_reload", new=AsyncMock()),
    ):
        await _async_options_updated(hass, entry)

    mock_write.assert_awaited_once()
    call_kwargs = mock_write.await_args.kwargs
    assert call_kwargs.get("stored_uid") == "uid@asp-parking.local"
    assert call_kwargs.get("lat") is None
    assert call_kwargs.get("lon") is None
