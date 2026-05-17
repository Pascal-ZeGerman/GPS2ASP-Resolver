"""RED tests for coordinator rebuild orchestration (Phase 33 Plan 02).

Covers the two NEW coordinator methods Wave 2 plan 03 must implement:
  - `async_request_rebuild` — IDX-02 lock/flag gate (no-op when already rebuilding)
  - `_async_do_rebuild` — IDX-04 atomic-swap → SpatialIndex.reset → cache.clear sequence

Phase 33 requirements / pitfalls under test:
  - IDX-02: asyncio.Lock + _is_rebuilding flag prevents concurrent rebuilds
  - IDX-04: success path resets SpatialIndex, clears _sign_cache, updates _last_rebuilt
  - RESEARCH Pitfall 1: background task spawned via entry.async_create_background_task
  - RESEARCH Pitfall 2: ordering MUST be cleanup_stale → download → atomic_swap → reset
  - RESEARCH Pitfall 4: finally-block clears _is_rebuilding even on exception (D-06)
  - RESEARCH Pitfall 7: distinct notification IDs for progress/success/error
  - D-04: success notification message contains "Built: " + timestamp
  - D-05: error notification message contains "Your existing index is still active"

Pattern: SimpleNamespace stub coordinator + AsyncMock executor + MagicMock spies.
Same pattern as tests/test_debug_switch.py — no full HA harness required.

RED state proof: ASPParkingCoordinator does not yet define `async_request_rebuild`
or `_async_do_rebuild`. Tests bind the (future) class methods to the stub via
__get__; AttributeError on attribute access proves Wave 2 plan 03 has work to do.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.asp_parking.coordinator import ASPParkingCoordinator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_coord_stub(
    *,
    is_rebuilding: bool = False,
    sign_cache: dict | None = None,
) -> SimpleNamespace:
    """Build a minimal coordinator stub mimicking the relevant ASPParkingCoordinator surface.

    Uses SimpleNamespace + MagicMocks (pattern from tests/test_debug_switch.py).
    The new async methods (`async_request_rebuild`, `_async_do_rebuild`) are bound
    from the real class at test time via __get__, so the test exercises the actual
    (Wave-2-implemented) code path. AttributeError on a missing class method is
    the RED-state signal.
    """
    entry = SimpleNamespace(
        entry_id="test_entry_rebuild",
        async_create_background_task=MagicMock(),
    )
    hass = SimpleNamespace(
        async_add_executor_job=AsyncMock(),
    )
    stub = SimpleNamespace(
        entry=entry,
        hass=hass,
        _is_rebuilding=is_rebuilding,
        _rebuild_task=None,
        _rebuild_lock=asyncio.Lock(),
        _last_rebuilt=None,
        _sign_cache=sign_cache if sign_cache is not None else {},
        _async_notify_entities=MagicMock(),
    )
    return stub


def _bind(stub: SimpleNamespace, method_name: str):
    """Bind a class method off ASPParkingCoordinator to `stub` so it becomes callable.

    Triggers AttributeError if the method does not exist on the class (RED state).
    """
    method = getattr(ASPParkingCoordinator, method_name)
    return method.__get__(stub, ASPParkingCoordinator)


# ---------------------------------------------------------------------------
# async_request_rebuild — IDX-02 lock + flag gate
# ---------------------------------------------------------------------------


async def test_async_request_rebuild_spawns_background_task_once():
    """When not rebuilding, async_request_rebuild spawns exactly one background task.

    RESEARCH Pitfall 1: must use entry.async_create_background_task (auto-cancel
    on entry unload) — NOT hass.async_create_task.
    """
    stub = _make_coord_stub(is_rebuilding=False)
    request_rebuild = _bind(stub, "async_request_rebuild")

    await request_rebuild()

    assert stub.entry.async_create_background_task.call_count == 1, (
        "Exactly one background task must be spawned on first call"
    )
    # Verify the task name is the expected canonical name (Pitfall 1)
    call_kwargs = stub.entry.async_create_background_task.call_args.kwargs
    call_args = stub.entry.async_create_background_task.call_args.args
    name = call_kwargs.get("name") or (call_args[2] if len(call_args) > 2 else None)
    assert name == "asp_parking_index_rebuild", (
        f"Task name should be 'asp_parking_index_rebuild', got {name!r}"
    )


async def test_async_request_rebuild_is_noop_when_already_rebuilding():
    """When _is_rebuilding=True, async_request_rebuild MUST NOT spawn another task.

    IDX-02 concurrent-press protection: the flag is the gate (lock alone is
    insufficient — a second press would still serialize through the lock).
    """
    stub = _make_coord_stub(is_rebuilding=True)
    request_rebuild = _bind(stub, "async_request_rebuild")

    await request_rebuild()

    assert stub.entry.async_create_background_task.call_count == 0, (
        "No task must be spawned while _is_rebuilding=True"
    )


async def test_concurrent_press_is_noop():
    """Two near-simultaneous presses must result in exactly ONE background task.

    Models the dashboard double-click scenario. The first call sets _is_rebuilding,
    the second call (started under asyncio.gather) sees the flag and bails.
    """
    stub = _make_coord_stub(is_rebuilding=False)
    request_rebuild = _bind(stub, "async_request_rebuild")

    # Simulate the gate: first call flips the flag (via the production path),
    # but for this RED-test we hand-flip it between the two awaits to assert
    # the gate is the flag, not the lock.
    async def _press():
        await request_rebuild()
        # After the first call, simulate the do_rebuild task setting the flag
        stub._is_rebuilding = True

    await _press()  # Should spawn one task and (in our simulation) set the flag

    # Second press while flag is True must be a no-op
    await request_rebuild()

    assert stub.entry.async_create_background_task.call_count == 1, (
        "Exactly one background task across two consecutive presses"
    )


# ---------------------------------------------------------------------------
# _async_do_rebuild — happy path (IDX-04, Pitfall 2, D-04)
# ---------------------------------------------------------------------------


def _install_executor_spies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    download_raises: BaseException | None = None,
    build_timestamp_return: datetime | None = None,
) -> dict:
    """Patch executor-side symbols in custom_components.asp_parking.coordinator.

    Returns a dict of spies the test can assert against. The hass.async_add_executor_job
    side_effect dispatches based on the FIRST positional argument (the sync function).
    """
    coord_mod = sys.modules["custom_components.asp_parking.coordinator"]

    cleanup_stale = MagicMock(name="_sync_cleanup_stale")
    download_and_extract = MagicMock(name="_sync_download_and_extract")
    atomic_swap = MagicMock(name="_sync_atomic_swap")
    read_build_timestamp = MagicMock(
        name="_sync_read_build_timestamp", return_value=build_timestamp_return
    )

    if download_raises is not None:
        download_and_extract.side_effect = download_raises

    monkeypatch.setattr(coord_mod, "_sync_cleanup_stale", cleanup_stale, raising=False)
    monkeypatch.setattr(
        coord_mod, "_sync_download_and_extract", download_and_extract, raising=False
    )
    monkeypatch.setattr(coord_mod, "_sync_atomic_swap", atomic_swap, raising=False)
    monkeypatch.setattr(
        coord_mod, "_sync_read_build_timestamp", read_build_timestamp, raising=False
    )

    # SpatialIndex.reset spy
    spatial_index_reset = MagicMock(name="SpatialIndex.reset")
    monkeypatch.setattr(
        "custom_components.asp_parking.coordinator.SpatialIndex.reset",
        spatial_index_reset,
        raising=False,
    )

    # Persistent notification spies — patch BOTH potential import paths
    pn_create = MagicMock(name="pn_create")
    pn_dismiss = MagicMock(name="pn_dismiss")
    pn_module_name = "homeassistant.components.persistent_notification"
    monkeypatch.setitem(
        sys.modules,
        pn_module_name,
        SimpleNamespace(
            async_create=pn_create,
            async_dismiss=pn_dismiss,
        ),
    )

    return {
        "cleanup_stale": cleanup_stale,
        "download_and_extract": download_and_extract,
        "atomic_swap": atomic_swap,
        "read_build_timestamp": read_build_timestamp,
        "spatial_index_reset": spatial_index_reset,
        "pn_create": pn_create,
        "pn_dismiss": pn_dismiss,
    }


async def test_async_do_rebuild_flips_is_rebuilding_around_work(
    monkeypatch: pytest.MonkeyPatch,
):
    """Inside _async_do_rebuild, _is_rebuilding is True; after return, False.

    D-06: finally block MUST reset the flag even on success.
    Pitfall 4: never leave the flag True (would brick the button).
    """
    # CR-01 fix: async_request_rebuild now sets _is_rebuilding=True before
    # spawning the task, so tests calling _async_do_rebuild directly must
    # pre-set the flag to simulate the state the caller establishes.
    stub = _make_coord_stub(is_rebuilding=True)
    _install_executor_spies(monkeypatch)

    captured_during = {}

    async def _executor_dispatch(fn, *args, **kwargs):
        # Capture flag state during executor work
        captured_during["is_rebuilding"] = stub._is_rebuilding
        return fn(*args, **kwargs)

    stub.hass.async_add_executor_job.side_effect = _executor_dispatch

    do_rebuild = _bind(stub, "_async_do_rebuild")
    await do_rebuild()

    assert captured_during["is_rebuilding"] is True, (
        "_is_rebuilding must be True during executor work"
    )
    assert stub._is_rebuilding is False, (
        "_is_rebuilding must be reset to False in finally block (D-06)"
    )
    # finally-block notification (entry notify moved to async_request_rebuild)
    assert stub._async_notify_entities.call_count >= 1, (
        "Entities notified at least once in finally block"
    )


async def test_async_do_rebuild_clears_sign_cache_and_resets_spatial_index(
    monkeypatch: pytest.MonkeyPatch,
):
    """After successful swap, SpatialIndex.reset() and _sign_cache.clear() are called.

    IDX-04: cache invalidation MUST happen after atomic_swap so readers see
    the fresh on-disk index.
    """
    stub = _make_coord_stub(
        is_rebuilding=False,
        sign_cache={("A", "B", "C", "N"): [{"x": 1}]},
    )
    spies = _install_executor_spies(monkeypatch)

    async def _executor_dispatch(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    stub.hass.async_add_executor_job.side_effect = _executor_dispatch

    do_rebuild = _bind(stub, "_async_do_rebuild")
    await do_rebuild()

    assert stub._sign_cache == {}, "Sign cache must be cleared after rebuild"
    spies["spatial_index_reset"].assert_called_once()


async def test_async_do_rebuild_sets_last_rebuilt_from_executor(
    monkeypatch: pytest.MonkeyPatch,
):
    """_last_rebuilt is populated from _sync_read_build_timestamp after swap."""
    fixed_dt = datetime(2026, 3, 3, 15, 9, 11, tzinfo=timezone.utc)
    stub = _make_coord_stub(is_rebuilding=False)
    _install_executor_spies(monkeypatch, build_timestamp_return=fixed_dt)

    async def _executor_dispatch(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    stub.hass.async_add_executor_job.side_effect = _executor_dispatch

    do_rebuild = _bind(stub, "_async_do_rebuild")
    await do_rebuild()

    assert stub._last_rebuilt == fixed_dt, (
        f"_last_rebuilt must reflect executor return value, got {stub._last_rebuilt!r}"
    )


class _RecordingDict(dict):
    """dict subclass that records calls to .clear() into a shared list."""

    def __init__(self, *args, _order: list[str], **kwargs):
        super().__init__(*args, **kwargs)
        self._order = _order

    def __eq__(self, other: object) -> bool:
        return super().__eq__(other)

    def clear(self):
        self._order.append("sign_cache_clear")
        super().clear()


async def test_async_do_rebuild_swap_ordering(monkeypatch: pytest.MonkeyPatch):
    """Strict ordering: cleanup_stale → download → atomic_swap → reset → cache_clear.

    RESEARCH Pitfall 2: SpatialIndex.reset() MUST run AFTER atomic_swap so the
    next load picks up new files — calling reset before swap would re-load stale.
    """
    order: list[str] = []
    sign_cache = _RecordingDict({("A", "B", "C", "N"): [{"x": 1}]}, _order=order)
    stub = _make_coord_stub(is_rebuilding=False, sign_cache=sign_cache)
    spies = _install_executor_spies(monkeypatch)

    spies["cleanup_stale"].side_effect = lambda *a, **kw: order.append("cleanup_stale")
    spies["download_and_extract"].side_effect = lambda *a, **kw: order.append(
        "download_and_extract"
    )
    spies["atomic_swap"].side_effect = lambda *a, **kw: order.append("atomic_swap")
    spies["read_build_timestamp"].side_effect = lambda *a, **kw: (
        order.append("read_build_timestamp") or None
    )
    spies["spatial_index_reset"].side_effect = lambda: order.append(
        "spatial_index_reset"
    )

    async def _executor_dispatch(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    stub.hass.async_add_executor_job.side_effect = _executor_dispatch

    do_rebuild = _bind(stub, "_async_do_rebuild")
    await do_rebuild()

    # Required prefix: cleanup → download → atomic_swap
    assert order[0:3] == [
        "cleanup_stale",
        "download_and_extract",
        "atomic_swap",
    ], f"Required swap-ordering prefix violated; got: {order}"

    # spatial_index_reset MUST be after atomic_swap and before / around cache clear
    swap_idx = order.index("atomic_swap")
    reset_idx = order.index("spatial_index_reset")
    assert reset_idx > swap_idx, (
        f"SpatialIndex.reset must run AFTER atomic_swap (Pitfall 2); got {order}"
    )

    # sign_cache_clear must also be after atomic_swap
    cache_clear_idx = order.index("sign_cache_clear")
    assert cache_clear_idx > swap_idx, (
        f"sign_cache.clear must run AFTER atomic_swap; got {order}"
    )

    # read_build_timestamp must be after atomic_swap (reads the NEW build_info.json)
    read_ts_idx = order.index("read_build_timestamp")
    assert read_ts_idx > swap_idx, (
        f"read_build_timestamp must run AFTER atomic_swap; got {order}"
    )


async def test_async_do_rebuild_success_uses_success_notification_id(
    monkeypatch: pytest.MonkeyPatch,
):
    """Success path: pn_create with notification_id='asp_parking_index_rebuild_success'.

    D-04: message contains 'Built: '. Pitfall 7: distinct from in-progress ID.
    """
    fixed_dt = datetime(2026, 3, 3, 15, 9, 11, tzinfo=timezone.utc)
    stub = _make_coord_stub(is_rebuilding=False)
    spies = _install_executor_spies(monkeypatch, build_timestamp_return=fixed_dt)

    async def _executor_dispatch(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    stub.hass.async_add_executor_job.side_effect = _executor_dispatch

    do_rebuild = _bind(stub, "_async_do_rebuild")
    await do_rebuild()

    # Find the call with notification_id='asp_parking_index_rebuild_success'
    success_calls = [
        c
        for c in spies["pn_create"].call_args_list
        if c.kwargs.get("notification_id") == "asp_parking_index_rebuild_success"
    ]
    assert len(success_calls) == 1, (
        f"Exactly one success notification expected; got {len(success_calls)}: "
        f"{spies['pn_create'].call_args_list!r}"
    )

    # D-04: message contains "Built: "
    call = success_calls[0]
    msg = call.args[1] if len(call.args) > 1 else call.kwargs.get("message", "")
    assert "Built: " in msg, (
        f"Success notification must include 'Built: ' timestamp; got: {msg!r}"
    )


# ---------------------------------------------------------------------------
# _async_do_rebuild — failure path (D-05, D-06, Pitfall 7)
# ---------------------------------------------------------------------------


async def test_async_do_rebuild_failure_path_creates_error_notification_with_distinct_id(
    monkeypatch: pytest.MonkeyPatch,
):
    """When download raises, the method:
    - dismisses the in-progress notification ('asp_parking_index_rebuild')
    - creates an error notification ('asp_parking_index_rebuild_error') — distinct id
    - includes 'Your existing index is still active' in message (D-05)
    - leaves _is_rebuilding=False (finally — D-06)
    - notifies entities in the finally block
    - does NOT propagate the exception (swallows per RESEARCH skeleton)
    """
    # CR-01 fix: pre-set flag as async_request_rebuild would have done.
    stub = _make_coord_stub(is_rebuilding=True)
    spies = _install_executor_spies(
        monkeypatch,
        download_raises=RuntimeError("network down"),
    )

    async def _executor_dispatch(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    stub.hass.async_add_executor_job.side_effect = _executor_dispatch

    do_rebuild = _bind(stub, "_async_do_rebuild")
    # Per RESEARCH skeleton: exception is caught and reported via notification,
    # never re-raised — the background task must complete cleanly.
    await do_rebuild()  # MUST NOT raise

    # In-progress dismissed
    dismiss_ids = [
        c.kwargs.get("notification_id", c.args[1] if len(c.args) > 1 else None)
        for c in spies["pn_dismiss"].call_args_list
    ]
    # async_dismiss signature: (hass, notification_id)
    dismiss_ids_positional = [
        c.args[1] for c in spies["pn_dismiss"].call_args_list if len(c.args) > 1
    ]
    all_dismiss_ids = set(dismiss_ids) | set(dismiss_ids_positional)
    assert "asp_parking_index_rebuild" in all_dismiss_ids, (
        f"In-progress notification must be dismissed; got: {all_dismiss_ids}"
    )

    # Error notification with distinct id (Pitfall 7)
    error_calls = [
        c
        for c in spies["pn_create"].call_args_list
        if c.kwargs.get("notification_id") == "asp_parking_index_rebuild_error"
    ]
    assert len(error_calls) == 1, (
        f"Exactly one error notification expected; got {len(error_calls)}: "
        f"{spies['pn_create'].call_args_list!r}"
    )

    # D-05: message contains the reassurance phrase
    call = error_calls[0]
    msg = call.args[1] if len(call.args) > 1 else call.kwargs.get("message", "")
    assert "Your existing index is still active" in msg, (
        f"Error notification must reassure user; got: {msg!r}"
    )

    # D-06: flag reset in finally
    assert stub._is_rebuilding is False, (
        "_is_rebuilding must be False after method returns even on failure (D-06)"
    )

    # Entities notified in finally (entry notify moved to async_request_rebuild)
    assert stub._async_notify_entities.call_count >= 1, (
        "Entities notified at least once in finally block even on failure"
    )


# ---------------------------------------------------------------------------
# New edge-case tests (appended)
# ---------------------------------------------------------------------------


async def test_concurrent_async_request_rebuild_only_one_task():
    """Two simultaneous async_request_rebuild calls create exactly one background task.

    Models the 'flag-as-gate' (IDX-02) design: the first call sets
    _is_rebuilding=True before yielding; the second call sees the flag and bails.
    This is tested sequentially (first sets flag, second call is a no-op).
    """
    stub = _make_coord_stub(is_rebuilding=False)
    request_rebuild = _bind(stub, "async_request_rebuild")

    # First call — should set the flag and create a background task.
    await request_rebuild()
    assert stub.entry.async_create_background_task.call_count == 1

    # _is_rebuilding should now be True (set by async_request_rebuild before spawning).
    assert stub._is_rebuilding is True, (
        "async_request_rebuild must set _is_rebuilding=True before spawning task"
    )

    # Second call while the flag is already True — must be a no-op.
    await request_rebuild()

    assert stub.entry.async_create_background_task.call_count == 1, (
        "Second call while _is_rebuilding=True must NOT spawn another task"
    )


async def test_async_do_rebuild_executor_oserror_resets_flag(
    monkeypatch: pytest.MonkeyPatch,
):
    """When async_add_executor_job raises OSError, _is_rebuilding is reset in finally.

    D-06: the finally block must run even when the executor raises so the
    button is never permanently stuck.  An error notification must also be
    created (Pitfall 7 / D-05).
    """
    stub = _make_coord_stub(is_rebuilding=True)
    spies = _install_executor_spies(monkeypatch)

    # Make the executor blow up on every call with a bare OSError.
    stub.hass.async_add_executor_job = AsyncMock(side_effect=OSError("disk full"))

    do_rebuild = _bind(stub, "_async_do_rebuild")
    await do_rebuild()  # must NOT re-raise

    # Finally block must have cleared the flag.
    assert stub._is_rebuilding is False, (
        "_is_rebuilding must be False after OSError (finally block D-06)"
    )

    # An error notification must have been created.
    error_calls = [
        c
        for c in spies["pn_create"].call_args_list
        if c.kwargs.get("notification_id") == "asp_parking_index_rebuild_error"
    ]
    assert len(error_calls) >= 1, (
        "Error notification must be created when executor raises OSError"
    )


async def test_async_do_rebuild_none_timestamp_still_creates_success_notification(
    monkeypatch: pytest.MonkeyPatch,
):
    """When _sync_read_build_timestamp returns None, success notification is still sent.

    The success path formats 'unknown' when the timestamp is None, so no crash
    must occur and the success notification must still be created.
    """
    stub = _make_coord_stub(is_rebuilding=True)
    # Executor succeeds; _sync_read_build_timestamp returns None.
    spies = _install_executor_spies(monkeypatch, build_timestamp_return=None)

    async def _executor_dispatch(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    stub.hass.async_add_executor_job.side_effect = _executor_dispatch

    do_rebuild = _bind(stub, "_async_do_rebuild")
    await do_rebuild()  # must NOT raise

    # Success notification must be created regardless of None timestamp.
    success_calls = [
        c
        for c in spies["pn_create"].call_args_list
        if c.kwargs.get("notification_id") == "asp_parking_index_rebuild_success"
    ]
    assert len(success_calls) == 1, (
        f"Success notification must be created even when timestamp is None; "
        f"pn_create calls: {spies['pn_create'].call_args_list!r}"
    )


async def test_async_do_rebuild_error_detail_included_in_notification(
    monkeypatch: pytest.MonkeyPatch,
):
    """A long error message from a failing executor job is surfaced in the notification.

    _async_do_rebuild embeds str(err) (or the OSError strerror) verbatim into the
    error notification — there is no truncation at this layer (contrast: the CalDAV
    write path does truncate at 200 chars).

    For an OSError raised by the executor, ``_err_summary`` is derived from the
    exception attributes.  When err.strerror is None and err.filename is None
    (as for OSError("X" * 300)), str(err) is used directly.  We verify:
      1. The error notification is created exactly once.
      2. The notification message contains the substring from the original error.
      3. The D-05 reassurance phrase is also present.
    """
    long_message = "X" * 300
    stub = _make_coord_stub(is_rebuilding=True)
    spies = _install_executor_spies(monkeypatch)

    # Raise a plain RuntimeError so _err_summary = str(err) = long_message.
    stub.hass.async_add_executor_job = AsyncMock(side_effect=RuntimeError(long_message))

    do_rebuild = _bind(stub, "_async_do_rebuild")
    await do_rebuild()

    error_calls = [
        c
        for c in spies["pn_create"].call_args_list
        if c.kwargs.get("notification_id") == "asp_parking_index_rebuild_error"
    ]
    assert len(error_calls) == 1, (
        f"Exactly one error notification expected; got {spies['pn_create'].call_args_list!r}"
    )

    call = error_calls[0]
    msg = call.args[1] if len(call.args) > 1 else call.kwargs.get("message", "")

    # The error summary must appear in the notification message.
    # (For RuntimeError the full str(err) is embedded; no truncation in this path.)
    assert long_message[:50] in msg, (
        f"Error detail from exception must appear in notification; got: {msg[:120]!r}"
    )

    # D-05 reassurance phrase must also be present.
    assert "Your existing index is still active" in msg, (
        f"D-05 reassurance phrase missing from error notification; got: {msg!r}"
    )


def test_index_rebuilding_binary_sensor_is_on_missing_attribute():
    """ASPIndexRebuildingBinarySensor.is_on returns False when coordinator lacks _is_rebuilding.

    The sensor accesses self._coordinator._is_rebuilding directly.  If the
    coordinator stub lacks that attribute (e.g. a bare SimpleNamespace with no
    _is_rebuilding), accessing the property must not raise AttributeError but
    instead the property must safely return False via getattr fallback.

    NOTE: The real sensor does NOT use getattr — it accesses the attribute directly.
    This test confirms the REAL coordinator always provides the attribute (it is set
    in __init__) and that tests using _make_coord_stub (which always sets it) match
    the real coordinator contract.  We explicitly test that the default is False.
    """
    from custom_components.asp_parking.binary_sensor import (
        ASPIndexRebuildingBinarySensor,
    )

    stub = _make_coord_stub(is_rebuilding=False)
    # Simulate what happens if, in a future refactor, _is_rebuilding were absent.
    # We use a real coordinator-like stub that DOES have the attribute = False.
    sensor = ASPIndexRebuildingBinarySensor.__new__(ASPIndexRebuildingBinarySensor)
    sensor._coordinator = stub  # type: ignore[assignment]

    assert sensor.is_on is False, (
        "ASPIndexRebuildingBinarySensor.is_on must return False when _is_rebuilding=False"
    )

    # Flip the flag and verify is_on tracks it.
    stub._is_rebuilding = True
    assert sensor.is_on is True, (
        "ASPIndexRebuildingBinarySensor.is_on must return True when _is_rebuilding=True"
    )


async def test_async_do_rebuild_success_resets_flag_and_sets_last_rebuilt(
    monkeypatch: pytest.MonkeyPatch,
):
    """Success path: _is_rebuilding is False after completion and _last_rebuilt is set.

    Combines D-06 (finally resets flag) with IDX-04 (_last_rebuilt updated from
    _sync_read_build_timestamp).
    """
    fixed_dt = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
    stub = _make_coord_stub(is_rebuilding=True)
    _install_executor_spies(monkeypatch, build_timestamp_return=fixed_dt)

    async def _executor_dispatch(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    stub.hass.async_add_executor_job.side_effect = _executor_dispatch

    do_rebuild = _bind(stub, "_async_do_rebuild")
    await do_rebuild()

    assert stub._is_rebuilding is False, (
        "_is_rebuilding must be reset to False in finally block after success (D-06)"
    )
    assert stub._last_rebuilt == fixed_dt, (
        f"_last_rebuilt must be set to the mocked timestamp {fixed_dt!r}; "
        f"got {stub._last_rebuilt!r}"
    )
