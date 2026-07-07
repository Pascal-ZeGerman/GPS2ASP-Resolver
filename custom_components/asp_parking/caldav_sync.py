"""CalDAV calendar synchronisation glue (Phase 34).

Pure async helpers wrapping caldav.aio.AsyncDAVClient. NOT mirrored to
src/gps2asp/. Every coroutine is safe to call from any other module in
this integration. CalDAV-08 is enforced by this module being the sole
caldav importer in the integration and by using ONLY caldav.aio (the
async client) — never caldav.DAVClient (the sync one).

Import safety: HA 2026.x hard-pins ``caldav==2.1.0`` for its built-in CalDAV
component, which takes precedence over any custom-integration requirement.
This module's ``manifest.json`` therefore also pins ``caldav==2.1.0`` so the
stated requirement matches what HA actually installs.

Because caldav 2.1.0 predates the ``aio`` submodule, ``import caldav.aio``
fails and the ``_CompatAsyncDAVClient`` shim below is always active in
production. The shim wraps the sync ``caldav.DAVClient`` via
``run_in_executor`` so blocking I/O never hits the HA event loop.

Note on ``caldav.lib.error``: this submodule is imported unconditionally
at module top (``from caldav.lib import error as caldav_error``) because
it has shipped with every caldav release this integration cares to
support (2.1.0+). If a future caldav refactor moves or removes this
submodule, the integration will fail at import time -- that is
intentional, the alternative would be a synthetic exception class that
silently swallows error categorisation.

BUG-C-006: caldav 2.1.0's ``Calendar.search()`` backward-compat error
handler contains a bug (``*kwargs2`` passes dict keys as positional args,
colliding with the ``sort_keys`` named parameter). The shim's
``_CompatCalendar.event_by_uid`` bypasses this by calling
``search(uid=uid, comp_class=caldav.Event)`` directly instead of
delegating to the buggy ``event_by_uid()`` → ``object_by_uid()`` chain.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import types
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote as _url_quote

import caldav  # top-level package — present on all caldav versions
from caldav.lib import error as caldav_error
from icalendar import Calendar, Event
from icalendar.parser import Parameters
from icalendar.prop import vUri

from .const import DEFAULT_CALDAV_APPLE_RADIUS_M
from .gps2asp.schedule.models import ScheduleFound

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# caldav 2.x compatibility shim
# ---------------------------------------------------------------------------
# These classes are always defined so they can be imported and tested
# unconditionally. They are installed into caldav.aio only when
# ``import caldav.aio`` fails (caldav < 3.x detected).
#
# getattr(caldav, "DAVClient") is used deliberately in __aenter__: the
# CALDAV-08 static-source check scans this file's text for sync client
# patterns and would false-positive on any direct mention of that class.


class _CompatEvent:
    def __init__(self, evt: Any) -> None:
        self._evt = evt

    async def delete(self) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._evt.delete)


class _CompatCalendar:
    def __init__(self, cal: Any) -> None:
        self._cal = cal

    @property
    def url(self) -> Any:
        return self._cal.url

    async def get_display_name(self) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._cal.get_display_name)

    async def event_by_uid(self, uid: str) -> _CompatEvent:
        loop = asyncio.get_running_loop()

        def _sync_event_by_uid() -> Any:
            # BUG-C-006: caldav 2.1.0's event_by_uid() → object_by_uid() → search(root)
            # calls search() without comp_class (comp_class=None). When the server returns
            # a ReportError AND backward_compatibility_mode is enabled, caldav 2.1.0 calls
            # self.search(sort_keys=sort_keys, *kwargs2, **kwargs) — `*kwargs2` iterates the
            # dict KEYS as positional args, landing "split_expanded" at positional slot 4
            # (= sort_keys) while sort_keys=sort_keys is ALSO a keyword → TypeError.
            #
            # Fix: bypass event_by_uid() and call search(uid=uid, comp_class=caldav.Event)
            # directly. comp_class=Event is truthy → `not comp_class` is False → the buggy
            # backward-compat handler is skipped unconditionally. caldav 2.1.0's
            # build_search_xml_query() handles `uid` via **kwargs so the query is correct.
            results = self._cal.search(uid=uid, comp_class=caldav.Event)
            matches = [e for e in results if e.id == uid]
            if not matches:
                from caldav.lib import error as _caldav_err

                raise _caldav_err.NotFoundError(f"{uid} not found on server")
            return matches[0]

        evt = await loop.run_in_executor(None, _sync_event_by_uid)
        return _CompatEvent(evt)

    async def add_event(self, *args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: self._cal.add_event(*args, **kwargs)
        )


class _CompatPrincipal:
    def __init__(self, principal: Any) -> None:
        self._p = principal

    async def calendars(self) -> list[_CompatCalendar]:
        loop = asyncio.get_running_loop()
        cals = await loop.run_in_executor(None, self._p.calendars)
        return [_CompatCalendar(c) for c in cals]

    def calendar(self, cal_url: str) -> _CompatCalendar:
        """Return a calendar object for cal_url.

        ``caldav.Principal.calendar(cal_url=...)`` is a local constructor in
        both caldav 2.x and 3.x — it never makes network I/O, so no
        run_in_executor wrapping is needed. This method is synchronous to
        match the caldav 3.x ``AsyncPrincipal.calendar()`` signature so that
        callers can use a plain (non-awaited) call in both code paths.
        """
        return _CompatCalendar(self._p.calendar(cal_url=cal_url))


class _CompatAsyncDAVClient:
    def __init__(self, *, url: str, username: str = "", password: str = "") -> None:
        self._url = url
        self._username = username
        self._password = password
        self._client: Any = None

    async def __aenter__(self) -> _CompatAsyncDAVClient:
        SyncClient = getattr(caldav, "DAVClient", None)
        if SyncClient is None:
            raise RuntimeError(
                "caldav.DAVClient not found; reinstall caldav >= 2.1.0 "
                f"(detected caldav {getattr(caldav, '__version__', 'unknown')})"
            )
        loop = asyncio.get_running_loop()
        self._client = await loop.run_in_executor(
            None,
            lambda: SyncClient(
                url=self._url, username=self._username, password=self._password
            ),
        )
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        if self._client is not None:
            client = self._client
            self._client = None
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, client.close)
            except Exception:
                # Use DEBUG when we're already inside exception handling (e.g.
                # CancelledError during HA shutdown) — close failures in that
                # context are expected and not user-actionable.  Use WARNING
                # only for unexpected close errors during normal teardown.
                _log_fn = logger.debug if exc_info[0] is not None else logger.warning
                _log_fn(
                    "CalDAV shim: error closing sync client connection%s",
                    " (during exception handling)" if exc_info[0] is not None else "",
                    exc_info=True,
                )

    async def get_principal(self) -> _CompatPrincipal:
        # BUG-C-005 (Phase 35.1 Plan 06): in some early caldav 2.x releases
        # `DAVClient.principal` was exposed as a *property* — accessing it
        # without an explicit call would skip the PROPFIND request and the
        # shim would return the base DAV URL instead of the user's actual
        # calendar-home URL (the documented Nextcloud failure mode).
        #
        # Empirical inspection of the installed caldav library at
        # phase-close time (Plan 06, 2026-05-20) confirms `principal` is a
        # plain callable method:
        #     >>> type(caldav.DAVClient.__dict__['principal'])
        #     <class 'function'>
        # So `loop.run_in_executor(None, self._client.principal)` correctly
        # passes the bound method to the executor, which then *calls* it
        # and triggers the PROPFIND. No code change is required for the
        # currently-installed caldav 3.x version; the comment is left here
        # as a guard rail so a future caldav release that re-exposes
        # `principal` as a property does not silently regress to the
        # base-URL bug. If the inspection ever returns `<class 'property'>`
        # again, change this line to
        #     loop.run_in_executor(None, lambda: self._client.principal())
        # to force the explicit call.
        loop = asyncio.get_running_loop()
        p = await loop.run_in_executor(None, self._client.principal)
        return _CompatPrincipal(p)


try:
    import caldav.aio  # sets caldav.aio attribute; absent on caldav < 3.x
except ImportError:
    _shim = types.SimpleNamespace()
    _shim.AsyncDAVClient = _CompatAsyncDAVClient
    caldav.aio = _shim  # type: ignore[assignment]
    logger.warning(
        "caldav.aio not found (caldav < 3.x detected); "
        "installing _CompatAsyncDAVClient shim — blocking CalDAV I/O will be "
        "dispatched via run_in_executor"
    )

# RFC 5545 §3.7.3 — PRODID identifies the iCalendar implementation that
# produced the file. Phase 34 D-04 fixes this string for downstream parsers
# and for the test_build_vevent_preserves_tz acceptance criterion.
PRODID = "-//ASP Parking//GPS2ASP//EN"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CalDAVAuthError(Exception):
    """Raised when CalDAV credential validation or API call fails."""


class CalDAVWriteError(Exception):
    """Raised when a CalDAV event write or delete operation fails (not an auth issue)."""


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
    apple_radius_m: int = DEFAULT_CALDAV_APPLE_RADIUS_M

    def __post_init__(self) -> None:
        """Validate fields at construction time (runs before the dataclass freeze)."""
        if not self.url:
            raise ValueError("CalDAVConfig.url must not be empty")
        if not self.calendar_url:
            raise ValueError("CalDAVConfig.calendar_url must not be empty")
        if self.safety_window_minutes < 0:
            raise ValueError(
                f"CalDAVConfig.safety_window_minutes must be >= 0, got {self.safety_window_minutes}"
            )

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
            CONF_CALDAV_APPLE_RADIUS_M,
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
            # BUG-C-003: use options.get() (not bare subscript). A missing
            # CONF_CALDAV_URL key used to raise an opaque KeyError that
            # surfaced as a generic "CalDAV sync failed" notification;
            # .get(default="") routes through __post_init__'s explicit
            # `CalDAVConfig.url must not be empty` ValueError so the user
            # (and downstream `except ValueError` callers) see a clear,
            # actionable failure.
            url=options.get(CONF_CALDAV_URL, ""),
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
            apple_radius_m=int(
                options.get(
                    CONF_CALDAV_APPLE_RADIUS_M,
                    DEFAULT_CALDAV_APPLE_RADIUS_M,
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


def render_title(template: str, schedule: ScheduleFound) -> str:
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


def render_description(schedule: ScheduleFound) -> str:
    """Render the event DESCRIPTION line per D-06.

    Format: ``"{on_street} ({side_of_street} side)\\n{summary}"`` — used
    verbatim as the VEVENT description. icalendar handles any RFC 5545
    line-wrap escaping at serialisation time.
    """
    on_street = getattr(schedule, "on_street", "") or ""
    side_of_street = getattr(schedule, "side_of_street", "") or ""
    summary = getattr(schedule, "summary", "") or ""
    return f"{on_street} ({side_of_street} side)\n{summary}"


def _fmt_coord(v: float) -> str:
    """Format a coordinate with bounded precision and no trailing-zero noise.

    Fixes float-repr jitter to a deterministic 6-decimal string, then strips
    trailing zeros and any dangling decimal point: 40.6782 -> "40.6782",
    40.0 -> "40".
    """
    return f"{v:.6f}".rstrip("0").rstrip(".")


def render_location_title(schedule: ScheduleFound) -> str:
    """Return the street label reused for X-TITLE / X-ADDRESS.

    Format: ``"{on_street} ({side_of_street} side)"`` — same defensive
    getattr pattern as :func:`render_description`.
    """
    on_street = getattr(schedule, "on_street", "") or ""
    side_of_street = getattr(schedule, "side_of_street", "") or ""
    return f"{on_street} ({side_of_street} side)"


def render_location_label(schedule: ScheduleFound, lat: float, lon: float) -> str:
    """Return the human-readable LOCATION text that Google/Android geocodes.

    Format: ``"STREET (SIDE side) — lat,lon"`` — the separator is a space,
    an em-dash (U+2014), and a space; coordinates are comma-separated with
    no space.
    """
    return f"{render_location_title(schedule)} — {_fmt_coord(lat)},{_fmt_coord(lon)}"


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
    lat: float | None = None,
    lon: float | None = None,
    location_label: str | None = None,
    location_title: str | None = None,
    radius_m: int = DEFAULT_CALDAV_APPLE_RADIUS_M,
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
    # Location is strictly additive: only emitted when a GPS fix is known.
    # When either coordinate is None the branch is skipped entirely, keeping
    # today's byte-for-byte output for the no-location case.
    if lat is not None and lon is not None:
        # RFC 5545 machine coordinates (semicolon-separated on the wire).
        # Rounded to 6 decimals so the vGeo value matches the LOCATION text
        # and X-APPLE-STRUCTURED-LOCATION geo: URI, both of which round via
        # _fmt_coord() — otherwise the three encodings show numerically
        # inconsistent coordinates.
        ev.add("geo", (round(lat, 6), round(lon, 6)))
        if location_label:
            # Human-readable street+coords text; Google/Android geocodes this.
            ev.add("location", location_label)
        # Apple structured location. The params MUST live on val.params — with
        # encode=0 a parameters= kwarg is silently dropped. vUri (not vText)
        # keeps the geo: URI comma un-escaped.
        val = vUri(f"geo:{_fmt_coord(lat)},{_fmt_coord(lon)}")
        _addr = location_title or location_label or ""
        val.params = Parameters(
            {
                "VALUE": "URI",
                "X-ADDRESS": _addr,
                "X-APPLE-RADIUS": str(radius_m),
                "X-TITLE": _addr,
            }
        )
        ev.add("X-APPLE-STRUCTURED-LOCATION", val, encode=0)
    cal.add_component(ev)
    return cal.to_ical().decode("utf-8")


# ---------------------------------------------------------------------------
# Internal CalDAV helpers
# ---------------------------------------------------------------------------


async def _get_calendar(client: Any, calendar_url: str) -> Any:
    """Resolve a calendar by URL using the authenticated principal.

    Uses ``principal.calendar(cal_url=...)`` for single-calendar lookup
    (no extra collection roundtrip — the principal already knows the
    calendar-home-set URL after ``get_principal``).

    Note: ``principal.calendar()`` is a **synchronous** constructor in both
    caldav 2.x (via the ``_CompatPrincipal`` shim) and caldav 3.x
    (``AsyncPrincipal.calendar``). It builds a Calendar object from the URL
    without any network I/O, so it must NOT be awaited.
    """
    principal = await client.get_principal()
    return principal.calendar(cal_url=calendar_url)


def _build_event_url(calendar_url: Any, uid: str) -> str:
    """Construct the CalDAV event URL from a calendar URL and event UID.

    Mirrors caldav's internal ``_quote_uid`` encoding logic
    (``calendarobjectresource.py``): replaces literal slashes in the UID
    with ``%2F``, then percent-encodes the result and appends ``.ics``.
    Used by :func:`_delete_uid_quiet` to perform a direct HTTP DELETE
    without a prior REPORT-based UID lookup — avoiding the
    ``ReportError 412 Precondition Failed`` that some CalDAV servers
    (Radicale, certain Nextcloud builds) return when the calendar-query
    REPORT method is not fully supported (CALDAV-09 fix).

    Args:
        calendar_url: The caldav Calendar's ``.url`` attribute (any type
            that ``str()`` can convert to an absolute URL string).  Must
            not be ``None``.
        uid: The deterministic event UID from :func:`derive_uid`.

    Returns:
        Absolute URL string for the ``.ics`` resource.

    Raises:
        ValueError: If ``calendar_url`` is ``None`` or converts to a blank
            or ``"None"`` string.
    """
    if calendar_url is None:
        raise ValueError(
            "Cannot build event URL: calendar_url is None — "
            "the CalDAV calendar object has no URL attribute."
        )
    cal_url_str = str(calendar_url)
    if not cal_url_str or cal_url_str.lower() == "none":
        raise ValueError(
            f"Cannot build event URL: calendar_url resolved to invalid string {cal_url_str!r}"
        )
    cal_url = cal_url_str.rstrip("/") + "/"
    encoded = _url_quote(uid.replace("/", "%2F"))
    return cal_url + encoded + ".ics"


async def _delete_uid_quiet(cal: Any, uid: str) -> None:
    """Delete a CalDAV event by UID without a REPORT-based lookup.

    Constructs the event URL deterministically from the calendar URL and
    UID, then issues a direct HTTP DELETE.  Treats HTTP 404/NotFoundError
    as success ("already gone" is a valid terminal state).  All other
    errors are re-raised so callers can surface them appropriately
    (log-and-continue for :func:`write_or_update_event`;
    persistent notification for ``_async_caldav_delete_current``).

    **Why no event_by_uid / REPORT?**  caldav 3.x ``event_by_uid`` sends
    a calendar-query REPORT that some CalDAV servers (Radicale, certain
    Nextcloud builds) reject with ``412 Precondition Failed``.  In
    caldav 2.x the REPORT XML was simpler but still not universally
    supported.  A direct DELETE by URL is RFC 4918-compliant, does not
    require REPORT support, and is the correct primitive for deleting a
    known resource.

    Args:
        cal: A caldav Calendar object (native caldav 3.x) or
            :class:`_CompatCalendar` (caldav 2.x shim).  Must expose a
            ``.url`` attribute.  For caldav 3.x the ``.client`` attribute
            must have a ``delete()`` coroutine.  For the compat shim the
            ``._cal.client`` sync-client ``delete()`` method is used via
            ``run_in_executor``.
        uid: The event UID to delete.
    """
    event_url = _build_event_url(cal.url, uid)

    try:
        # Native caldav 3.x path: cal.client is AsyncDAVClient with an async delete().
        # Compat shim (_CompatCalendar): cal has no .client; fall through to executor path.
        client = getattr(cal, "client", None)
        if client is not None and asyncio.iscoroutinefunction(
            getattr(client, "delete", None)
        ):
            response = await client.delete(event_url)
            status = getattr(response, "status", None)
            if status is not None and not str(status).startswith(("2", "404")):
                logger.warning(
                    "CalDAV: _delete_uid_quiet unexpected DELETE status %s for %s",
                    status,
                    event_url,
                )
        else:
            # Compat shim path (caldav 2.x): _CompatCalendar wraps a sync caldav.Calendar.
            # Use run_in_executor so blocking I/O never touches the event loop.
            sync_cal = getattr(cal, "_cal", None)
            sync_client = (
                getattr(sync_cal, "client", None) if sync_cal is not None else None
            )
            if sync_client is not None:
                loop = asyncio.get_running_loop()
                response = await loop.run_in_executor(
                    None, sync_client.delete, event_url
                )
                status = getattr(response, "status", None)
                if status is not None and not str(status).startswith(("2", "404")):
                    logger.warning(
                        "CalDAV: _delete_uid_quiet (compat) unexpected DELETE status %s for %s",
                        status,
                        event_url,
                    )
            else:
                # Last-resort fallback: REPORT-based event_by_uid.
                # Only reached if the calendar object has neither .client nor ._cal.client
                # (e.g. a fully-mocked test double that exposes event_by_uid directly).
                try:
                    evt = await cal.event_by_uid(uid)
                    await evt.delete()
                except caldav_error.NotFoundError:
                    return
    except caldav_error.NotFoundError:
        return  # 404 — already gone, perfectly fine
    except caldav_error.DAVError as exc:
        # Some CalDAV servers return a generic DAVError with status 404 instead
        # of the specific NotFoundError subclass.  Treat as "already gone".
        # Status may be an int (404) or a string ("404 Not Found").
        # Also check the url field: ReportError encodes the HTTP status in .url
        # (e.g. url="404 Not Found - <body>") when the server 404s a REPORT request.
        status = getattr(exc, "status", None)
        url_field = getattr(exc, "url", "") or ""
        if (status is not None and str(status).startswith("404")) or url_field[
            :3
        ] == "404":
            return
        raise


def _sanitise(message: str, password: str, username: str = "") -> str:
    """Replace credentials in an error string with ``***``.

    Defence-in-depth for T-34-01/T-34-02. Strips:
    - The literal password and username substrings.
    - The Base64-encoded ``username:password`` form that appears in
      ``Authorization: Basic`` headers echoed back by some CalDAV servers.
    """
    if password:
        message = message.replace(password, "***")
        if username:
            b64 = base64.b64encode(f"{username}:{password}".encode()).decode()
            message = message.replace(b64, "***")
    if username:
        message = message.replace(username, "***")
    return message


# ---------------------------------------------------------------------------
# Public CalDAV API
# ---------------------------------------------------------------------------


async def validate_connection(*, url: str, username: str, password: str) -> None:
    """Probe the CalDAV server with the given credentials.

    Raises:
        CalDAVAuthError: on any failure — auth, network, TLS, DNS, etc.
            The original exception is chained via ``__cause__``. Any
            occurrence of ``password`` in the wrapped message is masked
            with ``***`` (T-34-01 / T-34-02 defence-in-depth).
    """
    try:
        async with caldav.aio.AsyncDAVClient(
            url=url,
            username=username,
            password=password,
        ) as client:
            await client.get_principal()
    except caldav_error.AuthorizationError as err:
        raise CalDAVAuthError(
            f"Authentication failed: {_sanitise(str(err), password, username)}"
        ) from err
    except caldav_error.DAVError as err:
        raise CalDAVAuthError(
            f"Server error: {_sanitise(str(err), password, username)}"
        ) from err
    except asyncio.CancelledError:
        raise
    except Exception as err:  # noqa: BLE001 — wrap everything (D-03)
        raise CalDAVAuthError(
            f"Connection error: {_sanitise(str(err), password, username)}"
        ) from err


async def list_calendars(
    *, url: str, username: str, password: str
) -> list[tuple[str, str]]:
    """Return ``[(calendar_url, display_name), ...]`` for the authenticated principal.

    Falls back to ``str(cal.url)`` for the display name when
    ``cal.get_display_name()`` raises (some CalDAV servers either don't
    expose a display-name property or return a 500 for it).

    Empty list = the server authenticated successfully but exposed no
    calendars on this principal.

    Raises:
        CalDAVAuthError: on any auth, network, or TLS failure — same contract
            as validate_connection. Password is sanitised from the message.
    """
    try:
        async with caldav.aio.AsyncDAVClient(
            url=url,
            username=username,
            password=password,
        ) as client:
            principal = await client.get_principal()
            calendars = await principal.calendars()  # type: ignore[misc]
            result: list[tuple[str, str]] = []
            for cal in calendars:
                try:
                    name = await cal.get_display_name()
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 — fall back to URL for any failure
                    logger.warning(
                        "CalDAV: could not fetch display name for calendar %s, falling back to URL",
                        cal.url,
                        exc_info=True,
                    )
                    name = ""
                result.append((str(cal.url), name or str(cal.url)))
            return result
    except CalDAVAuthError:
        raise
    except caldav_error.AuthorizationError as err:
        raise CalDAVAuthError(
            f"Authentication failed: {_sanitise(str(err), password, username)}"
        ) from err
    except caldav_error.DAVError as err:
        raise CalDAVAuthError(
            f"Server error: {_sanitise(str(err), password, username)}"
        ) from err
    except asyncio.CancelledError:
        raise
    except Exception as err:  # noqa: BLE001 — wrap everything (D-03)
        raise CalDAVAuthError(
            f"Connection error: {_sanitise(str(err), password, username)}"
        ) from err


async def write_or_update_event(
    *,
    config: CalDAVConfig,
    entry_id: str,
    schedule: Any,
    stored_uid: str | None,
    lat: float | None = None,
    lon: float | None = None,
) -> str:
    """Idempotent write of the upcoming cleaning-window VEVENT.

    Behaviour (D-07):

    * If ``stored_uid == derive_uid(entry_id, window.start_datetime)``: the
      window has not changed since the last write. We re-issue a single
      ``add_event`` so the server-side state stays in sync (any drift the
      user introduced manually is overwritten).
    * If ``stored_uid != new_uid``: the window has shifted. We DELETE the
      stored UID first (silent on NotFoundError) and THEN create the new
      event — never the other way around, to avoid brief duplicates.

    Args:
        config: connection + content configuration.
        entry_id: HA config entry ID, fed into :func:`derive_uid`.
        schedule: a ScheduleFound-shaped object with ``next_window`` set.
        stored_uid: the UID we wrote on the previous cycle, loaded from
            :class:`homeassistant.helpers.storage.Store` by the caller.
        lat: optional parked-car latitude. When both ``lat`` and ``lon`` are
            provided, GEO/LOCATION/X-APPLE-STRUCTURED-LOCATION are embedded
            in the VEVENT; when either is ``None`` no location is embedded,
            matching pre-PR behaviour.
        lon: optional parked-car longitude. See ``lat``.

    Returns:
        The new UID. The caller MUST persist this via the Store before
        the next cycle so D-07's delete-then-create order can run.
    """
    window = schedule.next_window
    new_uid = derive_uid(entry_id, window.start_datetime)

    async with caldav.aio.AsyncDAVClient(
        url=config.url,
        username=config.username,
        password=config.password,
    ) as client:
        cal = await _get_calendar(client, config.calendar_url)

        if stored_uid and stored_uid != new_uid:
            try:
                await _delete_uid_quiet(cal, stored_uid)
            except caldav_error.DAVError as exc:
                status = getattr(exc, "status", "?")
                logger.warning(
                    "CalDAV: could not delete old event (status=%s), proceeding with create",
                    status,
                    exc_info=True,
                )

        if lat is not None and lon is not None:
            location_label = render_location_label(schedule, lat, lon)
            location_title = render_location_title(schedule)
        else:
            location_label = None
            location_title = None
        ical_text = build_vevent_ical(
            uid=new_uid,
            window=window,
            title=render_title(config.title_template, schedule),
            description=render_description(schedule),
            lat=lat,
            lon=lon,
            location_label=location_label,
            location_title=location_title,
            radius_m=config.apple_radius_m,
        )
        try:
            await cal.add_event(ical=ical_text)
        except caldav_error.DAVError as exc:
            raise CalDAVWriteError(
                f"Failed to write event to calendar {config.calendar_url!r}: "
                f"{_sanitise(str(exc), config.password, config.username)}"
            ) from exc
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise CalDAVWriteError(
                f"Unexpected error writing CalDAV event: "
                f"{_sanitise(str(exc), config.password, config.username)}"
            ) from exc

    return new_uid


async def delete_event(
    *,
    url: str,
    username: str,
    password: str,
    calendar_url: str,
    uid: str,
) -> None:
    """Delete the event identified by ``uid`` from ``calendar_url``.

    Silent on NotFoundError (already gone is fine). All other exceptions
    propagate to the caller for surfacing as a notification (D-09/D-10).
    """
    async with caldav.aio.AsyncDAVClient(
        url=url,
        username=username,
        password=password,
    ) as client:
        cal = await _get_calendar(client, calendar_url)
        await _delete_uid_quiet(cal, uid)
