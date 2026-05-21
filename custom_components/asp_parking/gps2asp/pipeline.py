"""GPS2ASP pipeline: full GPS-to-ASP-schedule resolver.

This module contains the implementation of resolve_asp(), the single public
entry point that wires the four pipeline stages together.
"""

from __future__ import annotations

from datetime import date
from typing import Literal, overload

from .api_models import ASPDebugResult, ASPResult
from .resolver import convert, resolve_segment
from .resolver.exceptions import AmbiguousResolutionError
from .schedule import compute_schedule
from .signs import retrieve_signs
from .signs.models import SignRetrievalSuccess
from .suspension import SuspensionInfo, apply_suspension


@overload
async def resolve_asp(
    lat: float,
    lon: float,
    debug: Literal[False] = ...,
    suspension_status: SuspensionInfo | None = ...,
    suspended_dates: frozenset[date] | None = ...,
) -> ASPResult: ...  # lgtm[py/ineffectual-statement]


@overload
async def resolve_asp(
    lat: float,
    lon: float,
    debug: Literal[True],
    suspension_status: SuspensionInfo | None = ...,
    suspended_dates: frozenset[date] | None = ...,
) -> ASPDebugResult: ...  # lgtm[py/ineffectual-statement]


async def resolve_asp(
    lat: float,
    lon: float,
    debug: bool = False,
    suspension_status: SuspensionInfo | None = None,
    suspended_dates: frozenset[date] | None = None,
) -> ASPResult | ASPDebugResult:
    """Resolve GPS coordinates to an ASP schedule.

    Runs the full pipeline: GPS -> street segment -> SODA signs -> schedule,
    with an optional Stage 4 suspension annotation.
    AmbiguousResolutionError is caught and surfaced as structured fields on the result
    rather than propagating. All other errors (OutsideNYCError, NoSegmentFoundError,
    network failures) propagate to the caller.

    Args:
        lat: Latitude in WGS84.
        lon: Longitude in WGS84.
        debug: When True, returns ASPDebugResult with all intermediate pipeline state.
            When False (default), returns lean ASPResult.
        suspension_status: Optional suspension check result. When provided and
            is_suspended=True, apply_suspension() runs as Stage 4 after
            compute_schedule(), annotating the result with suspended=True,
            suspension_reason, and resolution_reason. When None (default),
            pipeline is identical to pre-v3.0 — fully backwards compatible.

    Returns:
        ASPResult when debug=False; ASPDebugResult when debug=True.

    Raises:
        OutsideNYCError: Coordinates are outside NYC bounding box.
        NoSegmentFoundError: No street segment found within 164ft.
        IndexNotFoundError: Spatial index files are absent (index not built).
        SODAAPIError: SODA API returned errors after retries.
        IncompleteResultsError: SODA pagination was interrupted.
    """
    # Convert coordinates once — used both as resolve_segment input and for state_plane fields
    x, y = convert(lat, lon)

    # Stage 1: GPS -> street segment + side
    try:
        resolution = await resolve_segment(x, y, input_lat=lat, input_lon=lon)
    except AmbiguousResolutionError as err:
        if debug:
            return ASPDebugResult.from_error(str(err), x, y)
        return ASPResult(
            schedule=None,
            resolution_failed=True,
            resolution_error=str(err),
        )

    # Stage 2: street segment -> SODA signs
    sign_result = await retrieve_signs(
        on_street=resolution.on_street,
        from_street=resolution.from_street,
        to_street=resolution.to_street,
        side_of_street=resolution.side_of_street,
    )

    # Stage 3: signs -> schedule
    schedule = compute_schedule(sign_result, suspended_dates=suspended_dates)

    # Stage 4: apply suspension annotation (optional, post-pipeline)
    if suspension_status is not None:
        schedule = apply_suspension(schedule, suspension_status)

    if debug:
        soda_level = (
            sign_result.soda_level
            if isinstance(sign_result, SignRetrievalSuccess)
            else 0
        )
        return ASPDebugResult.from_resolution(
            resolution=resolution,
            sign_result=sign_result,
            schedule=schedule,
            state_plane_x=x,
            state_plane_y=y,
            soda_level=soda_level,
        )

    return ASPResult(
        schedule=schedule,
        resolution_failed=False,
        resolution_error=None,
        soda_level=sign_result.soda_level
        if isinstance(sign_result, SignRetrievalSuccess)
        else 0,
    )
