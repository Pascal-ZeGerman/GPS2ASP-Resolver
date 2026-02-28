"""GPS2ASP: GPS-to-street resolver for NYC Alternate Side Parking."""

from __future__ import annotations

__version__ = "0.1.0"

from typing import Literal, overload

from gps2asp.resolver import resolve, convert, resolve_segment
from gps2asp.resolver.models import ResolutionResult
from gps2asp.resolver.exceptions import (
    ResolutionError,
    OutsideNYCError,
    NoSegmentFoundError,
    AmbiguousResolutionError,
)
from gps2asp.api_models import ASPResult, ASPDebugResult
from gps2asp.signs import retrieve_signs
from gps2asp.signs.models import SignRetrievalSuccess
from gps2asp.schedule import compute_schedule

__all__ = [
    "resolve",
    "convert",
    "resolve_segment",
    "ResolutionResult",
    "ResolutionError",
    "OutsideNYCError",
    "NoSegmentFoundError",
    "AmbiguousResolutionError",
    "resolve_asp",
    "ASPResult",
    "ASPDebugResult",
]


@overload
async def resolve_asp(
    lat: float,
    lon: float,
    debug: Literal[False] = ...,
) -> ASPResult: ...


@overload
async def resolve_asp(
    lat: float,
    lon: float,
    debug: Literal[True],
) -> ASPDebugResult: ...


async def resolve_asp(
    lat: float,
    lon: float,
    debug: bool = False,
) -> ASPResult | ASPDebugResult:
    """Resolve GPS coordinates to an ASP schedule.

    Runs the full three-stage pipeline: GPS -> street segment -> SODA signs -> schedule.
    AmbiguousResolutionError is caught and surfaced as structured fields on the result
    rather than propagating. All other errors (OutsideNYCError, NoSegmentFoundError,
    network failures) propagate to the caller.

    Args:
        lat: Latitude in WGS84.
        lon: Longitude in WGS84.
        debug: When True, returns ASPDebugResult with all intermediate pipeline state.
            When False (default), returns lean ASPResult.

    Returns:
        ASPResult when debug=False; ASPDebugResult when debug=True.

    Raises:
        OutsideNYCError: Coordinates are outside NYC bounding box.
        NoSegmentFoundError: No street segment found within 164ft.
        SODAAPIError: SODA API returned errors after retries.
        IncompleteResultsError: SODA pagination was interrupted.
    """
    # Convert coordinates once — used both as resolve_segment input and for state_plane fields
    x, y = convert(lat, lon)

    # Stage 1: GPS -> street segment + side
    try:
        resolution = await resolve_segment(x, y, _input_lat=lat, _input_lon=lon)
    except AmbiguousResolutionError as err:
        if debug:
            return ASPDebugResult(
                schedule=None,
                resolution_failed=True,
                resolution_error=str(err),
                on_street=None,
                from_street=None,
                to_street=None,
                side_of_street=None,
                resolution=None,
                sign_result=None,
                confidence=0.0,
                state_plane_x=x,
                state_plane_y=y,
                soda_level=0,
            )
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
    schedule = compute_schedule(sign_result)

    if debug:
        soda_level = sign_result.soda_level if isinstance(sign_result, SignRetrievalSuccess) else 0
        return ASPDebugResult(
            schedule=schedule,
            resolution_failed=False,
            resolution_error=None,
            on_street=resolution.on_street,
            from_street=resolution.from_street,
            to_street=resolution.to_street,
            side_of_street=resolution.side_of_street,
            resolution=resolution,
            sign_result=sign_result,
            confidence=resolution.confidence,
            state_plane_x=x,
            state_plane_y=y,
            soda_level=soda_level,
        )

    return ASPResult(
        schedule=schedule,
        resolution_failed=False,
        resolution_error=None,
    )
