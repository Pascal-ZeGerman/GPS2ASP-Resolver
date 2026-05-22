"""RED tests for coordinator stale-detection lifecycle (Phase 38 Plan 03 / IDX-07 + IDX-05).

Covers the NEW coordinator surface added by Plan 03:

  - ``_async_check_stale_and_rebuild(self, now: datetime | None = None) -> None``
        Shared startup + daily-interval helper.  Skips when ``_last_rebuilt`` is
        None (first install).  Returns silently when ``age <= 60d`` (fresh).
        Skips rebuild when ``_is_rebuilding`` is True.  Otherwise posts a
        persistent notification (id ``"asp_parking_index_stale"``) AND awaits
        ``async_request_rebuild(triggered_by="stale_check")``.  Always writes
        ``last_stale_check`` to the index-stale Store in a ``finally`` block.

  - ``_async_init_stale_lifecycle(self) -> None``
        Called from ``async_start`` after ``_last_rebuilt`` is populated.
        Initialises the ``asp_parking_index_stale`` Store with a FIXED key
        (NOT per-entry-id per SPEC §Requirement 3), hydrates
        ``_last_button_press`` + ``_last_stale_check`` from disk, spawns the
        startup fire-and-forget background task, and registers the daily
        24h ``async_track_time_interval`` listener (unsub appended to
        ``self._listeners``).

D-01 / D-02 / Pitfall 12 guards:
  - The helper MUST accept BOTH zero args (startup background task) AND a
    single positional ``datetime`` (``async_track_time_interval`` callback).
  - The startup background task and the daily interval call the SAME helper.

Pattern: SimpleNamespace + ``_bind`` (mirror tests/test_coordinator_path_selection.py
+ tests/test_coordinator_rebuild.py).  Persistent-notification module mocked
via ``sys.modules`` patch (matches existing test pattern).

RED state proof: ``_async_check_stale_and_rebuild`` and
``_async_init_stale_lifecycle`` do not yet exist on ``ASPParkingCoordinator``.
``_bind`` raises ``AttributeError`` during collection / first call until
Task 2 (GREEN) lands the implementation.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.asp_parking.coordinator import ASPParkingCoordinator
from custom_components.asp_parking.const import (
    STALE_CHECK_INTERVAL_HOURS,
    STALE_INDEX_DAYS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_coord_stub_stale(
    *,
    last_rebuilt: datetime | None = None,
    is_rebuilding: bool = False,
    last_button_press_iso: str | None = None,
    last_stale_check_iso: str | None = None,
    store_load_value=None,
) -> SimpleNamespace:
    """Build a stub coordinator mirroring tests/test_coordinator_path_selection.py.

    Adds Plan 03 attributes:
      _index_stale_store with async_load AsyncMock returning a Store-shaped
        dict (or whatever ``store_load_value`` overrides to) + async_save
        AsyncMock spy.
      async_request_rebuild as an AsyncMock so tests can assert call args
        without actually spawning a real rebuild.

    The Store's ``async_load`` return value is computed as follows:
      - If ``store_load_value`` is given (any non-sentinel), use it as-is.
      - Otherwise, if either ``last_button_press_iso`` or
        ``last_stale_check_iso`` is truthy, return a dict containing those
        two keys (mirroring the production Store payload schema).
      - Otherwise return ``None`` (matches a never-written Store).
    """
    entry = SimpleNamespace(
        entry_id="test_entry_38_03",
        async_create_background_task=MagicMock(),
    )
    hass = SimpleNamespace(async_add_executor_job=AsyncMock())

    # Compute the Store payload that async_load returns.
    _sentinel = object()
    if store_load_value is not _sentinel and store_load_value is not None:
        load_value = store_load_value
    elif last_button_press_iso or last_stale_check_iso:
        load_value = {
            "last_button_press": last_button_press_iso,
            "last_stale_check": last_stale_check_iso,
        }
    else:
        load_value = None

    index_stale_store = SimpleNamespace(
        async_load=AsyncMock(return_value=load_value),
        async_save=AsyncMock(),
    )

    stub = SimpleNamespace(
        entry=entry,
        hass=hass,
        _is_rebuilding=is_rebuilding,
        _rebuild_task=None,
        _rebuild_lock=asyncio.Lock(),
        _last_rebuilt=last_rebuilt,
        _sign_cache={},
        _async_notify_entities=MagicMock(),
        # Plan 02 (IDX-05) attributes
        _index_stale_store=index_stale_store,
        _last_button_press=None,
        _last_stale_check=None,
        _remote_age_cache=None,
        # AsyncMock placeholder so tests can verify call args without spawning rebuilds.
        async_request_rebuild=AsyncMock(),
        # `_listeners` is populated by _async_init_stale_lifecycle when invoked.
        _listeners=[],
    )
    return stub


def _bind(stub: SimpleNamespace, method_name: str):
    """Bind ASPParkingCoordinator.method_name onto ``stub``.

    AttributeError on a missing class method is the RED-state signal — both
    ``_async_check_stale_and_rebuild`` and ``_async_init_stale_lifecycle``
    raise here until Task 2 (GREEN) lands.
    """
    method = getattr(ASPParkingCoordinator, method_name)
    return method.__get__(stub, ASPParkingCoordinator)


@pytest.fixture
def pn_module(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Install a stub homeassistant.components.persistent_notification module.

    The fixture returns a SimpleNamespace exposing ``async_create`` and
    ``async_dismiss`` as MagicMock spies.  Tests inspect ``call_args_list`` to
    assert the notification id / title / message contents.
    """
    pn_create = MagicMock(name="pn_create")
    pn_dismiss = MagicMock(name="pn_dismiss")
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.persistent_notification",
        SimpleNamespace(async_create=pn_create, async_dismiss=pn_dismiss),
    )
    return SimpleNamespace(async_create=pn_create, async_dismiss=pn_dismiss)


# ===========================================================================
# Stale-detection helper — guard / threshold / rebuild trigger
# ===========================================================================


async def test_first_install_guard_skips_when_last_rebuilt_none(
    pn_module: SimpleNamespace,
):
    """SPEC AC IDX-07: ``_last_rebuilt is None`` (first install) → no rebuild,
    no notification, but last_stale_check IS written so the Store record
    progresses on every run.
    """
    stub = _make_coord_stub_stale(last_rebuilt=None)
    check = _bind(stub, "_async_check_stale_and_rebuild")
    await check()

    stub.async_request_rebuild.assert_not_called()
    pn_module.async_create.assert_not_called()
    # last_stale_check is still persisted (try/finally guarantee).
    assert stub._index_stale_store.async_save.await_count == 1


async def test_fresh_index_skips_silently(pn_module: SimpleNamespace):
    """Local index 30 days old (<= 60d threshold) → no rebuild, no notification."""
    fresh = datetime.now(timezone.utc) - timedelta(days=30)
    stub = _make_coord_stub_stale(last_rebuilt=fresh)
    check = _bind(stub, "_async_check_stale_and_rebuild")
    await check()

    stub.async_request_rebuild.assert_not_called()
    pn_module.async_create.assert_not_called()
    # last_stale_check is always written.
    assert stub._index_stale_store.async_save.await_count == 1
    saved = stub._index_stale_store.async_save.call_args.args[0]
    assert saved["last_stale_check"] is not None


async def test_boundary_60_days_is_not_stale(pn_module: SimpleNamespace):
    """Boundary semantics: index exactly 60d old is NOT stale.

    SPEC wording "> 60 days" = strict-less; the helper uses
    ``age <= timedelta(days=STALE_INDEX_DAYS)`` to skip.
    """
    sixty = datetime.now(timezone.utc) - timedelta(days=STALE_INDEX_DAYS)
    stub = _make_coord_stub_stale(last_rebuilt=sixty)
    check = _bind(stub, "_async_check_stale_and_rebuild")
    await check()

    stub.async_request_rebuild.assert_not_called()
    pn_module.async_create.assert_not_called()


async def test_61_days_is_stale(pn_module: SimpleNamespace):
    """Index 61 days old → stale → notification + rebuild triggered."""
    stale = datetime.now(timezone.utc) - timedelta(days=STALE_INDEX_DAYS + 1)
    stub = _make_coord_stub_stale(last_rebuilt=stale)
    check = _bind(stub, "_async_check_stale_and_rebuild")
    await check()

    stub.async_request_rebuild.assert_awaited_once_with(triggered_by="stale_check")
    # Exactly one persistent_notification.async_create with our id.
    matching = [
        c
        for c in pn_module.async_create.call_args_list
        if c.kwargs.get("notification_id") == "asp_parking_index_stale"
    ]
    assert len(matching) == 1, (
        f"Expected exactly one pn_create with id 'asp_parking_index_stale'; "
        f"got {pn_module.async_create.call_args_list!r}"
    )


async def test_stale_index_triggers_rebuild_and_notification(
    pn_module: SimpleNamespace,
):
    """Index 65 days old → stale → notification + rebuild triggered (longer age)."""
    stale = datetime.now(timezone.utc) - timedelta(days=65)
    stub = _make_coord_stub_stale(last_rebuilt=stale)
    check = _bind(stub, "_async_check_stale_and_rebuild")
    await check()

    stub.async_request_rebuild.assert_awaited_once_with(triggered_by="stale_check")
    assert any(
        c.kwargs.get("notification_id") == "asp_parking_index_stale"
        for c in pn_module.async_create.call_args_list
    )


async def test_is_rebuilding_guard_skips_trigger(pn_module: SimpleNamespace):
    """SPEC AC: ``_is_rebuilding=True`` → skip rebuild even when stale.

    last_stale_check is still updated (try/finally).
    """
    stale = datetime.now(timezone.utc) - timedelta(days=65)
    stub = _make_coord_stub_stale(last_rebuilt=stale, is_rebuilding=True)
    check = _bind(stub, "_async_check_stale_and_rebuild")
    await check()

    stub.async_request_rebuild.assert_not_called()
    # Notification is also skipped when guard fires (no double-notify).
    pn_module.async_create.assert_not_called()
    # last_stale_check still persisted.
    assert stub._index_stale_store.async_save.await_count == 1


# ===========================================================================
# Store hydration / persistence semantics
# ===========================================================================


async def test_last_stale_check_written_to_store_after_each_run(
    pn_module: SimpleNamespace,
):
    """SPEC AC: last_stale_check is persisted on every run (regardless of branch)."""
    stub = _make_coord_stub_stale(last_rebuilt=None)
    check = _bind(stub, "_async_check_stale_and_rebuild")
    await check()

    assert stub._index_stale_store.async_save.await_count == 1
    saved = stub._index_stale_store.async_save.call_args.args[0]
    assert "last_stale_check" in saved
    assert saved["last_stale_check"] is not None
    # ISO 8601 string with UTC marker.
    iso = saved["last_stale_check"]
    assert iso.endswith("+00:00") or iso.endswith("Z"), (
        f"last_stale_check must be ISO 8601 UTC; got {iso!r}"
    )


async def test_store_payload_preserves_last_button_press(
    pn_module: SimpleNamespace,
):
    """The helper preserves ``last_button_press`` across writes (it is not its anchor)."""
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    stub = _make_coord_stub_stale(last_rebuilt=None)
    stub._last_button_press = one_hour_ago  # simulate prior button press
    check = _bind(stub, "_async_check_stale_and_rebuild")
    await check()

    saved = stub._index_stale_store.async_save.call_args.args[0]
    assert saved["last_button_press"] == one_hour_ago.isoformat(), (
        f"Helper must preserve _last_button_press across writes; got {saved!r}"
    )


async def test_store_payload_iso_8601_format(pn_module: SimpleNamespace):
    """V14 boundary: persisted timestamps are ISO 8601 strings parseable back to UTC."""
    # Lazy import dt_util to keep the test module lightweight.
    from homeassistant.util import dt as dt_util  # type: ignore[import-not-found]

    stub = _make_coord_stub_stale(last_rebuilt=None)
    check = _bind(stub, "_async_check_stale_and_rebuild")
    await check()

    saved = stub._index_stale_store.async_save.call_args.args[0]
    parsed = dt_util.parse_datetime(saved["last_stale_check"])
    assert parsed is not None, "last_stale_check must round-trip via dt_util.parse_datetime"
    assert parsed.tzinfo is not None, "last_stale_check must be tz-aware"


# ===========================================================================
# Positional-arg compat (Pitfall 12)
# ===========================================================================


async def test_callback_accepts_positional_datetime_from_interval(
    pn_module: SimpleNamespace,
):
    """Pitfall 12: ``async_track_time_interval`` invokes the callback with a
    positional ``datetime`` argument.  The helper MUST accept that signature.
    """
    stub = _make_coord_stub_stale(last_rebuilt=None)
    check = _bind(stub, "_async_check_stale_and_rebuild")

    # MUST NOT raise TypeError.
    await check(datetime.now(timezone.utc))
    # The Store still gets a write — proving the helper actually ran.
    assert stub._index_stale_store.async_save.await_count == 1


async def test_callback_accepts_no_args_from_startup_task(
    pn_module: SimpleNamespace,
):
    """The startup fire-and-forget background task invokes the helper with no args.

    The helper's default ``now: datetime | None = None`` enables this call shape.
    """
    stub = _make_coord_stub_stale(last_rebuilt=None)
    check = _bind(stub, "_async_check_stale_and_rebuild")

    # MUST NOT raise TypeError.
    await check()
    assert stub._index_stale_store.async_save.await_count == 1


# ===========================================================================
# Notification distinctness + body shape
# ===========================================================================


async def test_notification_id_is_distinct_from_rebuild_ids(
    pn_module: SimpleNamespace,
):
    """SPEC AC: notification id is ``"asp_parking_index_stale"`` — distinct from
    the rebuild progress / success / error ids used by Phase 33.
    """
    stale = datetime.now(timezone.utc) - timedelta(days=72)
    stub = _make_coord_stub_stale(last_rebuilt=stale)
    check = _bind(stub, "_async_check_stale_and_rebuild")
    await check()

    pn_module.async_create.assert_called_once()
    notification_id = pn_module.async_create.call_args.kwargs.get("notification_id")
    assert notification_id == "asp_parking_index_stale", (
        f"Notification id must be 'asp_parking_index_stale'; got {notification_id!r}"
    )
    for forbidden in (
        "asp_parking_index_rebuild",
        "asp_parking_index_rebuild_success",
        "asp_parking_index_rebuild_error",
    ):
        assert notification_id != forbidden, (
            f"Notification id must NOT collide with Phase 33 id {forbidden!r}"
        )


async def test_notification_title_contains_stale_word(pn_module: SimpleNamespace):
    """Notification title hints at staleness so the user understands the alert."""
    stale = datetime.now(timezone.utc) - timedelta(days=72)
    stub = _make_coord_stub_stale(last_rebuilt=stale)
    check = _bind(stub, "_async_check_stale_and_rebuild")
    await check()

    pn_module.async_create.assert_called_once()
    title = pn_module.async_create.call_args.kwargs.get("title", "")
    assert "stale" in title.lower(), (
        f"Notification title must mention staleness; got {title!r}"
    )


async def test_notification_message_contains_age_in_days(
    pn_module: SimpleNamespace,
):
    """Notification body includes the actual age in days so the user sees the value."""
    stale = datetime.now(timezone.utc) - timedelta(days=72)
    stub = _make_coord_stub_stale(last_rebuilt=stale)
    check = _bind(stub, "_async_check_stale_and_rebuild")
    await check()

    pn_module.async_create.assert_called_once()
    # message is positional arg index 1: (hass, message, *, title, notification_id).
    message = pn_module.async_create.call_args.args[1]
    assert "72" in message, (
        f"Notification message must include age in days (72); got {message!r}"
    )


# ===========================================================================
# async_start wiring — _async_init_stale_lifecycle
# ===========================================================================


async def test_async_start_initializes_index_stale_store_with_fixed_key(
    monkeypatch: pytest.MonkeyPatch,
):
    """SPEC §Requirement 3: Store uses FIXED key 'asp_parking_index_stale'
    (NOT per-entry-id).  Test confirms ``Store(...)`` is called with that key.
    """
    coord_mod = sys.modules["custom_components.asp_parking.coordinator"]
    captured: dict = {}

    class _FakeStore:
        def __init__(self, hass, version: int, key: str):
            captured["hass"] = hass
            captured["version"] = version
            captured["key"] = key

        async def async_load(self):
            return None

        async def async_save(self, payload):
            captured["save_payload"] = payload

    monkeypatch.setattr(coord_mod, "Store", _FakeStore, raising=True)
    monkeypatch.setattr(
        coord_mod, "async_track_time_interval", MagicMock(return_value=lambda: None)
    )

    stub = _make_coord_stub_stale(last_rebuilt=None)
    init_lifecycle = _bind(stub, "_async_init_stale_lifecycle")
    await init_lifecycle()

    assert captured.get("key") == "asp_parking_index_stale", (
        f"Store key MUST be 'asp_parking_index_stale' (fixed, not per-entry-id); "
        f"got {captured!r}"
    )
    assert captured.get("version") == 1, "Store version must be 1"


async def test_async_start_hydrates_last_button_press_from_store(
    monkeypatch: pytest.MonkeyPatch,
):
    """SPEC §Requirement 3: ``last_button_press`` is hydrated from Store at startup.

    The 24h double-press window must survive HA restarts.
    """
    from homeassistant.util import dt as dt_util  # type: ignore[import-not-found]

    coord_mod = sys.modules["custom_components.asp_parking.coordinator"]
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    iso = one_hour_ago.isoformat()

    class _FakeStore:
        def __init__(self, hass, version: int, key: str):
            pass

        async def async_load(self):
            return {"last_button_press": iso, "last_stale_check": None}

        async def async_save(self, payload):
            pass

    monkeypatch.setattr(coord_mod, "Store", _FakeStore, raising=True)
    monkeypatch.setattr(
        coord_mod, "async_track_time_interval", MagicMock(return_value=lambda: None)
    )

    stub = _make_coord_stub_stale(last_rebuilt=None)
    init_lifecycle = _bind(stub, "_async_init_stale_lifecycle")
    await init_lifecycle()

    assert stub._last_button_press is not None, (
        "last_button_press must be hydrated from Store payload"
    )
    parsed = dt_util.parse_datetime(iso)
    assert stub._last_button_press == parsed, (
        f"hydrated value {stub._last_button_press!r} must equal Store ISO {parsed!r}"
    )


async def test_async_start_spawns_startup_background_task(
    monkeypatch: pytest.MonkeyPatch,
):
    """D-01: startup stale-check runs as a fire-and-forget background task."""
    coord_mod = sys.modules["custom_components.asp_parking.coordinator"]

    class _FakeStore:
        def __init__(self, hass, version: int, key: str):
            pass

        async def async_load(self):
            return None

        async def async_save(self, payload):
            pass

    monkeypatch.setattr(coord_mod, "Store", _FakeStore, raising=True)
    monkeypatch.setattr(
        coord_mod, "async_track_time_interval", MagicMock(return_value=lambda: None)
    )

    stub = _make_coord_stub_stale(last_rebuilt=None)
    init_lifecycle = _bind(stub, "_async_init_stale_lifecycle")
    await init_lifecycle()

    # entry.async_create_background_task was called at least once.
    assert stub.entry.async_create_background_task.call_count >= 1, (
        "D-01: startup stale check must spawn a background task"
    )
    # Verify name pattern.
    names = [
        call.kwargs.get("name")
        or (call.args[2] if len(call.args) > 2 else None)
        for call in stub.entry.async_create_background_task.call_args_list
    ]
    assert "asp_parking_index_stale_check_startup" in names, (
        f"D-01: startup task name must be 'asp_parking_index_stale_check_startup'; "
        f"got {names!r}"
    )


async def test_async_start_registers_daily_interval(monkeypatch: pytest.MonkeyPatch):
    """D-02: a daily 24h ``async_track_time_interval`` is registered and its
    unsub is appended to ``self._listeners`` for ``async_stop`` cleanup.
    """
    coord_mod = sys.modules["custom_components.asp_parking.coordinator"]
    unsub = MagicMock(name="unsub_stale_interval")
    interval_spy = MagicMock(name="async_track_time_interval", return_value=unsub)

    class _FakeStore:
        def __init__(self, hass, version: int, key: str):
            pass

        async def async_load(self):
            return None

        async def async_save(self, payload):
            pass

    monkeypatch.setattr(coord_mod, "Store", _FakeStore, raising=True)
    monkeypatch.setattr(coord_mod, "async_track_time_interval", interval_spy)

    stub = _make_coord_stub_stale(last_rebuilt=None)
    init_lifecycle = _bind(stub, "_async_init_stale_lifecycle")
    await init_lifecycle()

    interval_spy.assert_called_once()
    interval = interval_spy.call_args.args[2]
    assert interval == timedelta(hours=STALE_CHECK_INTERVAL_HOURS), (
        f"Interval must be timedelta(hours={STALE_CHECK_INTERVAL_HOURS}); "
        f"got {interval!r}"
    )
    assert unsub in stub._listeners, (
        "Unsub from async_track_time_interval must be appended to self._listeners"
    )


# ===========================================================================
# Store data hygiene (V14 boundary)
# ===========================================================================


async def test_store_corrupt_payload_falls_back_to_none(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """V14: a corrupt (non-dict) Store payload is discarded, both hydrated
    timestamps fall back to None, and a WARNING is logged.
    """
    coord_mod = sys.modules["custom_components.asp_parking.coordinator"]

    class _FakeStore:
        def __init__(self, hass, version: int, key: str):
            pass

        async def async_load(self):
            return ["unexpected", "list", "shape"]  # not a dict

        async def async_save(self, payload):
            pass

    monkeypatch.setattr(coord_mod, "Store", _FakeStore, raising=True)
    monkeypatch.setattr(
        coord_mod, "async_track_time_interval", MagicMock(return_value=lambda: None)
    )

    stub = _make_coord_stub_stale(last_rebuilt=None)
    init_lifecycle = _bind(stub, "_async_init_stale_lifecycle")
    caplog.set_level(logging.WARNING, logger="custom_components.asp_parking.coordinator")
    await init_lifecycle()

    assert stub._last_button_press is None
    assert stub._last_stale_check is None
    # WARNING log emitted.
    warnings = [
        r for r in caplog.records if r.levelno == logging.WARNING and "index_stale" in r.getMessage()
    ]
    assert warnings, (
        f"Corrupt payload should emit a WARNING about index_stale store; "
        f"got {[r.getMessage() for r in caplog.records]!r}"
    )
