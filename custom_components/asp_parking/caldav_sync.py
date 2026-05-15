"""CalDAV calendar synchronisation glue (Phase 34).

Pure async helpers wrapping caldav.aio.AsyncDAVClient. NOT mirrored to
src/gps2asp/. Every coroutine is safe to call from any other module in
this integration. CalDAV-08 is enforced by this module being the sole
caldav importer in the integration and by using ONLY caldav.aio (the
async client) — never caldav.DAVClient (the sync one).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import caldav.aio  # noqa: F401 — module-top import enforces CALDAV-08 statically
from caldav.lib import error as caldav_error  # noqa: F401 — used by Task 2 async API
from icalendar import Calendar, Event

logger = logging.getLogger(__name__)

# RFC 5545 §3.7.3 — PRODID identifies the iCalendar implementation that
# produced the file. Phase 34 D-04 fixes this string for downstream parsers
# and for the test_build_vevent_preserves_tz acceptance criterion.
PRODID = "-//ASP Parking//GPS2ASP//EN"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CalDAVAuthError(Exception):
    """Raised when CalDAV credential validation or API call fails."""


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CalDAVConfig:
    """Immutable CalDAV connection + content configuration.

    Constructed from ``entry.options`` via :meth:`from_options`. All fields
    are mandatory at construction time — the caller is responsible for
    skipping CalDAV-related code paths entirely when the user has not
    configured a CalDAV URL (D-02).
    """

    url: str
    username: str
    password: str
    calendar_url: str
    title_template: str
    safety_window_minutes: int

    @classmethod
    def from_options(cls, options: dict[str, Any]) -> "CalDAVConfig":
        """Build a CalDAVConfig from a HA config entry options dict.

        Imports CONF_CALDAV_* lazily to avoid a circular import between
        ``caldav_sync`` and ``const`` (the latter is small and HA-agnostic,
        but the lazy import keeps the module-import graph simple).
        """
        # Local import to keep the module-load graph minimal and to avoid
        # any potential circular import with .const additions in Plan 03.
        from .const import (  # noqa: PLC0415 — intentional lazy import
            CONF_CALDAV_CALENDAR,
            CONF_CALDAV_EVENT_TITLE_TEMPLATE,
            CONF_CALDAV_PASSWORD,
            CONF_CALDAV_SAFETY_WINDOW,
            CONF_CALDAV_URL,
            CONF_CALDAV_USERNAME,
            DEFAULT_CALDAV_EVENT_TITLE_TEMPLATE,
            DEFAULT_CALDAV_SAFETY_WINDOW,
        )

        return cls(
            url=options[CONF_CALDAV_URL],
            username=options.get(CONF_CALDAV_USERNAME, ""),
            password=options.get(CONF_CALDAV_PASSWORD, ""),
            calendar_url=options.get(CONF_CALDAV_CALENDAR, ""),
            title_template=options.get(
                CONF_CALDAV_EVENT_TITLE_TEMPLATE,
                DEFAULT_CALDAV_EVENT_TITLE_TEMPLATE,
            ),
            safety_window_minutes=int(
                options.get(
                    CONF_CALDAV_SAFETY_WINDOW,
                    DEFAULT_CALDAV_SAFETY_WINDOW,
                )
            ),
        )


# ---------------------------------------------------------------------------
# Template rendering — SafeDict mitigates Don't Hand-Roll row 7
# ---------------------------------------------------------------------------


class _SafeDict(dict):
    """dict subclass that preserves unknown ``{placeholder}`` keys literally.

    ``str.format_map(_SafeDict(fields))`` will never raise KeyError on an
    unknown placeholder; instead the placeholder appears verbatim in the
    output. This protects users who craft a title template containing an
    unsupported placeholder (e.g. ``{borough}``) from breaking the entire
    CalDAV sync.
    """

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render_title(template: str, schedule: Any) -> str:
    """Render the event title template against a ScheduleFound-shaped object.

    Supported placeholders: ``{street}``, ``{side}``, ``{time}``. Unknown
    placeholders are preserved literally via :class:`_SafeDict`.
    """
    fields = {
        "street": getattr(schedule, "on_street", "") or "",
        "side": getattr(schedule, "side_of_street", "") or "",
        "time": getattr(schedule, "summary", "") or "",
    }
    return template.format_map(_SafeDict(fields))


def render_description(schedule: Any) -> str:
    """Render the event DESCRIPTION line per D-06.

    Format: ``"{on_street} ({side_of_street} side)\\n{summary}"`` — used
    verbatim as the VEVENT description. icalendar handles any RFC 5545
    line-wrap escaping at serialisation time.
    """
    return f"{schedule.on_street} ({schedule.side_of_street} side)\n{schedule.summary}"


# ---------------------------------------------------------------------------
# UID derivation — CALDAV-04 (deterministic, survives HA restarts)
# ---------------------------------------------------------------------------


def derive_uid(entry_id: str, window_start: datetime) -> str:
    """Compute a deterministic UID for the VEVENT representing window_start.

    Survives HA restarts and Python hash-seed randomisation (we use
    SHA-256, not the built-in ``hash()``). Two calls with identical
    inputs produce identical 32-hex-char prefixes — the suffix is the
    fixed reverse-DNS-style domain ``@asp-parking.local``.

    Args:
        entry_id: HA config entry ID (unique per integration instance).
        window_start: tz-aware start of the cleaning window. The unix
            timestamp is used (not the ISO string) so DST transitions and
            tzinfo identity differences cannot accidentally split the UID.

    Returns:
        ``"{32 lowercase hex chars}@asp-parking.local"``
    """
    unix_ts = int(window_start.timestamp())
    digest = hashlib.sha256(f"{entry_id}|{unix_ts}".encode("utf-8")).hexdigest()
    return f"{digest[:32]}@asp-parking.local"


# ---------------------------------------------------------------------------
# VEVENT serialisation — Pitfall 9 (tz-aware DTSTART), RFC 5545 (UTC DTSTAMP)
# ---------------------------------------------------------------------------


def build_vevent_ical(
    *,
    uid: str,
    window: Any,
    title: str,
    description: str,
) -> str:
    """Return RFC 5545 iCalendar text for a single VEVENT.

    Trusts the tz-aware ``window.start_datetime`` and ``window.end_datetime``;
    icalendar emits ``DTSTART;TZID=America/New_York:...`` automatically for
    a ZoneInfo-tagged datetime, which is essential for cross-timezone
    correctness (Pitfall 9 — a floating-local DTSTART would render in the
    viewer's local timezone, not NYC's).

    DTSTAMP is always UTC (suffixed ``Z``) per RFC 5545 §3.8.7.2.
    """
    cal = Calendar()
    cal.add("prodid", PRODID)
    cal.add("version", "2.0")

    ev = Event()
    ev.add("uid", uid)
    ev.add("summary", title)
    ev.add("description", description)
    # Pitfall 9: trust the tz-aware datetime; DO NOT call .replace(tzinfo=None).
    ev.add("dtstart", window.start_datetime)
    ev.add("dtend", window.end_datetime)
    # RFC 5545 §3.8.7.2: DTSTAMP MUST be in UTC.
    ev.add("dtstamp", datetime.now(timezone.utc))
    cal.add_component(ev)
    return cal.to_ical().decode("utf-8")
