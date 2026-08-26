"""Reconfigure-flow tests for ASPParkingConfigFlow.async_step_reconfigure.

Guards the contract that lets a user swap the vehicle's GPS source
(``device_tracker``) from the integration card without deleting the entry:

* the handler advertises the step, which is exactly how HA decides whether the
  Reconfigure action is offered (``ConfigEntry.supports_reconfigure``);
* the form renders pre-filled with the currently configured entity;
* ``manifest.json``'s ``single_config_entry: true`` does not abort the flow;
* a submit persists into ``entry.data``, merges rather than replaces, notifies
  the entry's registered update listener exactly once, and leaves
  ``entry.options`` (thresholds, NYC 311 key, notify service, parking area,
  CalDAV binding) bit-for-bit untouched;
* re-saving the same entity is a true no-op with no listener notification.

The reconfigure step deliberately relies on ``async_update_entry``'s own
update-listener notification for the reload -- it must NOT also call
``async_schedule_reload`` itself, or a real submission would reload the
integration twice. Tests that need to observe "was a reload triggered"
therefore register their own fake update listener on the entry (real
``async_setup_entry`` is never invoked here, so the production listener,
``_async_options_updated``, is never registered).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.data_entry_flow import FlowResultType

from custom_components.asp_parking.config_flow import ASPParkingConfigFlow
from custom_components.asp_parking.const import (
    CONF_DEVICE_TRACKER,
    CONF_MOVEMENT_THRESHOLD,
    CONF_NOTIFY_SERVICE,
    CONF_REFRESH_INTERVAL,
    CONF_STALE_TIMEOUT,
    DOMAIN,
)

pytestmark = pytest.mark.ha_integration


def _make_entry(hass, data: dict | None = None, options: dict | None = None):
    """Create and add a MockConfigEntry for the asp_parking integration."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data=data if data is not None else {CONF_DEVICE_TRACKER: "device_tracker.car"},
        options=options or {},
        title="ASP Parking Monitor",
    )
    entry.add_to_hass(hass)
    return entry


async def _submit_reconfigure(hass, entry, new_entity_id: str):
    """Run the reconfigure flow to completion and return its result.

    Registers a fake update listener on the entry beforehand so callers can
    observe whether the submission notified it (real ``async_setup_entry``,
    and thus the production listener, is never invoked in these tests).
    Returns ``(result, listener)``.
    """
    listener = AsyncMock(return_value=None)
    entry.async_on_unload(entry.add_update_listener(listener))

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DEVICE_TRACKER: new_entity_id}
    )
    await hass.async_block_till_done()
    return result, listener


def test_handler_advertises_reconfigure_step() -> None:
    """Defining the method is the whole registration mechanism.

    ``ConfigEntry.supports_reconfigure`` is computed as
    ``hasattr(handler, "async_step_reconfigure")`` -- this assertion is
    therefore the exact predicate that decides whether the Reconfigure action
    shows up on the integration card.
    """
    assert hasattr(ASPParkingConfigFlow, "async_step_reconfigure")


async def test_form_renders_with_current_tracker_as_default(
    hass, enable_custom_integrations
) -> None:
    """The form pre-fills the device_tracker already stored on the entry."""
    entry = _make_entry(hass)

    result = await entry.start_reconfigure_flow(hass)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    # vol.Required with default= resolves against an empty mapping, and the
    # EntitySelector accepts the well-formed entity id it round-trips.
    assert result["data_schema"]({})[CONF_DEVICE_TRACKER] == "device_tracker.car"


async def test_single_config_entry_does_not_block_reconfigure(
    hass, enable_custom_integrations
) -> None:
    """manifest single_config_entry: true must not abort this flow.

    config_entries.py guards the single_instance_allowed abort with
    ``source not in {SOURCE_IGNORE, SOURCE_REAUTH, SOURCE_RECONFIGURE}``.
    """
    entry = _make_entry(hass)
    # The entry really is registered, so the single_instance_allowed guard
    # would fire here if reconfigure were not exempt from it.
    assert hass.config_entries.async_entries(DOMAIN) == [entry]

    result = await entry.start_reconfigure_flow(hass)

    assert result["type"] == FlowResultType.FORM
    assert result.get("reason") != "single_instance_allowed"
    assert result.get("reason") is None


async def test_submit_persists_new_tracker_and_aborts_successfully(
    hass, enable_custom_integrations
) -> None:
    """A new entity id lands in entry.data and the flow ends in ABORT."""
    entry = _make_entry(hass)

    result, _ = await _submit_reconfigure(hass, entry, "device_tracker.new_car")

    # single_config_entry forbids a second entry, so the terminal result is
    # ABORT -- never CREATE_ENTRY.
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_DEVICE_TRACKER] == "device_tracker.new_car"


async def test_submit_notifies_entry_update_listener_once(
    hass, enable_custom_integrations
) -> None:
    """A real change notifies the entry's update listener exactly once.

    Regression guard for a double-reload bug: async_step_reconfigure must
    update entry.data via async_update_entry -- which drives HA's own
    update-listener notification -- rather than also scheduling a reload
    itself, which would reload the integration twice for one submission.
    """
    entry = _make_entry(hass)

    _, listener = await _submit_reconfigure(hass, entry, "device_tracker.new_car")

    listener.assert_called_once_with(hass, entry)


async def test_reconfigure_leaves_options_untouched(
    hass, enable_custom_integrations
) -> None:
    """Thresholds, notify service and friends survive a tracker swap."""
    # A fully populated options dict: three thresholds plus one non-threshold
    # key, to prove the reconfigure step never reaches into entry.options.
    options = {
        CONF_MOVEMENT_THRESHOLD: 50,
        CONF_REFRESH_INTERVAL: 8,
        CONF_STALE_TIMEOUT: 8,
        CONF_NOTIFY_SERVICE: "notify.mobile_app_phone",
    }
    entry = _make_entry(hass, options=options)

    result, _ = await _submit_reconfigure(hass, entry, "device_tracker.new_car")

    assert result["type"] == FlowResultType.ABORT
    assert dict(entry.options) == options


async def test_reconfigure_merges_data_instead_of_replacing_it(
    hass, enable_custom_integrations
) -> None:
    """Regression guard pinning data_updates= -- data= would drop the sentinel."""
    entry = _make_entry(
        hass,
        data={
            CONF_DEVICE_TRACKER: "device_tracker.car",
            "unrelated_sentinel": "keep-me",
        },
    )

    _, _ = await _submit_reconfigure(hass, entry, "device_tracker.new_car")

    assert entry.data[CONF_DEVICE_TRACKER] == "device_tracker.new_car"
    assert entry.data["unrelated_sentinel"] == "keep-me"


async def test_resubmitting_same_tracker_is_a_no_op(
    hass, enable_custom_integrations
) -> None:
    """Re-saving the identical entity must not reload the spatial index.

    ``async_update_entry`` only notifies update listeners when a value
    actually changed, so resubmitting the same tracker must not fire one.
    """
    entry = _make_entry(hass)

    result, listener = await _submit_reconfigure(hass, entry, "device_tracker.car")

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_DEVICE_TRACKER] == "device_tracker.car"
    listener.assert_not_called()
