"""Top-level API result models for the resolve_asp() pipeline wrapper.

These frozen dataclasses represent the output of resolve_asp() — the single
importable function that runs the full GPS-to-schedule pipeline.

Two variants:
    ASPResult      — lean result when debug=False (schedule + error fields only)
    ASPDebugResult — rich result when debug=True (all 17 intermediate fields)
"""

from __future__ import annotations

from dataclasses import dataclass

from .resolver.models import ResolutionResult
from .schedule.models import ScheduleResult
from .signs.models import SignRetrievalResult


@dataclass(frozen=True)
class ASPResult:
    """Top-level result from resolve_asp() when debug=False.

    Provides the minimal information callers need to act on the schedule
    or surface an error to the user.

    Attributes:
        schedule: Parsed schedule result. None if resolution failed (i.e.,
            AmbiguousResolutionError was caught inside resolve_asp).
        resolution_failed: True when AmbiguousResolutionError was caught
            inside resolve_asp(). The GPS point could not be assigned to
            a unique street segment.
        resolution_error: Human-readable error message string when
            resolution_failed is True; None on success.
        soda_level: Which SODA fallback level resolved the parking data (1–4).
            Set to 0 when no SODA query was reached (resolution failed) or
            when sign retrieval returned no match.
    """

    schedule: ScheduleResult | None
    resolution_failed: bool
    resolution_error: str | None
    soda_level: int = 0  # 0 = no SODA match; 1–4 = which fallback level matched


@dataclass(frozen=True)
class ASPDebugResult:
    """Top-level result from resolve_asp(debug=True).

    All intermediate pipeline state is included for inspection and testing.
    Enables callers to trace exactly which street segment was resolved,
    which SODA fallback level matched, and what confidence score was assigned.

    Attributes:
        schedule: Parsed schedule result. None if resolution failed.
        resolution_failed: True when AmbiguousResolutionError was caught.
        resolution_error: Error message if resolution_failed is True, else None.
        on_street: Resolved street name in CSCL format (e.g., "PROSPECT PL"),
            or None if resolution failed.
        from_street: Cross street at one end in CSCL format, or None if
            resolution failed.
        to_street: Cross street at other end in CSCL format, or None if
            resolution failed.
        side_of_street: Compass direction side of street (N/S/E/W), or None
            if resolution failed.
        resolution: Full ResolutionResult from Phase 1 resolver, or None if
            resolution failed.
        sign_result: Full SignRetrievalResult from Phase 2 sign retrieval, or
            None if resolution failed.
        confidence: Resolution confidence score in [0.0, 1.0]. Set to 0.0
            when resolution failed.
        state_plane_x: NY State Plane X coordinate (feet) for the input GPS
            point.
        state_plane_y: NY State Plane Y coordinate (feet) for the input GPS
            point.
        soda_level: SODA fallback level that matched (1, 2, 3, or 4). Set to 0
            if no SODA match was found or resolution failed.
        borocode: CSCL borough code as string ("1"=Manhattan…"5"=Staten Island), or None when resolution failed.
        perpendicular_distance_ft: Perpendicular distance from GPS point to segment centerline (feet), rounded to 2 decimals. None when resolution failed.
        street_width_ft: Effective street width used in confidence calc (feet). None when resolution failed.
        segment_id: CSCL physical segment ID. None when resolution failed.
    """

    schedule: ScheduleResult | None
    resolution_failed: bool
    resolution_error: str | None
    on_street: str | None
    from_street: str | None
    to_street: str | None
    side_of_street: str | None
    resolution: ResolutionResult | None
    sign_result: SignRetrievalResult | None
    confidence: float
    state_plane_x: float
    state_plane_y: float
    soda_level: int
    borocode: str | None = None
    perpendicular_distance_ft: float | None = None
    street_width_ft: float | None = None
    segment_id: int | None = None

    @classmethod
    def from_resolution(
        cls,
        resolution: ResolutionResult,
        sign_result: SignRetrievalResult,
        schedule: ScheduleResult,
        state_plane_x: float,
        state_plane_y: float,
        soda_level: int,
    ) -> ASPDebugResult:
        """Build ASPDebugResult for the successful pipeline resolution path."""
        return cls(
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
            state_plane_x=state_plane_x,
            state_plane_y=state_plane_y,
            soda_level=soda_level,
            borocode=resolution.borocode,
            perpendicular_distance_ft=resolution.perpendicular_distance_ft,
            street_width_ft=resolution.street_width_ft,
            segment_id=resolution.segment_id,
        )

    @classmethod
    def from_error(
        cls,
        error: str,
        state_plane_x: float,
        state_plane_y: float,
    ) -> ASPDebugResult:
        """Build ASPDebugResult when AmbiguousResolutionError is caught."""
        return cls(
            schedule=None,
            resolution_failed=True,
            resolution_error=error,
            on_street=None,
            from_street=None,
            to_street=None,
            side_of_street=None,
            resolution=None,
            sign_result=None,
            confidence=0.0,
            state_plane_x=state_plane_x,
            state_plane_y=state_plane_y,
            soda_level=0,
            borocode=None,
            perpendicular_distance_ft=None,
            street_width_ft=None,
            segment_id=None,
        )
