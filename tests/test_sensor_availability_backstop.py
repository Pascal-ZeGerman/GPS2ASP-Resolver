"""Regression tests for the availability/staleness gate (debug: unavailable-while-parked).

Background — the bug these guard against:
    ``ASPNextMoveTimeSensor.available`` gated on ``last_gps_update`` being newer
    than ``stale_timeout`` (then 8 h). ``last_gps_update`` only advances inside
    ``_async_on_gps_update``, i.e. on a real ``state_changed`` event from the
    configured ``device_tracker``. The periodic heartbeat re-runs the whole
    pipeline from cached coordinates and logs a clean resolve, but never touches
    that timestamp.

    So once a car is parked and its tracker goes quiet — VW CarNet telematics
    sleeping on ignition-off, or a Shortcut-posted tracker that only fires when
    the phone moves — the sensor flipped to ``unavailable`` after 8 h while the
    resolved curb position was still perfectly correct. Every overnight park
    tripped it.

Fix under test, in two halves:
    1. ``stale_timeout`` becomes a 168 h (7-day) backstop rather than a
       freshness SLA. 7 days is the NYC ASP recurrence cycle, so a car sitting
       untouched for a week is ordinary rather than exceptional.
    2. A tracker that self-reports ``unavailable`` / ``unknown`` is a real
       integration failure (expired OAuth token, dead API) and marks the sensor
       unavailable immediately, without waiting out the backstop.

Pattern: SimpleNamespace stubs + real production descriptors rebound onto a
stub class (mirrors tests/test_coordinator_stale.py's ``_bind`` approach), so
the assertions exercise the shipped property bodies rather than a replica.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import State
from homeassistant.util import dt as dt_util

from custom_components.asp_parking.binary_sensor import (
    ASPGpsPipelineHealthBinarySensor,
)
from custom_components.asp_parking.const import (
    CONF_DEVICE_TRACKER,
    CONF_STALE_TIMEOUT,
    DEFAULT_STALE_TIMEOUT,
    LEGACY_STALE_TIMEOUT_HOURS,
)
from custom_components.asp_parking.coordinator import (
    ASPParkingCoordinator,
    ASPParkingData,
)
from custom_components.asp_parking.sensor import ASPNextMoveTimeSensor

TRACKER = "device_tracker.taos_carplay"


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _StubCoordinator:
    """Minimal coordinator exposing the REAL availability/watchdog descriptors.

    ``tracker_unavailable``, ``device_tracker_entity``, ``stale_timeout``,
    ``gps_data_available``, ``tracker_registered``, ``tracker_failed`` and the
    watchdog methods are the production objects rebound onto this class, so
    their bodies (including ``_is_failed_tracker_state``) are what actually
    run under test. ``hass`` is a bare SimpleNamespace -- entity-registry
    lookups go through ``er.async_get``, which tests patch directly rather
    than modelling a real registry.
    """

    device_tracker_entity = ASPParkingCoordinator.device_tracker_entity
    tracker_unavailable = ASPParkingCoordinator.tracker_unavailable
    tracker_registered = ASPParkingCoordinator.tracker_registered
    tracker_failed = ASPParkingCoordinator.tracker_failed
    stale_timeout = ASPParkingCoordinator.stale_timeout
    gps_data_available = ASPParkingCoordinator.gps_data_available
    _gps_watchdog_cancel = ASPParkingCoordinator._gps_watchdog_cancel
    _gps_watchdog_arm_normal = ASPParkingCoordinator._gps_watchdog_arm_normal
    _gps_watchdog_rearm = ASPParkingCoordinator._gps_watchdog_rearm
    _on_gps_stale_timeout = ASPParkingCoordinator._on_gps_stale_timeout
    _async_post_gps_stale_notification = (
        ASPParkingCoordinator._async_post_gps_stale_notification
    )

    def __init__(
        self,
        *,
        tracker_state: State | None,
        last_gps_update=None,
        pipeline_error: bool = False,
        stale_timeout: int | None = None,
    ) -> None:
        options: dict = {}
        if stale_timeout is not None:
            options[CONF_STALE_TIMEOUT] = stale_timeout

        self.entry = SimpleNamespace(
            entry_id="test_entry_availability",
            data={CONF_DEVICE_TRACKER: TRACKER},
            options=options,
        )
        self.hass = SimpleNamespace(
            states=SimpleNamespace(
                get=lambda entity_id: tracker_state if entity_id == TRACKER else None
            )
        )
        self.data = ASPParkingData(last_gps_update=last_gps_update)
        self._last_pipeline_error = pipeline_error
        # Only exercised by the watchdog tests below, but harmless elsewhere.
        self._gps_stale_unsub = None
        self._async_notify_entities = MagicMock()


def _tracker_state(state: str) -> State:
    """Build a device_tracker State carrying a valid GPS location."""
    return State(
        TRACKER,
        state,
        {"latitude": 40.6782, "longitude": -73.9442, "gps_accuracy": 10},
    )


def _make_sensor(**kwargs) -> ASPNextMoveTimeSensor:
    return ASPNextMoveTimeSensor(_StubCoordinator(**kwargs))


def _silent_for(days: float = 0, hours: float = 0):
    """Return a UTC timestamp that far in the past (i.e. tracker silence)."""
    return dt_util.utcnow() - timedelta(days=days, hours=hours)


# ===========================================================================
# (a) The 7-day backstop
# ===========================================================================


class TestSevenDayBackstop:
    """stale_timeout is a multi-day backstop, not an 8-hour freshness SLA."""

    def test_default_stale_timeout_is_seven_days(self) -> None:
        """The default is 168 h. A shorter default is what caused the bug."""
        assert DEFAULT_STALE_TIMEOUT == 168, (
            "stale_timeout is a backstop for total tracker silence, and a parked "
            "car is silent for days by design. Shortening this default "
            "reintroduces false 'unavailable' on ordinary overnight parking."
        )

    @pytest.mark.parametrize(
        "hours_silent",
        [
            9,  # the old 8 h gate — this is the exact regression
            24,
            48,
            24 * 6,  # 6 days: still inside the backstop
        ],
    )
    def test_available_through_six_days_of_tracker_silence(
        self, hours_silent: int
    ) -> None:
        """A parked car whose tracker has gone quiet stays available."""
        sensor = _make_sensor(
            tracker_state=_tracker_state("home"),
            last_gps_update=_silent_for(hours=hours_silent),
        )
        assert sensor.available is True, (
            f"{hours_silent} h of tracker silence must not mark the sensor "
            "unavailable: the resolved curb position is still correct and the "
            "heartbeat keeps re-resolving it."
        )

    def test_unavailable_just_past_seven_days(self) -> None:
        """Past the 7-day backstop the position is finally treated as unproven."""
        sensor = _make_sensor(
            tracker_state=_tracker_state("home"),
            last_gps_update=_silent_for(days=7, hours=1),
        )
        assert sensor.available is False

    def test_boundary_just_inside_seven_days_is_available(self) -> None:
        """168 h minus a minute is still inside the window (gate is ``<=``)."""
        sensor = _make_sensor(
            tracker_state=_tracker_state("home"),
            last_gps_update=_silent_for(days=7) + timedelta(minutes=1),
        )
        assert sensor.available is True

    def test_no_gps_update_yet_is_available(self) -> None:
        """Startup before the first GPS event is not 'stale'."""
        sensor = _make_sensor(tracker_state=_tracker_state("home"))
        assert sensor.available is True

    def test_explicit_option_still_overrides_the_default(self) -> None:
        """A user who deliberately configures a short window keeps it."""
        sensor = _make_sensor(
            tracker_state=_tracker_state("home"),
            last_gps_update=_silent_for(hours=9),
            stale_timeout=8,
        )
        assert sensor.available is False


# ===========================================================================
# (b) Tracker-health fast path
# ===========================================================================


class TestTrackerHealthFastPath:
    """A tracker that self-reports failure short-circuits the backstop."""

    @pytest.mark.parametrize("bad_state", [STATE_UNAVAILABLE, STATE_UNKNOWN])
    def test_unavailable_immediately_when_tracker_reports_failure(
        self, bad_state: str
    ) -> None:
        """Well inside the 7-day window, a broken tracker still means unavailable."""
        sensor = _make_sensor(
            tracker_state=State(TRACKER, bad_state),
            last_gps_update=_silent_for(hours=1),
        )
        assert sensor.available is False, (
            f"A device_tracker reporting '{bad_state}' is its integration "
            "declaring itself broken (dead API / expired token). There is "
            "nothing to wait for, so the backstop must be short-circuited."
        )

    @pytest.mark.parametrize("bad_state", [STATE_UNAVAILABLE, STATE_UNKNOWN])
    def test_fast_path_beats_a_fresh_gps_timestamp(self, bad_state: str) -> None:
        """Even a seconds-old timestamp cannot rescue a failed tracker."""
        sensor = _make_sensor(
            tracker_state=State(TRACKER, bad_state),
            last_gps_update=dt_util.utcnow(),
        )
        assert sensor.available is False

    def test_missing_tracker_entity_is_not_treated_as_failure(self) -> None:
        """A tracker absent from the state machine falls through to the backstop.

        This is deliberately NOT a failure signal. A manually-posted / Shortcut
        driven tracker has no restored state after an HA restart, and an
        integration mid-setup has not registered its entity yet. Treating either
        as a failure would flap the sensor unavailable on every reboot.
        """
        sensor = _make_sensor(
            tracker_state=None,
            last_gps_update=_silent_for(hours=2),
        )
        assert sensor.available is True

    def test_healthy_tracker_state_does_not_trip_the_fast_path(self) -> None:
        """Ordinary zone states (home / not_home) are healthy."""
        for good in ("home", "not_home", "Work"):
            sensor = _make_sensor(
                tracker_state=_tracker_state(good),
                last_gps_update=_silent_for(hours=2),
            )
            assert sensor.available is True, f"state '{good}' must be healthy"

    def test_coordinator_property_reads_live_state_each_call(self) -> None:
        """``tracker_unavailable`` is not cached — it re-reads the state machine.

        Reading live is what makes the fast path work when the tracker was
        ALREADY unavailable at HA start and therefore never fired a
        state_changed event for the coordinator to observe.
        """
        current: dict = {"state": _tracker_state("home")}
        coord = _StubCoordinator(tracker_state=None)
        coord.hass = SimpleNamespace(
            states=SimpleNamespace(get=lambda _eid: current["state"])
        )

        assert coord.tracker_unavailable is False
        current["state"] = State(TRACKER, STATE_UNAVAILABLE)
        assert coord.tracker_unavailable is True
        current["state"] = _tracker_state("home")
        assert coord.tracker_unavailable is False


# ===========================================================================
# (c) Pipeline-error gate is unchanged
# ===========================================================================


class TestPipelineErrorGateUnchanged:
    """The pre-existing ``_last_pipeline_error`` behaviour must not regress."""

    def test_pipeline_error_marks_unavailable(self) -> None:
        sensor = _make_sensor(
            tracker_state=_tracker_state("home"),
            last_gps_update=dt_util.utcnow(),
            pipeline_error=True,
        )
        assert sensor.available is False

    def test_pipeline_error_wins_over_a_healthy_tracker(self) -> None:
        """A healthy tracker does not mask a failed pipeline run."""
        sensor = _make_sensor(
            tracker_state=_tracker_state("home"),
            last_gps_update=_silent_for(hours=1),
            pipeline_error=True,
        )
        assert sensor.available is False

    def test_cleared_pipeline_error_restores_availability(self) -> None:
        coord = _StubCoordinator(
            tracker_state=_tracker_state("home"),
            last_gps_update=_silent_for(hours=1),
            pipeline_error=True,
        )
        sensor = ASPNextMoveTimeSensor(coord)
        assert sensor.available is False
        coord._last_pipeline_error = False
        assert sensor.available is True


# ===========================================================================
# Diagnostic binary sensor keeps its value under the longer backstop
# ===========================================================================


class TestGpsPipelineHealthTrackerCheck:
    """The health binary sensor would otherwise stay ON for a week after a death."""

    def test_off_when_tracker_reports_unavailable(self) -> None:
        coord = _StubCoordinator(
            tracker_state=State(TRACKER, STATE_UNAVAILABLE),
            last_gps_update=dt_util.utcnow(),
            stale_timeout=DEFAULT_STALE_TIMEOUT,
        )
        assert ASPGpsPipelineHealthBinarySensor(coord).is_on is False

    def test_on_when_tracker_is_merely_silent(self) -> None:
        """Silence still reads healthy inside the backstop — it means 'parked'."""
        coord = _StubCoordinator(
            tracker_state=_tracker_state("home"),
            last_gps_update=_silent_for(days=2),
            stale_timeout=DEFAULT_STALE_TIMEOUT,
        )
        assert ASPGpsPipelineHealthBinarySensor(coord).is_on is True


# ===========================================================================
# Prompt refresh: entities must re-render on a tracker health transition
# ===========================================================================


class TestGpsUpdateNotifiesOnHealthTransition:
    """``available`` reads live state, so something must push a re-render."""

    @staticmethod
    def _stub_coordinator_for_event() -> SimpleNamespace:
        stub = SimpleNamespace(
            data=ASPParkingData(),
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
        # The real method (not a mock) so its own logic -- deciding whether to
        # call the two mocks above -- is what actually runs under test.
        stub._async_handle_tracker_health_transition = (
            ASPParkingCoordinator._async_handle_tracker_health_transition.__get__(stub)
        )
        return stub

    @staticmethod
    def _fire(stub: SimpleNamespace, old_state, new_state) -> None:
        handler = ASPParkingCoordinator._async_on_gps_update.__get__(
            stub, ASPParkingCoordinator
        )
        handler(SimpleNamespace(data={"old_state": old_state, "new_state": new_state}))

    def test_notifies_when_tracker_goes_unavailable(self) -> None:
        stub = self._stub_coordinator_for_event()
        self._fire(stub, _tracker_state("home"), State(TRACKER, STATE_UNAVAILABLE))
        stub._async_notify_entities.assert_called_once()
        # The watchdog must also be poked on this transition (not just
        # entities) so the "GPS Signal Lost" notification can fire via its
        # own immediate fast path instead of waiting out stale_timeout.
        stub._gps_watchdog_rearm.assert_called_once()

    def test_notifies_when_tracker_recovers(self) -> None:
        """Recovery carries a fresh location fix, so the main path arms the
        backstop directly via ``_gps_watchdog_arm_normal`` rather than
        re-deriving tracker health through ``_gps_watchdog_rearm``.
        """
        stub = self._stub_coordinator_for_event()
        self._fire(stub, State(TRACKER, STATE_UNAVAILABLE), _tracker_state("home"))
        stub._async_notify_entities.assert_called_once()
        stub._gps_watchdog_arm_normal.assert_called_once()

    def test_no_notify_on_ordinary_location_update(self) -> None:
        """A healthy -> healthy update must not add an extra entity write."""
        stub = self._stub_coordinator_for_event()
        self._fire(stub, _tracker_state("not_home"), _tracker_state("home"))
        stub._async_notify_entities.assert_not_called()

    def test_watchdog_rearmed_on_unavailable_transition(self) -> None:
        """An unavailable state carries no location, so it is not a GPS fix --

        but the watchdog must still be rearmed on this transition (rather than
        only on a real location update) so a genuinely broken tracker gets the
        immediate notification fast path instead of waiting out the full
        stale_timeout backstop.
        """
        stub = self._stub_coordinator_for_event()
        self._fire(stub, _tracker_state("home"), State(TRACKER, STATE_UNAVAILABLE))
        assert stub.data.last_gps_update is None
        stub._gps_watchdog_rearm.assert_called_once()


# ===========================================================================
# Deleted-tracker detection + watchdog notification fast path
# ===========================================================================


def _patched_registry(*, registered: bool):
    """Patch ``er.async_get`` so ``tracker_registered`` returns ``registered``."""
    fake_registry = SimpleNamespace(
        async_get=lambda entity_id: object() if registered else None
    )
    return patch(
        "custom_components.asp_parking.coordinator.er.async_get",
        return_value=fake_registry,
    )


class TestTrackerRegisteredAndFailed:
    """A deleted/renamed tracker entity is distinguishable from 'not started yet'."""

    def test_registered_true_when_entity_registry_has_it(self) -> None:
        coord = _StubCoordinator(tracker_state=_tracker_state("home"))
        with _patched_registry(registered=True):
            assert coord.tracker_registered is True

    def test_registered_false_when_entity_registry_lacks_it(self) -> None:
        """Deleted / renamed / never-existed entities are not in the registry."""
        coord = _StubCoordinator(tracker_state=None)
        with _patched_registry(registered=False):
            assert coord.tracker_registered is False

    def test_failed_true_when_tracker_reports_unavailable(self) -> None:
        coord = _StubCoordinator(tracker_state=State(TRACKER, STATE_UNAVAILABLE))
        with _patched_registry(registered=True):
            assert coord.tracker_failed is True

    def test_failed_true_when_entity_deleted(self) -> None:
        """Missing *state* alone is not a failure (see tracker_unavailable), but
        a missing *registry entry* is -- there is no recovering event coming.
        """
        coord = _StubCoordinator(tracker_state=None)
        with _patched_registry(registered=False):
            assert coord.tracker_failed is True

    def test_failed_false_when_healthy_and_registered(self) -> None:
        coord = _StubCoordinator(tracker_state=_tracker_state("home"))
        with _patched_registry(registered=True):
            assert coord.tracker_failed is False

    def test_failed_false_when_state_missing_but_still_registered(self) -> None:
        """Integration mid-setup: registered, no state yet -- not a failure."""
        coord = _StubCoordinator(tracker_state=None)
        with _patched_registry(registered=True):
            assert coord.tracker_failed is False


class TestGpsWatchdogFastPath:
    """The GPS-stale notification must use the same fast path as availability.

    Regression coverage for the bug where ``_gps_watchdog_rearm`` still waited
    out the full (now 168 h) ``stale_timeout`` before alerting, even though a
    genuinely broken tracker is caught immediately everywhere else.
    """

    def test_immediate_alert_when_tracker_unavailable(self) -> None:
        coord = _StubCoordinator(
            tracker_state=State(TRACKER, STATE_UNAVAILABLE), stale_timeout=168
        )
        with (
            _patched_registry(registered=True),
            patch("custom_components.asp_parking.coordinator.pn_create") as mock_create,
            patch(
                "custom_components.asp_parking.coordinator.pn_dismiss"
            ) as mock_dismiss,
            patch(
                "custom_components.asp_parking.coordinator.async_call_later"
            ) as mock_call_later,
        ):
            coord._gps_watchdog_rearm()

        mock_create.assert_called_once()
        assert "unavailable" in mock_create.call_args.args[1]
        mock_dismiss.assert_not_called()
        mock_call_later.assert_not_called()
        coord._async_notify_entities.assert_called_once()

    def test_immediate_alert_when_tracker_deleted(self) -> None:
        coord = _StubCoordinator(tracker_state=None, stale_timeout=168)
        with (
            _patched_registry(registered=False),
            patch("custom_components.asp_parking.coordinator.pn_create") as mock_create,
            patch(
                "custom_components.asp_parking.coordinator.async_call_later"
            ) as mock_call_later,
        ):
            coord._gps_watchdog_rearm()

        mock_create.assert_called_once()
        message = mock_create.call_args.args[1]
        assert "no longer exists" in message
        assert TRACKER in message
        mock_call_later.assert_not_called()
        coord._async_notify_entities.assert_called_once()

    def test_normal_arm_when_tracker_healthy(self) -> None:
        """A healthy tracker still gets the full-length backstop timer, not an alert."""
        coord = _StubCoordinator(
            tracker_state=_tracker_state("home"), stale_timeout=168
        )
        with (
            _patched_registry(registered=True),
            patch("custom_components.asp_parking.coordinator.pn_create") as mock_create,
            patch(
                "custom_components.asp_parking.coordinator.pn_dismiss"
            ) as mock_dismiss,
            patch(
                "custom_components.asp_parking.coordinator.async_call_later"
            ) as mock_call_later,
        ):
            coord._gps_watchdog_rearm()

        mock_create.assert_not_called()
        mock_dismiss.assert_called_once()
        mock_call_later.assert_called_once()
        assert mock_call_later.call_args.args[1] == 168 * 3600

    def test_timeout_fires_generic_stale_message_when_still_healthy(self) -> None:
        """The eventual backstop timeout still uses the plain silence wording."""
        coord = _StubCoordinator(
            tracker_state=_tracker_state("home"), stale_timeout=168
        )
        with (
            _patched_registry(registered=True),
            patch("custom_components.asp_parking.coordinator.pn_create") as mock_create,
        ):
            coord._on_gps_stale_timeout(dt_util.utcnow())

        mock_create.assert_called_once()
        message = mock_create.call_args.args[1]
        assert "No GPS update has been received" in message
        coord._async_notify_entities.assert_called_once()


# ===========================================================================
# Migration: existing entries carry a literal 8 that shadows the new default
# ===========================================================================


class TestStaleTimeoutMigration:
    """Without this, the const change reaches nobody who already installed."""

    @staticmethod
    async def _migrate(options: dict, minor_version: int = 1):
        from custom_components.asp_parking import async_migrate_entry

        hass = MagicMock()
        entry = SimpleNamespace(
            version=2, minor_version=minor_version, options=dict(options)
        )
        assert await async_migrate_entry(hass, entry) is True
        return hass.config_entries.async_update_entry

    async def test_legacy_default_is_raised_to_the_backstop(self) -> None:
        update = await self._migrate({CONF_STALE_TIMEOUT: LEGACY_STALE_TIMEOUT_HOURS})
        update.assert_called_once()
        assert (
            update.call_args.kwargs["options"][CONF_STALE_TIMEOUT]
            == DEFAULT_STALE_TIMEOUT
        )
        assert update.call_args.kwargs["minor_version"] == 2

    @pytest.mark.parametrize("customised", [4, 12, 24, 72])
    async def test_customised_values_are_left_alone(self, customised: int) -> None:
        """Any non-legacy value is a deliberate user choice."""
        update = await self._migrate({CONF_STALE_TIMEOUT: customised})
        assert update.call_args.kwargs["options"][CONF_STALE_TIMEOUT] == customised

    async def test_other_options_are_preserved(self) -> None:
        update = await self._migrate(
            {CONF_STALE_TIMEOUT: LEGACY_STALE_TIMEOUT_HOURS, "movement_threshold": 50.0}
        )
        assert update.call_args.kwargs["options"]["movement_threshold"] == 50.0

    async def test_already_migrated_entry_is_untouched(self) -> None:
        update = await self._migrate(
            {CONF_STALE_TIMEOUT: LEGACY_STALE_TIMEOUT_HOURS}, minor_version=2
        )
        update.assert_not_called()
