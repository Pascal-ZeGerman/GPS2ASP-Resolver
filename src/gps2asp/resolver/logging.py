"""JSON debug logging for GPS-to-street resolution.

Logs every resolution attempt as structured JSON at DEBUG level, enabling
users to review coordinates, distances, confidence scores, and outcomes
to tune the confidence threshold.

The logger uses the standard Python logging module with the named logger
'gps2asp.resolver'. By default, it logs at WARNING level. Call
configure_logging("DEBUG") to see resolution attempt details.

Usage:
    from gps2asp.resolver.logging import configure_logging
    configure_logging("DEBUG")
    # Now all resolution attempts will be logged as JSON
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gps2asp.resolver.models import ResolutionDebugInfo

# Named logger for the resolver module
logger = logging.getLogger("gps2asp.resolver")


def log_resolution(debug_info: ResolutionDebugInfo) -> None:
    """Log a resolution attempt as structured JSON at DEBUG level.

    Captures the full resolution pipeline state including input coordinates,
    State Plane conversion, candidate segments, selected segment, distances,
    confidence score, determined side, and outcome.

    This is logged regardless of whether the resolution succeeded or failed,
    providing a complete audit trail for threshold calibration.

    Args:
        debug_info: The ResolutionDebugInfo dataclass with all resolution state.
    """
    info_dict = asdict(debug_info)
    logger.debug(
        "resolution_attempt: %s",
        json.dumps(info_dict, default=str, separators=(",", ":")),
    )


def configure_logging(level: str = "WARNING") -> None:
    """Configure the gps2asp.resolver logger level.

    Convenience function for users to enable debug logging for
    resolution attempts. Set to "DEBUG" to see JSON logs of every
    resolution attempt.

    Args:
        level: Logging level string (e.g., "DEBUG", "INFO", "WARNING").
    """
    logger.setLevel(getattr(logging, level.upper(), logging.WARNING))

    # Add a handler if none exists (prevents "No handlers" warning)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
        )
        logger.addHandler(handler)
