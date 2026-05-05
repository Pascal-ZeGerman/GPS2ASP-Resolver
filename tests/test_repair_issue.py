"""Verify ImportError handling creates a repair issue and auto-dismisses on success (DIAG-02/03).

Wave 0 RED tests for Phase 27. These tests fail until Plan 04 wires
``async_setup_entry`` to:

  * Catch ImportError raised by the gps2asp coordinator import.
  * Log an actionable ERROR mentioning ``gps2asp`` and ``reinstall via HACS``.
  * Create a repair issue ``(asp_parking, gps2asp_import_error)`` with
    ``severity=ERROR`` and ``is_fixable=False``.
  * Delete the same repair issue on a subsequent successful setup.

Per Pitfall #1 (27-RESEARCH.md), the ONLY supported import path for repair
issues in HA 2026.x is ``homeassistant.helpers.issue_registry``. The legacy
helper-module path under ``homeassistant.components`` is intentionally avoided.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.asp_parking.const import DOMAIN

pytestmark = pytest.mark.ha_integration


def _make_entry(hass):
    """Create and add a v2 MockConfigEntry for the asp_parking integration."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={"device_tracker": "device_tracker.car"},
        options={},
        title="ASP Parking Monitor",
    )
    entry.add_to_hass(hass)
    return entry


# ---------------------------------------------------------------------------
# DIAG-02 — actionable log line
# ---------------------------------------------------------------------------


async def test_import_error_logs_actionable(
    hass, enable_custom_integrations, caplog
) -> None:
    """ImportError during setup logs an ERROR mentioning gps2asp + reinstall via HACS."""
    caplog.set_level(logging.ERROR, logger="custom_components.asp_parking")

    entry = _make_entry(hass)

    with (
        patch(
            "custom_components.asp_parking._async_ensure_index",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.asp_parking.ASPParkingCoordinator",
            side_effect=ImportError("simulated missing gps2asp.signs"),
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert "gps2asp" in caplog.text
    assert "reinstall via HACS" in caplog.text


# ---------------------------------------------------------------------------
# DIAG-02/03 — repair issue creation
# ---------------------------------------------------------------------------


async def test_import_error_creates_repair(hass, enable_custom_integrations) -> None:
    """ImportError during setup creates the gps2asp_import_error repair issue."""
    from homeassistant.helpers import issue_registry as ir

    entry = _make_entry(hass)

    with (
        patch(
            "custom_components.asp_parking._async_ensure_index",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.asp_parking.ASPParkingCoordinator",
            side_effect=ImportError("simulated"),
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    issue_reg = ir.async_get(hass)
    issue = issue_reg.async_get_issue(DOMAIN, "gps2asp_import_error")

    assert issue is not None
    assert issue.severity == ir.IssueSeverity.ERROR
    assert issue.is_fixable is False
    assert issue.translation_key == "gps2asp_import_error"


# ---------------------------------------------------------------------------
# DIAG-03 — repair issue auto-dismiss on successful setup
# ---------------------------------------------------------------------------


async def test_setup_dismisses_repair(hass, enable_custom_integrations) -> None:
    """A pre-existing repair issue is removed when setup succeeds (D-07)."""
    from homeassistant.helpers import issue_registry as ir

    entry = _make_entry(hass)

    # Pre-seed the repair issue as if a previous setup had failed
    ir.async_create_issue(
        hass,
        DOMAIN,
        "gps2asp_import_error",
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="gps2asp_import_error",
    )
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, "gps2asp_import_error") is not None
    )

    # Now run a successful setup. Patch the index-ensure helper to a no-op so
    # the test does not require a built spatial index, and patch the
    # coordinator to a stub whose async_start / async_stop are awaitable so
    # async_setup_entry / async_unload_entry both complete cleanly. We also
    # patch async_forward_entry_setups to avoid bringing up the entity
    # platforms (which would try to introspect coordinator.data fields).
    fake_coordinator = MagicMock()
    fake_coordinator.async_start = AsyncMock()
    fake_coordinator.async_stop = AsyncMock()
    with (
        patch(
            "custom_components.asp_parking._async_ensure_index",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.asp_parking.ASPParkingCoordinator",
            return_value=fake_coordinator,
        ),
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert ir.async_get(hass).async_get_issue(DOMAIN, "gps2asp_import_error") is None
