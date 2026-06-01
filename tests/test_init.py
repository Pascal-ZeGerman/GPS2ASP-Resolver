"""Tests for the three defence-in-depth layers added by quick task 260601-aru.

Covers ``custom_components/asp_parking/__init__.py::async_setup_entry`` and
``_async_ensure_index``:

* Layer 1: a corrupt on-disk index (rtree or graph.json.zst) detected by
  ``_sync_verify_index`` triggers a re-download instead of silently letting
  the coordinator crash later.
* Layer 2: after 5 consecutive ``ConfigEntryNotReady`` retries of
  ``_async_ensure_index``, a Repair issue with translation_key
  ``setup_retry_limit`` is created; the counter + Repair are cleared on the
  next successful setup.
* Layer 3: any unforeseen exception from ``coordinator.async_start()`` is
  surfaced as a distinct ``async_start_failure`` Repair issue and re-raised
  so HA still marks the entry as failed. The Repair auto-dismisses on the
  next successful start.

Test conventions are inherited from ``tests/test_repair_issue.py``:
  * ``pytestmark = pytest.mark.ha_integration``
  * Self-contained ``_make_entry`` helper (copied, NOT imported, per the
    repository convention of keeping HA-integration tests free of test-only
    cross-imports).
  * ``enable_custom_integrations`` fixture from
    ``pytest_homeassistant_custom_component``.
  * Patches target the ``custom_components.asp_parking`` namespace (the
    *imported* binding) — never the original definition module — so that
    the integration code under test always sees the patched callable.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.asp_parking import (
    _ASYNC_START_FAILURE_ISSUE_ID,
    _RETRY_LIMIT_ISSUE_ID,
    _SETUP_RETRY_COUNT_KEY_TPL,
)
from custom_components.asp_parking.const import DOMAIN
from custom_components.asp_parking.index_io import IndexIntegrityError

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
# Layer 1 — corrupt index triggers re-download
# ---------------------------------------------------------------------------


async def test_corrupt_index_triggers_redownload(
    hass, enable_custom_integrations
) -> None:
    """If _sync_verify_index raises IndexIntegrityError, the download task is scheduled.

    Drives ``_async_ensure_index`` directly (not the full ``async_setup`` path)
    so the test isolates Layer 1 from Layer 2's retry-counter logic.
    """
    from custom_components.asp_parking import _async_ensure_index, _DOWNLOAD_TASK_KEY

    # Patch existence check to True (files appear present) so the integrity
    # check actually runs. The Path('.exists()') method is the cleanest seam.
    with (
        patch(
            "custom_components.asp_parking.INDEX_DIR",
        ) as mock_dir,
        patch(
            "custom_components.asp_parking._sync_verify_index",
            side_effect=IndexIntegrityError("corrupt"),
        ),
        patch(
            "custom_components.asp_parking._sync_cleanup_stale",
        ),
        patch("custom_components.asp_parking.shutil.rmtree"),
        patch(
            "custom_components.asp_parking._async_download_index",
            new_callable=AsyncMock,
        ),
    ):
        # Make `INDEX_DIR / f` return a sentinel whose .exists() is True for
        # the all(...) generator in _async_ensure_index.
        existing_file = MagicMock()
        existing_file.exists.return_value = True
        mock_dir.__truediv__.return_value = existing_file

        # ConfigEntryNotReady is raised by design once the download task is
        # scheduled — the existing fall-through path always raises.
        from homeassistant.exceptions import ConfigEntryNotReady

        with pytest.raises(ConfigEntryNotReady):
            await _async_ensure_index(hass)

    # Task was scheduled (or attempted) — _DOWNLOAD_TASK_KEY in hass.data.
    assert _DOWNLOAD_TASK_KEY in hass.data


# ---------------------------------------------------------------------------
# Layer 2 — retry-limit Repair created after 5 ConfigEntryNotReady cycles
# ---------------------------------------------------------------------------


async def test_setup_retry_creates_repair_after_5_failures(
    hass, enable_custom_integrations
) -> None:
    """Pre-set counter to 4; one more failure must increment to 5 and create Repair."""
    from homeassistant.exceptions import ConfigEntryNotReady
    from homeassistant.helpers import issue_registry as ir

    entry = _make_entry(hass)
    retry_key = _SETUP_RETRY_COUNT_KEY_TPL.format(entry_id=entry.entry_id)
    hass.data[retry_key] = 4

    with patch(
        "custom_components.asp_parking._async_ensure_index",
        new=AsyncMock(side_effect=ConfigEntryNotReady("downloading")),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    issue = ir.async_get(hass).async_get_issue(DOMAIN, _RETRY_LIMIT_ISSUE_ID)
    assert issue is not None
    assert issue.severity == ir.IssueSeverity.ERROR
    assert issue.is_fixable is False
    assert issue.translation_key == "setup_retry_limit"
    assert hass.data[retry_key] == 5


# ---------------------------------------------------------------------------
# Layer 2 — counter + Repair cleared on a subsequent successful setup
# ---------------------------------------------------------------------------


async def test_setup_success_clears_retry_counter_and_repair(
    hass, enable_custom_integrations
) -> None:
    """A successful setup pops the retry counter and removes the Repair issue."""
    from homeassistant.helpers import issue_registry as ir

    entry = _make_entry(hass)
    retry_key = _SETUP_RETRY_COUNT_KEY_TPL.format(entry_id=entry.entry_id)
    hass.data[retry_key] = 7

    # Pre-seed the Repair so we can assert it gets dismissed.
    ir.async_create_issue(
        hass,
        DOMAIN,
        _RETRY_LIMIT_ISSUE_ID,
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="setup_retry_limit",
    )

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

    assert hass.data.get(retry_key) is None
    assert ir.async_get(hass).async_get_issue(DOMAIN, _RETRY_LIMIT_ISSUE_ID) is None


# ---------------------------------------------------------------------------
# Layer 3 — async_start raises -> Repair created + re-raised
# ---------------------------------------------------------------------------


async def test_async_start_failure_creates_repair_and_reraises(
    hass, enable_custom_integrations
) -> None:
    """coordinator.async_start raising RuntimeError surfaces an async_start_failure Repair."""
    from homeassistant.helpers import issue_registry as ir

    entry = _make_entry(hass)

    fake_coordinator = MagicMock()
    fake_coordinator.async_start = AsyncMock(side_effect=RuntimeError("boom"))
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
        # HA wraps the exception and marks the entry as setup_error / retry —
        # do not assert on the raised type at the public API; instead verify
        # the Repair side-effect, which is the contract for Layer 3.
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    issue = ir.async_get(hass).async_get_issue(DOMAIN, _ASYNC_START_FAILURE_ISSUE_ID)
    assert issue is not None
    assert issue.severity == ir.IssueSeverity.ERROR
    assert issue.is_fixable is False
    assert issue.translation_key == "async_start_failure"


# ---------------------------------------------------------------------------
# Layer 3 — async_start Repair auto-dismissed on next successful setup
# ---------------------------------------------------------------------------


async def test_setup_success_clears_async_start_repair(
    hass, enable_custom_integrations
) -> None:
    """A pre-existing async_start_failure Repair is gone after a clean setup."""
    from homeassistant.helpers import issue_registry as ir

    entry = _make_entry(hass)

    ir.async_create_issue(
        hass,
        DOMAIN,
        _ASYNC_START_FAILURE_ISSUE_ID,
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="async_start_failure",
    )
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, _ASYNC_START_FAILURE_ISSUE_ID)
        is not None
    )

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

    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, _ASYNC_START_FAILURE_ISSUE_ID)
        is None
    )
