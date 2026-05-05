"""Async SODA API client for NYC parking sign retrieval.

Handles pagination, retry with exponential backoff, and query
construction for the Parking Regulation Locations and Signs dataset
(identifier: nfid-uabd).
"""

from __future__ import annotations

import asyncio
import logging
import os

import httpx

from gps2asp.signs.exceptions import IncompleteResultsError, SODAAPIError
from gps2asp.signs.normalize import escape_soql

logger = logging.getLogger("gps2asp.signs")


class SODAClient:
    """Async client for querying NYC Open Data SODA API parking signs.

    Supports optional app token for dedicated rate limit pool.
    All queries include the SANITATION BROOM filter and voided sign
    exclusion (sign_design_voided_on_date IS NULL) per SIGN-02.

    Args:
        app_token: Optional NYC Open Data app token. If not provided,
            falls back to the NYC_OPEN_DATA_APP_TOKEN environment variable.
    """

    PARKING_SIGNS_URL = "https://data.cityofnewyork.us/resource/nfid-uabd.json"
    DEFAULT_BATCH_SIZE = 1000
    MAX_RETRIES = 3
    BASE_DELAY = 1.0  # seconds

    def __init__(self, app_token: str | None = None) -> None:
        self._app_token = app_token or os.environ.get("NYC_OPEN_DATA_APP_TOKEN")

    async def fetch_signs(self, where: str) -> list[dict]:
        """Fetch all matching sign records with pagination and retry.

        Paginates through all matching records using $limit/$offset
        with $order=order_number for consistent results. Each
        individual page request is retried with exponential backoff
        on transient errors.

        Args:
            where: SoQL $where clause (e.g., from build_block_query).

        Returns:
            List of raw SODA API record dicts.

        Raises:
            SODAAPIError: After MAX_RETRIES exhausted on any page.
            IncompleteResultsError: If initial pages succeeded but
                a subsequent page fails after retries.
        """
        all_records: list[dict] = []
        offset = 0

        headers: dict[str, str] = {}
        if self._app_token:
            headers["X-App-Token"] = self._app_token

        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            while True:
                params = {
                    "$where": where,
                    "$limit": str(self.DEFAULT_BATCH_SIZE),
                    "$offset": str(offset),
                    "$order": "order_number",
                }

                records = await self._fetch_page_with_retry(
                    client, params, len(all_records)
                )
                all_records.extend(records)

                logger.debug(
                    "SODA query batch: offset=%d, received=%d, total=%d",
                    offset,
                    len(records),
                    len(all_records),
                )

                if len(records) < self.DEFAULT_BATCH_SIZE:
                    break
                offset += self.DEFAULT_BATCH_SIZE

        return all_records

    async def _fetch_page_with_retry(
        self,
        client: httpx.AsyncClient,
        params: dict[str, str],
        records_fetched_so_far: int,
    ) -> list[dict]:
        """Fetch a single page of results with retry logic.

        Args:
            client: The httpx async client to use.
            params: Query parameters including $where, $limit, $offset, $order.
            records_fetched_so_far: Number of records already fetched
                (used for IncompleteResultsError if this is not the first page).

        Returns:
            List of record dicts for this page.

        Raises:
            SODAAPIError: If this is the first page and all retries exhausted.
            IncompleteResultsError: If previous pages succeeded but
                this page fails after all retries.
        """
        last_error: Exception | None = None

        for attempt in range(self.MAX_RETRIES):
            try:
                response = await client.get(self.PARKING_SIGNS_URL, params=params)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status_code = exc.response.status_code
                delay = self.BASE_DELAY * (2**attempt)
                logger.warning(
                    "SODA API attempt %d/%d failed: HTTP %d (retry in %.1fs)",
                    attempt + 1,
                    self.MAX_RETRIES,
                    status_code,
                    delay,
                )
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(delay)
            except httpx.TransportError as exc:
                last_error = exc
                delay = self.BASE_DELAY * (2**attempt)
                logger.warning(
                    "SODA API attempt %d/%d failed: %s (retry in %.1fs)",
                    attempt + 1,
                    self.MAX_RETRIES,
                    exc,
                    delay,
                )
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(delay)

        # All retries exhausted
        if last_error is None:
            raise RuntimeError(
                "unreachable: retry loop exited without recording an error"
            )

        if records_fetched_so_far > 0:
            # Previous pages succeeded -- this is an incomplete result
            raise IncompleteResultsError(
                records_fetched=records_fetched_so_far,
                detail=str(last_error),
            )

        # First page failed -- raise SODA API error
        raise SODAAPIError(
            status_code=last_error.response.status_code
            if isinstance(last_error, httpx.HTTPStatusError)
            else None,
            detail=str(last_error),
        )

    def build_block_query(
        self,
        on_street: str,
        from_street: str,
        to_street: str,
        side: str,
    ) -> str:
        """Build a $where clause for exact four-field block-face match.

        Always includes the SANITATION BROOM filter and voided sign
        exclusion per SIGN-02.

        Args:
            on_street: Street name (will be SoQL-escaped).
            from_street: Cross street at one end (will be SoQL-escaped).
            to_street: Cross street at the other end (will be SoQL-escaped).
            side: Side of street (N, S, E, or W).

        Returns:
            SoQL $where clause string.
        """
        on_esc = escape_soql(on_street)
        from_esc = escape_soql(from_street)
        to_esc = escape_soql(to_street)
        side_esc = escape_soql(side)

        return (
            "sign_description LIKE '%SANITATION BROOM%'"
            " AND sign_design_voided_on_date IS NULL"
            f" AND on_street='{on_esc}'"
            f" AND from_street='{from_esc}'"
            f" AND to_street='{to_esc}'"
            f" AND side_of_street='{side_esc}'"
        )

    def build_on_street_query(self, on_street: str, side: str) -> str:
        """Build a $where clause for broad on_street + side match.

        Used for Level 3 fallback queries where cross streets are
        dropped in favor of client-side filtering. Always includes
        the SANITATION BROOM filter and voided sign exclusion.

        Args:
            on_street: Street name (will be SoQL-escaped).
            side: Side of street (N, S, E, or W).

        Returns:
            SoQL $where clause string.
        """
        on_esc = escape_soql(on_street)
        side_esc = escape_soql(side)

        return (
            "sign_description LIKE '%SANITATION BROOM%'"
            " AND sign_design_voided_on_date IS NULL"
            f" AND on_street='{on_esc}'"
            f" AND side_of_street='{side_esc}'"
        )
