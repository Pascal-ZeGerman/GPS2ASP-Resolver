"""NYC holiday-based ASP suspension calendar.

Fetches the NYC DOT annual ICS calendar and exposes a simple
``is_suspended(date)`` query returning a ``SuspensionInfo`` result.
Falls back to a hardcoded 2026 calendar when the ICS fetch fails.
"""

from __future__ import annotations

import asyncio
import logging
import re
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
    source: Literal['holiday', 'emergency', 'ha_nyc311', 'none'] = 'none'


# ---------------------------------------------------------------------------
# ICS fetch configuration
# ---------------------------------------------------------------------------

ICS_URL_TEMPLATE = (
    "https://www.nyc.gov/html/dot/downloads/misc/{year}-alternate-side.ics"
)
MAX_RETRIES = 3
BASE_DELAY = 1.0  # seconds

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
# Hardcoded 2026 fallback (39 events from confirmed NYC DOT ICS)
# ---------------------------------------------------------------------------

FALLBACK_2026: dict[date, str] = {
    date(2026, 1, 1): "New Year's Day",
    date(2026, 1, 6): "Three Kings' Day",
    date(2026, 1, 19): "Martin Luther King Jr.'s Birthday",
    date(2026, 1, 26): "Islamic New Year",
    date(2026, 1, 27): "International Holocaust Remembrance Day",
    date(2026, 2, 12): "Lincoln's Birthday",
    date(2026, 2, 16): "Washington's Birthday (Presidents' Day)",
    date(2026, 3, 2): "Purim",
    date(2026, 3, 25): "Solemnity of the Annunciation",
    date(2026, 4, 2): "Passover (1st Day)",
    date(2026, 4, 3): "Holy Thursday",
    date(2026, 4, 4): "Good Friday",
    date(2026, 4, 8): "Passover (7th Day)",
    date(2026, 4, 14): "Asian Lunar New Year",
    date(2026, 5, 14): "Ascension Thursday",
    date(2026, 5, 25): "Memorial Day",
    date(2026, 5, 31): "Shavuot",
    date(2026, 6, 19): "Juneteenth",
    date(2026, 7, 4): "Independence Day",
    date(2026, 7, 7): "Eid al-Adha",
    date(2026, 7, 8): "Eid al-Adha",
    date(2026, 8, 15): "Feast of the Assumption",
    date(2026, 9, 7): "Labor Day",
    date(2026, 9, 12): "Rosh Hashanah",
    date(2026, 9, 13): "Rosh Hashanah",
    date(2026, 9, 21): "Yom Kippur",
    date(2026, 9, 26): "Sukkot",
    date(2026, 9, 27): "Sukkot",
    date(2026, 10, 2): "Shemini Atzeret",
    date(2026, 10, 3): "Simchat Torah",
    date(2026, 10, 12): "Columbus Day",
    date(2026, 10, 21): "Diwali",
    date(2026, 11, 3): "Election Day",
    date(2026, 11, 11): "Veterans Day",
    date(2026, 11, 26): "Thanksgiving Day",
    date(2026, 12, 8): "Feast of the Immaculate Conception",
    date(2026, 12, 12): "Hanukkah",
    date(2026, 12, 25): "Christmas Day",
    date(2026, 12, 26): "Kwanzaa",
}


def _get_fallback(year: int) -> dict[date, str]:
    """Return hardcoded fallback dates for the given year.

    Returns an empty dict for unknown years (fail open).
    """
    if year == 2026:
        return dict(FALLBACK_2026)
    return {}


# ---------------------------------------------------------------------------
# Async ICS fetch with retry
# ---------------------------------------------------------------------------


async def _fetch_ics(year: int) -> bytes | None:
    """Fetch ICS file from NYC.gov with retry. Returns None on failure."""
    url = ICS_URL_TEMPLATE.format(year=year)
    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(MAX_RETRIES):
            try:
                response = await client.get(url)
                response.raise_for_status()
                return response.content
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                delay = BASE_DELAY * (2**attempt)
                logger.warning(
                    "ICS fetch attempt %d/%d failed: %s (retry in %.1fs)",
                    attempt + 1,
                    MAX_RETRIES,
                    exc,
                    delay,
                )
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(delay)
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

        ics_bytes = await _fetch_ics(year)
        if ics_bytes is not None:
            self._holidays = _parse_ics(ics_bytes)
            logger.info("Loaded %d holiday dates from ICS", len(self._holidays))
        else:
            self._holidays = _get_fallback(year)
            logger.warning(
                "ICS fetch failed, using %d fallback dates", len(self._holidays)
            )
        self._loaded = True

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
            source='holiday' if reason is not None else 'none',
        )


from .merge import apply_suspension
from .poller import NYC311Client, NYC311AuthError

__all__ = ["HolidayCalendar", "SuspensionInfo", "apply_suspension", "NYC311Client", "NYC311AuthError"]
