# Architecture Research

**Domain:** GPS-to-ASP-regulation resolver for NYC alternate side parking
**Researched:** 2026-02-21
**Confidence:** HIGH

## Standard Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     HOME ASSISTANT LAYER                                 │
│                                                                          │
│  ┌────────────────┐    ┌────────────────────┐    ┌───────────────────┐   │
│  │  VW CarNet     │    │  GPS2ASP Resolver   │    │  HA Notifications │   │
│  │  device_tracker│───>│  (custom component) │───>│  & Automations    │   │
│  │  lat/lng       │    │                     │    │                   │   │
│  └────────────────┘    └─────────┬───────────┘    └───────────────────┘   │
│                                  │                                        │
├──────────────────────────────────┼────────────────────────────────────────┤
│                     RESOLVER CORE                                        │
│                                  │                                        │
│  ┌────────────────┐    ┌────────┴────────┐    ┌───────────────────────┐  │
│  │  Coordinate    │    │  Sign Matcher   │    │  Schedule Computer    │  │
│  │  Converter     │───>│  (street+side   │───>│  (parse sign text,    │  │
│  │  WGS84→SP     │    │   resolution)   │    │   compute next move)  │  │
│  └────────────────┘    └────────┬────────┘    └──────────┬────────────┘  │
│                                 │                        │               │
│                        ┌────────┴────────┐    ┌──────────┴────────────┐  │
│                        │  Sign Cache     │    │  Suspension Service   │  │
│                        │  (SQLite)       │    │  (holidays+weather)   │  │
│                        └────────┬────────┘    └──────────┬────────────┘  │
│                                 │                        │               │
├─────────────────────────────────┼────────────────────────┼───────────────┤
│                     EXTERNAL SERVICES                    │               │
│                                 │                        │               │
│  ┌──────────────────────────────┴────────────┐  ┌───────┴────────────┐  │
│  │  NYC Open Data SODA API                    │  │  NYC 311 API       │  │
│  │  dataset: nfid-uabd                        │  │  (nyc311calendar)  │  │
│  │  Parking Regulation Locations and Signs     │  │  ASP suspensions   │  │
│  └────────────────────────────────────────────┘  └────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| **Coordinate Converter** | Transforms WGS84 lat/lng from GPS to NY State Plane (EPSG:2263, NAD83, feet) for matching against sign coordinates | `pyproj.Transformer.from_crs(4326, 2263, always_xy=True)` singleton |
| **Sign Matcher** | Given converted coordinates, finds the correct street segment and side, then retrieves all ASP signs for that location | SODA API `$where` with bounding box on `sign_x_coord`/`sign_y_coord`, filtered by `side_of_street` |
| **Schedule Computer** | Parses sign description text into structured schedule, computes next ASP window from current datetime | Regex parser for `"TUESDAY FRIDAY 8:30AM-10AM"` format, datetime arithmetic |
| **Sign Cache** | Stores previously fetched sign data per street segment to avoid redundant API calls | SQLite database keyed by `(on_street, from_street, to_street, side_of_street)` |
| **Suspension Service** | Tracks holiday calendar and weather-based ASP suspensions, adjusts "next move" computation | `nyc311calendar` package wrapping NYC 311 API + periodic polling |
| **HA Integration Layer** | Exposes resolver as sensor entities within Home Assistant, handles polling and notifications | `DataUpdateCoordinator` pattern, sensor platform |

## Recommended Project Structure

```
gps2asp_resolver/
├── custom_components/
│   └── gps2asp/
│       ├── __init__.py            # Integration setup, config entry
│       ├── manifest.json          # HA integration manifest
│       ├── config_flow.py         # Configuration UI flow
│       ├── const.py               # Constants (EPSG codes, API URLs, etc.)
│       ├── coordinator.py         # DataUpdateCoordinator subclass
│       ├── sensor.py              # Sensor entity definitions
│       ├── strings.json           # Localization strings
│       └── translations/
│           └── en.json
├── gps2asp/                       # Core library (HA-independent)
│   ├── __init__.py
│   ├── converter.py               # WGS84 <-> NY State Plane conversion
│   ├── matcher.py                 # Street segment + side-of-street matching
│   ├── parser.py                  # Sign description text parser
│   ├── scheduler.py               # Next-move datetime computation
│   ├── cache.py                   # SQLite sign data cache
│   ├── soda_client.py             # NYC Open Data SODA API client
│   ├── suspension.py              # ASP suspension service
│   └── models.py                  # Data classes (Sign, Schedule, ASPWindow)
├── tests/
│   ├── test_converter.py
│   ├── test_matcher.py
│   ├── test_parser.py
│   ├── test_scheduler.py
│   ├── test_suspension.py
│   └── fixtures/                  # Sample API responses, sign descriptions
│       ├── sample_signs.json
│       └── sample_suspensions.json
├── pyproject.toml
└── README.md
```

### Structure Rationale

- **`gps2asp/` (core library):** Deliberately separated from `custom_components/` so the resolver logic can be tested, developed, and run independently of Home Assistant. This is the standard HA integration pattern -- keep business logic in a standalone library, keep HA wiring in the integration folder. The core library has zero HA dependencies.
- **`custom_components/gps2asp/`:** Thin HA integration wrapper that uses `DataUpdateCoordinator` to poll the resolver on a schedule and expose results as sensor entities. This is the part that registers with Home Assistant.
- **`tests/fixtures/`:** Critical for this project because sign description parsing is the riskiest component. Real API response samples enable regression testing without network calls.

## Architectural Patterns

### Pattern 1: Pipeline Architecture (Core Data Flow)

**What:** The resolver is a linear pipeline where each stage transforms data for the next. GPS coordinates enter, "next move time" exits. Each stage has a single clear responsibility.

**When to use:** Always -- this is the fundamental processing model.

**Trade-offs:** Simple to reason about and test. Each stage is independently testable. The linear flow means a failure at any stage halts the pipeline, but that is the correct behavior (you cannot compute move time without signs).

**Data flow:**

```
GPS (lat, lng)                     # Input from VW CarNet device_tracker
    │
    ▼
Coordinate Converter               # pyproj: WGS84 (EPSG:4326) → NY State Plane (EPSG:2263)
    │
    ├── (x_feet, y_feet)           # Coordinates now in same system as sign data
    │
    ▼
Sign Matcher                       # Find ASP signs for this location
    │
    ├── Cache HIT? ──────────────> Return cached signs
    │       │
    │       NO
    │       │
    │       ▼
    │   SODA API Query             # $where=sign_x_coord BETWEEN x-R AND x+R
    │       │                      #    AND sign_y_coord BETWEEN y-R AND y+R
    │       │                      #    AND sign_description LIKE '%BROOM%'
    │       ▼
    │   Street Segment Resolver    # Group by (on_street, from_street, to_street)
    │       │                      # Filter to side_of_street matching car position
    │       ▼
    │   Cache STORE                # SQLite: key=(segment+side), value=signs, ttl=7d
    │
    ├── [Sign, Sign, ...]          # Array of ASP signs for this curb segment
    │
    ▼
Schedule Parser                    # Regex extraction from sign_description
    │
    ├── ASPSchedule[]              # Structured: [{day: TUE, start: 08:30, end: 10:00}, ...]
    │
    ▼
Suspension Checker                 # Is ASP suspended today or next scheduled day?
    │
    ├── Holiday calendar           # NYC 311 API via nyc311calendar
    ├── Weather suspension          # Periodic polling for emergency suspensions
    │
    ▼
Next Move Computer                 # Given schedule + suspensions + current datetime
    │
    ├── next_move_at: datetime     # "2026-02-24T08:30:00-05:00"
    ├── next_window: str           # "Tuesday 8:30 AM - 10:00 AM"
    ├── is_suspended: bool         # Whether next window is currently suspended
    │
    ▼
Home Assistant Sensors             # Exposed to HA automations and notifications
```

### Pattern 2: Cache-Through with Street Segment Key

**What:** Sign data is cached in SQLite keyed by the street segment tuple `(on_street, from_street, to_street, side_of_street)`. On cache miss, the SODA API is queried and results stored. Cache has a 7-day TTL (ASP signs change rarely, perhaps yearly).

**When to use:** Every sign lookup. The cache is not optional -- it is the primary data store after first fetch.

**Trade-offs:** Eliminates repeated SODA API calls for the same parking spot (common when car parks on the same block regularly). SQLite is zero-dependency on Python 3.x. Downside: first lookup for a new location requires a network call that may take 1-3 seconds.

**Example:**

```python
import sqlite3
from datetime import datetime, timedelta

CACHE_TTL_DAYS = 7

class SignCache:
    def __init__(self, db_path: str = "sign_cache.db"):
        self.conn = sqlite3.connect(db_path)
        self._ensure_table()

    def _ensure_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS signs (
                segment_key TEXT PRIMARY KEY,
                signs_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            )
        """)

    def get(self, on_street: str, from_street: str,
            to_street: str, side: str) -> list | None:
        key = f"{on_street}|{from_street}|{to_street}|{side}"
        row = self.conn.execute(
            "SELECT signs_json, fetched_at FROM signs WHERE segment_key = ?",
            (key,)
        ).fetchone()
        if row is None:
            return None
        fetched = datetime.fromisoformat(row[1])
        if datetime.now() - fetched > timedelta(days=CACHE_TTL_DAYS):
            return None  # Expired
        return json.loads(row[0])

    def put(self, on_street, from_street, to_street, side, signs):
        key = f"{on_street}|{from_street}|{to_street}|{side}"
        self.conn.execute(
            "INSERT OR REPLACE INTO signs VALUES (?, ?, ?)",
            (key, json.dumps(signs), datetime.now().isoformat())
        )
        self.conn.commit()
```

### Pattern 3: DataUpdateCoordinator for HA Polling

**What:** Home Assistant's `DataUpdateCoordinator` handles periodic polling of the resolver. It ensures a single coordinated update across all entities (next-move sensor, suspension sensor, etc.) rather than each entity polling independently.

**When to use:** For the HA integration layer. The coordinator calls the core resolver pipeline on a configurable interval (e.g., every 30 minutes, or on GPS position change).

**Trade-offs:** Standard HA pattern, well-documented, handles error retry and throttling. The resolver itself is stateless -- the coordinator manages the polling lifecycle.

**Example:**

```python
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from datetime import timedelta

class GPS2ASPCoordinator(DataUpdateCoordinator):
    """Coordinator to poll the GPS2ASP resolver."""

    def __init__(self, hass, resolver, device_tracker_entity):
        super().__init__(
            hass,
            logger,
            name="GPS2ASP",
            update_interval=timedelta(minutes=30),
        )
        self.resolver = resolver
        self.device_tracker = device_tracker_entity

    async def _async_update_data(self):
        state = self.hass.states.get(self.device_tracker)
        lat = state.attributes.get("latitude")
        lng = state.attributes.get("longitude")

        # Run blocking resolver in executor (pyproj, sqlite are sync)
        return await self.hass.async_add_executor_job(
            self.resolver.resolve, lat, lng
        )
```

### Pattern 4: Side-of-Street Resolution via Dataset Fields

**What:** The parking signs dataset already includes `side_of_street` (N/S/E/W) and block segment (`on_street`, `from_street`, `to_street`). Rather than implementing geometric side-of-street detection from GPS, use the dataset's own street/side grouping. Query a bounding box around the GPS point, group results by segment, pick the nearest segment, then filter to the side whose sign coordinates are closest to the car's converted coordinates.

**When to use:** Always. This avoids the need for a separate street centerline dataset or complex map-matching algorithms.

**Trade-offs:** Leverages the structure already in the data (each sign knows its street, cross streets, and side). The 3-5m GPS accuracy confirmed by the user is sufficient to distinguish which cluster of signs (left side vs right side) the car is closest to. No need for the LION dataset or geometric perpendicular-to-centerline calculations.

**Algorithm:**

```
1. Convert GPS to State Plane (x_car, y_car)
2. Query SODA: signs within ~150ft radius bounding box, BROOM signs only
3. Group returned signs by (on_street, from_street, to_street, side_of_street)
4. For each group, compute centroid of sign coordinates
5. Pick group whose centroid is nearest to (x_car, y_car)
6. That group's signs are the ASP regulations for this parking spot
```

This works because:
- Signs on opposite sides of a street are typically 30-60 feet apart (street width)
- GPS accuracy of 3-5m (~10-16 feet) is well within the margin needed
- The bounding box query returns signs from adjacent segments too, but grouping + nearest-centroid filters to the correct one

## Data Flow

### Primary Resolution Flow

```
[VW CarNet device_tracker]
    │
    │  GPS update (lat, lng) from HA state
    │
    ▼
[DataUpdateCoordinator]
    │
    │  Triggers resolve() on interval or GPS change
    │
    ▼
[Coordinate Converter]
    │
    │  pyproj Transformer (singleton, created once)
    │  Input:  (40.6782, -73.9442)  WGS84
    │  Output: (993412, 187523)     NY State Plane feet
    │
    ▼
[Sign Matcher]
    │
    ├── Check SQLite cache for known segment
    │   Key: nearest (on_street, from_street, to_street, side)
    │
    ├── Cache MISS → SODA API call:
    │   GET data.cityofnewyork.us/resource/nfid-uabd.json
    │     ?$where=sign_x_coord BETWEEN 993262 AND 993562
    │       AND sign_y_coord BETWEEN 187373 AND 187673
    │       AND sign_description LIKE '%BROOM%'
    │     &$limit=50
    │
    ├── Group by segment tuple, pick nearest to car
    │   Store in cache with 7-day TTL
    │
    ▼
[Schedule Parser]
    │
    │  Input:  "NO PARKING (SANITATION BROOM SYMBOL) TUESDAY FRIDAY 8:30AM-10AM"
    │  Output: [Schedule(days=[TUE, FRI], start=08:30, end=10:00)]
    │
    │  Handles variations:
    │  - "MON THURS 8AM-9:30AM"
    │  - "TUESDAY & FRIDAY 11:30AM-1PM"
    │  - "EXCEPT SUNDAY"
    │  - Arrow directions (→ ← ↔)
    │
    ▼
[Suspension Service]
    │
    │  NYC 311 API via nyc311calendar:
    │  - Holiday suspensions (known calendar, ~34 days/year)
    │  - Weather/emergency suspensions (polled periodically)
    │
    │  Merges suspension data with schedule:
    │  If next ASP window is suspended → skip to following window
    │
    ▼
[Next Move Computer]
    │
    │  Given: current datetime, ASP schedule, active suspensions
    │  Produces:
    │    next_move_at:   2026-02-25T08:30:00-05:00
    │    window_desc:    "Tuesday 8:30 AM - 10:00 AM"
    │    hours_until:    36.5
    │    is_suspended:   false
    │    suspension_reason: null
    │
    ▼
[HA Sensor Entities]
    │
    ├── sensor.asp_next_move         # "2026-02-25 08:30 AM"
    ├── sensor.asp_hours_until_move  # 36.5
    ├── sensor.asp_schedule          # "Tue & Fri 8:30-10:00 AM"
    ├── binary_sensor.asp_suspended  # off
    └── sensor.asp_suspension_reason # ""
```

### Suspension Polling Flow

```
[Cron / HA time trigger]
    │
    │  Every 2 hours (or on-demand)
    │
    ▼
[Suspension Service]
    │
    ├── nyc311calendar.NYC311API.get_calendar(CalendarType.WEEK_AHEAD)
    │   Returns: {date: CalendarDayEntry(status, description)}
    │
    ├── Check for weather-based suspensions
    │   (311 API returns these as same-day entries)
    │
    ├── Store suspension state in memory
    │   (No persistence needed -- 311 API is the source of truth)
    │
    ▼
[DataUpdateCoordinator]
    │
    │  Triggers re-computation of next_move_at
    │  if suspension state changed
```

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| Single car, single location (target) | Exactly as designed. SQLite cache, 30-min polling, one street segment in cache. No optimization needed. |
| Multiple cars / locations | Add per-vehicle config entries. Cache naturally handles multiple segments. Coordinator per vehicle. Still SQLite. |
| Neighborhood-wide pre-cache | Bulk-fetch all BROOM signs for a borough via SODA API (paginated), populate SQLite at install time. Eliminates cold-start latency. |

### Scaling Priorities

1. **First bottleneck (not expected):** SODA API rate limits. The free tier has generous limits and this system makes at most a few calls per day. If needed, bulk-fetch and cache the entire borough.
2. **Second bottleneck (not expected):** Sign description parsing for unusual formats. The regex parser should handle 95%+ of cases, with a fallback logging mechanism for unparseable signs.

## Anti-Patterns

### Anti-Pattern 1: Geometric Side-of-Street Detection

**What people do:** Import LION street centerline data, compute perpendicular distance from GPS point to road segment, determine side based on bearing vector.

**Why it's wrong:** Massive over-engineering for this problem. The parking signs dataset already contains `side_of_street` per sign. GPS accuracy (3-5m) is sufficient to cluster signs by proximity. Adding LION data means another dataset to manage, another coordinate system to handle, and a complex geometric algorithm that adds little accuracy.

**Do this instead:** Group signs by `(on_street, from_street, to_street, side_of_street)`, compute centroid per group, pick nearest group to car position. The data tells you the side -- let it.

### Anti-Pattern 2: Using OpenCurb as Primary Data Source

**What people do:** Use the OpenCurb API because it accepts GPS coordinates directly and returns curb regulations.

**Why it's wrong:** OpenCurb returns regulation summaries (allowed/prohibited for a time window) but not the raw sign schedule text needed to compute "next time to move." It also officially covers only Manhattan (works in Brooklyn anecdotally but is unreliable). You would need to reverse-engineer the regulation output back into a schedule, which is fragile.

**Do this instead:** Use NYC Open Data SODA API as primary source. The `sign_description` field contains the parseable schedule. OpenCurb can serve as an optional validation/sanity-check layer, not a primary source.

### Anti-Pattern 3: Polling the Resolver Too Frequently

**What people do:** Set polling interval to every minute to catch GPS changes immediately.

**Why it's wrong:** The car does not move while parked. ASP schedules do not change intraday. Suspension status changes at most once per morning. Frequent polling wastes resources and hammers the 311 API for no benefit.

**Do this instead:** Poll every 30 minutes. Additionally, trigger an immediate re-resolve when the device_tracker entity's GPS coordinates change by more than 50 meters (indicating the car has actually moved). Use HA state change listener with a distance threshold.

### Anti-Pattern 4: Parsing Sign Text with LLM/NLP

**What people do:** Use an LLM or NLP library to "understand" the sign description text.

**Why it's wrong:** The sign descriptions follow a highly regular format from NYC DOT's database. There are a limited number of patterns. A well-crafted regex handles this deterministically, without network calls, latency, cost, or hallucination risk.

**Do this instead:** Build a regex-based parser with exhaustive test fixtures covering known sign description patterns. Log any unparseable descriptions for manual review and pattern expansion.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| **NYC Open Data SODA API** | REST GET with SoQL `$where` clause, JSON response. No auth required (app token optional for higher rate limits). | Endpoint: `data.cityofnewyork.us/resource/nfid-uabd.json`. No spatial queries on numeric coords -- use `BETWEEN` for bounding box. Rate limit: 1000 req/hour without token, higher with token. |
| **NYC 311 API** | Via `nyc311calendar` Python package. Requires free API key from `api-portal.nyc.gov`. | Returns structured suspension data. Package handles response normalization. Key supports both primary and secondary credentials. |
| **VW CarNet / WeConnect** | Via existing HA `device_tracker` entity. Read `latitude`/`longitude` from state attributes. | No direct integration needed -- just read HA entity state. GPS updates when HA polls the VW API. |
| **OpenCurb API (optional)** | REST GET to `opencurb.nyc/search.php` with GPS coords. No auth. | Validation/fallback only. Returns GeoJSON but not parseable schedules. Officially Manhattan only. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| HA Integration <-> Core Library | Direct Python function call (`resolver.resolve(lat, lng)`) | Core library is a plain Python package with no HA imports. HA wrapper calls it via `async_add_executor_job` since pyproj and sqlite3 are synchronous. |
| Core Library <-> SODA API | HTTP GET via `requests` or `aiohttp` | Simple REST calls. Core library owns the client. Responses are JSON arrays of sign dicts. |
| Core Library <-> SQLite Cache | `sqlite3` stdlib module | Cache is internal to the core library. No external database server. File stored alongside HA config or in a configurable path. |
| Suspension Service <-> 311 API | Via `nyc311calendar` async client | The suspension service wraps `nyc311calendar` and exposes a simple `is_suspended(date)` interface to the scheduler. |
| Coordinator <-> Sensor Entities | HA `CoordinatorEntity` base class | Sensors read from `coordinator.data` dict. Coordinator handles all update scheduling. Sensors are thin read-only views. |

## Build Order (Dependency Chain)

The components have clear dependencies that dictate implementation order:

```
Phase 1: Foundation (no external dependencies between these)
├── Coordinate Converter (pyproj, standalone)
├── SODA API Client (requests, standalone)
├── Sign Description Parser (regex, standalone)
└── Data Models (dataclasses, standalone)

Phase 2: Integration (depends on Phase 1)
├── Sign Matcher (uses: Converter + SODA Client + Models)
├── SQLite Cache (uses: Models)
└── Suspension Service (uses: nyc311calendar)

Phase 3: Orchestration (depends on Phase 2)
└── Resolver Pipeline (uses: Matcher + Cache + Parser + Suspension)

Phase 4: HA Integration (depends on Phase 3)
├── DataUpdateCoordinator (uses: Resolver Pipeline)
├── Sensor Entities (uses: Coordinator)
└── Config Flow (HA setup UI)
```

**Key insight:** Phase 1 components are all independently testable with no cross-dependencies. This means they can be built and validated in parallel. Phase 2 composes them. Phase 3 orchestrates the full pipeline. Phase 4 wraps it for Home Assistant.

## Sources

- [NYC Open Data - Parking Regulation Locations and Signs](https://data.cityofnewyork.us/Transportation/Parking-Regulation-Locations-and-Signs/nfid-uabd) -- PRIMARY data source, verified via live API query
- [EPSG:2263 - NAD83 / New York Long Island (ftUS)](https://epsg.io/2263) -- Coordinate system for NYC sign data
- [pyproj Getting Started](https://pyproj4.github.io/pyproj/stable/examples.html) -- Transformer.from_crs() usage and best practices
- [Socrata within_circle() docs](https://dev.socrata.com/docs/functions/within_circle.html) -- Confirmed NOT usable for numeric coord columns
- [Socrata BETWEEN function](https://dev.socrata.com/docs/functions/between.html) -- Correct approach for bounding box on numeric columns
- [OpenCurb API Documentation](https://www.opencurb.nyc/doc.html) -- API structure, response format, Manhattan-only limitation
- [ha-nyc311 GitHub](https://github.com/elahd/ha-nyc311) -- Reference HA integration for NYC 311 suspension data
- [nyc311calendar on PyPI](https://pypi.org/project/nyc311calendar/) -- Python package for ASP suspension data
- [HA Developer Docs - Fetching Data](https://developers.home-assistant.io/docs/integration_fetching_data/) -- DataUpdateCoordinator pattern
- [HA Developer Docs - Integration Architecture](https://developers.home-assistant.io/docs/architecture_components/) -- Component/platform structure
- [NYC LION Street Centerline](https://www.nyc.gov/content/planning/pages/resources/datasets/lion) -- Evaluated and rejected for side-of-street (anti-pattern)
- [NYC DOT ASP Suspension Calendar](https://www.nyc.gov/html/dot/html/motorist/alternate-side-parking.shtml) -- Official suspension information

---
*Architecture research for: GPS2ASP Resolver -- NYC Alternate Side Parking*
*Researched: 2026-02-21*
