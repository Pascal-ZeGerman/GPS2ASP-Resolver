"""Cross-cutting integration edge cases spanning coordinator rebuild + CalDAV paths."""

from __future__ import annotations

import asyncio
import sys

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.asp_parking.coordinator import ASPParkingCoordinator


# ---------------------------------------------------------------------------
# Helpers (mirrors test_coordinator_rebuild.py pattern)
# ---------------------------------------------------------------------------


def _make_combined_stub(
    *,
    is_rebuilding: bool = False,
    caldav_uid: str | None = None,
    caldav_store_present: bool = False,
    suspension_is_suspended: bool = False,
    sign_cache: dict | None = None,
) -> SimpleNamespace:
    """Build a stub coordinator with BOTH rebuild and CalDAV fields.

    Needed for cross-cutting tests that exercise the interaction between the two
    subsystems. Follows the same SimpleNamespace + MagicMock pattern as
    test_coordinator_rebuild.py::_make_coord_stub but adds CalDAV surface.
    """
    entry = SimpleNamespace(
        entry_id="test_entry_integration",
        async_create_background_task=MagicMock(),
        options={},
    )
    hass = SimpleNamespace(
        async_add_executor_job=AsyncMock(),
    )

    # Minimal suspension_state object (coordinator reads .is_suspended from it).
    from custom_components.asp_parking.gps2asp.suspension import SuspensionInfo

    suspension_state = SuspensionInfo(
        is_suspended=suspension_is_suspended, reason=None, source="none"
    )

    # Minimal data container with suspension_state attr.
    data = SimpleNamespace(suspension_state=suspension_state)

    stub = SimpleNamespace(
        entry=entry,
        hass=hass,
        data=data,
        # Rebuild fields
        _is_rebuilding=is_rebuilding,
        _rebuild_task=None,
        _rebuild_lock=asyncio.Lock(),
        _last_rebuilt=None,
        _sign_cache=sign_cache if sign_cache is not None else {},
        _async_notify_entities=MagicMock(),
        # CalDAV fields
        _caldav_uid=caldav_uid,
        _caldav_store=object() if caldav_store_present else None,  # truthy sentinel
        _caldav_lock=asyncio.Lock(),
        _caldav_write_task=None,
        _caldav_delete_task=None,
        _caldav_write_error_notified=False,
        _caldav_delete_error_notified=False,
        _last_suspension_state=suspension_is_suspended,
    )
    return stub


def _bind(stub: SimpleNamespace, method_name: str):
    """Bind a class method off ASPParkingCoordinator to `stub`."""
    method = getattr(ASPParkingCoordinator, method_name)
    return method.__get__(stub, ASPParkingCoordinator)


def _install_pn_mock(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Install persistent-notification module mock; return pn_create/pn_dismiss spies."""
    pn_create = MagicMock(name="pn_create")
    pn_dismiss = MagicMock(name="pn_dismiss")
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.persistent_notification",
        SimpleNamespace(async_create=pn_create, async_dismiss=pn_dismiss),
    )
    return {"pn_create": pn_create, "pn_dismiss": pn_dismiss}


def _install_executor_spies(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Patch index_io sync helpers in coordinator module to no-ops."""
    coord_mod = sys.modules["custom_components.asp_parking.coordinator"]

    cleanup_stale = MagicMock(name="_sync_cleanup_stale")
    download_and_extract = MagicMock(name="_sync_download_and_extract")
    atomic_swap = MagicMock(name="_sync_atomic_swap")
    read_build_timestamp = MagicMock(name="_sync_read_build_timestamp", return_value=None)

    monkeypatch.setattr(coord_mod, "_sync_cleanup_stale", cleanup_stale, raising=False)
    monkeypatch.setattr(
        coord_mod, "_sync_download_and_extract", download_and_extract, raising=False
    )
    monkeypatch.setattr(coord_mod, "_sync_atomic_swap", atomic_swap, raising=False)
    monkeypatch.setattr(
        coord_mod, "_sync_read_build_timestamp", read_build_timestamp, raising=False
    )
    monkeypatch.setattr(
        "custom_components.asp_parking.coordinator.SpatialIndex.reset",
        MagicMock(),
        raising=False,
    )
    pn_create = MagicMock(name="pn_create")
    pn_dismiss = MagicMock(name="pn_dismiss")
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.persistent_notification",
        SimpleNamespace(async_create=pn_create, async_dismiss=pn_dismiss),
    )
    return {
        "cleanup_stale": cleanup_stale,
        "download_and_extract": download_and_extract,
        "atomic_swap": atomic_swap,
        "read_build_timestamp": read_build_timestamp,
        "pn_create": pn_create,
        "pn_dismiss": pn_dismiss,
    }


# ---------------------------------------------------------------------------
# Test 1: Rebuild during active CalDAV write — no deadlock, no interference
# ---------------------------------------------------------------------------


async def test_rebuild_does_not_wait_for_caldav_lock():
    """async_request_rebuild completes without waiting for a held _caldav_lock.

    The rebuild and CalDAV write subsystems use SEPARATE locks (_rebuild_lock
    and _caldav_lock). This test acquires _caldav_lock to simulate an
    in-progress CalDAV write, then calls async_request_rebuild and asserts it
    spawns the background task without deadlocking.

    If the two paths ever shared a single lock, this test would hang forever.
    """
    stub = _make_combined_stub(is_rebuilding=False)
    request_rebuild = _bind(stub, "async_request_rebuild")

    # Hold the CalDAV lock (simulating an in-progress CalDAV write task).
    await stub._caldav_lock.acquire()
    try:
        # async_request_rebuild must not touch _caldav_lock — it should complete.
        await asyncio.wait_for(request_rebuild(), timeout=1.0)
    finally:
        stub._caldav_lock.release()

    # Exactly one background rebuild task must have been spawned.
    assert stub.entry.async_create_background_task.call_count == 1, (
        "async_request_rebuild must spawn background task even when _caldav_lock is held"
    )


# ---------------------------------------------------------------------------
# Test 2: CancelledError inside _async_do_rebuild resets _is_rebuilding
# ---------------------------------------------------------------------------


async def test_async_do_rebuild_cancelled_error_resets_is_rebuilding(
    monkeypatch: pytest.MonkeyPatch,
):
    """CancelledError inside _async_do_rebuild causes _is_rebuilding to be reset.

    CancelledError is a BaseException, NOT an Exception, so the bare
    ``except Exception`` block in _async_do_rebuild does NOT catch it.
    However, the ``finally`` block always runs, which resets _is_rebuilding=False.

    This test verifies the finally-block guarantee survives task cancellation,
    matching the HA lifecycle: when the config entry is unloaded, HA cancels all
    background tasks created via entry.async_create_background_task.
    """
    stub = _make_combined_stub(is_rebuilding=True)
    _install_executor_spies(monkeypatch)

    # Make the first executor call raise CancelledError to simulate task cancellation.
    stub.hass.async_add_executor_job = AsyncMock(
        side_effect=asyncio.CancelledError("task cancelled")
    )

    do_rebuild = _bind(stub, "_async_do_rebuild")

    # CancelledError IS re-raised (it's a BaseException); catch it in the test.
    with pytest.raises(asyncio.CancelledError):
        await do_rebuild()

    # Despite the CancelledError, the finally block must have reset the flag.
    assert stub._is_rebuilding is False, (
        "_is_rebuilding must be reset to False in finally block even on CancelledError"
    )

    # Entities must have been notified in the finally block.
    assert stub._async_notify_entities.call_count >= 1, (
        "Entities must be notified in finally block even on CancelledError"
    )


# ---------------------------------------------------------------------------
# Test 3: CalDAV hook not called when pipeline raises NoSegmentFoundError
# ---------------------------------------------------------------------------


async def test_caldav_hook_not_called_on_pipeline_nosegmentfounderror():
    """_async_caldav_hook_after_resolve is NOT invoked when the pipeline raises.

    The coordinator's _async_resolve_pipeline catches NoSegmentFoundError and
    sets special_state='no_street_match' WITHOUT calling the CalDAV hook.
    This test verifies that a resolve-pipeline failure does not trigger a
    spurious CalDAV write or delete.

    Design note: we spy on the METHOD on the stub by replacing it with an
    AsyncMock — if the production code calls self._async_caldav_hook_after_resolve
    the mock is invoked; if it does not, the mock has call_count=0.
    """
    from custom_components.asp_parking.gps2asp.resolver.exceptions import (
        NoSegmentFoundError,
    )

    stub = _make_combined_stub(
        is_rebuilding=False,
        caldav_store_present=True,
        caldav_uid="some-uid",
        suspension_is_suspended=False,
    )

    # _async_resolve_pipeline mutates self.data — ensure all accessed attrs exist.
    stub.data.special_state = None
    stub.data.last_lat = None
    stub.data.last_lon = None
    stub.data.soda_level = 0
    stub.data.borough = None
    stub.data.distance_ft = None
    stub.data.street_width_ft = None
    stub.data.segment_id = None
    stub.data.last_error = None
    stub.data.last_error_time = None

    # Install a spy on the CalDAV hook.
    caldav_hook_spy = AsyncMock(name="_async_caldav_hook_after_resolve")
    stub._async_caldav_hook_after_resolve = caldav_hook_spy

    # Stub out everything _async_resolve_pipeline needs:
    stub._pending_lat = 40.6782
    stub._pending_lon = -73.9442
    stub._debug_enabled = False
    stub._debug_lat = None
    stub._debug_lon = None
    stub._notify_service = ""
    stub._debug_suppress_notifications = False

    # Patch the `resolve` coroutine used inside _async_resolve_pipeline so it
    # raises NoSegmentFoundError (simulating GPS coordinates with no street match).
    # NoSegmentFoundError requires (x, y, max_distance_ft) positional args.
    coord_mod = sys.modules["custom_components.asp_parking.coordinator"]
    original_resolve = getattr(coord_mod, "resolve", None)

    async def _fake_resolve(lat, lon):
        raise NoSegmentFoundError(x=1.0, y=2.0, max_distance_ft=164.0)

    coord_mod.resolve = _fake_resolve
    try:
        resolve_pipeline = _bind(stub, "_async_resolve_pipeline")
        await resolve_pipeline()
    finally:
        # Restore original to avoid polluting other tests.
        if original_resolve is not None:
            coord_mod.resolve = original_resolve
        else:
            del coord_mod.resolve

    # The CalDAV hook must NOT have been called.
    caldav_hook_spy.assert_not_called()

    # The special_state must reflect the pipeline failure.
    assert stub.data.special_state == "no_street_match", (
        f"special_state must be 'no_street_match' after NoSegmentFoundError; "
        f"got {stub.data.special_state!r}"
    )
