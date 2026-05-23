"""RED tests for window-boundary timer (Phase 39).

Covers the NEW coordinator surface added by Plan 01:

  - ``_boundary_timer_cancel(self) -> None``
        Safe cancel helper.  No-op when ``_boundary_timer_unsub`` is None.
        D-09: clears ``_boundary_timer_unsub`` to None BEFORE calling the
        stored cancel callable (defensive clear-first ordering).

  - ``_async_schedule_boundary_timer(self, schedule: ScheduleResult) -> None``
        @callback-decorated synchronous method.  Unconditionally cancels any
        prior timer via ``_boundary_timer_cancel()``, then:
          - ASPActiveNow → registers a one-shot timer at active_window.end_datetime.
          - ScheduleFound with non-None next_window → registers at next_window.start_datetime.
          - ScheduleFound with next_window=None (D-01) → logs DEBUG, skips registration.
          - Any other status (D-02) → logs DEBUG, skips registration.
        Delay is clamped to max(0.0, ...) to handle past boundaries (D-06).
        Timer fires by spawning _async_resolve_pipeline via
        entry.async_create_background_task (D-04 / WR-01).

The _bind pattern raises AttributeError until Task 2 (GREEN) lands the
implementation on ASPParkingCoordinator.  The import-time module load succeeds;
only method bindings inside test functions are the RED signal.

Pattern: SimpleNamespace + ``_bind`` (mirrors tests/test_coordinator_stale.py:60–137).
Patching uses ``monkeypatch.setattr(coord_mod, "async_call_later", ...)`` to patch
the coordinator module's imported name (Pitfall 3 — NOT homeassistant.helpers.event).
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.asp_parking.coordinator import ASPParkingCoordinator
from custom_components.asp_parking.gps2asp.schedule.models import (
    ASPActiveNow,
    AllUnparseable,
    ASPDay,
    CleaningWindow,
    NoASPSchedule,
    NoMatchSchedule,
    ScheduleFound,
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

NYC_TZ = __import__("zoneinfo").ZoneInfo("America/New_York")

# Module handle for Pitfall-3 monkeypatching.
coord_mod = sys.modules["custom_components.asp_parking.coordinator"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_coord_stub() -> SimpleNamespace:
    """Build a minimal stub coordinator for boundary-timer unit tests.

    Provides the attributes accessed by _boundary_timer_cancel and
    _async_schedule_boundary_timer without touching HA state machine.
    """
    entry = SimpleNamespace(
        entry_id="test_entry_39",
        async_create_background_task=MagicMock(),
    )
    hass = SimpleNamespace(loop=MagicMock())
    return SimpleNamespace(
        entry=entry,
        hass=hass,
        _boundary_timer_unsub=None,
        _async_resolve_pipeline=AsyncMock(),
    )


def _bind(stub: SimpleNamespace, method_name: str):
    """Bind ASPParkingCoordinator.method_name onto ``stub``.

    AttributeError on a missing class method is the RED-state signal —
    both ``_boundary_timer_cancel`` and ``_async_schedule_boundary_timer``
    raise here until Task 2 (GREEN) lands.
    """
    method = getattr(ASPParkingCoordinator, method_name)
    return method.__get__(stub, ASPParkingCoordinator)


def _make_cleaning_window(*, start: datetime, end: datetime) -> CleaningWindow:
    """Construct a CleaningWindow from tz-aware NYC datetimes."""
    return CleaningWindow(
        day=ASPDay(start.weekday()),
        start_time=start.time(),
        end_time=end.time(),
        start_datetime=start,
        end_datetime=end,
        source_signs=["TEST SIGN"],
    )


# ---------------------------------------------------------------------------
# Helpers for building ScheduleFound / ASPActiveNow
# ---------------------------------------------------------------------------


def _make_schedule_found(
    next_window: CleaningWindow | None,
    *,
    suspended: bool = False,
) -> ScheduleFound:
    """Build a ScheduleFound with a MagicMock weekly_schedule."""
    return ScheduleFound(
        status="schedule_found",
        next_window=next_window,
        weekly_schedule=MagicMock(),
        on_street="TEST ST",
        from_street="FIRST AVE",
        to_street="SECOND AVE",
        side_of_street="N",
        source_signs=["TEST SIGN"],
        summary="Mon 8-9 AM",
        parse_failures=[],
        suspended=suspended,
    )


def _make_asp_active_now(active_window: CleaningWindow) -> ASPActiveNow:
    """Build an ASPActiveNow wrapping the given window."""
    return ASPActiveNow(
        status="asp_active_now",
        active_window=active_window,
        on_street="TEST ST",
        from_street="FIRST AVE",
        to_street="SECOND AVE",
        side_of_street="N",
        source_signs=["TEST SIGN"],
        summary="Active now",
    )


# ===========================================================================
# _boundary_timer_cancel — unit tests
# ===========================================================================


def test_cancel_is_noop_when_unsub_is_none() -> None:
    """D-09 / D-03: cancel on a fresh stub with _boundary_timer_unsub=None
    must not raise and must leave the attribute as None.
    """
    stub = _make_coord_stub()
    cancel = _bind(stub, "_boundary_timer_cancel")
    cancel()  # Must not raise
    assert stub._boundary_timer_unsub is None


def test_cancel_clears_attr_before_calling_unsub() -> None:
    """D-09 ordering: _boundary_timer_unsub must be None at the moment the
    stored callable is invoked (clear-first guarantees no double-call on retry).
    """
    stub = _make_coord_stub()
    captured: dict = {}

    def _fake_unsub() -> None:
        # Snapshot the attribute value AT call time.
        captured["attr_at_call_time"] = stub._boundary_timer_unsub

    stub._boundary_timer_unsub = _fake_unsub
    cancel = _bind(stub, "_boundary_timer_cancel")
    cancel()

    # Attribute must have been cleared before calling the callable.
    assert captured["attr_at_call_time"] is None, (
        "D-09: _boundary_timer_unsub must be set to None BEFORE the cancel callable is invoked"
    )
    assert stub._boundary_timer_unsub is None


def test_cancel_calls_stored_callable_once() -> None:
    """The stored cancel callable is invoked exactly once."""
    stub = _make_coord_stub()
    mock_unsub = MagicMock()
    stub._boundary_timer_unsub = mock_unsub
    cancel = _bind(stub, "_boundary_timer_cancel")
    cancel()
    mock_unsub.assert_called_once()


# ===========================================================================
# _async_schedule_boundary_timer — scheduling tests
# ===========================================================================


def test_aspactivenow_schedules_timer_at_window_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ASPActiveNow → timer registered at active_window.end_datetime (~30 min)."""
    stub = _make_coord_stub()
    sentinel_unsub = MagicMock(name="unsub_sentinel")
    acl_spy = MagicMock(name="async_call_later", return_value=sentinel_unsub)
    monkeypatch.setattr(coord_mod, "async_call_later", acl_spy)

    now_nyc = datetime.now(NYC_TZ)
    end_nyc = now_nyc + timedelta(minutes=30)
    window = _make_cleaning_window(start=now_nyc - timedelta(minutes=5), end=end_nyc)
    schedule = _make_asp_active_now(window)

    schedule_timer = _bind(stub, "_async_schedule_boundary_timer")
    schedule_timer(schedule)

    acl_spy.assert_called_once()
    actual_delay = acl_spy.call_args.args[1]
    assert abs(actual_delay - 1800.0) < 2.0, (
        f"Delay should be ~1800s for a 30-minute future end; got {actual_delay}"
    )
    assert stub._boundary_timer_unsub is sentinel_unsub


def test_schedulefound_with_next_window_schedules_at_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ScheduleFound with next_window → timer registered at next_window.start_datetime (~30 min)."""
    stub = _make_coord_stub()
    sentinel_unsub = MagicMock(name="unsub_sentinel")
    acl_spy = MagicMock(name="async_call_later", return_value=sentinel_unsub)
    monkeypatch.setattr(coord_mod, "async_call_later", acl_spy)

    now_nyc = datetime.now(NYC_TZ)
    start_nyc = now_nyc + timedelta(minutes=30)
    end_nyc = start_nyc + timedelta(hours=1)
    window = _make_cleaning_window(start=start_nyc, end=end_nyc)
    schedule = _make_schedule_found(window)

    schedule_timer = _bind(stub, "_async_schedule_boundary_timer")
    schedule_timer(schedule)

    acl_spy.assert_called_once()
    actual_delay = acl_spy.call_args.args[1]
    assert abs(actual_delay - 1800.0) < 2.0, (
        f"Delay should be ~1800s for a 30-minute future start; got {actual_delay}"
    )
    assert stub._boundary_timer_unsub is sentinel_unsub


def test_schedulefound_with_none_next_window_skips_with_debug_log(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """D-01: ScheduleFound(next_window=None) must NOT register a timer and must log DEBUG
    containing 'next_window=None'.
    """
    stub = _make_coord_stub()
    acl_spy = MagicMock(name="async_call_later")
    monkeypatch.setattr(coord_mod, "async_call_later", acl_spy)

    schedule = _make_schedule_found(None)
    caplog.set_level(logging.DEBUG, logger="custom_components.asp_parking.coordinator")

    schedule_timer = _bind(stub, "_async_schedule_boundary_timer")
    schedule_timer(schedule)

    acl_spy.assert_not_called()
    assert any(
        "next_window=None" in record.getMessage()
        for record in caplog.records
        if record.levelno == logging.DEBUG
    ), (
        "D-01: must emit a DEBUG log containing 'next_window=None' when skipping timer registration"
    )


def test_new_schedule_cancels_prior_timer_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-02/D-05: A prior timer is unconditionally cancelled before registering a new one."""
    stub = _make_coord_stub()
    prior_unsub = MagicMock(name="prior_unsub")
    stub._boundary_timer_unsub = prior_unsub

    sentinel_unsub = MagicMock(name="new_unsub_sentinel")
    acl_spy = MagicMock(name="async_call_later", return_value=sentinel_unsub)
    monkeypatch.setattr(coord_mod, "async_call_later", acl_spy)

    now_nyc = datetime.now(NYC_TZ)
    start_nyc = now_nyc + timedelta(minutes=30)
    end_nyc = start_nyc + timedelta(hours=1)
    window = _make_cleaning_window(start=start_nyc, end=end_nyc)
    schedule = _make_schedule_found(window)

    schedule_timer = _bind(stub, "_async_schedule_boundary_timer")
    schedule_timer(schedule)

    prior_unsub.assert_called_once()
    acl_spy.assert_called_once()
    assert stub._boundary_timer_unsub is sentinel_unsub


def test_noasp_status_cancels_prior_and_does_not_register(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-02: Non-ASP status (NoASPSchedule) cancels any prior timer and does NOT register a new one."""
    stub = _make_coord_stub()
    prior_unsub = MagicMock(name="prior_unsub")
    stub._boundary_timer_unsub = prior_unsub

    acl_spy = MagicMock(name="async_call_later")
    monkeypatch.setattr(coord_mod, "async_call_later", acl_spy)

    schedule = NoASPSchedule()
    schedule_timer = _bind(stub, "_async_schedule_boundary_timer")
    schedule_timer(schedule)

    prior_unsub.assert_called_once()
    acl_spy.assert_not_called()
    assert stub._boundary_timer_unsub is None


def test_past_boundary_produces_delay_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-06: If boundary_dt is in the past, delay is clamped to exactly 0.0."""
    stub = _make_coord_stub()
    sentinel_unsub = MagicMock(name="unsub_sentinel")
    acl_spy = MagicMock(name="async_call_later", return_value=sentinel_unsub)
    monkeypatch.setattr(coord_mod, "async_call_later", acl_spy)

    now_nyc = datetime.now(NYC_TZ)
    # end_datetime is 10 seconds in the past
    end_nyc = now_nyc - timedelta(seconds=10)
    start_nyc = end_nyc - timedelta(hours=1)
    window = _make_cleaning_window(start=start_nyc, end=end_nyc)
    schedule = _make_asp_active_now(window)

    schedule_timer = _bind(stub, "_async_schedule_boundary_timer")
    schedule_timer(schedule)

    acl_spy.assert_called_once()
    actual_delay = acl_spy.call_args.args[1]
    assert actual_delay == 0.0, (
        f"D-06: past boundary must produce delay == 0.0 (max clamp); got {actual_delay}"
    )


def test_fire_callback_spawns_pipeline_via_entry_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-04: The timer fire callback spawns _async_resolve_pipeline via
    entry.async_create_background_task with name='asp_parking_boundary_timer'.
    """
    stub = _make_coord_stub()
    sentinel_unsub = MagicMock(name="unsub_sentinel")
    acl_spy = MagicMock(name="async_call_later", return_value=sentinel_unsub)
    monkeypatch.setattr(coord_mod, "async_call_later", acl_spy)

    now_nyc = datetime.now(NYC_TZ)
    start_nyc = now_nyc + timedelta(minutes=30)
    end_nyc = start_nyc + timedelta(hours=1)
    window = _make_cleaning_window(start=start_nyc, end=end_nyc)
    schedule = _make_schedule_found(window)

    schedule_timer = _bind(stub, "_async_schedule_boundary_timer")
    schedule_timer(schedule)

    # Capture the fire closure (3rd positional arg to async_call_later).
    fire_callback = acl_spy.call_args.args[2]

    # Invoke the fire callback with a fake datetime arg (as HA would).
    fake_fire_time = datetime.now(timezone.utc)
    fire_callback(fake_fire_time)

    # Assert that entry.async_create_background_task was called with the correct name.
    stub.entry.async_create_background_task.assert_called_once()
    call_kwargs = stub.entry.async_create_background_task.call_args.kwargs
    call_args = stub.entry.async_create_background_task.call_args.args
    # name may be positional (index 2) or keyword
    name = call_kwargs.get("name") or (call_args[2] if len(call_args) > 2 else None)
    assert name == "asp_parking_boundary_timer", (
        f"D-04: background task name must be 'asp_parking_boundary_timer'; got {name!r}"
    )


def test_suspended_schedulefound_still_schedules_timer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-07: ScheduleFound with suspended=True and a valid next_window still schedules a timer.
    Suspension state is re-evaluated at fire time, not at scheduling time.
    """
    stub = _make_coord_stub()
    sentinel_unsub = MagicMock(name="unsub_sentinel")
    acl_spy = MagicMock(name="async_call_later", return_value=sentinel_unsub)
    monkeypatch.setattr(coord_mod, "async_call_later", acl_spy)

    now_nyc = datetime.now(NYC_TZ)
    start_nyc = now_nyc + timedelta(minutes=30)
    end_nyc = start_nyc + timedelta(hours=1)
    window = _make_cleaning_window(start=start_nyc, end=end_nyc)
    # suspended=True: should still schedule
    schedule = _make_schedule_found(window, suspended=True)

    schedule_timer = _bind(stub, "_async_schedule_boundary_timer")
    schedule_timer(schedule)

    acl_spy.assert_called_once()
