"""Constants for the ASP Parking integration."""

from __future__ import annotations

DOMAIN = "asp_parking"

PLATFORMS = ["sensor", "binary_sensor"]

# Config entry data keys
CONF_DEVICE_TRACKER = "device_tracker"

# Config entry options keys (reconfigurable via options flow)
CONF_MOVEMENT_THRESHOLD = "movement_threshold"
CONF_REFRESH_INTERVAL = "refresh_interval"
CONF_STALE_TIMEOUT = "stale_timeout"

# Default values
DEFAULT_MOVEMENT_THRESHOLD = 50.0  # meters before re-resolve
DEFAULT_REFRESH_INTERVAL = 8  # hours between periodic refreshes
DEFAULT_STALE_TIMEOUT = 8  # hours before marking sensor unavailable

# Internal tuning
GPS_DEBOUNCE_COOLDOWN = 5.0  # seconds (debounce rapid GPS jitter)
