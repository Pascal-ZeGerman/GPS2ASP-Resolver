"""GPS2ASP: GPS-to-street resolver for NYC Alternate Side Parking."""

from __future__ import annotations

__version__ = "0.1.0"

from gps2asp.pipeline import resolve_asp
from gps2asp.api_models import ASPResult, ASPDebugResult
from gps2asp.resolver.exceptions import (
    ResolutionError,
    OutsideNYCError,
    NoSegmentFoundError,
    AmbiguousResolutionError,
    IndexNotFoundError,
)
from gps2asp.signs.exceptions import SODAAPIError, IncompleteResultsError

__all__ = [
    "resolve_asp",
    "ASPResult",
    "ASPDebugResult",
    "ResolutionError",
    "OutsideNYCError",
    "NoSegmentFoundError",
    "AmbiguousResolutionError",
    "IndexNotFoundError",
    "SODAAPIError",
    "IncompleteResultsError",
]
