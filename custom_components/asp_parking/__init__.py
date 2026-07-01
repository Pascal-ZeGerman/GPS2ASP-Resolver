"""ASP Parking - Alternate Side Parking integration for Home Assistant.

Creates the ASPParkingCoordinator, stores it in runtime_data, forwards
sensor and binary_sensor platforms, registers the resolve_now service,
and sets up an options update listener for reconfiguration.
"""

from __future__ import annotations

import logging
import shutil

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir

from .const import (
    CONF_CALDAV_CALENDAR,
    CONF_CALDAV_PASSWORD,
    CONF_CALDAV_URL,
    CONF_CALDAV_USERNAME,
    DOMAIN,
    INDEX_DOWNLOAD_URL,
    PLATFORMS,
)
from .coordinator import ASPParkingCoordinator
from .index_io import (
    INDEX_DIR,
    INDEX_FILES,
    IndexIntegrityError,
    _sync_atomic_swap,
    _sync_cleanup_stale,
    _sync_download_and_extract,
    _sync_verify_index,
)

logger = logging.getLogger(__name__)

_DOWNLOAD_TASK_KEY = f"{DOMAIN}_index_task"
_IMPORT_ERROR_ISSUE_ID = "gps2asp_import_error"

# Quick task 260601-aru — three new defence-in-depth layers around startup.
# Per-entry retry counter for _async_ensure_index ConfigEntryNotReady cycles;
# at >=5 consecutive retries we surface a user-visible Repair issue.
_SETUP_RETRY_COUNT_KEY_TPL = f"{DOMAIN}_setup_retry_count_{{entry_id}}"
_RETRY_LIMIT_ISSUE_ID = "asp_parking_setup_retry_limit"
# Distinct issue_id (NOT shared with _IMPORT_ERROR_ISSUE_ID or
# _RETRY_LIMIT_ISSUE_ID) so the Repair UI can route translations correctly
# and so dismissal of one does not silence the others.
_ASYNC_START_FAILURE_ISSUE_ID = "asp_parking_async_start_failure"

# Per-entry cache of CalDAV options captured at setup time.  Keyed by
# f"{DOMAIN}_caldav_opts_{entry.entry_id}" so multiple instances never clash.
# Used by _async_options_updated to access the OLD credentials after HA has
# already written the new options to entry.options.
_CALDAV_OPTIONS_CACHE_KEY_TPL = f"{DOMAIN}_caldav_opts_{{entry_id}}"


async def _async_ensure_index(hass: HomeAssistant) -> None:
    """Ensure spatial index files are present, downloading on first setup.

    Raises ConfigEntryNotReady while the download is in progress so HA retries
    automatically. After the download completes, the next retry succeeds.
    """
    from homeassistant.components.persistent_notification import (
        async_dismiss as pn_dismiss,
    )

    # Dismiss any stale error notification from a previous failed download attempt
    pn_dismiss(hass, "asp_parking_index_error")

    if all((INDEX_DIR / f).exists() for f in INDEX_FILES):
        # Layer 1 (quick task 260601-aru): existence is necessary but not
        # sufficient — actually open the rtree and decompress 1 byte of the
        # graph file to confirm the files are USABLE, not just present.
        # On corruption (truncated download, partial extraction, disk decay):
        # wipe the live index dir and fall through to the normal download
        # path. We MUST NOT raise IndexIntegrityError here — the
        # ConfigEntryNotReady raised below preserves HA's existing retry/
        # backoff semantics that the rest of this module depends on.
        try:
            await hass.async_add_executor_job(_sync_verify_index, INDEX_DIR)
        except IndexIntegrityError as err:
            logger.warning(
                "ASP Parking: on-disk index failed integrity check (%s); "
                "re-downloading",
                err,
            )
            # Force re-download by removing the live INDEX_DIR (and any stale
            # _tmp/_bak siblings). cleanup_stale is idempotent and safe even
            # if the rmtree below has not yet run.
            await hass.async_add_executor_job(_sync_cleanup_stale, INDEX_DIR)
            await hass.async_add_executor_job(
                shutil.rmtree,
                INDEX_DIR,
                True,  # ignore_errors=True
            )
            # Intentional fall-through to the download path below.
        else:
            return

    task = hass.data.get(_DOWNLOAD_TASK_KEY)

    if task is None:
        task = hass.async_create_task(
            _async_download_index(hass),
            name="asp_parking_index_download",
        )
        hass.data[_DOWNLOAD_TASK_KEY] = task
    elif task.done() and (exc := task.exception()) is not None:
        raise ConfigEntryNotReady(
            f"Spatial index download failed: {exc}. See documentation for manual setup."
        ) from exc

    raise ConfigEntryNotReady(
        "Downloading NYC street index (~73 MB), will retry automatically"
    )


async def _async_download_index(hass: HomeAssistant) -> None:
    """Download and extract the spatial index ZIP from the GitHub release.

    Phase 33 D-01: this first-time-setup flow now consumes the same shared
    sync helpers from ``index_io.py`` that the manual rebuild flow uses
    (single source of truth for zip-slip safety + atomic swap). The
    first-time-setup notification IDs (``asp_parking_index_download`` /
    ``asp_parking_index_error``) remain DISTINCT from the rebuild-flow IDs
    by design -- different UX for different lifecycle events (RESEARCH
    Pitfall 7).
    """
    from homeassistant.components.persistent_notification import (
        async_create as pn_create,
        async_dismiss as pn_dismiss,
    )

    pn_create(
        hass,
        "Downloading NYC street index (~73 MB). ASP Parking will start automatically when complete.",
        title="ASP Parking: First-Time Setup",
        notification_id="asp_parking_index_download",
    )

    try:
        # D-01 single source of truth: same three sync helpers the manual
        # rebuild flow uses (coordinator._async_do_rebuild). cleanup_stale
        # is idempotent — safe on a fresh install where no _tmp/_bak exist.
        await hass.async_add_executor_job(_sync_cleanup_stale, INDEX_DIR)
        await hass.async_add_executor_job(
            _sync_download_and_extract, INDEX_DIR, INDEX_DOWNLOAD_URL
        )
        await hass.async_add_executor_job(_sync_atomic_swap, INDEX_DIR)
        hass.data.pop(_DOWNLOAD_TASK_KEY, None)
        pn_dismiss(hass, "asp_parking_index_download")
        logger.info("ASP Parking: spatial index downloaded to %s", INDEX_DIR)
    except Exception as err:
        hass.data.pop(_DOWNLOAD_TASK_KEY, None)
        pn_dismiss(hass, "asp_parking_index_download")
        pn_create(
            hass,
            f"Failed to download spatial index: {err}. "
            "Place index files manually — see documentation.",
            title="ASP Parking: Setup Error",
            notification_id="asp_parking_index_error",
        )
        logger.error("ASP Parking: index download failed: %s", err)
        raise


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate config entry from version 1 to 2.

    No data shape change needed -- NYC311 API key defaults to not-configured.
    """
    if config_entry.version == 1:
        hass.config_entries.async_update_entry(config_entry, version=2)
        logger.info("Migrated ASP Parking config entry from v1 to v2")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ASP Parking from a config entry.

    Creates the coordinator, starts GPS tracking, forwards entity platforms,
    registers the resolve_now service, and sets up options change listener.

    On ImportError from the vendored gps2asp package (DIAG-02/03), logs an
    actionable error message, creates a persistent HA Repair issue, and
    raises ConfigEntryNotReady. On every successful setup attempt, any
    stale repair issue is auto-dismissed first (D-07).

    Args:
        hass: Home Assistant instance.
        entry: Config entry for this integration instance.

    Returns:
        True if setup was successful.
    """
    # D-07: auto-dismiss stale repair on every setup attempt (no-op if absent).
    # Runs first so a successful HACS reinstall clears the Repairs badge automatically.
    # Quick task 260601-aru: also dismiss the two new Repair issues — they are
    # auto-clearing by design (next successful setup resolves the symptom).
    ir.async_delete_issue(hass, DOMAIN, _IMPORT_ERROR_ISSUE_ID)
    ir.async_delete_issue(hass, DOMAIN, _RETRY_LIMIT_ISSUE_ID)
    ir.async_delete_issue(hass, DOMAIN, _ASYNC_START_FAILURE_ISSUE_ID)

    # Layer 2 (quick task 260601-aru): track _async_ensure_index retry count so
    # we can surface a user-visible Repair once HA's backoff has consumed
    # ~5 consecutive ConfigEntryNotReady cycles without progress (~5 minutes
    # of "Downloading…" with no end in sight is the actionable threshold).
    retry_key = _SETUP_RETRY_COUNT_KEY_TPL.format(entry_id=entry.entry_id)
    try:
        await _async_ensure_index(hass)
    except ConfigEntryNotReady:
        count = int(hass.data.get(retry_key, 0)) + 1
        hass.data[retry_key] = count
        if count >= 5:
            ir.async_create_issue(
                hass,
                DOMAIN,
                _RETRY_LIMIT_ISSUE_ID,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="setup_retry_limit",
            )
        raise

    # Index ensured successfully — clear the retry counter. The Repair issue
    # itself was already dismissed at the top of this function.
    hass.data.pop(retry_key, None)

    # D-06: guard the gps2asp-dependent coordinator instantiation. Late
    # vendored imports happen inside the coordinator's __init__ chain;
    # ImportError surfaces here. (Module-level coordinator.py import failure
    # is caught at HA's own integration loader -- see 27-04-SUMMARY.)
    try:
        coordinator = ASPParkingCoordinator(hass, entry)
    except ImportError as err:
        logger.error(
            "ASP Parking: gps2asp vendored package is incomplete -- "
            "reinstall via HACS. (%s)",
            err,
        )
        ir.async_create_issue(
            hass,
            DOMAIN,
            _IMPORT_ERROR_ISSUE_ID,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="gps2asp_import_error",
        )
        raise ConfigEntryNotReady(
            "gps2asp vendored package is incomplete -- reinstall via HACS"
        ) from err

    entry.runtime_data = coordinator

    # Layer 3 (quick task 260601-aru): wrap coordinator.async_start() so any
    # unforeseen startup exception leaves a visible Repair entry. Bare
    # ``raise`` preserves the original traceback for HA's logs.
    try:
        await coordinator.async_start()
    except Exception as err:  # noqa: BLE001 — defence-in-depth: catch all startup failures
        logger.error(
            "ASP Parking: coordinator.async_start() raised %s: %s; "
            "see HA logs for traceback",
            type(err).__name__,
            err,
        )
        ir.async_create_issue(
            hass,
            DOMAIN,
            _ASYNC_START_FAILURE_ISSUE_ID,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="async_start_failure",
        )
        raise

    # Snapshot the CalDAV-relevant options so _async_options_updated can access
    # the OLD credentials after HA has already written new options to entry.options.
    _cache_key = _CALDAV_OPTIONS_CACHE_KEY_TPL.format(entry_id=entry.entry_id)
    hass.data[_cache_key] = dict(entry.options)

    # Forward entity platforms (sensor, binary_sensor)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register resolve_now service (idempotent -- only if not already registered)
    async def async_resolve_now(call: ServiceCall) -> None:
        """Service handler for resolve_now."""
        await coordinator.async_force_resolve()

    if not hass.services.has_service(DOMAIN, "resolve_now"):
        hass.services.async_register(DOMAIN, "resolve_now", async_resolve_now)

    # Reload integration when options change (e.g., threshold reconfiguration)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    logger.info("ASP Parking integration setup complete for %s", entry.title)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an ASP Parking config entry.

    Stops the coordinator and unloads entity platforms.

    Args:
        hass: Home Assistant instance.
        entry: Config entry being unloaded.

    Returns:
        True if unload was successful.
    """
    # Stop the coordinator (cancels listeners, debouncer)
    await entry.runtime_data.async_stop()

    # Unload entity platforms
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up the CalDAV event before HA forgets this config entry (CALDAV-07).

    Note: this runs AFTER async_unload_entry — runtime_data is no longer
    available; we must reconstruct the Store from scratch.

    Best-effort guarantees (Phase 34 Plan 05):
      - D-02 zero-cost no-op when CONF_CALDAV_URL is absent.
      - Pitfall 5: empty/missing Store data is gracefully handled — no
        delete_event call, no exception raised.
      - On caldav_sync.delete_event failure, the exception is caught +
        logged at WARNING; the Store file is STILL removed (T-34-13
        mitigation — leave a clean state for any future re-install).
      - Credentials are NEVER included in the failure log line (T-34-01).
    """
    # D-02 guard FIRST — zero-cost no-op when CalDAV was never configured.
    if not entry.options.get(CONF_CALDAV_URL):
        return

    # Lazy imports inside the function body — caldav has a ~25 MB transitive
    # dep tree (RESEARCH §finding 2) and homeassistant.helpers.storage is
    # only needed on the rare remove-entry path; keep module-top imports
    # focused on the hot setup path.
    from homeassistant.helpers.storage import Store

    from . import caldav_sync

    # Reconstruct Store using the SAME storage_key Plan 04 uses in
    # async_start — same Store namespace.
    store: Store[dict[str, str]] = Store(
        hass, version=1, key=f"{DOMAIN}_caldav_{entry.entry_id}"
    )
    raw = await store.async_load()
    # Pitfall 5 coercion: handle first-load (None) and empty-dict cases.
    uid = (raw or {}).get("uid")

    if uid:
        password = entry.options.get(CONF_CALDAV_PASSWORD, "")
        try:
            await caldav_sync.delete_event(
                url=entry.options[CONF_CALDAV_URL],
                username=entry.options.get(CONF_CALDAV_USERNAME, ""),
                password=password,
                calendar_url=entry.options.get(CONF_CALDAV_CALENDAR, ""),
                uid=uid,
            )
        except Exception:  # noqa: BLE001 — best-effort: never block uninstall
            # T-34-01 / T-34-08: the log line excludes username, password,
            # URL, and the raw exception object (which could embed creds).
            # Only the UID — a deterministic hash — is included so the user
            # can locate the orphan event manually if needed.
            logger.warning(
                "ASP Parking: CalDAV delete during remove failed; "
                "manual cleanup may be needed (uid=%s)",
                uid,
            )

    # ALWAYS remove the Store file — even on delete failure — to leave a
    # clean state (T-34-13 mitigation; test_async_remove_entry_continues_when_delete_fails).
    await store.async_remove()


async def _async_caldav_cleanup_on_deconfigure(
    hass: HomeAssistant,
    entry: ConfigEntry,
    old_options: dict,
) -> None:
    """Delete the stored CalDAV event when the user removes the CalDAV URL.

    Mirrors the pattern from async_remove_entry but uses the OLD credentials
    (captured before HA overwrote entry.options) so the delete call can reach
    the server. Called only when old CalDAV URL was set and new URL is absent.

    Best-effort: all exceptions are caught so the subsequent reload always runs.
      - Pitfall 5: empty/missing Store data (no uid) → no delete attempt.
      - On delete failure: log at WARNING, continue. Store uid key is removed
        regardless to avoid a stale pointer on the next setup cycle.
      - T-34-01: credentials are never included in log output.
    """
    # Lazy imports — same reasoning as in async_remove_entry: heavy dep tree
    # (caldav + icalendar) should not appear in the hot setup-entry path.
    from homeassistant.helpers.storage import Store

    from . import caldav_sync

    # Reconstruct the Store using the same key the coordinator uses in async_start.
    store: Store[dict[str, str]] = Store(
        hass, version=1, key=f"{DOMAIN}_caldav_{entry.entry_id}"
    )
    raw = await store.async_load()
    uid = (raw or {}).get("uid")

    if not uid:
        # Nothing stored — CalDAV was configured but no event was ever written.
        return

    password = old_options.get(CONF_CALDAV_PASSWORD, "")
    try:
        await caldav_sync.delete_event(
            url=old_options[CONF_CALDAV_URL],
            username=old_options.get(CONF_CALDAV_USERNAME, ""),
            password=password,
            calendar_url=old_options.get(CONF_CALDAV_CALENDAR, ""),
            uid=uid,
        )
    except Exception:  # noqa: BLE001 — best-effort; never block reload
        # T-34-01 / T-34-08: no URL, username, password, or raw exception in log.
        logger.warning(
            "ASP Parking: CalDAV delete on deconfigure failed; "
            "manual cleanup may be needed (uid=%s)",
            uid,
        )

    # Clear the uid from the Store so the next setup cycle starts clean.
    # Pop-then-save pattern (Finding 8) preserves any other future store keys.
    data = (raw or {}).copy()
    data.pop("uid", None)
    await store.async_save(data)


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update by reloading the integration.

    If the user removed the CalDAV URL (transition from set → empty), clean up
    the stored calendar event using the OLD credentials before reloading.  This
    prevents orphan events from accumulating on the server (CALDAV-07 extension).

    The old options are read from hass.data (snapshot written in async_setup_entry)
    because entry.options already reflects the NEW values by the time this listener
    fires.

    Args:
        hass: Home Assistant instance.
        entry: Config entry whose options were updated.
    """
    _cache_key = _CALDAV_OPTIONS_CACHE_KEY_TPL.format(entry_id=entry.entry_id)
    old_options: dict = hass.data.get(_cache_key, {})

    old_caldav_url = old_options.get(CONF_CALDAV_URL, "")
    new_caldav_url = entry.options.get(CONF_CALDAV_URL, "")

    if old_caldav_url and not new_caldav_url:
        # CalDAV URL was removed — clean up the orphan calendar event before reload.
        await _async_caldav_cleanup_on_deconfigure(hass, entry, old_options)

    await hass.config_entries.async_reload(entry.entry_id)
