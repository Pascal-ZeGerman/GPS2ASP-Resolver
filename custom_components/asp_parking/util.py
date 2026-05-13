"""Shared utilities for the ASP Parking integration.

Pure-function helpers wrapping Home Assistant primitives. No state, no
class — every function is safe to import from any other module in this
integration without circular-import risk.
"""

from __future__ import annotations

from datetime import datetime

from homeassistant.util import dt as dt_util


def now_ha_local() -> datetime:
    """Return the current datetime in Home Assistant's configured local timezone.

    Thin wrapper over ``homeassistant.util.dt.now()`` so callers do not need
    to import ``dt_util`` directly. Used by Phase 32 (sensor display format)
    and Phase 34 (CalDAV calendar integration).
    """
    return dt_util.now()
