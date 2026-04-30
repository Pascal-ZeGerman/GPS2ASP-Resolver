"""NYC 311 API client for weather/emergency ASP suspension status.

Polls the NYC 311 GetCalendar endpoint for today's Alternate Side
Parking status. Fails open on network errors (returns not-suspended).
Raises NYC311AuthError on HTTP 401/403.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from . import SuspensionInfo

logger = logging.getLogger("gps2asp.suspension.poller")

NYC_TZ = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class NYC311AuthError(Exception):
    """Raised when the NYC 311 API returns HTTP 401 or 403.

    Attributes:
        status_code: HTTP status code (401 or 403).
        detail: Human-readable error description.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"NYC 311 API auth error (HTTP {status_code}): {detail}")


# ---------------------------------------------------------------------------
# Fail-open default
# ---------------------------------------------------------------------------

_NOT_SUSPENDED = SuspensionInfo(is_suspended=False, reason=None, source="none")

# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class NYC311Client:
    """Async client for NYC 311 GetCalendar API.

    Fetches today's ASP suspension status. Mirrors SODAClient pattern:
    constructor arg with env-var fallback, retry with exponential backoff.

    Args:
        api_key: Optional NYC 311 API subscription key. Falls back to
            the NYC_311_API_KEY environment variable.
    """

    API_URL = "https://api.nyc.gov/public/api/GetCalendar"
    MAX_RETRIES = 3
    BASE_DELAY = 1.0  # seconds

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("NYC_311_API_KEY")

    async def fetch_status(self) -> SuspensionInfo:
        """Fetch today's ASP suspension status from the 311 API.

        Returns:
            SuspensionInfo with is_suspended=True and source='emergency'
            when ASP is suspended, otherwise is_suspended=False.

        Raises:
            NYC311AuthError: On HTTP 401 or 403 (invalid/missing key).
        """
        # D-06: no key => fail open immediately, no HTTP call
        if self._api_key is None:
            return _NOT_SUSPENDED

        today = datetime.now(NYC_TZ).date()
        today_str = today.strftime("%m/%d/%Y")

        headers = {"Ocp-Apim-Subscription-Key": self._api_key}
        params = {"fromdate": today_str, "todate": today_str}

        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(self.MAX_RETRIES):
                try:
                    response = await client.get(
                        self.API_URL, params=params, headers=headers
                    )
                    response.raise_for_status()
                    return self._parse_response(response.json())

                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code
                    # D-08: auth errors are NOT retried
                    if status_code in (401, 403):
                        raise NYC311AuthError(
                            status_code=status_code, detail=str(exc)
                        ) from exc
                    # Transient server error — retry
                    delay = self.BASE_DELAY * (2**attempt)
                    logger.warning(
                        "311 API attempt %d/%d failed: HTTP %d (retry in %.1fs)",
                        attempt + 1,
                        self.MAX_RETRIES,
                        status_code,
                        delay,
                    )
                    if attempt < self.MAX_RETRIES - 1:
                        await asyncio.sleep(delay)

                except httpx.TransportError as exc:
                    # D-09: network errors — retry, then fail open
                    delay = self.BASE_DELAY * (2**attempt)
                    logger.warning(
                        "311 API attempt %d/%d failed: %s (retry in %.1fs)",
                        attempt + 1,
                        self.MAX_RETRIES,
                        exc,
                        delay,
                    )
                    if attempt < self.MAX_RETRIES - 1:
                        await asyncio.sleep(delay)

        # All retries exhausted — fail open
        logger.warning("311 API all %d attempts exhausted, failing open", self.MAX_RETRIES)
        return _NOT_SUSPENDED

    @staticmethod
    def _parse_response(data: dict) -> SuspensionInfo:
        """Extract ASP suspension status from 311 API response JSON."""
        days = data.get("days", [])
        if not days:
            return _NOT_SUSPENDED

        items = days[0].get("items", [])
        for item in items:
            if item.get("type") == "Alternate Side Parking":
                if item.get("status") == "SUSPENDED":
                    reason = item.get("exceptionName") or item.get("details")
                    return SuspensionInfo(
                        is_suspended=True,
                        reason=reason or None,
                        source="emergency",
                    )
                # IN_EFFECT, NOT_IN_EFFECT, NO_INFORMATION — not suspended
                return _NOT_SUSPENDED

        # No ASP item found
        return _NOT_SUSPENDED
