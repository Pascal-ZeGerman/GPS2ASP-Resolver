"""Test the asp_parking diagnostics export (DIAG-01).

Wave 0 RED tests for Phase 27: every test in this file must FAIL on first run
because ``custom_components.asp_parking.diagnostics`` does not yet exist.
Plan 02 will create the module; once it does these tests turn GREEN and lock
the diagnostics shape (top-level keys, redaction set, ISO datetime
serialization).

Per Pitfall #5 (27-RESEARCH.md), the production coordinator is NOT imported at
module top — instead a local ``_FakeData`` dataclass mirrors the field shape of
``coordinator.ASPParkingData`` and the runtime_data is a ``SimpleNamespace`` so
the real coordinator/spatial-index never has to load.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from custom_components.asp_parking.const import (
    CONF_DEBUG_LAT,
    CONF_DEBUG_LON,
    CONF_NYC311_API_KEY,
    CONF_PARKING_LAT,
    CONF_PARKING_LON,
    DOMAIN,
)

pytestmark = pytest.mark.ha_integration


# ---------------------------------------------------------------------------
# Local mirror of ASPParkingData — avoids importing the HA-bound coordinator
# (Pitfall #5: coordinator imports SpatialIndex transitively which fails at
# collection time when no index is built).
# Field shape mirrors custom_components/asp_parking/coordinator.py:103-141.
# ---------------------------------------------------------------------------


@dataclass
class _FakeData:
    """Test-local mirror of ``ASPParkingData`` for diagnostics tests."""

    last_resolved: datetime | None = None
    confidence_score: float | None = None
    soda_level: int = 0
    last_error: str | None = None
    last_error_time: datetime | None = None
    sign_count: int = 0
    parse_failures: int = 0
    schedule_result: object | None = None
    special_state: str | None = None


def _make_entry(
    hass,
    options: dict,
    *,
    last_resolved: datetime | None = None,
    confidence_score: float | None = None,
    soda_level: int = 0,
    last_error: str | None = None,
    last_error_time: datetime | None = None,
    sign_count: int = 0,
    parse_failures: int = 0,
    schedule_result: object | None = None,
    special_state: str | None = None,
):
    """Construct a MockConfigEntry with a fake runtime_data namespace."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={"device_tracker": "device_tracker.car"},
        options=options,
        title="ASP Parking Monitor",
    )
    entry.add_to_hass(hass)
    entry.runtime_data = SimpleNamespace(
        data=_FakeData(
            last_resolved=last_resolved,
            confidence_score=confidence_score,
            soda_level=soda_level,
            last_error=last_error,
            last_error_time=last_error_time,
            sign_count=sign_count,
            parse_failures=parse_failures,
            schedule_result=schedule_result,
            special_state=special_state,
        ),
    )
    return entry


# ---------------------------------------------------------------------------
# DIAG-01 tests
# ---------------------------------------------------------------------------


async def test_diagnostics_shape(hass, enable_custom_integrations) -> None:
    """Top-level export keys are exactly {config, state, last_resolve, last_error}."""
    from custom_components.asp_parking.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    entry = _make_entry(
        hass,
        options={
            CONF_PARKING_LAT: 40.7,
            CONF_PARKING_LON: -74.0,
            "movement_threshold": 50,
        },
    )

    out = await async_get_config_entry_diagnostics(hass, entry)

    assert set(out.keys()) == {"config", "state", "last_resolve", "last_error"}


async def test_diagnostics_redacts_lat_lon(
    hass, enable_custom_integrations
) -> None:
    """All five sensitive option keys redact to the literal ``**REDACTED**`` token.

    Token is HA's standard substitution from ``async_redact_data`` (Assumption A2).
    """
    from custom_components.asp_parking.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    entry = _make_entry(
        hass,
        options={
            CONF_PARKING_LAT: 40.7128,
            CONF_PARKING_LON: -74.0060,
            CONF_DEBUG_LAT: 40.5,
            CONF_DEBUG_LON: -74.5,
            CONF_NYC311_API_KEY: "secret123",
            "movement_threshold": 50,
        },
    )

    out = await async_get_config_entry_diagnostics(hass, entry)

    assert out["config"][CONF_PARKING_LAT] == "**REDACTED**"
    assert out["config"][CONF_PARKING_LON] == "**REDACTED**"
    assert out["config"][CONF_DEBUG_LAT] == "**REDACTED**"
    assert out["config"][CONF_DEBUG_LON] == "**REDACTED**"
    assert out["config"][CONF_NYC311_API_KEY] == "**REDACTED**"
    # Sanity passthrough check on a non-sensitive sibling
    assert out["config"]["movement_threshold"] == 50


async def test_diagnostics_passthrough(
    hass, enable_custom_integrations
) -> None:
    """Non-sensitive options pass through unchanged."""
    from custom_components.asp_parking.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    entry = _make_entry(
        hass,
        options={
            "notify_service": "notify.mobile_app_phone",
            "movement_threshold": 50,
            "parking_radius": 500,
            "notify_lead_time": 120,
            "stale_timeout": 8,
            "refresh_interval": 8,
        },
    )

    out = await async_get_config_entry_diagnostics(hass, entry)

    assert out["config"]["notify_service"] == "notify.mobile_app_phone"
    assert out["config"]["movement_threshold"] == 50
    assert out["config"]["parking_radius"] == 500
    assert out["config"]["notify_lead_time"] == 120
    assert out["config"]["stale_timeout"] == 8
    assert out["config"]["refresh_interval"] == 8


async def test_state_section_iso_datetime(
    hass, enable_custom_integrations
) -> None:
    """``state`` section serialises datetimes to ISO 8601 strings."""
    from custom_components.asp_parking.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    entry = _make_entry(
        hass,
        options={"movement_threshold": 50},
        last_resolved=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
        last_error_time=datetime(2026, 5, 1, 13, 30, tzinfo=timezone.utc),
        confidence_score=0.85,
        soda_level=2,
        last_error="boom",
        sign_count=3,
        parse_failures=0,
    )

    out = await async_get_config_entry_diagnostics(hass, entry)

    assert out["state"]["last_resolved"] == "2026-05-01T12:00:00+00:00"
    assert out["state"]["last_error_time"] == "2026-05-01T13:30:00+00:00"
    assert out["state"]["confidence_score"] == 0.85
    assert out["state"]["soda_level"] == 2
    assert out["state"]["last_error"] == "boom"
