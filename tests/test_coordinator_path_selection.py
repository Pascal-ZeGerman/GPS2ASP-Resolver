"""RED tests for coordinator dual-path rebuild routing (Phase 38 Plan 02 / IDX-05).

Covers smart path-selection added on top of Phase 33's `async_request_rebuild`
and `_async_do_rebuild`:

  - ``RebuildPath`` enum (DOWNLOAD / FROM_SOURCE)
  - ``_async_decide_rebuild_path(triggered_by) -> (RebuildPath, reason_str)``
  - ``_fetch_remote_asset_age_days() -> float | None``  (10-minute cache; Pitfall 2)
  - ``triggered_by`` keyword parameter on ``async_request_rebuild`` and
    ``_async_do_rebuild``  (default "button"; D-03 supports "stale_check")
  - Routing inside ``_async_do_rebuild`` to ``_sync_download_and_extract``
    OR ``_sync_build_from_source`` based on the decision.

Deviation guard (ROADMAP/SPEC say `/releases/latest`; we use `/tags/index-v1`):
  - ``test_github_api_uses_tag_v1_not_latest_url`` enforces the exact URL.

Pattern: SimpleNamespace + ``_bind`` (mirror tests/test_coordinator_rebuild.py)
plus ``respx`` for httpx mocking (D-08).

RED state proof: ``RebuildPath`` and the new helpers do not yet exist on
``ASPParkingCoordinator``. The module-level import below raises ImportError
during collection until Task 2 (GREEN) lands the implementation.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

# Target symbols — import MUST fail in RED until Task 2 lands them.
from custom_components.asp_parking.coordinator import (
    ASPParkingCoordinator,
    RebuildPath,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


GITHUB_TAG_URL = (
    "https://api.github.com/repos/Pascal-ZeGerman/GPS2ASP-Resolver"
    "/releases/tags/index-v1"
)
GITHUB_LATEST_URL = (
    "https://api.github.com/repos/Pascal-ZeGerman/GPS2ASP-Resolver"
    "/releases/latest"
)


def _make_coord_stub(
    *,
    is_rebuilding: bool = False,
    last_button_press: datetime | None = None,
    last_stale_check: datetime | None = None,
    remote_age_days: float | None = 10.0,
    sign_cache: dict | None = None,
) -> SimpleNamespace:
    """Build a stub coordinator mirroring tests/test_coordinator_rebuild.py.

    Adds Phase-38 attributes touched by the dual-path code:
      _index_stale_store (async_load/async_save AsyncMocks)
      _last_button_press / _last_stale_check
      _remote_age_cache  (None or (datetime, float | None))
      _fetch_remote_asset_age_days (AsyncMock; tests can replace with a real
        binding when exercising the GitHub API helper itself).
    """
    entry = SimpleNamespace(
        entry_id="test_entry_38_02",
        async_create_background_task=MagicMock(),
    )
    hass = SimpleNamespace(async_add_executor_job=AsyncMock())
    index_stale_store = SimpleNamespace(
        async_load=AsyncMock(return_value=None),
        async_save=AsyncMock(),
    )
    stub = SimpleNamespace(
        entry=entry,
        hass=hass,
        _is_rebuilding=is_rebuilding,
        _rebuild_task=None,
        _rebuild_lock=asyncio.Lock(),
        _last_rebuilt=datetime.now(timezone.utc) - timedelta(days=5),
        _sign_cache=sign_cache if sign_cache is not None else {},
        _async_notify_entities=MagicMock(),
        _index_stale_store=index_stale_store,
        _last_button_press=last_button_press,
        _last_stale_check=last_stale_check,
        _remote_age_cache=None,
        _fetch_remote_asset_age_days=AsyncMock(return_value=remote_age_days),
    )
    return stub


def _bind(stub: SimpleNamespace, method_name: str):
    """Bind ASPParkingCoordinator.method_name onto ``stub``.

    AttributeError on a missing class method is the RED-state signal.
    """
    method = getattr(ASPParkingCoordinator, method_name)
    return method.__get__(stub, ASPParkingCoordinator)


def _install_path_spies(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Patch executor-side symbols + SpatialIndex.reset + persistent_notification.

    Mirror of ``tests/test_coordinator_rebuild.py:_install_executor_spies``
    extended with ``_sync_build_from_source`` for the FROM_SOURCE branch.
    """
    coord_mod = sys.modules["custom_components.asp_parking.coordinator"]

    cleanup_stale = MagicMock(name="_sync_cleanup_stale")
    download_and_extract = MagicMock(name="_sync_download_and_extract")
    build_from_source = MagicMock(name="_sync_build_from_source")
    atomic_swap = MagicMock(name="_sync_atomic_swap")
    read_build_timestamp = MagicMock(
        name="_sync_read_build_timestamp", return_value=None
    )

    monkeypatch.setattr(coord_mod, "_sync_cleanup_stale", cleanup_stale, raising=False)
    monkeypatch.setattr(
        coord_mod, "_sync_download_and_extract", download_and_extract, raising=False
    )
    monkeypatch.setattr(
        coord_mod, "_sync_build_from_source", build_from_source, raising=False
    )
    monkeypatch.setattr(coord_mod, "_sync_atomic_swap", atomic_swap, raising=False)
    monkeypatch.setattr(
        coord_mod, "_sync_read_build_timestamp", read_build_timestamp, raising=False
    )

    spatial_index_reset = MagicMock(name="SpatialIndex.reset")
    monkeypatch.setattr(
        "custom_components.asp_parking.coordinator.SpatialIndex.reset",
        spatial_index_reset,
        raising=False,
    )

    pn_create = MagicMock(name="pn_create")
    pn_dismiss = MagicMock(name="pn_dismiss")
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.persistent_notification",
        SimpleNamespace(
            async_create=pn_create,
            async_dismiss=pn_dismiss,
        ),
    )

    return {
        "cleanup_stale": cleanup_stale,
        "download_and_extract": download_and_extract,
        "build_from_source": build_from_source,
        "atomic_swap": atomic_swap,
        "read_build_timestamp": read_build_timestamp,
        "spatial_index_reset": spatial_index_reset,
        "pn_create": pn_create,
        "pn_dismiss": pn_dismiss,
    }


# ---------------------------------------------------------------------------
# _async_decide_rebuild_path — IDX-05 acceptance criteria
# ---------------------------------------------------------------------------


async def test_press_remote_fresh_uses_download():
    """SPEC AC: press with remote < 30 days and no prior press -> DOWNLOAD."""
    stub = _make_coord_stub(remote_age_days=10.0, last_button_press=None)
    decide = _bind(stub, "_async_decide_rebuild_path")
    path, reason = await decide("button")
    assert path == RebuildPath.DOWNLOAD
    assert reason == "remote_fresh"


async def test_press_remote_stale_uses_from_source():
    """SPEC AC: press with remote >= 30 days and no prior press -> FROM_SOURCE."""
    stub = _make_coord_stub(remote_age_days=45.0, last_button_press=None)
    decide = _bind(stub, "_async_decide_rebuild_path")
    path, reason = await decide("button")
    assert path == RebuildPath.FROM_SOURCE
    assert reason == "remote_stale"


async def test_press_remote_exactly_30_days_uses_from_source():
    """Boundary: ``age_days >= REMOTE_FRESH_DAYS`` -> FROM_SOURCE.

    SPEC text "remote asset age < 30 days" means strict-less; exactly 30
    days falls through to FROM_SOURCE.
    """
    stub = _make_coord_stub(remote_age_days=30.0, last_button_press=None)
    decide = _bind(stub, "_async_decide_rebuild_path")
    path, reason = await decide("button")
    assert path == RebuildPath.FROM_SOURCE
    assert reason == "remote_stale"


async def test_double_press_within_24h_uses_from_source():
    """SPEC AC: second press within 24h -> FROM_SOURCE regardless of remote age."""
    recent = datetime.now(timezone.utc) - timedelta(hours=2)
    stub = _make_coord_stub(remote_age_days=5.0, last_button_press=recent)
    decide = _bind(stub, "_async_decide_rebuild_path")
    path, reason = await decide("button")
    assert path == RebuildPath.FROM_SOURCE
    assert reason == "double_press"


async def test_press_after_24h_window_uses_download():
    """Press 25h after the previous one falls outside the double-press window."""
    past = datetime.now(timezone.utc) - timedelta(hours=25)
    stub = _make_coord_stub(remote_age_days=5.0, last_button_press=past)
    decide = _bind(stub, "_async_decide_rebuild_path")
    path, reason = await decide("button")
    assert path == RebuildPath.DOWNLOAD
    assert reason == "remote_fresh"


async def test_stale_check_triggered_by_skips_24h_override():
    """D-03: triggered_by=stale_check ignores last_button_press window."""
    recent = datetime.now(timezone.utc) - timedelta(hours=2)
    stub = _make_coord_stub(remote_age_days=5.0, last_button_press=recent)
    decide = _bind(stub, "_async_decide_rebuild_path")
    path, reason = await decide("stale_check")
    assert path == RebuildPath.DOWNLOAD
    assert reason == "remote_fresh"


async def test_stale_check_uses_from_source_when_remote_stale():
    """triggered_by=stale_check still respects remote-stale -> FROM_SOURCE."""
    stub = _make_coord_stub(remote_age_days=45.0, last_button_press=None)
    decide = _bind(stub, "_async_decide_rebuild_path")
    path, reason = await decide("stale_check")
    assert path == RebuildPath.FROM_SOURCE
    assert reason == "remote_stale"


# ---------------------------------------------------------------------------
# _fetch_remote_asset_age_days — GitHub Releases API (with respx)
# ---------------------------------------------------------------------------


@respx.mock
async def test_github_api_failure_falls_back_to_from_source():
    """SPEC AC: 5xx response from GitHub -> (FROM_SOURCE, github_api_failed)."""
    respx.get(GITHUB_TAG_URL).mock(
        return_value=httpx.Response(500, json={"error": "boom"})
    )
    stub = _make_coord_stub()
    # Use the REAL _fetch_remote_asset_age_days instead of the mocked stub.
    stub._fetch_remote_asset_age_days = _bind(stub, "_fetch_remote_asset_age_days")
    decide = _bind(stub, "_async_decide_rebuild_path")
    path, reason = await decide("button")
    assert path == RebuildPath.FROM_SOURCE
    assert reason == "github_api_failed"


@respx.mock
async def test_github_api_no_assets_falls_back_to_from_source():
    """200 response with empty assets list -> (FROM_SOURCE, github_api_failed)."""
    respx.get(GITHUB_TAG_URL).mock(
        return_value=httpx.Response(200, json={"assets": []})
    )
    stub = _make_coord_stub()
    stub._fetch_remote_asset_age_days = _bind(stub, "_fetch_remote_asset_age_days")
    decide = _bind(stub, "_async_decide_rebuild_path")
    path, reason = await decide("button")
    assert path == RebuildPath.FROM_SOURCE
    assert reason == "github_api_failed"


@respx.mock
async def test_github_api_uses_tag_v1_not_latest_url():
    """ROADMAP deviation guard: URL is /tags/index-v1, NOT /releases/latest.

    Mounts both routes; only the /tags/index-v1 route should be hit.
    """
    tag_route = respx.get(GITHUB_TAG_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "assets": [
                    {
                        "name": "index.zip",
                        "created_at": (
                            datetime.now(timezone.utc) - timedelta(days=5)
                        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }
                ]
            },
        )
    )
    latest_route = respx.get(GITHUB_LATEST_URL).mock(
        return_value=httpx.Response(404, json={"message": "should not be called"})
    )
    stub = _make_coord_stub()
    fetch = _bind(stub, "_fetch_remote_asset_age_days")
    age = await fetch()
    assert age is not None
    assert tag_route.called, "tags/index-v1 route MUST be called"
    assert not latest_route.called, "/releases/latest route MUST NOT be called"


@respx.mock
async def test_remote_age_uses_created_at_not_updated_at():
    """Pitfall 3: age is computed from ``created_at``, not ``updated_at``."""
    created = datetime.now(timezone.utc) - timedelta(days=52)
    updated = datetime.now(timezone.utc) - timedelta(days=22)
    respx.get(GITHUB_TAG_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "assets": [
                    {
                        "name": "index.zip",
                        "created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "updated_at": updated.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }
                ]
            },
        )
    )
    stub = _make_coord_stub()
    fetch = _bind(stub, "_fetch_remote_asset_age_days")
    age = await fetch()
    assert age is not None
    # created_at -> ~52d; updated_at -> ~22d. Tolerate clock drift.
    assert 51.0 < age < 53.5, f"age {age} should match created_at (~52d), not updated_at"


@respx.mock
async def test_remote_age_cache_hits_within_10_minutes():
    """Pitfall 2: second call within 10 min reuses the cached value."""
    route = respx.get(GITHUB_TAG_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "assets": [
                    {
                        "name": "index.zip",
                        "created_at": (
                            datetime.now(timezone.utc) - timedelta(days=10)
                        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }
                ]
            },
        )
    )
    stub = _make_coord_stub()
    fetch = _bind(stub, "_fetch_remote_asset_age_days")
    age1 = await fetch()
    age2 = await fetch()
    assert age1 is not None and age2 is not None
    assert route.call_count == 1, (
        f"Cache MUST suppress second HTTP call within 10 min; got {route.call_count}"
    )


@respx.mock
async def test_remote_age_cache_expires_after_10_minutes():
    """Cache TTL: an entry older than 10 minutes triggers a refetch."""
    route = respx.get(GITHUB_TAG_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "assets": [
                    {
                        "name": "index.zip",
                        "created_at": (
                            datetime.now(timezone.utc) - timedelta(days=10)
                        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }
                ]
            },
        )
    )
    stub = _make_coord_stub()
    # Pre-seed an expired cache entry.
    stub._remote_age_cache = (
        datetime.now(timezone.utc) - timedelta(minutes=11),
        5.0,
    )
    fetch = _bind(stub, "_fetch_remote_asset_age_days")
    age = await fetch()
    assert age is not None
    assert route.call_count == 1, "Expired cache MUST trigger HTTP refetch"


# ---------------------------------------------------------------------------
# async_request_rebuild — triggered_by parameter
# ---------------------------------------------------------------------------


async def test_async_request_rebuild_triggered_by_button_default():
    """Calling ``async_request_rebuild()`` with no args defaults to button.

    Verifies _is_rebuilding is set and exactly one background task is spawned
    with triggered_by="button" (default preserves button.py call site).
    """
    stub = _make_coord_stub(is_rebuilding=False)
    request_rebuild = _bind(stub, "async_request_rebuild")
    await request_rebuild()
    assert stub._is_rebuilding is True
    assert stub.entry.async_create_background_task.call_count == 1


async def test_async_request_rebuild_triggered_by_stale_check_does_not_write_last_button_press():
    """D-03: triggered_by=stale_check MUST NOT update ``_last_button_press``.

    Per SPEC: ``last_button_press`` is the 24h-double-press anchor and is
    button-only. A stale_check-triggered rebuild must leave it unchanged.
    """
    stub = _make_coord_stub(is_rebuilding=False, last_button_press=None)
    request_rebuild = _bind(stub, "async_request_rebuild")
    await request_rebuild(triggered_by="stale_check")
    # _last_button_press unchanged (still None)
    assert stub._last_button_press is None
    # async_save should NOT have been called with a button-press payload.
    # (Either not called at all, or called with last_button_press=None.)
    if stub._index_stale_store.async_save.await_count:
        for call in stub._index_stale_store.async_save.await_args_list:
            payload = call.args[0] if call.args else {}
            assert payload.get("last_button_press") in (None, "")


async def test_button_press_writes_last_button_press_before_spawn():
    """SPEC Requirement 1.6: store the press timestamp BEFORE the task is created.

    A second press during a running rebuild must still see a recent press.
    """
    stub = _make_coord_stub(is_rebuilding=False, last_button_press=None)
    # Record the sequence of events.
    ordering: list[str] = []

    def _spawn(*args, **kwargs):
        ordering.append("spawn")

    stub.entry.async_create_background_task.side_effect = _spawn

    async def _save(payload):
        ordering.append("save")

    stub._index_stale_store.async_save.side_effect = _save

    request_rebuild = _bind(stub, "async_request_rebuild")
    await request_rebuild()  # default triggered_by="button"

    # Both events must have happened, with save BEFORE spawn.
    assert "save" in ordering, "async_save MUST be awaited for button press"
    assert "spawn" in ordering, "background task MUST be spawned"
    assert ordering.index("save") < ordering.index("spawn"), (
        f"Store write MUST happen BEFORE task spawn; got {ordering}"
    )
    assert stub._last_button_press is not None


# ---------------------------------------------------------------------------
# _async_do_rebuild — routing to download vs from-source
# ---------------------------------------------------------------------------


async def test_do_rebuild_download_path_calls_sync_download_and_extract(
    monkeypatch: pytest.MonkeyPatch,
):
    """When decision == DOWNLOAD, _sync_download_and_extract runs; build_from_source does NOT."""
    stub = _make_coord_stub(is_rebuilding=True)
    spies = _install_path_spies(monkeypatch)

    async def _executor_dispatch(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    stub.hass.async_add_executor_job.side_effect = _executor_dispatch

    # Force the decision instead of going through the real helper.
    stub._async_decide_rebuild_path = AsyncMock(
        return_value=(RebuildPath.DOWNLOAD, "remote_fresh")
    )

    do_rebuild = _bind(stub, "_async_do_rebuild")
    await do_rebuild(triggered_by="button")

    assert spies["download_and_extract"].call_count == 1, (
        "DOWNLOAD path MUST invoke _sync_download_and_extract exactly once"
    )
    assert spies["build_from_source"].call_count == 0, (
        "DOWNLOAD path MUST NOT invoke _sync_build_from_source"
    )


async def test_do_rebuild_from_source_path_calls_sync_build_from_source(
    monkeypatch: pytest.MonkeyPatch,
):
    """When decision == FROM_SOURCE, _sync_build_from_source runs."""
    stub = _make_coord_stub(is_rebuilding=True)
    spies = _install_path_spies(monkeypatch)

    async def _executor_dispatch(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    stub.hass.async_add_executor_job.side_effect = _executor_dispatch

    stub._async_decide_rebuild_path = AsyncMock(
        return_value=(RebuildPath.FROM_SOURCE, "remote_stale")
    )

    do_rebuild = _bind(stub, "_async_do_rebuild")
    await do_rebuild(triggered_by="button")

    assert spies["build_from_source"].call_count == 1, (
        "FROM_SOURCE path MUST invoke _sync_build_from_source exactly once"
    )
    assert spies["download_and_extract"].call_count == 0, (
        "FROM_SOURCE path MUST NOT invoke _sync_download_and_extract"
    )


async def test_do_rebuild_logs_path_decision_info(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """An INFO log line documents the chosen path + reason."""
    stub = _make_coord_stub(is_rebuilding=True)
    _install_path_spies(monkeypatch)

    async def _executor_dispatch(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    stub.hass.async_add_executor_job.side_effect = _executor_dispatch
    stub._async_decide_rebuild_path = AsyncMock(
        return_value=(RebuildPath.DOWNLOAD, "remote_fresh")
    )

    caplog.set_level(logging.INFO, logger="custom_components.asp_parking.coordinator")
    do_rebuild = _bind(stub, "_async_do_rebuild")
    await do_rebuild(triggered_by="button")

    pattern = re.compile(
        r"asp_parking: index rebuild path=(download|from_source) reason=\w+"
    )
    matching = [r for r in caplog.records if pattern.search(r.getMessage())]
    assert matching, (
        f"Expected INFO log matching {pattern.pattern!r}; got "
        f"{[r.getMessage() for r in caplog.records]!r}"
    )
