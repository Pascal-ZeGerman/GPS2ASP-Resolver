"""Diagnostics support for ASP Parking.

Exposes async_get_config_entry_diagnostics() which HA discovers automatically
via integration_platform.async_process_integration_platforms. Sensitive fields
(GPS coordinates, NYC 311 API key) are redacted using HA's async_redact_data
helper. Datetime fields are serialized to ISO strings.

Per Phase 27 D-01..D-04 in .planning/phases/27-diagnostics/27-CONTEXT.md.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse, urlunparse

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_CALDAV_PASSWORD,
    CONF_CALDAV_URL,
    CONF_CALDAV_USERNAME,
    CONF_DEBUG_LAT,
    CONF_DEBUG_LON,
    CONF_NOTIFY_SERVICE,
    CONF_NYC311_API_KEY,
    CONF_PARKING_LAT,
    CONF_PARKING_LON,
)


def _strip_userinfo(url: str) -> str:
    """Strip embedded HTTP Basic credentials from a URL's userinfo section.

    CR-02: The CalDAV URL form field accepts URLs with embedded credentials
    (``https://user:pw@host/path``). The CalDAV URL itself is preserved in
    diagnostics for debugging purposes, but any embedded credentials must be
    removed before emitting the diagnostics blob — otherwise users sharing
    diagnostics on support threads leak their CalDAV password in plain text.

    Returns the URL with userinfo stripped, preserving scheme/host/port/path.
    If parsing fails or no userinfo is present, the input is returned unchanged.
    """
    try:
        parsed = urlparse(url)
    except (ValueError, AttributeError):
        return url
    if not (parsed.username or parsed.password):
        return url
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))

TO_REDACT = {
    CONF_PARKING_LAT,
    CONF_PARKING_LON,
    CONF_DEBUG_LAT,
    CONF_DEBUG_LON,
    CONF_NYC311_API_KEY,
    CONF_NOTIFY_SERVICE,
    # Phase 34: CalDAV credentials only — URL is not secret and useful for debugging
    CONF_CALDAV_USERNAME,
    CONF_CALDAV_PASSWORD,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the ASP Parking config entry.

    Structure (D-01): four top-level sections — config, state, last_resolve,
    last_error — each independently collapsible in the HA Diagnostics viewer.

    Sensitive fields (D-03): parking_lat, parking_lon, debug_lat, debug_lon,
    nyc311_api_key are replaced with the standard HA REDACTED token via
    async_redact_data.

    Defensive (Pitfall #3): when the entry is in 'Setup failed' state, runtime_data
    may not be set. We surface this without crashing.
    """
    config_section = async_redact_data(dict(entry.options), TO_REDACT)

    # CR-02: strip embedded credentials from CalDAV URL. The URL itself is
    # kept (useful for debugging) but ``https://user:pw@host/path`` must not
    # leak ``pw`` in a user-shareable diagnostics artefact.
    if CONF_CALDAV_URL in config_section and isinstance(
        config_section[CONF_CALDAV_URL], str
    ):
        config_section[CONF_CALDAV_URL] = _strip_userinfo(
            config_section[CONF_CALDAV_URL]
        )

    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None or not hasattr(coordinator, "data"):
        return {
            "config": config_section,
            "state": None,
            "last_resolve": None,
            "last_error": {"setup_status": "not_ready"},
        }

    data = coordinator.data

    # Schedule summary — only ScheduleFound and ASPActiveNow expose .summary
    schedule_summary: str | None = None
    if data.schedule_result is not None and hasattr(data.schedule_result, "summary"):
        schedule_summary = data.schedule_result.summary

    schedule_status: str | None = None
    if data.schedule_result is not None and hasattr(data.schedule_result, "status"):
        schedule_status = data.schedule_result.status

    last_resolved_iso = data.last_resolved.isoformat() if data.last_resolved else None
    last_error_time_iso = (
        data.last_error_time.isoformat() if data.last_error_time else None
    )

    return {
        "config": config_section,
        "state": {
            "confidence_score": data.confidence_score,
            "soda_level": data.soda_level,
            "schedule_summary": schedule_summary,
        },
        "last_resolve": {
            "last_resolved": last_resolved_iso,
            "sign_count": data.sign_count,
            "parse_failures": data.parse_failures,
            "soda_level": data.soda_level,
            "special_state": data.special_state,
            "schedule_status": schedule_status,
        },
        "last_error": {
            "last_error": data.last_error,
            "last_error_time": last_error_time_iso,
        },
    }
