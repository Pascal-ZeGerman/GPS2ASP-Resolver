"""Constants for the ASP Parking integration."""

from __future__ import annotations

DOMAIN = "asp_parking"
VERSION = "3.1.0"

PLATFORMS = ["sensor", "binary_sensor", "switch", "button"]

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
# NOTE: CONF_DEBUG_ENABLED and DEFAULT_DEBUG_ENABLED have been removed (Phase 29,
# IN-01). The coordinator unconditionally resets _debug_enabled = False on
# async_start (D-02); the switch entity is the sole runtime setter.
CONF_DEBUG_LAT = "debug_lat"
DEFAULT_DEBUG_LAT = None
CONF_DEBUG_LON = "debug_lon"
DEFAULT_DEBUG_LON = None
CONF_DEBUG_DATETIME = "debug_datetime"
DEFAULT_DEBUG_DATETIME = None
CONF_SUPPRESS_NOTIFICATIONS = "suppress_notifications"
DEFAULT_SUPPRESS_NOTIFICATIONS = False

# Parking area (Phase 26) — D-05/D-06/D-07: lat/lon-only, all optional
CONF_PARKING_LAT = "parking_lat"
DEFAULT_PARKING_LAT = None
CONF_PARKING_LON = "parking_lon"
DEFAULT_PARKING_LON = None
CONF_PARKING_RADIUS = "parking_radius"
DEFAULT_PARKING_RADIUS = 500  # metres; D-06

# Notifications (Phase 24)
CONF_NOTIFY_SERVICE = "notify_service"
DEFAULT_NOTIFY_SERVICE = ""
CONF_NOTIFY_LEAD_TIME = "notify_lead_time"
DEFAULT_NOTIFY_LEAD_TIME = 120  # minutes; matches former hardcoded 2-hour threshold

# Spatial index download (first-time HA setup)
INDEX_DOWNLOAD_URL = (
    "https://github.com/Pascal-ZeGerman/GPS2ASP-Resolver"
    "/releases/download/index-v1/index.zip"
)

# Phase 38: dual-path rebuild + stale detection
# IDX-06 / Plan 38-01: from-source CSCL rebuild constants
#
# GITHUB_INDEX_RELEASE_TAG = "index-v1" — deviation acknowledgement: ROADMAP/SPEC
# reference the "latest release" GitHub endpoint, but a research probe confirmed
# that endpoint returns v3.0.0 with ZERO assets while `index.zip` lives on tag
# `index-v1`.  Plan 02 consumes this tag via
# `GET /repos/.../releases/tags/{GITHUB_INDEX_RELEASE_TAG}`.
GITHUB_RELEASES_API_BASE = (
    "https://api.github.com/repos/Pascal-ZeGerman/GPS2ASP-Resolver"
)
GITHUB_INDEX_RELEASE_TAG = "index-v1"
CSCL_GEOJSON_URL = "https://data.cityofnewyork.us/resource/inkn-q76z.geojson"
SODA_PARKING_SIGNS_URL = "https://data.cityofnewyork.us/resource/nfid-uabd.json"

# Stale detection thresholds (Plans 02/03)
STALE_INDEX_DAYS = 60
REMOTE_FRESH_DAYS = 30
BUTTON_DOUBLE_PRESS_WINDOW_HOURS = 24
STALE_CHECK_INTERVAL_HOURS = 24

# CSCL pagination / DoS guard
MAX_CSCL_PAGES = 30
CSCL_BATCH_SIZE = 10000
SIGNS_BATCH_SIZE = 50000

# Vehicular street filter (CSCL RW_TYPE codes)
VEHICULAR_RW_TYPES = frozenset({1, 2, 3, 4, 5})

# CalDAV calendar sync (Phase 34) — CALDAV-01..08
CONF_CALDAV_URL = "caldav_url"
DEFAULT_CALDAV_URL = None
CONF_CALDAV_USERNAME = "caldav_username"
DEFAULT_CALDAV_USERNAME = ""
CONF_CALDAV_PASSWORD = "caldav_password"
DEFAULT_CALDAV_PASSWORD = ""
CONF_CALDAV_CALENDAR = "caldav_calendar"
DEFAULT_CALDAV_CALENDAR = ""
CONF_CALDAV_SAFETY_WINDOW = "caldav_safety_window"
DEFAULT_CALDAV_SAFETY_WINDOW = 15  # minutes; D-04 / CALDAV-03
CONF_CALDAV_EVENT_TITLE_TEMPLATE = "caldav_event_title_template"
DEFAULT_CALDAV_EVENT_TITLE_TEMPLATE = "ASP: {street}"  # D-04
