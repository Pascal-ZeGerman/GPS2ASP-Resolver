"""Options flow tests for AREA-01: parking_area step.

Verifies the new parking_area options step renders, accepts empty submission,
round-trips lat/lon/radius into entry.options, and that the init step
correctly carries forward parking values across saves.
"""

from __future__ import annotations

import pytest
from homeassistant.data_entry_flow import FlowResultType

from custom_components.asp_parking.const import (
    CONF_DEVICE_TRACKER,
    CONF_MOVEMENT_THRESHOLD,
    CONF_PARKING_LAT,
    CONF_PARKING_LON,
    CONF_PARKING_RADIUS,
    CONF_REFRESH_INTERVAL,
    CONF_STALE_TIMEOUT,
    DOMAIN,
)

pytestmark = pytest.mark.ha_integration


# Default valid input for the options init step (satisfies _validate_settings)
_INIT_INPUT: dict = {
    CONF_MOVEMENT_THRESHOLD: 50,
    CONF_REFRESH_INTERVAL: 8,
    CONF_STALE_TIMEOUT: 8,
}


def _make_entry(hass, options: dict | None = None):
    """Create and add a MockConfigEntry for the asp_parking integration."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={CONF_DEVICE_TRACKER: "device_tracker.car"},
        options=options or {},
        title="ASP Parking Monitor",
    )
    entry.add_to_hass(hass)
    return entry


async def test_parking_area_step_renders_after_init(
    hass, enable_custom_integrations
) -> None:
    """init step must chain into a parking_area form on submit."""
    entry = _make_entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _INIT_INPUT
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "parking_area"


async def test_parking_area_empty_submission_saves_without_parking_keys(
    hass, enable_custom_integrations
) -> None:
    """Submitting parking_area with no fields must NOT write parking keys.

    NOTE: Phase 34 (Plan 03) inserted a CalDAV step between parking_area
    and CREATE_ENTRY. We advance through the new caldav step with an
    empty URL (D-02 no-op) to reach CREATE_ENTRY without touching the
    parking-area contract.
    """
    entry = _make_entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _INIT_INPUT
    )
    # Submit empty parking_area form → advances to caldav (Phase 34)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    # Phase 34: submit empty CalDAV URL = D-02 no-op = CREATE_ENTRY
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"caldav_url": ""}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY

    assert CONF_PARKING_LAT not in entry.options
    assert CONF_PARKING_LON not in entry.options
    assert CONF_PARKING_RADIUS not in entry.options


async def test_parking_area_round_trip_persists_values(
    hass, enable_custom_integrations
) -> None:
    """Submitting lat/lon/radius must persist them with correct types.

    NOTE: Phase 34 inserts a CalDAV step; advance through it with an
    empty URL (D-02 no-op) to reach CREATE_ENTRY.
    """
    entry = _make_entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _INIT_INPUT
    )
    parking_input = {
        CONF_PARKING_LAT: 40.6778,
        CONF_PARKING_LON: -73.9690,
        CONF_PARKING_RADIUS: 500,
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], parking_input
    )
    # Phase 34: submit empty CalDAV URL = D-02 no-op = CREATE_ENTRY
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"caldav_url": ""}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY

    assert entry.options[CONF_PARKING_LAT] == pytest.approx(40.6778)
    assert entry.options[CONF_PARKING_LON] == pytest.approx(-73.9690)
    assert entry.options[CONF_PARKING_RADIUS] == 500
    assert isinstance(entry.options[CONF_PARKING_LAT], float)
    assert isinstance(entry.options[CONF_PARKING_LON], float)
    assert isinstance(entry.options[CONF_PARKING_RADIUS], int)


async def test_init_step_preserves_parking_keys_when_unchanged(
    hass, enable_custom_integrations
) -> None:
    """Pre-existing parking keys round-trip through init→parking_area unchanged.

    NOTE: Phase 34 inserts a CalDAV step; advance through it with an
    empty URL (D-02 no-op) to reach CREATE_ENTRY.
    """
    pre = {
        CONF_PARKING_LAT: 40.6778,
        CONF_PARKING_LON: -73.9690,
        CONF_PARKING_RADIUS: 250,
    }
    entry = _make_entry(hass, options=pre)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _INIT_INPUT
    )
    # Accept the parking_area defaults (which were pre-seeded from entry.options)
    result = await hass.config_entries.options.async_configure(result["flow_id"], pre)
    # Phase 34: submit empty CalDAV URL = D-02 no-op = CREATE_ENTRY
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"caldav_url": ""}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY

    assert entry.options[CONF_PARKING_LAT] == pytest.approx(40.6778)
    assert entry.options[CONF_PARKING_LON] == pytest.approx(-73.9690)
    assert entry.options[CONF_PARKING_RADIUS] == 250
