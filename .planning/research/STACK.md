# Stack Research

**Domain:** GPS-to-ASP parking regulation resolver with Home Assistant integration
**Researched:** 2026-02-21
**Confidence:** HIGH

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | >=3.12 | Runtime language | HA native language; pyproj 3.7.2 requires >=3.11; 3.12 is the stable sweet spot with good performance and typing support |
| pyproj | 3.7.2 | WGS84 (EPSG:4326) to NY State Plane Long Island (EPSG:2263) coordinate conversion | The only serious Python library for CRS transformations. Wraps PROJ C library, handles all EPSG codes natively. `Transformer.from_crs(4326, 2263, always_xy=True)` is a one-liner for our exact conversion need |
| aiohttp | 3.13.2 | Async HTTP client for SODA API and NYC 311 API calls | Home Assistant's built-in HTTP client. HA provides `async_get_clientsession(hass)` helper that returns a managed aiohttp ClientSession -- custom integrations MUST use this rather than bringing their own HTTP library |
| python-dateutil | 2.9.0.post0 | Schedule computation: parsing times, computing next occurrence of recurring weekly windows | `rrule` module handles recurring weekly schedules natively (FREQ=WEEKLY, BYDAY). `parser.parse()` handles time strings like "8:30AM". Standard library `datetime` alone cannot express "every Tuesday and Friday 8:30AM-10AM" |
| SQLite | stdlib (sqlite3) | Local cache for ASP sign data per block segment | Zero-dependency (Python stdlib), file-based, perfect for "cache that survives restarts with weekly refresh." No need for Redis/external DB for a single-user tool |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| nyc311calendar | latest | ASP suspension calendar via NYC 311 API | Handles holiday suspensions and weather emergency suspensions. Already powers ha-nyc311 integration. Async-native (`await calendar.get_calendar()`). Requires free NYC API Portal key |
| diskcache | 5.6.3 | Higher-level caching with TTL expiration | ALTERNATIVE to raw SQLite if you want automatic expiration (set TTL to 7 days for weekly refresh). Use if manual SQLite cache management becomes tedious. Pure Python, Django-compatible API |
| zoneinfo | stdlib | NYC timezone handling (America/New_York) | Always use for "next move time" calculations. Handles EST/EDT transitions automatically. Stdlib since Python 3.9, no external dependency needed |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| pytest | Testing | Standard Python test framework. Use `pytest-asyncio` for testing async HA integration code |
| pytest-aiohttp | Testing aiohttp sessions | Test async HTTP calls without hitting real APIs |
| ruff | Linting + formatting | Modern replacement for flake8+black+isort. Single tool, fast, config in pyproject.toml |
| mypy | Type checking | pyproj and aiohttp have good type stubs. Catches coordinate mix-ups (lat/lon order bugs) at type-check time |
| pre-commit | Git hooks | Run ruff and mypy before commits. Standard HA development practice |

### Home Assistant Integration Layer

| Component | Purpose | Notes |
|-----------|---------|-------|
| `custom_components/{domain}/` | Integration directory | Standard HA custom component structure: `__init__.py`, `manifest.json`, `sensor.py`, `const.py` |
| `manifest.json` | Integration metadata | Must include `version` key for custom integrations. Declare `requirements: ["pyproj==3.7.2"]` so HA auto-installs |
| `async_setup_entry()` | Integration setup | Async entry point. Use config flow for NYC API key input |
| `SensorEntity` | Expose "next move time" | Create sensor entity with `device_class: timestamp` for "next ASP window" datetime |
| `CalendarEntity` | ASP schedule calendar | Show upcoming ASP windows on HA calendar. Uses `CalendarEvent` dataclass |

## Coordinate System Details

This is the most technically critical piece of the stack. Getting it wrong means querying the wrong block.

| Parameter | Value | Notes |
|-----------|-------|-------|
| Input CRS | EPSG:4326 (WGS84) | GPS coordinates from VW CarNet device_tracker. Latitude/longitude in degrees |
| Output CRS | EPSG:2263 (NAD83 / NY Long Island, ftUS) | NYC Open Data `sign_x_coord`/`sign_y_coord` columns. Units are US survey feet |
| Conversion | `Transformer.from_crs(4326, 2263, always_xy=True)` | `always_xy=True` is critical -- ensures lon,lat input order (not lat,lon). Without it, pyproj uses CRS-native axis order which differs between 4326 and 2263 |
| Accuracy | GPS ~3-5m = ~10-16 ft in State Plane | Sufficient to determine which side of a ~60ft wide NYC street the car is on |

```python
# Core conversion pattern
from pyproj import Transformer
from functools import lru_cache

@lru_cache(maxsize=1)
def get_transformer():
    return Transformer.from_crs(4326, 2263, always_xy=True)

def wgs84_to_state_plane(lon: float, lat: float) -> tuple[float, float]:
    """Convert GPS coordinates to NY State Plane (feet)."""
    transformer = get_transformer()
    x, y = transformer.transform(lon, lat)
    return x, y
```

## NYC Data API Details

### SODA API (Parking Signs)

| Parameter | Value |
|-----------|-------|
| Endpoint | `https://data.cityofnewyork.us/resource/nfid-uabd.json` |
| Auth | App token recommended (avoids throttling) but not required |
| Rate limit | 1000 req/hour with app token; throttled without |
| Query language | SoQL (Socrata Query Language), similar to SQL |
| Key filter | `$where=sign_description like '%SANITATION BROOM SYMBOL%'` |
| Pagination | `$limit` and `$offset` parameters |
| Response format | JSON (default) or CSV |

**Do NOT use sodapy.** It is unmaintained since August 2022, supports only Python <=3.10, and the SODA API is simple enough to query directly with aiohttp. A SoQL query is just URL parameters on a GET request.

```python
# Direct SODA API call pattern (no sodapy needed)
async def query_asp_signs(session: aiohttp.ClientSession, x: float, y: float, radius: float = 200):
    url = "https://data.cityofnewyork.us/resource/nfid-uabd.json"
    params = {
        "$where": f"sign_description like '%SANITATION BROOM SYMBOL%' AND within_circle(the_geom, {lat}, {lon}, {radius})",
        "$limit": 50,
    }
    async with session.get(url, params=params) as resp:
        return await resp.json()
```

### NYC 311 API (Suspensions)

| Parameter | Value |
|-----------|-------|
| Access | Free NYC API Portal developer account required |
| Signup | https://api-portal.nyc.gov/signup/ |
| Product | "NYC 311 Public Developers" subscription |
| Python client | `nyc311calendar` package (async, aiohttp-based) |
| Coverage | Holiday suspensions + weather emergency suspensions |
| Update frequency | 90-day rolling calendar, refreshed on API call |

## Installation

```bash
# Core dependencies
pip install pyproj==3.7.2 aiohttp>=3.13.0 python-dateutil>=2.9.0

# NYC 311 calendar (ASP suspensions)
pip install nyc311calendar

# Optional: higher-level caching
pip install diskcache>=5.6.3

# Dev dependencies
pip install pytest pytest-asyncio pytest-aiohttp ruff mypy pre-commit
```

For Home Assistant custom integration, dependencies go in `manifest.json`:
```json
{
  "domain": "gps2asp",
  "name": "GPS to ASP Resolver",
  "version": "0.1.0",
  "requirements": ["pyproj==3.7.2", "nyc311calendar"],
  "dependencies": [],
  "codeowners": [],
  "iot_class": "cloud_polling"
}
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| Direct aiohttp SODA calls | sodapy | Never. sodapy is unmaintained (2022), Python <=3.10 only, and SODA API is trivial to call directly |
| aiohttp | httpx | Only if NOT integrating with HA. httpx is excellent standalone but HA's ecosystem is built on aiohttp. Using httpx in an HA integration means managing a separate session lifecycle |
| aiohttp | requests | Never for HA integration. requests is sync-only and will block the HA event loop. Only acceptable for a standalone CLI tool |
| SQLite (stdlib) | diskcache | If you want automatic TTL-based expiration without writing cache invalidation logic yourself. diskcache uses SQLite under the hood anyway |
| SQLite (stdlib) | JSON file cache | For prototyping/MVP only. No query capability, no concurrent access safety, no expiration. Graduate to SQLite before shipping |
| Custom integration | AppDaemon | If you want to avoid the HA integration boilerplate and just need a standalone Python daemon that talks to HA via websocket. Trades HA-native entities for simpler development. Worse UX (no config flow, no auto-discovery) |
| Custom integration | pyscript | For lightweight automations only. Cannot install pip packages (no pyproj), limited stdlib access. Not viable for this project |
| nyc311calendar | Manual calendar scraping | Never. nyc311calendar already handles the API auth, date normalization, and status standardization. Don't re-invent |
| pyproj | Manual math | Never. State Plane projections involve complex geodetic calculations. pyproj wraps the authoritative PROJ library used by every GIS tool on earth |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| sodapy | Unmaintained since 2022, Python <=3.10, archived on GitHub | Direct aiohttp calls to SODA REST API |
| requests | Synchronous only, blocks HA event loop, no async support | aiohttp (HA-native) |
| GeoPandas | Massive dependency (numpy, pandas, shapely, fiona) for what amounts to one coordinate transform and a nearest-neighbor lookup | pyproj directly + manual distance calculation |
| PostGIS/PostgreSQL | Overkill for a single-user tool caching ~100 sign records per block | SQLite stdlib |
| OpenCurb API as primary | Does not expose parseable ASP schedules (days/times). Good for validation but cannot compute "next move time" | NYC Open Data SODA API (nfid-uabd) as primary, OpenCurb as optional validation |
| python_script (HA) | Cannot import pip packages, heavily sandboxed, no file I/O | Custom integration in custom_components/ |

## Stack Patterns by Variant

**If standalone CLI tool (no HA):**
- Use `httpx` instead of `aiohttp` (better standalone DX, sync+async)
- Use `click` for CLI argument parsing
- Use `rich` for formatted terminal output
- Skip manifest.json, config flow, entity classes

**If Home Assistant custom integration (recommended):**
- Use `aiohttp` via `async_get_clientsession(hass)`
- Use `SensorEntity` with `device_class: timestamp` for next-move-time
- Use config flow for NYC API key input
- Store cache in `hass.config.path("custom_components/gps2asp/cache.db")`
- Use `async_track_time_interval` for periodic suspension checks

**If Home Assistant + HACS distribution:**
- Add `hacs.json` with `render_readme: true`
- Add GitHub Actions for HACS validation
- Follow HACS repository structure requirements
- Adds distribution channel but no architectural changes

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| pyproj 3.7.2 | Python >=3.11 | Drops Python 3.9/3.10 support. Uses PROJ 9.x C library |
| aiohttp 3.13.x | Python >=3.9 | But HA 2025.x targets Python 3.12+, so use 3.12+ |
| python-dateutil 2.9.x | Python >=3.8 | Widely compatible, no conflicts expected |
| nyc311calendar | Python >=3.9 | Alpha release, API may change. Pin to specific version |
| diskcache 5.6.x | Python >=3 | Pure Python, no compatibility issues |
| Home Assistant 2025.7+ | Python 3.12+ | Latest HA versions require 3.12. Aligns with pyproj requirement |

**Minimum viable Python version: 3.12** -- driven by both pyproj >=3.7 and Home Assistant 2025.x requirements.

## Sources

- [pyproj 3.7.2 documentation](https://pyproj4.github.io/pyproj/stable/) -- Transformer API, EPSG support, version info (HIGH confidence)
- [pyproj on PyPI](https://pypi.org/project/pyproj/) -- Version 3.7.2, released Aug 2025, Python >=3.11 (HIGH confidence)
- [sodapy on PyPI](https://pypi.org/project/sodapy/) -- Version 2.2.0, unmaintained since Aug 2022, Python <=3.10 (HIGH confidence)
- [EPSG:2263 - NAD83 / New York Long Island (ftUS)](https://epsg.io/2263) -- NYC's coordinate reference system (HIGH confidence)
- [NYC Open Data - Parking Regulation Locations and Signs](https://data.cityofnewyork.us/Transportation/Parking-Regulation-Locations-and-Signs/nfid-uabd) -- Dataset nfid-uabd, SODA API endpoint (HIGH confidence)
- [HA Developer Docs - Creating Integrations](https://developers.home-assistant.io/docs/creating_component_index/) -- manifest.json, async_setup, custom_components structure (HIGH confidence)
- [HA Developer Docs - aiohttp session helper](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/inject-websession/) -- async_get_clientsession pattern (HIGH confidence)
- [ha-nyc311 on GitHub](https://github.com/elahd/ha-nyc311) -- Reference implementation for NYC 311 API + HA integration pattern (MEDIUM confidence -- last release Feb 2023)
- [nyc311calendar on PyPI](https://pypi.org/project/nyc311calendar/) -- Alpha, async NYC 311 calendar client (MEDIUM confidence -- alpha status)
- [aiohttp on PyPI](https://pypi.org/project/aiohttp/) -- Version 3.13.2, released Jan 2026 (HIGH confidence)
- [python-dateutil on PyPI](https://pypi.org/project/python-dateutil/) -- Version 2.9.0.post0 (HIGH confidence)
- [diskcache on PyPI](https://pypi.org/project/diskcache/) -- Version 5.6.3 (HIGH confidence)
- [httpx on PyPI](https://pypi.org/project/httpx/) -- Version 0.28.1, Dec 2024. Good but not for HA integrations (HIGH confidence)
- [NYC DOT ASP Suspension Calendar 2026](https://www.nyc.gov/html/dot/downloads/pdf/asp-calendar-2026.pdf) -- Official holiday calendar (HIGH confidence)
- [NYC API Portal](https://api-portal.nyc.gov/signup/) -- Free developer account for 311 API access (HIGH confidence)

---
*Stack research for: GPS2ASP Resolver -- GPS to NYC Alternate Side Parking regulation resolver*
*Researched: 2026-02-21*
