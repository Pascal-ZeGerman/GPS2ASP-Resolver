# Technology Stack

**Project:** GPS2ASP Resolver — v3.0 Suspension Handling
**Researched:** 2026-03-31
**Overall confidence:** HIGH

> **Scope note:** This update covers ONLY the four new capability areas for v3.0:
> (1) NYC holiday ASP suspension calendar, (2) 311 API for weather/emergency suspensions,
> (3) suspension/schedule merging, (4) ha-nyc311 bridge in HA.
> The validated v2.0 stack (Python 3.11+, pyproj, shapely, rtree, httpx, zstandard,
> Home Assistant custom component, stdlib logging) is NOT re-researched here.
> See the 2026-03-13 STACK.md history for that foundation.

---

## Capability 1: Holiday ASP Suspension Calendar

### Data Source Analysis

NYC DOT publishes the annual ASP suspension calendar at:
`https://www.nyc.gov/html/dot/html/motorist/alternate-side-parking.shtml`

Two machine-readable formats are available:
- **ICS file**: `https://www.nyc.gov/html/dot/downloads/ics/asp-calendar-YYYY.ics` (URL
  pattern inferred from PDF pattern `asp-calendar-YYYY.pdf`; confirmed ICS format offered
  on the page for import into Outlook/Google/macOS Calendar)
- **PDF**: `https://www.nyc.gov/html/dot/downloads/pdf/asp-calendar-YYYY.pdf` (not
  machine-parseable; do not use)

There is no REST API or JSON feed for this data. The ICS file is updated annually (new
year = new file). The ICS contains all known holiday suspension dates for the full year.
Weather/emergency suspensions are NOT in the ICS — those require live polling (see
Capability 2).

**Verdict: Download the annual ICS file once per year (or on startup if missing) and
parse it with `icalendar`. Store the parsed dates as a frozen set in memory.**

### ICS Parsing Library

| Library | Version | Purpose | Why |
|---------|---------|---------|-----|
| icalendar | >=6.1.0 | Parse NYC DOT ICS calendar file | Actively maintained (v7.x in development, v6.x stable as of late 2025); RFC 5545 compliant; pure Python; no aiohttp dependency; works with httpx for download. The `python-icalendar` package on PyPI. Simpler API than ics.py for the use case of iterating VEVENT components. |

**Do NOT use:**
- `ics` (ics.py): Less maintained, more complex API for simple date extraction
- `ical`: Newer package, less established, no significant advantage here
- `recurring-ical-events`: Overkill — ASP suspension dates are one-off events, not
  recurring rules

### Integration with Existing Stack

The ICS download uses the existing `httpx.AsyncClient` already in `signs/client.py`.
The parsed suspension dates are a `frozenset[date]` — a simple stdlib type, no new
model needed. A new `gps2asp/suspension/` subpackage is the right home.

**No new HTTP library needed.** httpx already handles async downloads.

---

## Capability 2: Weather/Emergency Suspension Polling (NYC 311 API)

### Data Source Analysis

Real-time ASP suspension status (snow days, emergency declarations) comes from the
**NYC 311 Public API** at `api-portal.nyc.gov`. This API requires a free developer
account and API key (subscribed to the "NYC 311 Public Developers" product).

The API endpoint returns a calendar of service statuses including `Alternate Side
Parking` suspension state for any requested date range. The `nyc311calendar` Python
library wraps this API.

**Alternative considered: `The-NYC-ASP-API` (github.com/erickouassi)** — A third-party
proxy with no-auth endpoints like `/v1/today`. Verdict: REJECT. The author explicitly
disclaims continued existence. Third-party proxy adds an unreliable middle layer. Use
the official API directly.

**Another alternative: 311 Open Inquiry API** (`api.cityofnewyork.us/311/v1/municipalservices`)
— An older endpoint identified in NYC Open Data community discussions that returns JSON
without OAuth. Status unknown as of 2026. REJECT as primary; document as fallback
emergency option only.

### NYC 311 API Wrapper

| Library | Version | Purpose | Why |
|---------|---------|---------|-----|
| nyc311calendar | 0.4.1 | Async fetch of ASP suspension status from NYC 311 Public API | Written specifically for this use case; used by ha-nyc311; supports Week Ahead and Quarter Ahead calendar types; returns typed Python dataclasses. Alpha-quality (author's own label) and last released Dec 2022. |

**Critical dependency issue with `nyc311calendar`:** It requires **aiohttp**, not
httpx. This conflicts with the project's existing choice of httpx as the sole HTTP
client. Adding aiohttp to the HA component footprint adds ~1 MB of compiled wheels
and creates two HTTP clients in the same process.

**Resolution: Do NOT use `nyc311calendar` as a library dependency.** Instead, call
the NYC 311 Public API directly with httpx. The API is a standard HTTPS JSON endpoint;
`nyc311calendar`'s source code (github.com/elahd/nyc311calendar) can be read to
extract the exact endpoint URL and response field names without taking a dependency
on the package itself.

This approach:
- Maintains a single HTTP client (httpx) in the codebase
- Avoids aiohttp as a second HTTP framework
- Keeps the HA component footprint small
- The API is simple enough (one endpoint, one response schema) that a wrapper is
  not needed

**Verdict: Implement a thin `NYC311SuspensionClient` in `gps2asp/suspension/` using
httpx directly. Model the response schema from nyc311calendar's open source code.**

### API Key Handling

The NYC 311 API key must be stored in the HA config entry (config flow). Add
`CONF_NYC311_API_KEY` as an optional config entry field. When absent, the suspension
feature degrades gracefully to holiday-calendar-only mode (SUSP-01 still works,
SUSP-02 disabled).

---

## Capability 3: Suspension/Schedule Merging

### Architecture

The existing `schedule/models.py` already has a `suspended: bool = False` hook on
`ScheduleFound` and `ASPActiveNow`. The merge logic needs to:

1. Check suspension state (holiday or 311 API) against the `next_window.start_datetime`
2. If suspended: set `suspended=True` on the result; set `next_window=None` on
   `ScheduleFound` (no move needed); transform `ASPActiveNow` → `ScheduleFound(suspended=True)`

Because `ScheduleFound` and `ASPActiveNow` are frozen dataclasses, mutation requires
`dataclasses.replace()`. This is already the pattern in the codebase.

**No new library needed.** Pure Python logic using `dataclasses.replace()` and
`datetime.date` comparison. The suspension check is a `date in suspension_dates` set
lookup — O(1).

### New Model

Add a `SuspensionState` frozen dataclass to `gps2asp/suspension/models.py`:

```python
@dataclass(frozen=True)
class SuspensionState:
    suspended: bool
    reason: str | None          # "New Year's Day", "Snow emergency", etc.
    source: Literal["holiday_calendar", "nyc311_api", "unknown"]
    as_of: datetime
```

This is a stdlib-only model. No new dependency.

---

## Capability 4: ha-nyc311 Bridge in Home Assistant

### ha-nyc311 Integration Analysis

**ha-nyc311** (github.com/elahd/ha-nyc311) is a Home Assistant custom component that
exposes NYC 311 calendar data as HA entities:

- `binary_sensor.nyc311_parking_exception_today` — `on` when ASP is suspended today
- `binary_sensor.nyc311_parking_exception_tomorrow` — `on` when ASP is suspended tomorrow
- Through `binary_sensor.nyc311_parking_exception_in_6_days`
- `sensor.next_parking_exception` — date of next suspension
- Calendar entity for all services

Latest version: **v0.1.5** (February 2023). The integration is functional but not
actively developed. It uses `nyc311calendar` (aiohttp) internally.

### Bridge Pattern

The ASP Parking integration should optionally read from ha-nyc311's entities rather
than polling the 311 API itself. This avoids duplicate API calls when both integrations
are installed.

**Implementation approach:** In `coordinator.py`, use the existing HA helper
`async_track_state_change_event` to watch `binary_sensor.nyc311_parking_exception_today`.
When that sensor changes state, invalidate the suspension cache and re-run the
schedule computation with the new suspension state.

This is the correct HA pattern: read another integration's entity state rather than
tight coupling to its internals. No new library is needed. The existing coordinator
already uses `async_track_state_change_event` for the device_tracker.

**Config flow addition:** Add an optional `CONF_NYC311_ENTITY` field (EntitySelector
filtered to `binary_sensor` domain). When configured, use the ha-nyc311 entity as the
suspension source instead of direct 311 API polling. When absent, fall back to direct
API polling (if API key configured) or holiday-calendar-only.

**Priority chain for suspension state:**
1. ha-nyc311 entity state (if `CONF_NYC311_ENTITY` configured)
2. Direct 311 API poll (if `CONF_NYC311_API_KEY` configured)
3. Holiday calendar only (always available, no external dependency)

This design makes all three modes independently useful and gracefully degrades.

### HA Helpers Used (all existing, no new imports)

| Helper | Source | Purpose |
|--------|--------|---------|
| `async_track_state_change_event` | `homeassistant.helpers.event` | Watch nyc311 entity state |
| `async_track_time_interval` | `homeassistant.helpers.event` | Poll 311 API on schedule |
| `selector.EntitySelector` | `homeassistant.helpers.selector` | Config flow entity picker |

---

## Summary of Stack Additions for v3.0

### New Runtime Dependencies

| Library | Version | Purpose | Where Used |
|---------|---------|---------|------------|
| icalendar | >=6.1.0 | Parse NYC DOT annual ASP suspension ICS file | `gps2asp/suspension/calendar.py` |

**That is the only new library dependency.** Everything else uses the existing stack.

### No New Dependencies For

| Capability | Why No New Dependency |
|------------|----------------------|
| 311 API client | httpx already present; thin wrapper over JSON endpoint |
| Suspension/schedule merge | `dataclasses.replace()` + stdlib `datetime.date` |
| ha-nyc311 bridge | `async_track_state_change_event` already in HA helpers |
| Holiday calendar download | httpx already present |
| Suspension state model | stdlib frozen dataclass |

### pyproject.toml Change

```toml
# Add to [project] dependencies:
"icalendar>=6.1.0",
```

### manifest.json Change

```json
"requirements": [
    "pyproj>=3.7.0",
    "rtree>=1.4.0",
    "shapely>=2.1.0",
    "httpx>=0.28.0",
    "zstandard>=0.21.0",
    "icalendar>=6.1.0"
]
```

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| ICS parsing | icalendar | ics.py | Less actively maintained; more complex API for simple VEVENT iteration |
| ICS parsing | icalendar | stdlib only (manual parse) | ICS format has enough edge cases (timezone, encoding) to warrant a proper parser |
| 311 API wrapper | httpx (direct) | nyc311calendar | Requires aiohttp; last released Dec 2022; alpha quality; adds a second HTTP client framework |
| 311 API wrapper | httpx (direct) | The-NYC-ASP-API (third-party proxy) | No auth, but author disclaims stability; unreliable external dependency |
| ha-nyc311 bridge | HA state machine bridge (entity read) | Import ha-nyc311 as a Python library | Custom components cannot import from each other's Python modules; HA entity state is the correct IPC mechanism |
| aiohttp for 311 | Rejected | aiohttp | Project already uses httpx; adding a second async HTTP framework is wasteful and creates version conflict risk in HA's shared Python environment |

## What NOT to Add

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `nyc311calendar` | aiohttp dependency conflicts with httpx; alpha quality; last release 2022 | Direct httpx call to NYC 311 API |
| `aiohttp` | Second HTTP framework; HA already ships aiohttp but custom components shouldn't declare it as a pip requirement when httpx covers all needs | httpx (existing) |
| `ics` (ics.py) | Less maintained than `icalendar`; no advantage for simple holiday date extraction | `icalendar` |
| `python-dateutil` | Not needed; ICS VEVENT DTSTART values for NYC DOT calendar are plain dates (no recurring rules, no complex timezone handling) | stdlib `datetime.date` |
| `recurring-ical-events` | Overkill; ASP suspension dates are non-recurring VEVENT entries | `icalendar` with direct DTSTART extraction |

---

## Version Compatibility

| Package | Version | Python Req | HA Compat | Notes |
|---------|---------|------------|-----------|-------|
| icalendar | >=6.1.0 | >=3.8 | Safe to add | Pure Python; no compiled extension; no conflict with HA's existing packages |

---

## Sources

- [NYC DOT ASP Suspension Calendar page](https://www.nyc.gov/html/dot/html/motorist/alternate-side-parking.shtml) — Confirmed ICS file available for download; no REST API (HIGH confidence, primary source)
- [nyc311calendar on PyPI](https://pypi.org/project/nyc311calendar/) — Version 0.4.1, Dec 2022, aiohttp dependency confirmed (HIGH confidence)
- [ha-nyc311 GitHub](https://github.com/elahd/ha-nyc311) — v0.1.5 Feb 2023; entity naming pattern `binary_sensor.nyc311_parking_exception_today`; ASP suspension sensor confirmed (HIGH confidence)
- [nyc311calendar GitHub](https://github.com/elahd/nyc311calendar) — aiohttp dependency, NYC 311 Public API endpoint, alpha release warning (HIGH confidence)
- [icalendar on PyPI](https://pypi.org/project/icalendar/) — v7.0.3/6.x stable, actively maintained, RFC 5545 compliant (HIGH confidence)
- [HA Developer Docs: Listening for Events](https://developers.home-assistant.io/docs/integration_listen_events/) — `async_track_state_change_event` is the recommended pattern for cross-integration state reading (HIGH confidence, official docs)
- [NYC Open Data community issue on 311 API endpoint](https://github.com/CityOfNewYork/DOT-Data-Feeds/issues/1) — `api.cityofnewyork.us/311/v1/municipalservices` endpoint confirmed as older alternative (MEDIUM confidence — community discussion, not official docs)
- [NYC API Portal](https://api-portal.nyc.gov/) — Free API key required for NYC 311 Public API; subscribe to "NYC 311 Public Developers" product (HIGH confidence)

---
*Stack research for: GPS2ASP Resolver v3.0 — Suspension Handling*
*Researched: 2026-03-31*
