"""Tests for gps2asp.suspension — holiday calendar and SuspensionInfo."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from gps2asp.suspension import HolidayCalendar, SuspensionInfo, _extract_reason, _parse_ics, FALLBACK_2026

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def ics_bytes() -> bytes:
    """Load the sample ICS fixture."""
    return (FIXTURES_DIR / "sample_asp_2026.ics").read_bytes()


# --- ICS parsing ---


def test_parse_ics(ics_bytes: bytes) -> None:
    """parse_ics returns dict mapping dates to holiday names from ICS bytes."""
    holidays = _parse_ics(ics_bytes)
    assert holidays[date(2026, 1, 1)] == "New Year's Day"
    assert holidays[date(2026, 12, 25)] == "Christmas Day"
    assert len(holidays) == 5  # fixture has 5 events


# --- Reason extraction ---


def test_extract_reason() -> None:
    """_extract_reason pulls holiday name from standard DESCRIPTION format."""
    desc = (
        "Alternate Side Parking suspended for Memorial Day. "
        "Parking meters will not be in effect."
    )
    assert _extract_reason(desc) == "Memorial Day"


def test_extract_reason_fallback() -> None:
    """_extract_reason returns 'Holiday' for unexpected format."""
    assert _extract_reason("Some unexpected format") == "Holiday"


# --- is_suspended ---


def test_is_suspended_holiday(ics_bytes: bytes) -> None:
    """is_suspended returns True with reason for a holiday date."""
    cal = HolidayCalendar()
    cal._holidays = _parse_ics(ics_bytes)
    cal._loaded = True
    result = cal.is_suspended(date(2026, 1, 1))
    assert result == SuspensionInfo(is_suspended=True, reason="New Year's Day", source="holiday")


def test_is_suspended_normal(ics_bytes: bytes) -> None:
    """is_suspended returns False with None reason for a normal weekday."""
    cal = HolidayCalendar()
    cal._holidays = _parse_ics(ics_bytes)
    cal._loaded = True
    result = cal.is_suspended(date(2026, 6, 3))
    assert result == SuspensionInfo(is_suspended=False, reason=None)


# --- load() with mocked httpx ---


async def test_load_fetches_ics(ics_bytes: bytes) -> None:
    """load() fetches ICS via httpx and populates holidays from parsed content."""
    mock_response = AsyncMock()
    mock_response.content = ics_bytes
    mock_response.raise_for_status = lambda: None

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("gps2asp.suspension.httpx.AsyncClient", return_value=mock_client):
        cal = HolidayCalendar()
        await cal.load(year=2026)
        assert cal._loaded is True
        assert len(cal._holidays) == 5
        assert cal.is_suspended(date(2026, 1, 1)).is_suspended is True


async def test_load_fallback_on_failure() -> None:
    """load() uses FALLBACK_2026 dict when httpx fetch fails."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.TransportError("Network error"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("gps2asp.suspension.httpx.AsyncClient", return_value=mock_client):
        cal = HolidayCalendar()
        await cal.load(year=2026)
        assert cal._loaded is True
        assert len(cal._holidays) == 39
        assert cal.is_suspended(date(2026, 1, 1)).is_suspended is True


# --- Fallback dict ---


def test_fallback_coverage() -> None:
    """FALLBACK_2026 has exactly 39 entries, all in year 2026."""
    assert len(FALLBACK_2026) == 39
    for d in FALLBACK_2026:
        assert d.year == 2026


# --- Frozen dataclass ---


def test_suspension_info_frozen() -> None:
    """SuspensionInfo is frozen — attribute assignment raises."""
    info = SuspensionInfo(is_suspended=True, reason="X")
    with pytest.raises(AttributeError):
        info.is_suspended = False  # type: ignore[misc]


# --- Datetime safety ---


def test_datetime_safety() -> None:
    """If DTSTART returns a datetime instead of date, parser extracts .date()."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    # Build a minimal ICS where DTSTART is a datetime (not VALUE=DATE)
    ics_content = (
        b"BEGIN:VCALENDAR\r\n"
        b"VERSION:2.0\r\n"
        b"PRODID:-//Test//Test//EN\r\n"
        b"BEGIN:VEVENT\r\n"
        b"DTSTART:20260704T000000Z\r\n"
        b"DESCRIPTION:Alternate Side Parking suspended for Independence Day. Parking meters will not be in effect.\r\n"
        b"END:VEVENT\r\n"
        b"END:VCALENDAR\r\n"
    )
    holidays = _parse_ics(ics_content)
    # Should have extracted date(2026, 7, 4) regardless of datetime input
    assert date(2026, 7, 4) in holidays
    assert holidays[date(2026, 7, 4)] == "Independence Day"
