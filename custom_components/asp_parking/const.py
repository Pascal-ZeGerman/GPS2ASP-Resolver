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

# Suspension
CONF_NYC311_API_KEY = "nyc311_api_key"
DEFAULT_SUSPENSION_INTERVAL = 60  # minutes between suspension polls
CONF_NYC311_ENTITY = "nyc311_entity"
DEFAULT_NYC311_ENTITY = ""
DEFAULT_NYC311_BRIDGE_ENTITY = "binary_sensor.nyc311_parking_exception_today"

# Debug overrides (Phase 24)
CONF_DEBUG_ENABLED = "debug_enabled"
DEFAULT_DEBUG_ENABLED = False
CONF_DEBUG_LAT = "debug_lat"
DEFAULT_DEBUG_LAT = None
CONF_DEBUG_LON = "debug_lon"
DEFAULT_DEBUG_LON = None
CONF_DEBUG_DATETIME = "debug_datetime"
DEFAULT_DEBUG_DATETIME = None
CONF_SUPPRESS_NOTIFICATIONS = "suppress_notifications"
DEFAULT_SUPPRESS_NOTIFICATIONS = False

# Notifications (Phase 24)
CONF_NOTIFY_SERVICE = "notify_service"
DEFAULT_NOTIFY_SERVICE = ""

# Spatial index download (first-time HA setup)
INDEX_DOWNLOAD_URL = (
    "https://github.com/Pascal-ZeGerman/GPS2ASP-Resolver"
    "/releases/latest/download/index.zip"
)
