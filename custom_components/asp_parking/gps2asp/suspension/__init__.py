"""NYC holiday-based ASP suspension calendar.

Fetches the NYC DOT annual ICS calendar and exposes a simple
``is_suspended(date)`` query returning a ``SuspensionInfo`` result.
Falls back to a hardcoded 2026 calendar when the ICS fetch fails.
"""

from __future__ import annotations

import asyncio
import logging
import re
import ssl
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

import httpx
from icalendar import Calendar

logger = logging.getLogger("gps2asp.suspension")

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SuspensionInfo:
    """Result of a suspension check for a specific date."""

    is_suspended: bool
    reason: str | None
    source: Literal["holiday", "emergency", "ha_nyc311", "none"] = "none"


# ---------------------------------------------------------------------------
# ICS fetch configuration
# ---------------------------------------------------------------------------

ICS_URL_TEMPLATE = (
    "https://www.nyc.gov/html/dot/downloads/misc/{year}-alternate-side.ics"
)
MAX_RETRIES = 3
BASE_DELAY = 1.0  # seconds

# NOTE: nyc.gov's edge (Akamai bot protection) returns HTTP 403 for
# non-browser User-Agent strings (e.g. a "compatible; ...GitHub..." bot UA or
# the default curl/httpx UA). A standard browser UA is required or the ICS
# fetch fails on every refresh and the integration silently falls back to the
# hardcoded FALLBACK calendar. Verified 2026-07-01: same URL, same time — the
# old bot UA -> 403, this browser UA -> 200. See debug/friday-move-not-suspended.
_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/calendar,*/*",
}


def _build_ssl_context() -> ssl.SSLContext:
    """Build an SSL context outside the event loop (avoids HA blocking-call warning)."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        logger.debug("certifi not installed; using system SSL CA bundle for ICS fetch")
        return ssl.create_default_context()


# ---------------------------------------------------------------------------
# Reason extraction
# ---------------------------------------------------------------------------

_REASON_PATTERN = re.compile(
    r"Alternate Side Parking suspended for (.+?)\.",
    re.IGNORECASE,
)


def _extract_reason(description: str) -> str:
    """Extract holiday name from ICS DESCRIPTION field.

    Falls back to ``"Holiday"`` if the expected pattern is not found.
    """
    match = _REASON_PATTERN.search(description)
    if match:
        return match.group(1).strip()
    return "Holiday"


# ---------------------------------------------------------------------------
# ICS parsing
# ---------------------------------------------------------------------------


def _parse_ics(ics_bytes: bytes) -> dict[date, str]:
    """Parse ICS bytes into a date-to-holiday-name mapping.

    Only uses DTSTART (not DTEND) per ICS RFC 5545 — DTEND for
    VALUE=DATE is the exclusive end, not a second suspension day.
    """
    cal = Calendar.from_ical(ics_bytes)
    holidays: dict[date, str] = {}
    for component in cal.walk("VEVENT"):
        dtstart = component.get("DTSTART")
        if dtstart is None:
            continue
        event_date = dtstart.dt
        # Safety: if DTSTART is datetime instead of date, extract .date()
        if hasattr(event_date, "date"):
            event_date = event_date.date()
        description = str(component.get("DESCRIPTION", ""))
        reason = _extract_reason(description)
        holidays[event_date] = reason
    return holidays


# ---------------------------------------------------------------------------
# Hardcoded 2026 fallback (36 events from the authoritative NYC DOT ICS)
# ---------------------------------------------------------------------------

# Derived directly from the authoritative NYC DOT ICS
# (https://www.nyc.gov/html/dot/downloads/misc/2026-alternate-side.ics) parsed
# with _parse_ics on 2026-07-01, so fallback behavior mirrors the live feed.
# Regenerate when the year rolls over or the ICS changes; do NOT hand-edit with
# generic holiday lists (the previous hand-maintained dict omitted real ASP
# suspensions such as 2026-07-03 and included dates that are not suspensions).
FALLBACK_2026: dict[date, str] = {
    date(2026, 1, 1): "New Year’s Day",
    date(2026, 1, 6): "Three Kings' Day",
    date(2026, 1, 19): "Martin Luther King Jr",
    date(2026, 2, 12): "Lincoln’s Birthday",
    date(2026, 2, 16): "Washington’s Birthday (Presidents Day)",
    date(2026, 2, 17): "Lunar New Year",
    date(2026, 2, 18): "Ash Wednesday",
    date(2026, 3, 3): "Purim",
    date(2026, 3, 20): "Idul-Fitr (Eid Al-Fitr)",
    date(2026, 4, 2): "Holy Thursday",
    date(2026, 4, 3): "Good Friday",
    date(2026, 4, 8): "the seventh and eighth days of Passover",
    date(2026, 4, 9): "Orthodox Holy Thursday",
    date(2026, 4, 10): "Orthodox Good Friday",
    date(2026, 5, 14): "Solemnity of the Ascension",
    date(2026, 5, 22): "Shavuoth",
    date(2026, 5, 25): "Memorial Day",
    date(2026, 5, 27): "Idul-Adha (Eid Al-Adha)",
    date(2026, 6, 19): "Juneteenth",
    date(2026, 7, 3): "Independence Day",
    date(2026, 7, 23): "Tisha B'Av",
    date(2026, 8, 15): "Feast of the Assumption",
    date(2026, 9, 7): "Labor Day",
    date(2026, 9, 12): "Rosh Hashanah",
    date(2026, 9, 21): "Yom Kippur",
    date(2026, 9, 26): "Succoth",
    date(2026, 10, 3): "Shemini Atzereth",
    date(2026, 10, 4): "Simchas Torah",
    date(2026, 10, 12): "Columbus Day",
    date(2026, 11, 1): "All Saints' Day",
    date(2026, 11, 3): "Election Day",
    date(2026, 11, 8): "Diwali",
    date(2026, 11, 11): "Veterans Day",
    date(2026, 11, 26): "Thanksgiving Day",
    date(2026, 12, 8): "Immaculate Conception",
    date(2026, 12, 25): "Christmas Day",
}


def _get_fallback(year: int) -> dict[date, str]:
    """Return hardcoded fallback dates for the given year.

    Returns an empty dict for unknown years (fail open).

    BUG-T-008: emits a single ERROR log for unknown years so HA diagnostics
    surface the missing fallback. Pre-fix, the silent empty return caused
    the integration to run as if no NYC holidays existed (e.g. waking the
    user at 7 AM on Christmas in a year past the hardcoded fallback).
    """
    if year == 2026:
        return dict(FALLBACK_2026)
    logger.error(
        "No fallback holiday data for year %d; ASP integration will run as if "
        "no NYC holidays exist. Please update FALLBACK_%d in "
        "src/gps2asp/suspension/__init__.py.",
        year,
        year,
    )
    return {}


# ---------------------------------------------------------------------------
# Async ICS fetch with retry
# ---------------------------------------------------------------------------


async def _fetch_ics(year: int) -> bytes | None:
    """Fetch ICS file from NYC.gov with retry. Returns None on failure."""
    url = ICS_URL_TEMPLATE.format(year=year)
    loop = asyncio.get_running_loop()
    ssl_context = await loop.run_in_executor(None, _build_ssl_context)
    async with httpx.AsyncClient(
        timeout=30.0, verify=ssl_context, headers=_FETCH_HEADERS
    ) as client:
        for attempt in range(MAX_RETRIES):
            try:
                response = await client.get(url)
                response.raise_for_status()
                return response.content
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                # BUG-T-009: auth errors (401, 403) are not transient and
                # must not be retried. Short-circuit with a single warning
                # so HA diagnostics surface the auth problem instead of a
                # multi-second retry loop. Matches NYC311Client convention.
                if isinstance(
                    exc, httpx.HTTPStatusError
                ) and exc.response.status_code in (401, 403):
                    logger.warning(
                        "ICS fetch failed with auth error %d (%s); not retrying "
                        "(auth errors are not transient)",
                        exc.response.status_code,
                        exc,
                    )
                    return None
                delay = BASE_DELAY * (2**attempt)
                if attempt < MAX_RETRIES - 1:
                    logger.warning(
                        "ICS fetch attempt %d/%d failed (%s): %s — retrying in %.1fs",
                        attempt + 1,
                        MAX_RETRIES,
                        type(exc).__name__,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.warning(
                        "ICS fetch attempt %d/%d failed (%s): %s — all retries exhausted",
                        attempt + 1,
                        MAX_RETRIES,
                        type(exc).__name__,
                        exc,
                    )
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class HolidayCalendar:
    """Holiday-based ASP suspension calendar.

    Usage::

        cal = HolidayCalendar()
        await cal.load()          # fetches ICS or uses fallback
        info = cal.is_suspended(date.today())
        if info.is_suspended:
            print(f"Suspended for {info.reason}")
    """

    def __init__(self) -> None:
        self._holidays: dict[date, str] = {}
        self._loaded: bool = False

    async def load(self, year: int | None = None) -> None:
        """Fetch and parse the ICS calendar for the given year.

        Falls back to hardcoded dates on fetch failure.
        """
        if year is None:
            year = datetime.now(ZoneInfo("America/New_York")).year

        try:
            ics_bytes = await _fetch_ics(year)
        except asyncio.CancelledError:
            # Task cancelled during ICS fetch — load fallback so _loaded is always
            # True and is_suspended() never silently returns a false negative.
            self._holidays = _get_fallback(year)
            self._loaded = True
            raise

        if ics_bytes is not None:
            try:
                self._holidays = _parse_ics(ics_bytes)
                logger.info("Loaded %d holiday dates from ICS", len(self._holidays))
            except Exception as exc:
                logger.warning(
                    "ICS parse failed for year %d (%s: %s); falling back to hardcoded dates",
                    year,
                    type(exc).__name__,
                    exc,
                )
                self._holidays = _get_fallback(year)
                logger.warning(
                    "ICS parse failed, using %d fallback dates", len(self._holidays)
                )
        else:
            self._holidays = _get_fallback(year)
            logger.warning(
                "ICS fetch failed, using %d fallback dates", len(self._holidays)
            )
        self._loaded = True

    @property
    def suspended_dates(self) -> frozenset[date]:
        """All holiday dates as an immutable set for forward-lookahead skipping."""
        return frozenset(self._holidays)

    def is_suspended(self, check_date: date) -> SuspensionInfo:
        """Check if ASP is suspended on the given date."""
        if not self._loaded:
            logger.warning(
                "HolidayCalendar.is_suspended() called before load() -- returning not suspended"
            )
        reason = self._holidays.get(check_date)
        return SuspensionInfo(
            is_suspended=reason is not None,
            reason=reason,
            source="holiday" if reason is not None else "none",
        )


from .merge import apply_suspension  # noqa: E402
from .poller import NYC311Client, NYC311AuthError  # noqa: E402

__all__ = [
    "HolidayCalendar",
    "SuspensionInfo",
    "apply_suspension",
    "NYC311Client",
    "NYC311AuthError",
]
