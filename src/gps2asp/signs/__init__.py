"""ASP sign retrieval from NYC Open Data SODA API.

Public API: retrieve_signs() queries the SODA Parking Regulation Locations
and Signs dataset for current, non-voided ASP/broom signs on a given
block-face. Implements a four-level fallback strategy to handle street
name mismatches between CSCL and SODA formats.

  Level 1: Exact four-field match with SODA-normalized names
  Level 2: Try all abbreviation variant combinations
  Level 3: Broad on_street + side query with client-side cross-street filtering
  Level 4: Best-covering span via street graph distance (mid-span blocks)

Level 4 activates only when Levels 1-3 return no SODA results at all,
and requires graph.json to be present in the index directory. It queries
all signs on the street+side and picks the SODA span whose endpoints are
graph-distance closest to the block's cross streets.

This module is standalone -- no Home Assistant dependency.
"""

from __future__ import annotations

import logging
from itertools import product

from .client import SODAClient
from .exceptions import (
    IncompleteResultsError,
    SODAAPIError,
    SignRetrievalError,
)
from .graph import StreetGraph
from .models import (
    NoASPSigns,
    NoMatchFound,
    SignRecord,
    SignRetrievalResult,
    SignRetrievalSuccess,
)
from .normalize import name_variants, normalize_to_soda

__all__ = [
    "retrieve_signs",
    "materialize_cached_records",
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


def materialize_cached_records(
    records: list[dict],
    on_street: str,
    from_street: str,
    to_street: str,
    side_of_street: str,
    soda_level: int = 1,
) -> SignRetrievalResult:
    """Build a SignRetrievalResult from pre-fetched raw SODA records.

    Used by the HA coordinator's parking-area sign cache to deliver
    the same result shape as retrieve_signs() without making a network
    call. Empty `records` => NoMatchFound; records present but after
    deduplication and SANITATION BROOM filtering no signs remain =>
    NoASPSigns; otherwise SignRetrievalSuccess.

    NOTE: This function applies a defensive SANITATION BROOM filter (IN-03).
    Callers should pass BROOM-filtered records from ``build_block_query`` for
    efficiency; the in-function filter is a defence-in-depth guard against
    future callers that bypass ``build_block_query``.

    Args:
        records: Raw SODA API record dicts as returned by SODAClient.fetch_signs.
        on_street: Canonical on_street name (CSCL format).
        from_street: Canonical from_street name (CSCL format).
        to_street: Canonical to_street name (CSCL format).
        side_of_street: Compass direction side (N, S, E, or W).
        soda_level: Fallback level marker; defaults to 1 since the cache
            is populated via Level 1 block queries.

    Returns:
        SignRetrievalResult of the appropriate variant.
    """
    if not records:
        return NoMatchFound()
    signs = _deduplicate(records)
    # IN-03: defensive BROOM filter. Callers MUST pass BROOM-filtered records
    # (the contract is documented above), but this guard catches any future
    # caller that bypasses ``build_block_query`` -- a silent contamination
    # bug would otherwise inject non-broom records (e.g. NO STANDING signs)
    # into the schedule pipeline. Cheap and idempotent on already-filtered
    # input.
    signs = [
        sign for sign in signs
        if "SANITATION BROOM" in sign.sign_description
    ]
    if not signs:
        return NoASPSigns()
    return SignRetrievalSuccess(
        status="signs_found",
        signs=signs,
        on_street=on_street,
        from_street=from_street,
        to_street=to_street,
        side_of_street=side_of_street,
        soda_level=soda_level,
    )


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
    # BUG-S-003: Refuse to match when either side of the comparison has an empty
    # cross-street name. name_variants("") returns [""], so without this guard
    # an empty SODA field matches an empty caller arg (or vice versa) and
    # silently admits an unrelated record into the filter results.
    record_from_raw = record.get("from_street", "")
    record_to_raw = record.get("to_street", "")
    if not record_from_raw or not record_to_raw:
        return False
    if not from_street or not to_street:
        return False

    # Normalize the raw SODA record fields (uppercase, strip, expand abbreviations)
    record_from = _normalize_street(record_from_raw)
    record_to = _normalize_street(record_to_raw)

    # Generate all known variants of the CSCL cross-street names for matching
    # (name_variants expands abbreviations like AVE→AVENUE, PL→PLACE, etc.)
    from_variants = {v.upper().strip() for v in name_variants(from_street)}
    to_variants = {v.upper().strip() for v in name_variants(to_street)}

    # Direct match: record from/to matches expected from/to
    if record_from in from_variants and record_to in to_variants:
        return True

    # Swapped match: record from/to matches expected to/from
    if record_from in to_variants and record_to in from_variants:
        return True

    return False


async def _try_query(
    client: SODAClient,
    on_var: str,
    from_var: str,
    to_var: str,
    side_of_street: str,
    on_street: str,
    from_street: str,
    to_street: str,
    soda_level: int,
    prefetched_records: list[dict] | None = None,
) -> SignRetrievalSuccess | None:
    """Attempt one SODA query level. Returns SignRetrievalSuccess or None.

    Deduplicates sign descriptions from records and returns a success result
    or None if no matching signs were found. If prefetched_records is provided,
    those records are used directly (skipping the network query). This supports
    Level 3's broad-fetch-then-filter pattern.

    Args:
        client: SODAClient instance to use for the query.
        on_var: on_street name variant for the SODA block query.
        from_var: from_street name variant for the SODA block query.
        to_var: to_street name variant for the SODA block query.
        side_of_street: Compass direction side (N, S, E, or W).
        on_street: Canonical on_street name (used in result, not in query).
        from_street: Canonical from_street name (used in result, not in query).
        to_street: Canonical to_street name (used in result, not in query).
        soda_level: Fallback level number (1, 2, or 3) for the result.
        prefetched_records: If provided, use these records instead of fetching.
            Used by Level 3 to pass pre-filtered broad-query results.

    Returns:
        SignRetrievalSuccess if matching signs found, None otherwise.
    """
    if prefetched_records is not None:
        records = prefetched_records
    else:
        query = client.build_block_query(on_var, from_var, to_var, side_of_street)
        records = await client.fetch_signs(query)
    if not records:
        return None
    signs = _deduplicate(records)
    if not signs:
        return None
    return SignRetrievalSuccess(
        status="signs_found",
        signs=signs,
        on_street=on_street,
        from_street=from_street,
        to_street=to_street,
        side_of_street=side_of_street,
        soda_level=soda_level,
    )


async def retrieve_signs(
    on_street: str,
    from_street: str,
    to_street: str,
    side_of_street: str,
    app_token: str | None = None,
) -> SignRetrievalResult:
    """Retrieve ASP/broom signs for a block-face from the SODA API.

    Implements a four-level fallback strategy:
      Level 1: Exact four-field match with SODA-normalized names
      Level 2: Try all abbreviation variant combinations
      Level 3: Broad on_street + side query with client-side cross-street filtering
      Level 4: Best-covering span via graph distance (mid-span blocks, requires graph.json)

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
    # BUG-S-001: capture L3's broad-query records keyed by on_var so that L4
    # can reuse them instead of issuing an identical second HTTP request.
    l3_broad_records_by_var: dict[str, list[dict]] = {}

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
    result = await _try_query(
        client,
        on_variants[0],
        from_variants[0],
        to_variants[0],
        side_of_street,
        on_street,
        from_street,
        to_street,
        soda_level=1,
    )
    if result is not None:
        logger.info(
            "Level 1 matched: on_street=%r, from=%r, to=%r (%d unique signs)",
            on_variants[0],
            from_variants[0],
            to_variants[0],
            len(result.signs),
        )
        return result

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
        result = await _try_query(
            client,
            on_var,
            from_var,
            to_var,
            side_of_street,
            on_street,
            from_street,
            to_street,
            soda_level=2,
        )
        if result is not None:
            logger.info(
                "Level 2 matched: on_street=%r, from=%r, to=%r (%d unique signs)",
                on_var,
                from_var,
                to_var,
                len(result.signs),
            )
            return result

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

        # BUG-S-001: Stash L3's broad records so L4 (if reached) can reuse them
        # rather than issuing an identical second HTTP call on the same on_var.
        l3_broad_records_by_var[on_var] = records

        if records:
            # Client-side cross-street filtering
            filtered = [
                r for r in records if _cross_streets_match(r, from_street, to_street)
            ]
            logger.debug(
                "Level 3: %d records after cross-street filtering", len(filtered)
            )

            if filtered:
                # Cross streets matched: this block exists in SODA. Level 4 is
                # not needed regardless of whether broom signs are present.
                any_soda_results = True
                result = await _try_query(
                    client,
                    on_var,
                    from_variants[0],
                    to_variants[0],
                    side_of_street,
                    on_street,
                    from_street,
                    to_street,
                    soda_level=3,
                    prefetched_records=filtered,
                )
                if result is not None:
                    logger.info(
                        "Level 3 matched: on_street=%r (broad), "
                        "client-side filtered (%d unique signs)",
                        on_var,
                        len(result.signs),
                    )
                    return result
                # filtered had records but dedup yielded no signs —
                # block is in SODA but has no ASP broom signs.

    # ------------------------------------------------------------------
    # Level 4: Best-covering span (mid-span blocks)
    # ------------------------------------------------------------------
    # Only attempt if no SODA results from Levels 1-3. When any_soda_results
    # is True but no ASP signs were found, the records existed but contained no
    # broom signs -- Level 4 won't help in that case.
    if not any_soda_results:
        graph = StreetGraph.get()
        if graph is None:
            logger.warning(
                "Level 4: graph.json not available -- skipping mid-span fallback"
            )
        else:
            logger.info(
                "l4_event=l4_entry on_street=%r from=%r to=%r side=%r "
                'reason="levels 1-3 returned no SODA results"',
                on_street,
                from_street,
                to_street,
                side_of_street,
            )
            for on_var in on_variants:
                logger.debug(
                    "Level 4: broad query on_street=%r, side=%r",
                    on_var,
                    side_of_street,
                )
                # BUG-S-001: Reuse L3's broad-query records when available
                # for this on_var, avoiding a duplicate HTTP round-trip
                # (the query string would be identical to L3's).
                cached = l3_broad_records_by_var.get(on_var)
                if cached is not None:
                    records = cached
                    logger.debug(
                        "Level 4: reused %d L3 broad records for on_var=%r "
                        "(no duplicate SODA call)",
                        len(records),
                        on_var,
                    )
                else:
                    query = client.build_on_street_query(on_var, side_of_street)
                    records = await client.fetch_signs(query)
                    logger.debug(
                        "Level 4: received %d raw records for broad query",
                        len(records),
                    )

                if records:
                    span_count = len(
                        {
                            (r.get("from_street", ""), r.get("to_street", ""))
                            for r in records
                        }
                    )
                    # Local import: _find_best_covering_span is a private
                    # implementation detail of signs.graph; importing here
                    # keeps it off the package's public namespace.
                    from .graph import _find_best_covering_span  # noqa: PLC0415

                    best_span = _find_best_covering_span(
                        records, from_street, to_street, graph
                    )
                    if best_span is not None:
                        # BUG-S-002: only mark "SODA confirmed this block" when
                        # L4 actually found a covering span — broad-query
                        # records on the same on_street/side do NOT mean our
                        # specific block exists in SODA. With this gate, the
                        # function correctly returns NoMatchFound (not
                        # NoASPSigns) when every on_var has best_span == None.
                        any_soda_results = True
                        span_from = best_span[0].get("from_street", "")
                        span_to = best_span[0].get("to_street", "")
                        logger.info(
                            "l4_event=l4_match on_street=%r span_from=%r span_to=%r signs=%d",
                            on_var,
                            span_from,
                            span_to,
                            len(best_span),
                        )
                        result = await _try_query(
                            client,
                            on_var,
                            from_variants[0],
                            to_variants[0],
                            side_of_street,
                            on_street,
                            from_street,
                            to_street,
                            soda_level=4,
                            prefetched_records=best_span,
                        )
                        if result is not None:
                            return result
                    else:
                        logger.info(
                            "l4_event=l4_no_span on_var=%r on_street=%r from=%r to=%r side=%r "
                            "span_candidates=%d",
                            on_var,
                            on_street,
                            from_street,
                            to_street,
                            side_of_street,
                            span_count,
                        )
                else:
                    logger.info(
                        "l4_event=l4_no_records on_var=%r on_street=%r from=%r to=%r side=%r",
                        on_var,
                        on_street,
                        from_street,
                        to_street,
                        side_of_street,
                    )

    # ------------------------------------------------------------------
    # All four levels exhausted
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
