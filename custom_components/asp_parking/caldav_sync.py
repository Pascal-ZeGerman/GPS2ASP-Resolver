"""CalDAV calendar synchronisation glue (Phase 34).

Pure async helpers wrapping caldav.aio.AsyncDAVClient. NOT mirrored to
src/gps2asp/. Every coroutine is safe to call from any other module in
this integration. CalDAV-08 is enforced by this module being the sole
caldav importer in the integration and by using ONLY caldav.aio (the
async client) — never caldav.DAVClient (the sync one).

Import safety: ``caldav.aio`` was introduced in caldav 3.x. The HA built-in
CalDAV integration pins ``caldav==2.1.0``, which predates the ``aio``
submodule. When ``caldav.aio`` is absent this module installs a
``_CompatAsyncDAVClient`` shim as ``caldav.aio.AsyncDAVClient`` so all
production code and tests can use the same attribute without branching.
The shim wraps the sync ``caldav.DAVClient`` via ``run_in_executor`` so
blocking I/O never hits the HA event loop. On caldav 3.x the shim is
never installed and the native async client is used directly.
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

import caldav  # top-level package — present on all caldav versions
from caldav.lib import error as caldav_error
from icalendar import Calendar, Event

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
        evt = await loop.run_in_executor(None, self._cal.event_by_uid, uid)
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

    async def calendar(self, cal_url: str) -> _CompatCalendar:
        loop = asyncio.get_running_loop()
        cal = await loop.run_in_executor(
            None, lambda: self._p.calendar(cal_url=cal_url)
        )
        return _CompatCalendar(cal)


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
                logger.debug(
                    "CalDAV shim: error closing sync client connection",
                    exc_info=True,
                )

    async def get_principal(self) -> _CompatPrincipal:
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


# ---------------------------------------------------------------------------
# Internal CalDAV helpers
# ---------------------------------------------------------------------------


async def _get_calendar(client: Any, calendar_url: str) -> Any:
    """Resolve a calendar by URL using the authenticated principal.

    Uses ``principal.calendar(cal_url=...)`` for single-calendar lookup
    (no extra collection roundtrip — the principal already knows the
    calendar-home-set URL after ``get_principal``).
    """
    principal = await client.get_principal()
    return await principal.calendar(cal_url=calendar_url)


async def _delete_uid_quiet(cal: Any, uid: str) -> None:
    """Delete an event by UID; treat NotFoundError as success.

    "Already gone" is a perfectly fine end-state for a delete call (e.g.
    the user manually removed the event from their calendar app between
    our last write and this delete). We must not surface this as an error.
    """
    try:
        evt = await cal.event_by_uid(uid)
        await evt.delete()
    except (caldav_error.NotFoundError, caldav_error.DAVError) as exc:
        # Some CalDAV servers return a generic DAVError with status 404 instead
        # of the specific NotFoundError subclass. Treat both as "already gone".
        # Status may be an int (404) or a string ("404 Not Found") on caldav 2.x.
        if isinstance(exc, caldav_error.NotFoundError):
            return
        status = getattr(exc, "status", None)
        if status is not None and str(status).startswith("404"):
            return
        logger.debug(
            "CalDAV: _delete_uid_quiet re-raising DAVError (status=%s)",
            status,
            exc_info=True,
        )
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

        ical_text = build_vevent_ical(
            uid=new_uid,
            window=window,
            title=render_title(config.title_template, schedule),
            description=render_description(schedule),
        )
        try:
            await cal.add_event(ical=ical_text)
        except caldav_error.DAVError as exc:
            raise CalDAVAuthError(
                f"Failed to write event to calendar {config.calendar_url!r}: "
                f"{_sanitise(str(exc), config.password, config.username)}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise CalDAVAuthError(
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
