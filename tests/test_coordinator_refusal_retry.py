"""Spike 013: a refused fix must not pin the 50 m movement gate.

The CarPlay-disconnect Shortcut sends a burst of fixes 5-15 s apart that settle
3-6 m from the first.  The first fix is often the worst (sidewalk or centre of
road) and is refused; ``_apply_no_street_match`` records it as ``last_lat/lon``,
so the old 50 m gate then dropped the refined fix that would have resolved
(Prospect Pl, 2026-10-17 19:19:59 refused -> 19:20:13 resolvable, 21 ft apart).

After a refusal the gate tightens to ``REFUSAL_RETRY_DISTANCE_M``; after a
resolved fix it is unchanged.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from homeassistant.core import State

from custom_components.asp_parking.const import REFUSAL_RETRY_DISTANCE_M
from custom_components.asp_parking.coordinator import (
    ASPParkingCoordinator,
    ASPParkingData,
)

TRACKER = "device_tracker.car"
LAT, LON = 40.67791374869708, -73.96964907653067  # Oct 17 19:19:59 first fix
# ~0.00006 deg lat ~ 6.7 m north: the refined fix of a burst (> retry distance)
REFINED = (LAT + 0.00006, LON)
# ~0.00001 deg lat ~ 1.1 m: jitter (< retry distance)
JITTER = (LAT + 0.00001, LON)
# ~0.00020 deg lat ~ 22 m: moved, but well inside the 50 m default gate
NEARBY_22M = (LAT + 0.0002, LON)


def _state(lat: float, lon: float) -> State:
    return State(TRACKER, "home", {"latitude": lat, "longitude": lon})


def _stub(special_state: str | None) -> SimpleNamespace:
    data = ASPParkingData()
    data.last_lat, data.last_lon = LAT, LON
    data.special_state = special_state
    stub = SimpleNamespace(
        data=data,
        _async_notify_entities=MagicMock(),
        _gps_watchdog_rearm=MagicMock(),
        _gps_watchdog_arm_normal=MagicMock(),
        movement_threshold=50.0,
        _caldav_uid=None,
        _caldav_store=None,
        entry=SimpleNamespace(async_create_background_task=MagicMock()),
        hass=SimpleNamespace(),
        _debouncer=SimpleNamespace(async_call=MagicMock()),
    )
    stub._async_handle_tracker_health_transition = (
        ASPParkingCoordinator._async_handle_tracker_health_transition.__get__(stub)
    )
    return stub


def _fire(stub: SimpleNamespace, lat: float, lon: float) -> None:
    handler = ASPParkingCoordinator._async_on_gps_update.__get__(
        stub, ASPParkingCoordinator
    )
    handler(
        SimpleNamespace(
            data={"old_state": _state(LAT, LON), "new_state": _state(lat, lon)}
        )
    )


def _pipeline_scheduled(stub: SimpleNamespace) -> bool:
    return stub.entry.async_create_background_task.called


def test_refined_fix_after_refusal_triggers_pipeline() -> None:
    stub = _stub("no_street_match")
    _fire(stub, *REFINED)
    assert _pipeline_scheduled(stub)
    assert (stub._pending_lat, stub._pending_lon) == REFINED


def test_same_fix_after_refusal_is_ignored() -> None:
    stub = _stub("no_street_match")
    _fire(stub, LAT, LON)
    assert not _pipeline_scheduled(stub)


def test_sub_retry_jitter_after_refusal_is_ignored() -> None:
    stub = _stub("no_street_match")
    _fire(stub, *JITTER)
    assert not _pipeline_scheduled(stub)


def test_nearby_fix_after_resolved_park_still_gated() -> None:
    """Unchanged behaviour: a settled park keeps the 50 m gate."""
    stub = _stub(None)
    _fire(stub, *REFINED)
    _fire(stub, *NEARBY_22M)
    assert not _pipeline_scheduled(stub)


def test_other_special_state_keeps_gate() -> None:
    """Only a curb-side/street refusal tightens the gate."""
    stub = _stub("outside_coverage")
    _fire(stub, *REFINED)
    assert not _pipeline_scheduled(stub)


def test_far_move_after_refusal_still_triggers() -> None:
    stub = _stub("no_street_match")
    _fire(stub, LAT + 0.01, LON)
    assert _pipeline_scheduled(stub)


def test_retry_distance_never_exceeds_user_threshold() -> None:
    """A user threshold below the retry distance wins (min of the two)."""
    stub = _stub("no_street_match")
    stub.movement_threshold = 1.0
    _fire(stub, *JITTER)  # ~1.1 m >= 1.0 m
    assert _pipeline_scheduled(stub)


def test_retry_constant_is_small() -> None:
    assert 0 < REFUSAL_RETRY_DISTANCE_M <= 5.0
