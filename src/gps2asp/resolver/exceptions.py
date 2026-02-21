"""Custom exceptions for GPS-to-street resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gps2asp.resolver.models import ResolutionDebugInfo


class ResolutionError(Exception):
    """Base exception for all resolution errors."""

    pass


class OutsideNYCError(ResolutionError):
    """Coordinates are outside the NYC bounding box.

    Raised when the input latitude/longitude falls outside the approximate
    bounds of New York City (lat 40.49-40.92, lon -74.27 to -73.68).
    """

    def __init__(self, lat: float, lon: float) -> None:
        self.lat = lat
        self.lon = lon
        super().__init__(
            f"Coordinates ({lat}, {lon}) are outside NYC bounding box "
            f"(lat 40.49-40.92, lon -74.27 to -73.68)"
        )


class NoSegmentFoundError(ResolutionError):
    """No street segment found within the snap distance (~164 ft / 50m).

    Raised when the spatial index query returns no candidates within
    the maximum distance threshold, indicating the point is likely
    in a park, on a highway, or over water.
    """

    def __init__(self, x: float, y: float, max_distance_ft: float) -> None:
        self.x = x
        self.y = y
        self.max_distance_ft = max_distance_ft
        super().__init__(
            f"No street segment found within {max_distance_ft:.0f} ft "
            f"of State Plane point ({x:.1f}, {y:.1f})"
        )


class AmbiguousResolutionError(ResolutionError):
    """Resolution confidence is below the threshold.

    Raised when the GPS point is too close to the street centerline
    (near the travel lane) or too close to an intersection, making
    side-of-street determination unreliable.

    Attributes:
        debug_info: Full resolution debug information for diagnostics.
        confidence: The computed confidence score (below threshold).
    """

    def __init__(
        self,
        message: str,
        debug_info: ResolutionDebugInfo,
        confidence: float,
    ) -> None:
        self.debug_info = debug_info
        self.confidence = confidence
        super().__init__(message)


class IndexNotFoundError(ResolutionError):
    """Pre-built spatial index files not found on disk.

    Raised when the R-tree index (.idx/.dat) or segment metadata files
    cannot be found in the expected data directory. The index must be
    built first using the build script.
    """

    def __init__(self, index_dir: str) -> None:
        self.index_dir = index_dir
        super().__init__(
            f"Spatial index files not found in '{index_dir}'. "
            f"Run the build script to create the index first."
        )
