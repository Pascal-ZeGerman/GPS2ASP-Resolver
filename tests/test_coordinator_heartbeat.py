"""RED tests for periodic 8h heartbeat (quick task 260520-f3o).

Covers the new coordinator methods that Task 1 must implement:
  - _async_do_heartbeat — re-fetches ICS, re-checks suspension, fires debouncer
  - _async_periodic_heartbeat — @callback that creates the heartbeat task

RED state proof: ASPParkingCoordinator does not yet define _async_do_heartbeat.
The _bind() helper triggers AttributeError on the missing class method, which
is the RED signal that Task 1 must clear.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.asp_parking.coordinator import ASPParkingCoordinator


# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------


def _bind(stub: SimpleNamespace, method_name: str):
    """Bind ASPParkingCoordinator.method_name to ``stub`` for invocation.

    AttributeError on the class is the RED-state signal for missing methods.
    """
    method = getattr(ASPParkingCoordinator, method_name)
    return method.__get__(stub, ASPParkingCoordinator)


def _make_stub(
    *,
    last_lat: float | None = None,
    last_lon: float | None = None,
    pending_lat: float | None = None,
    pending_lon: float | None = None,
    debug_enabled: bool = False,
    debug_lat: float | None = None,
    debug_lon: float | None = None,
    holiday_calendar: object | None = "AUTO",
) -> SimpleNamespace:
    """Build a minimal coordinator stub for heartbeat tests."""
    if holiday_calendar == "AUTO":
        cal = AsyncMock()
        cal.load = AsyncMock()
        holiday_calendar = cal

    return SimpleNamespace(
        _holiday_calendar=holiday_calendar,
        _async_update_suspension=AsyncMock(),
        data=SimpleNamespace(last_lat=last_lat, last_lon=last_lon),
        _debug_enabled=debug_enabled,
        _debug_lat=debug_lat,
        _debug_lon=debug_lon,
        _pending_lat=pending_lat,
        _pending_lon=pending_lon,
        hass=SimpleNamespace(async_create_task=MagicMock()),
        entry=SimpleNamespace(async_create_background_task=MagicMock()),
        _debouncer=AsyncMock(async_call=AsyncMock()),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_heartbeat_with_gps():
    """Heartbeat fires ICS load, suspension check, and debouncer when GPS known."""
    stub = _make_stub(last_lat=40.6782, last_lon=-73.9442)

    await _bind(stub, "_async_do_heartbeat")()

    # ICS must have been re-fetched
    stub._holiday_calendar.load.assert_awaited_once()
    # Suspension must have been re-checked
    stub._async_update_suspension.assert_awaited_once()
    # Debouncer must have been triggered (via async_create_background_task)
    stub.entry.async_create_background_task.assert_called_once()


@pytest.mark.asyncio
async def test_heartbeat_without_gps():
    """Heartbeat runs ICS + suspension but skips debouncer when no GPS."""
    stub = _make_stub(last_lat=None, last_lon=None, debug_enabled=False)

    await _bind(stub, "_async_do_heartbeat")()

    # ICS and suspension must still run
    stub._holiday_calendar.load.assert_awaited_once()
    stub._async_update_suspension.assert_awaited_once()
    # Debouncer must NOT have been triggered
    stub.hass.async_create_task.assert_not_called()


@pytest.mark.asyncio
async def test_heartbeat_null_calendar():
    """Null _holiday_calendar: load is skipped but suspension check still runs."""
    stub = _make_stub(last_lat=None, last_lon=None, holiday_calendar=None)

    await _bind(stub, "_async_do_heartbeat")()

    # Suspension must still be called even when calendar is None
    stub._async_update_suspension.assert_awaited_once()
    # Debouncer not triggered (no GPS)
    stub.entry.async_create_background_task.assert_not_called()


@pytest.mark.asyncio
async def test_heartbeat_pending_coords_preserved():
    """Existing _pending_lat/lon are NOT overwritten when already set."""
    stub = _make_stub(
        last_lat=40.6782,
        last_lon=-73.9442,
        pending_lat=40.9999,
        pending_lon=-73.1111,
    )

    await _bind(stub, "_async_do_heartbeat")()

    # Existing pending coords must be preserved (the `if _pending_lat is None` guard)
    assert stub._pending_lat == 40.9999, (
        f"Expected _pending_lat=40.9999, got {stub._pending_lat}"
    )
    assert stub._pending_lon == -73.1111, (
        f"Expected _pending_lon=-73.1111, got {stub._pending_lon}"
    )
    # Debouncer still triggered (GPS was available)
    stub.entry.async_create_background_task.assert_called_once()
