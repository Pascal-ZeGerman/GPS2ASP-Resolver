"""ASP sign retrieval from NYC Open Data SODA API.

Public API: retrieve_signs() queries the SODA Parking Regulation Locations
and Signs dataset for current, non-voided ASP/broom signs on a given
block-face. Implements a three-level fallback strategy to handle street
name mismatches between CSCL and SODA formats.

This module is standalone -- no Home Assistant dependency.
"""

from __future__ import annotations

import logging
from itertools import product

from gps2asp.signs.client import SODAClient
from gps2asp.signs.exceptions import (
    IncompleteResultsError,
    SODAAPIError,
    SignRetrievalError,
)
from gps2asp.signs.models import (
    NoASPSigns,
    NoMatchFound,
    SignRecord,
    SignRetrievalResult,
    SignRetrievalSuccess,
)
from gps2asp.signs.normalize import name_variants, normalize_to_soda

__all__ = [
    "retrieve_signs",
    "SignRetrievalResult",
    "SignRetrievalSuccess",
    "NoASPSigns",
    "NoMatchFound",
    "SignRecord",
    "SODAAPIError",
    "IncompleteResultsError",
    "SignRetrievalError",
]

logger = logging.getLogger("gps2asp.signs")


def _deduplicate(records: list[dict]) -> list[SignRecord]:
    """Extract unique sign descriptions from raw SODA records.

    Args:
        records: Raw SODA API response record dicts.

    Returns:
        List of SignRecord with unique sign_description values.
    """
    seen: set[str] = set()
    unique: list[SignRecord] = []
    for record in records:
        desc = record.get("sign_description", "").strip()
        if desc and desc not in seen:
            seen.add(desc)
            unique.append(SignRecord(sign_description=desc))
    return unique


def _normalize_street(name: str) -> str:
    """Normalize a street name for comparison (uppercase, strip, expand)."""
    return normalize_to_soda(name.upper().strip())


def _cross_streets_match(
    record: dict,
    from_street: str,
    to_street: str,
) -> bool:
    """Check if a SODA record's cross streets match the expected ones.

    Compares normalized forms and also tries with from/to swapped,
    since SODA may have different directionality than CSCL.

    Args:
        record: Raw SODA API record dict.
        from_street: Expected from_street (CSCL format).
        to_street: Expected to_street (CSCL format).

    Returns:
        True if cross streets match in either direction.
    """
    record_from = _normalize_street(record.get("from_street", ""))
    record_to = _normalize_street(record.get("to_street", ""))

    # Normalize expected cross streets using all variants
    from_variants = {v.upper().strip() for v in name_variants(from_street)}
    to_variants = {v.upper().strip() for v in name_variants(to_street)}

    # Direct match: record from/to matches expected from/to
    if record_from in from_variants and record_to in to_variants:
        return True

    # Swapped match: record from/to matches expected to/from
    if record_from in to_variants and record_to in from_variants:
        return True

    return False


async def retrieve_signs(
    on_street: str,
    from_street: str,
    to_street: str,
    side_of_street: str,
    app_token: str | None = None,
) -> SignRetrievalResult:
    """Retrieve ASP/broom signs for a block-face from the SODA API.

    Implements a three-level fallback strategy:
      Level 1: Exact four-field match with SODA-normalized names
      Level 2: Try all abbreviation variant combinations
      Level 3: Broad on_street + side query with client-side cross-street filtering

    Args:
        on_street: Street name in CSCL format (e.g., "PROSPECT PL").
        from_street: Cross street at one end in CSCL format.
        to_street: Cross street at the other end in CSCL format.
        side_of_street: Compass direction side - N, S, E, or W.
        app_token: Optional NYC Open Data app token for higher rate limits.

    Returns:
        SignRetrievalResult: One of SignRetrievalSuccess, NoASPSigns,
        or NoMatchFound.

    Raises:
        SODAAPIError: If the SODA API returns errors after retries.
        IncompleteResultsError: If pagination was interrupted.
    """
    client = SODAClient(app_token=app_token)

    on_variants = name_variants(on_street)
    from_variants = name_variants(from_street)
    to_variants = name_variants(to_street)

    any_soda_results = False

    # ------------------------------------------------------------------
    # Level 1: Exact four-field match with SODA-normalized names (first variant)
    # ------------------------------------------------------------------
    logger.debug(
        "Level 1: exact match on_street=%r, from=%r, to=%r, side=%r",
        on_variants[0],
        from_variants[0],
        to_variants[0],
        side_of_street,
    )
    query = client.build_block_query(
        on_variants[0], from_variants[0], to_variants[0], side_of_street
    )
    records = await client.fetch_signs(query)
    logger.debug("Level 1: received %d raw records", len(records))

    if records:
        any_soda_results = True
        signs = _deduplicate(records)
        if signs:
            logger.info(
                "Level 1 matched: on_street=%r, from=%r, to=%r (%d unique signs)",
                on_variants[0],
                from_variants[0],
                to_variants[0],
                len(signs),
            )
            return SignRetrievalSuccess(
                status="signs_found",
                signs=signs,
                on_street=on_street,
                from_street=from_street,
                to_street=to_street,
                side_of_street=side_of_street,
                soda_level=1,
            )

    # ------------------------------------------------------------------
    # Level 2: Try remaining variant combinations (skip the first, which
    # was already tried in Level 1)
    # ------------------------------------------------------------------
    all_combos = list(product(on_variants, from_variants, to_variants))
    # Skip first combo (already tried in Level 1)
    remaining_combos = all_combos[1:]

    for on_var, from_var, to_var in remaining_combos:
        logger.debug(
            "Level 2: trying on_street=%r, from=%r, to=%r",
            on_var,
            from_var,
            to_var,
        )
        query = client.build_block_query(on_var, from_var, to_var, side_of_street)
        records = await client.fetch_signs(query)
        logger.debug("Level 2: received %d raw records", len(records))

        if records:
            any_soda_results = True
            signs = _deduplicate(records)
            if signs:
                logger.info(
                    "Level 2 matched: on_street=%r, from=%r, to=%r (%d unique signs)",
                    on_var,
                    from_var,
                    to_var,
                    len(signs),
                )
                return SignRetrievalSuccess(
                    status="signs_found",
                    signs=signs,
                    on_street=on_street,
                    from_street=from_street,
                    to_street=to_street,
                    side_of_street=side_of_street,
                    soda_level=2,
                )

    # ------------------------------------------------------------------
    # Level 3: Broad match (on_street + side only), client-side filtering
    # ------------------------------------------------------------------
    for on_var in on_variants:
        logger.debug(
            "Level 3: broad query on_street=%r, side=%r",
            on_var,
            side_of_street,
        )
        query = client.build_on_street_query(on_var, side_of_street)
        records = await client.fetch_signs(query)
        logger.debug("Level 3: received %d raw records for broad query", len(records))

        if records:
            any_soda_results = True
            # Client-side cross-street filtering
            filtered = [
                r
                for r in records
                if _cross_streets_match(r, from_street, to_street)
            ]
            logger.debug(
                "Level 3: %d records after cross-street filtering", len(filtered)
            )

            if filtered:
                signs = _deduplicate(filtered)
                if signs:
                    logger.info(
                        "Level 3 matched: on_street=%r (broad), "
                        "client-side filtered (%d unique signs)",
                        on_var,
                        len(signs),
                    )
                    return SignRetrievalSuccess(
                        status="signs_found",
                        signs=signs,
                        on_street=on_street,
                        from_street=from_street,
                        to_street=to_street,
                        side_of_street=side_of_street,
                        soda_level=3,
                    )

    # ------------------------------------------------------------------
    # All three levels exhausted
    # ------------------------------------------------------------------
    if any_soda_results:
        # SODA returned records, but none were broom signs after filtering
        logger.info(
            "No ASP signs found for %s between %s and %s (%s side)",
            on_street,
            from_street,
            to_street,
            side_of_street,
        )
        return NoASPSigns()

    # No results from SODA at all
    logger.info(
        "No match found in SODA for %s between %s and %s (%s side)",
        on_street,
        from_street,
        to_street,
        side_of_street,
    )
    return NoMatchFound()
