"""CR-01 regression test (38-REVIEW.md): real end-to-end button-press routing.

Prior to the CR-01 fix, ``async_request_rebuild()`` overwrote
``self._last_button_press`` with "now" *before* spawning
``_async_do_rebuild()``, which in turn called
``_async_decide_rebuild_path()``. That method re-read the (already
mutated) ``self._last_button_press`` attribute, so the "was there a press
within the last 24h?" check always compared "now" against itself --
misrouting *every* button press (including the very first one ever) to
the slow FROM_SOURCE path.

None of the existing tests in ``test_coordinator_path_selection.py``
caught this: they either (a) call ``_async_decide_rebuild_path`` directly
against a stub with a hand-set ``_last_button_press``/``previous_button_press``
(never going through ``async_request_rebuild``), or (b) call
``_async_do_rebuild`` directly with ``_async_decide_rebuild_path`` replaced
by an ``AsyncMock``. This test drives the REAL production call chain
``async_request_rebuild()`` -> ``_async_do_rebuild()`` ->
``_async_decide_rebuild_path()`` twice in a row to prove the fix.
"""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.asp_parking.coordinator import (
    ASPParkingCoordinator,
    RebuildPath,
)


def _make_stub() -> SimpleNamespace:
    """Build a bare coordinator stub with the REAL decision method bound.

    Unlike ``tests/test_coordinator_path_selection.py``'s
    ``_make_coord_stub`` (which leaves ``_async_decide_rebuild_path``
    unbound so individual tests can stub it), this stub binds the real
    method -- that binding is the entire point of this regression test.
    """
    entry = SimpleNamespace(
        entry_id="test_entry_38_cr01_e2e",
        async_create_background_task=MagicMock(),
    )
    # Plain AsyncMock (no side_effect): executor jobs are recorded but
    # never actually run, so this test does not depend on real on-disk
    # index files / network access.
    hass = SimpleNamespace(async_add_executor_job=AsyncMock())
    index_stale_store = SimpleNamespace(
        async_load=AsyncMock(return_value=None),
        async_save=AsyncMock(),
    )
    stub = SimpleNamespace(
        entry=entry,
        hass=hass,
        _is_rebuilding=False,
        _rebuild_task=None,
        _rebuild_lock=asyncio.Lock(),
        _last_rebuilt=None,
        _sign_cache={},
        _async_notify_entities=MagicMock(),
        _index_stale_store=index_stale_store,
        _last_button_press=None,
        _last_stale_check=None,
        _remote_age_cache=None,
        # Mocked-fresh GitHub remote (< REMOTE_FRESH_DAYS=30): absent the
        # CR-01 fix, EVERY press would still be misrouted to FROM_SOURCE
        # via the double-press self-comparison, so this alone would not
        # prove the fix -- the double_press check must run first and
        # correctly distinguish "no prior press" from "prior press".
        _fetch_remote_asset_age_days=AsyncMock(return_value=5.0),
    )
    stub._async_decide_rebuild_path = (
        ASPParkingCoordinator._async_decide_rebuild_path.__get__(
            stub, ASPParkingCoordinator
        )
    )
    return stub


def _install_spies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mirror test_coordinator_path_selection.py's _install_path_spies.

    Only patches what runs OUTSIDE the executor (SpatialIndex.reset,
    persistent_notification) since ``hass.async_add_executor_job`` is a
    plain (non-dispatching) AsyncMock here.
    """
    monkeypatch.setattr(
        "custom_components.asp_parking.coordinator.SpatialIndex.reset",
        MagicMock(name="SpatialIndex.reset"),
        raising=False,
    )
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.persistent_notification",
        SimpleNamespace(
            async_create=MagicMock(name="pn_create"),
            async_dismiss=MagicMock(name="pn_dismiss"),
        ),
    )


async def test_two_button_presses_first_download_second_double_press(
    monkeypatch: pytest.MonkeyPatch,
):
    """1st button press -> DOWNLOAD; 2nd press within 24h -> FROM_SOURCE/double_press.

    Before the CR-01 fix this test failed on the FIRST assertion: the
    first-ever button press was already misrouted to FROM_SOURCE because
    ``_last_button_press`` had just been set to "now" by
    ``async_request_rebuild`` before ``_async_decide_rebuild_path`` read it.
    """
    _install_spies(monkeypatch)
    stub = _make_stub()

    decisions: list[tuple[RebuildPath, str]] = []
    real_decide = stub._async_decide_rebuild_path

    async def _spy_decide(triggered_by, previous_button_press=None):
        result = await real_decide(triggered_by, previous_button_press)
        decisions.append(result)
        return result

    stub._async_decide_rebuild_path = _spy_decide

    captured_coros: list = []

    def _capture_spawn(hass, coro, *, name=None):
        captured_coros.append(coro)

    stub.entry.async_create_background_task.side_effect = _capture_spawn

    request_rebuild = ASPParkingCoordinator.async_request_rebuild.__get__(
        stub, ASPParkingCoordinator
    )

    # -- First press: no prior press exists ------------------------------
    await request_rebuild(triggered_by="button")
    assert len(captured_coros) == 1
    await captured_coros[0]  # run _async_do_rebuild -> _async_decide_rebuild_path
    assert stub._is_rebuilding is False, (
        "finally block must reset _is_rebuilding so the button is usable again"
    )

    assert decisions[0] == (RebuildPath.DOWNLOAD, "remote_fresh"), (
        "CR-01 regression: the first-ever button press with a fresh remote "
        f"must resolve to DOWNLOAD, got {decisions[0]!r} -- if this is "
        "FROM_SOURCE/double_press, self-comparison bug is back"
    )

    # -- Second press: within the 24h double-press window ----------------
    await request_rebuild(triggered_by="button")
    assert len(captured_coros) == 2
    await captured_coros[1]
    assert stub._is_rebuilding is False

    assert decisions[1] == (RebuildPath.FROM_SOURCE, "double_press"), (
        f"Second button press within 24h must be FROM_SOURCE/double_press, "
        f"got {decisions[1]!r}"
    )
