"""Tests for gps2asp.suspension — holiday calendar and SuspensionInfo."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from gps2asp.suspension import (
    HolidayCalendar,
    SuspensionInfo,
    _extract_reason,
    _get_fallback,
    _parse_ics,
    FALLBACK_2026,
)

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
    assert result == SuspensionInfo(
        is_suspended=True, reason="New Year's Day", source="holiday"
    )


def test_is_suspended_normal(ics_bytes: bytes) -> None:
    """is_suspended returns False with None reason for a normal weekday."""
    cal = HolidayCalendar()
    cal._holidays = _parse_ics(ics_bytes)
    cal._loaded = True
    result = cal.is_suspended(date(2026, 6, 3))
    assert result == SuspensionInfo(is_suspended=False, reason=None, source="none")


def test_is_suspended_before_load_warns(caplog: pytest.LogCaptureFixture) -> None:
    """is_suspended() before load() logs a warning and returns source='none'."""
    import logging

    cal = HolidayCalendar()
    with caplog.at_level(logging.WARNING, logger="gps2asp.suspension"):
        result = cal.is_suspended(date(2026, 1, 1))
    assert any("before load()" in r.message for r in caplog.records)
    assert result == SuspensionInfo(is_suspended=False, reason=None, source="none")


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


# ---------------------------------------------------------------------------
# New edge-case tests
# ---------------------------------------------------------------------------

# 1. load() raises mid-execution, then is_suspended() called before _loaded is set


async def test_load_parse_error_uses_fallback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If _parse_ics raises during load(), falls back to hardcoded dates; _loaded stays True."""
    import logging

    # A minimal but valid-enough bytes payload so _fetch_ics "succeeds"
    dummy_bytes = b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"

    mock_response = AsyncMock()
    mock_response.content = dummy_bytes
    mock_response.raise_for_status = lambda: None

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("gps2asp.suspension.httpx.AsyncClient", return_value=mock_client):
        with patch("gps2asp.suspension._parse_ics", side_effect=ValueError("bad ics")):
            cal = HolidayCalendar()
            with caplog.at_level(logging.WARNING, logger="gps2asp.suspension"):
                await cal.load(year=2026)

    # Falls back to hardcoded dates — _loaded is True
    assert cal._loaded is True
    assert len(cal._holidays) == 39  # FALLBACK_2026 has 39 entries
    assert cal.is_suspended(date(2026, 1, 1)).is_suspended is True

    # A warning was logged mentioning the parse failure
    assert any("bad ics" in r.message for r in caplog.records)


# 2. load() called twice replaces holidays (idempotent replacement, not accumulation)

_ICS_JAN1_ONLY = (
    b"BEGIN:VCALENDAR\r\n"
    b"VERSION:2.0\r\n"
    b"BEGIN:VEVENT\r\n"
    b"DTSTART;VALUE=DATE:20260101\r\n"
    b"DESCRIPTION:Alternate Side Parking suspended for New Year's Day. Parking meters will not be in effect.\r\n"
    b"END:VEVENT\r\n"
    b"END:VCALENDAR\r\n"
)

_ICS_JUL4_ONLY = (
    b"BEGIN:VCALENDAR\r\n"
    b"VERSION:2.0\r\n"
    b"BEGIN:VEVENT\r\n"
    b"DTSTART;VALUE=DATE:20260704\r\n"
    b"DESCRIPTION:Alternate Side Parking suspended for Independence Day. Parking meters will not be in effect.\r\n"
    b"END:VEVENT\r\n"
    b"END:VCALENDAR\r\n"
)


def _make_mock_client(responses: list[bytes]) -> AsyncMock:
    """Return an AsyncMock httpx.AsyncClient that yields successive byte payloads."""
    side_effects = []
    for content in responses:
        mock_resp = AsyncMock()
        mock_resp.content = content
        mock_resp.raise_for_status = lambda: None
        side_effects.append(mock_resp)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=side_effects)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


async def test_load_twice_replaces_not_accumulates() -> None:
    """Second load() replaces _holidays entirely; Jan 1 gone, Jul 4 present."""
    mock_client = _make_mock_client([_ICS_JAN1_ONLY, _ICS_JUL4_ONLY])

    with patch("gps2asp.suspension.httpx.AsyncClient", return_value=mock_client):
        cal = HolidayCalendar()
        await cal.load(year=2026)
        # After first load: Jan 1 present
        assert date(2026, 1, 1) in cal._holidays

        await cal.load(year=2026)
        # After second load: Jul 4 present, Jan 1 gone
        assert date(2026, 7, 4) in cal._holidays
        assert date(2026, 1, 1) not in cal._holidays
        assert len(cal._holidays) == 1


# 3. is_suspended(None) — None as check_date does not raise


def test_is_suspended_none_date() -> None:
    """is_suspended(None) returns not-suspended without raising."""
    cal = HolidayCalendar()
    cal._loaded = True
    cal._holidays = {}
    result = cal.is_suspended(None)  # type: ignore[arg-type]
    assert result == SuspensionInfo(is_suspended=False, reason=None, source="none")


# 4. is_suspended with a datetime instead of date — dict lookup misses


def test_is_suspended_datetime_key_miss() -> None:
    """Passing a datetime (not date) to is_suspended causes a dict miss — returns False."""
    cal = HolidayCalendar()
    cal._loaded = True
    cal._holidays = {date(2026, 1, 1): "New Year's Day"}

    dt = datetime(2026, 1, 1, 8, 0)
    result = cal.is_suspended(dt)  # type: ignore[arg-type]
    # datetime != date for dict lookup, so the holiday is not found
    assert result.is_suspended is False
    assert result.source == "none"


# 5. _get_fallback(year) for an unknown year returns empty dict and load() succeeds


def test_get_fallback_unknown_year() -> None:
    """_get_fallback returns {} for any year without a hardcoded calendar."""
    assert _get_fallback(2099) == {}
    assert _get_fallback(2000) == {}
    assert _get_fallback(1999) == {}


async def test_load_unknown_year_uses_empty_fallback() -> None:
    """load(year=2099) with httpx failure falls back to empty dict; is_suspended returns False."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.TransportError("Network error"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("gps2asp.suspension.httpx.AsyncClient", return_value=mock_client):
        cal = HolidayCalendar()
        await cal.load(year=2099)

    assert cal._loaded is True
    assert cal._holidays == {}
    assert cal.is_suspended(date(2099, 1, 1)).is_suspended is False


# 6. load(year=2025) with httpx failure uses correct fallback (empty for unknown years)


async def test_load_year_2025_uses_correct_fallback() -> None:
    """load(year=2025) uses _get_fallback(2025); holidays match the fallback exactly."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.TransportError("Network error"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("gps2asp.suspension.httpx.AsyncClient", return_value=mock_client):
        cal = HolidayCalendar()
        await cal.load(year=2025)

    assert cal._loaded is True
    expected = _get_fallback(2025)
    assert cal._holidays == expected


# ---------------------------------------------------------------------------
# Phase 35.1 regression tests: HolidayCalendar.suspended_dates property
#
# These tests guard BUG-H-002 (vendored copy was missing this property,
# causing AttributeError in the HA Stage-3 pipeline call). Plan 35.1-01
# Task 2 syncs the property into the vendored copy; these tests document
# the property contract and prevent silent regression.
# ---------------------------------------------------------------------------


def test_suspended_dates_property_returns_frozenset() -> None:
    """suspended_dates returns a frozenset containing every loaded holiday date."""
    cal = HolidayCalendar()
    cal._holidays = {
        date(2026, 1, 1): "New Year",
        date(2026, 1, 19): "MLK Day",
    }
    result = cal.suspended_dates
    assert type(result) is frozenset
    assert date(2026, 1, 1) in result
    assert date(2026, 1, 19) in result


def test_suspended_dates_empty_before_load() -> None:
    """A fresh HolidayCalendar() with no holidays loaded returns frozenset()."""
    cal = HolidayCalendar()
    assert cal.suspended_dates == frozenset()


# ---------------------------------------------------------------------------
# Phase 35.1 BUG-T-008: _get_fallback unknown year logs ERROR
#
# Pre-fix, _get_fallback(2027) silently returned {} so the integration ran
# 2027 as if NYC had zero holidays — waking the user at 7 AM on Christmas
# to move their car. The fix is to ERROR-log when no fallback is hardcoded
# so HA diagnostics surface the missing data.
# ---------------------------------------------------------------------------


def test_get_fallback_unknown_year_logs_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """_get_fallback(2027) returns {} AND logs ERROR with the year and 'No fallback'."""
    import logging

    with caplog.at_level(logging.ERROR, logger="gps2asp.suspension"):
        result = _get_fallback(2027)

    assert result == {}
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1, (
        f"Expected exactly one ERROR log, got {len(error_records)}: "
        f"{[r.message for r in caplog.records]}"
    )
    msg = error_records[0].getMessage()
    assert "No fallback" in msg, f"Expected 'No fallback' in message, got: {msg}"
    assert "2027" in msg, f"Expected '2027' in message, got: {msg}"


def test_get_fallback_known_year_does_not_log_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """_get_fallback(2026) returns FALLBACK_2026 copy AND does not log ERROR."""
    import logging

    with caplog.at_level(logging.ERROR, logger="gps2asp.suspension"):
        result = _get_fallback(2026)

    assert result == FALLBACK_2026
    assert result is not FALLBACK_2026  # returns a copy, not the original
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert error_records == [], (
        f"Expected zero ERROR logs for known year 2026, got: "
        f"{[r.message for r in error_records]}"
    )


# ---------------------------------------------------------------------------
# Phase 35.1 BUG-T-009: _fetch_ics does NOT retry on 401/403
#
# Pre-fix, _fetch_ics retried up to MAX_RETRIES times on any HTTPStatusError
# including 401 and 403. Auth errors are not transient, so retrying wastes
# ~7s per request and produces misleading log noise. The fix short-circuits
# on 401/403 with a single warning log.
# ---------------------------------------------------------------------------


def _make_status_error(status_code: int) -> httpx.HTTPStatusError:
    """Build an httpx.HTTPStatusError mimicking a real response."""
    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(status_code=status_code, request=request)
    return httpx.HTTPStatusError(
        f"{status_code} error", request=request, response=response
    )


async def test_fetch_ics_no_retry_on_401(caplog: pytest.LogCaptureFixture) -> None:
    """401 short-circuits: _fetch_ics returns None after exactly 1 attempt."""
    import logging
    from gps2asp.suspension import _fetch_ics

    mock_get = AsyncMock(side_effect=_make_status_error(401))
    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("gps2asp.suspension.httpx.AsyncClient", return_value=mock_client):
        with caplog.at_level(logging.WARNING, logger="gps2asp.suspension"):
            result = await _fetch_ics(2026)

    assert result is None
    assert mock_get.await_count == 1, (
        f"Expected exactly 1 attempt for 401 (no retry), got {mock_get.await_count}"
    )
    assert any(
        "401" in r.getMessage() or "auth" in r.getMessage().lower()
        for r in caplog.records
    ), f"Expected an auth-error warning, got: {[r.getMessage() for r in caplog.records]}"


async def test_fetch_ics_no_retry_on_403(caplog: pytest.LogCaptureFixture) -> None:
    """403 short-circuits: _fetch_ics returns None after exactly 1 attempt."""
    from gps2asp.suspension import _fetch_ics

    mock_get = AsyncMock(side_effect=_make_status_error(403))
    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("gps2asp.suspension.httpx.AsyncClient", return_value=mock_client):
        result = await _fetch_ics(2026)

    assert result is None
    assert mock_get.await_count == 1


async def test_fetch_ics_still_retries_on_500() -> None:
    """500 keeps existing retry behaviour (up to MAX_RETRIES attempts)."""
    from gps2asp.suspension import _fetch_ics, MAX_RETRIES

    mock_get = AsyncMock(side_effect=_make_status_error(500))
    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    # Patch asyncio.sleep to make retries instant.
    with patch("gps2asp.suspension.httpx.AsyncClient", return_value=mock_client):
        with patch("gps2asp.suspension.asyncio.sleep", new=AsyncMock()):
            result = await _fetch_ics(2026)

    assert result is None
    assert mock_get.await_count == MAX_RETRIES, (
        f"Expected {MAX_RETRIES} attempts for 500, got {mock_get.await_count}"
    )
