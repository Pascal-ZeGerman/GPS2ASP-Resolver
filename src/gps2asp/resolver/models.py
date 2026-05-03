"""Data models for GPS-to-street resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from shapely.geometry import LineString


@dataclass(frozen=True)
class ResolutionResult:
    """Result of resolving a GPS coordinate to a street segment and side.

    Attributes:
        on_street: The street the car is parked on (e.g., "PROSPECT PLACE").
        from_street: The cross street at one end of the block (e.g., "VANDERBILT AVENUE").
        to_street: The cross street at the other end of the block (e.g., "CARLTON AVENUE").
        side_of_street: Compass direction side - N, S, E, or W.
        confidence: Confidence score from 0.0 (ambiguous) to 1.0 (certain).
        has_asp: Whether this segment has any ASP regulations.
        borocode: CSCL borough code as string ("1"=Manhattan, "2"=Bronx, "3"=Brooklyn,
            "4"=Queens, "5"=Staten Island), or None when resolution failed.
        perpendicular_distance_ft: Perpendicular distance from the GPS point to the
            segment centerline (feet), rounded to 2 decimals. None when not computed.
        street_width_ft: Effective street width used in confidence calculation
            (feet, post-fallback from _NYC_DEFAULT_WIDTHS). None when not computed.
        segment_id: CSCL physical segment ID for the matched street segment.
            None when no segment was matched.
    """

    on_street: str
    from_street: str
    to_street: str
    side_of_street: Literal["N", "S", "E", "W"]
    confidence: float
    has_asp: bool
    borocode: str | None = None
    perpendicular_distance_ft: float | None = None
    street_width_ft: float | None = None
    segment_id: int | None = None


@dataclass(frozen=True)
class SegmentCandidate:
    """A candidate street segment returned from the spatial index.

    Attributes:
        segment_id: Unique physical ID of the street segment.
        geometry: Shapely LineString of the segment centerline in State Plane feet.
        full_street_name: Full street name (e.g., "PROSPECT PLACE").
        from_street: Cross street at the from-node end of the segment.
        to_street: Cross street at the to-node end of the segment.
        trafdir: Traffic direction (FT=with digitized, TF=against, TW=two-way, NV=non-vehicular).
        nominaldir: Nominal compass direction of the segment.
        rw_type: Road type (1=Street, 2=Highway, etc.).
        streetwidth: Paved width in feet.
        borocode: Borough code (1=Manhattan, 2=Bronx, 3=Brooklyn, 4=Queens, 5=Staten Island).
        distance_ft: Distance from the query point to the segment centerline in feet.
    """

    segment_id: int
    geometry: LineString
    full_street_name: str
    from_street: str
    to_street: str
    trafdir: str
    nominaldir: str
    rw_type: int
    streetwidth: float
    borocode: str
    has_asp_left: bool
    has_asp_right: bool
    distance_ft: float


@dataclass(frozen=True)
class ResolutionDebugInfo:
    """Debug information for a resolution attempt, used for logging and diagnostics.

    Every resolution attempt (successful or not) produces one of these for
    JSON debug logging, enabling users to review and tune confidence thresholds.

    Attributes:
        input_lat: Original WGS84 latitude input.
        input_lon: Original WGS84 longitude input.
        state_plane_x: Converted State Plane X coordinate (feet).
        state_plane_y: Converted State Plane Y coordinate (feet).
        candidates: List of candidate segment summaries (id, name, distance).
        selected_segment_id: ID of the segment chosen, or None if resolution failed.
        perpendicular_distance_ft: Perpendicular distance to the selected segment, or None.
        confidence: Computed confidence score.
        side: Determined side of street (N/S/E/W), or None if ambiguous.
        outcome: Resolution outcome string.
        street_width_ft: Effective street width used in confidence calculation (post-fallback
            from _NYC_DEFAULT_WIDTHS if CSCL data was missing). None if not yet computed.
    """

    input_lat: float
    input_lon: float
    state_plane_x: float
    state_plane_y: float
    candidates: list[dict] = field(default_factory=list)
    selected_segment_id: int | None = None
    perpendicular_distance_ft: float | None = None
    confidence: float = 0.0
    side: str | None = None
    outcome: str = "no_segment"
    street_width_ft: float | None = None    # effective width used in confidence calc (post-fallback)
