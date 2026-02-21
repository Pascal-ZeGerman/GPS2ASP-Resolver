"""GPS2ASP: GPS-to-street resolver for NYC Alternate Side Parking."""

__version__ = "0.1.0"

from gps2asp.resolver import resolve, convert, resolve_segment
from gps2asp.resolver.models import ResolutionResult
from gps2asp.resolver.exceptions import (
    ResolutionError,
    OutsideNYCError,
    NoSegmentFoundError,
    AmbiguousResolutionError,
)

__all__ = [
    "resolve",
    "convert",
    "resolve_segment",
    "ResolutionResult",
    "ResolutionError",
    "OutsideNYCError",
    "NoSegmentFoundError",
    "AmbiguousResolutionError",
]
