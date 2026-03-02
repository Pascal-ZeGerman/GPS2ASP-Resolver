# gps2asp

> **GPS coordinates → NYC Alternate Side Parking schedule → "next move" datetime**

`gps2asp` resolves a GPS location to the [NYC Alternate Side Parking](https://www.nyc.gov/html/dot/html/motorist/alternate-side-parking.shtml) (ASP)
schedule for the nearest street block, then computes the next time you need to move your car.

Designed as a custom sensor backend for [Home Assistant](https://www.home-assistant.io/).

## How it works

```
GPS (lat, lon)
  → NY State Plane coordinates
    → CSCL R-tree spatial index → nearest street segment + side of street
      → NYC Open Data SODA API → ASP sign records for that block
        → schedule parser
          → next move datetime
```

Data source: [NYC Open Data Parking Regulation Locations and Signs](https://data.cityofnewyork.us/Transportation/Parking-Regulation-Locations-and-Signs/xswq-wnv9)

## Installation

Requires Python 3.11+. Install into your Home Assistant Python environment:

```bash
git clone <repo-url>
cd gps2asp
pip install -e .
```

> You must build the spatial index before first use. See [Build Index](#build-index) below.

## Quick Start

```python
import asyncio
from gps2asp import resolve_asp

async def main():
    # PROSPECT PL between VANDERBILT AVE and CARLTON AVE, Brooklyn
    result = await resolve_asp(40.677629, -73.968527)

    if result.resolution_failed:
        print(f"Resolution error: {result.resolution_error}")
        return

    schedule = result.schedule
    if schedule is None or schedule.status != "schedule_found":
        status = schedule.status if schedule else "none"
        print(f"No ASP schedule: {status}")
        return

    # schedule is ScheduleFound
    if schedule.next_window:
        print(f"Move by: {schedule.next_window.start_datetime}")
        print(f"Block:   {schedule.on_street} ({schedule.from_street} to {schedule.to_street}, {schedule.side_of_street} side)")
        print(f"Schedule: {schedule.summary}")
    else:
        print("No upcoming ASP window in the next 7 days")

asyncio.run(main())
```

### Result fields

`resolve_asp()` returns `ASPResult`:

| Field | Type | Description |
|-------|------|-------------|
| `schedule` | `ScheduleResult \| None` | Parsed schedule. `None` if `resolution_failed` is `True`. |
| `resolution_failed` | `bool` | `True` when the GPS point could not be uniquely assigned to a street segment. |
| `resolution_error` | `str \| None` | Error message when `resolution_failed` is `True`. |

When `schedule.status == "schedule_found"` (`ScheduleFound`):

| Field | Type | Description |
|-------|------|-------------|
| `next_window` | `CleaningWindow \| None` | Next upcoming ASP window, or `None` if none within 7 days. |
| `next_window.start_datetime` | `datetime` | NYC-local datetime when you must move your car by. |
| `next_window.end_datetime` | `datetime` | NYC-local datetime when cleaning ends. |
| `summary` | `str` | Human-readable schedule (e.g., `"Mon 8–9:30 AM, Thu 11:30 AM–1 PM"`). |
| `on_street` | `str` | Street name. |
| `from_street` / `to_street` | `str` | Cross streets at block boundaries. |
| `side_of_street` | `str` | `N` / `S` / `E` / `W`. |

### Schedule status values

| `schedule.status` | Meaning |
|-------------------|---------|
| `"schedule_found"` | ASP schedule found; `next_window` has the next cleaning time. |
| `"asp_active_now"` | ASP cleaning is currently in progress at your location. |
| `"no_asp"` | No ASP restrictions on this block. |
| `"no_match"` | Block not found in SODA sign data. |
| `"all_unparseable"` | Signs found but none could be parsed. |

### Exceptions

These propagate from `resolve_asp()` and must be handled by the caller:

| Exception | When |
|-----------|------|
| `OutsideNYCError` | Coordinates outside NYC bounding box |
| `NoSegmentFoundError` | No street segment within 164 ft |
| `SODAAPIError` | SODA API errors after retries |
| `IncompleteResultsError` | SODA pagination interrupted |

`AmbiguousResolutionError` is caught internally and surfaced as `resolution_failed=True`.

### Debug mode

```python
debug_result = await resolve_asp(40.677629, -73.968527, debug=True)
print(f"Confidence:   {debug_result.confidence:.2f}")
print(f"SODA level:   {debug_result.soda_level}")      # 1, 2, or 3 (fallback level)
print(f"State Plane:  ({debug_result.state_plane_x:.1f}, {debug_result.state_plane_y:.1f})")
print(f"Sign result:  {debug_result.sign_result}")
```

## Build Index

`gps2asp` requires a prebuilt spatial index of NYC street segments with ASP sign data.
Index files are large and are gitignored — you must build them locally before first use.

```bash
# From the project root (requires internet access to NYC Open Data)
python scripts/build_index.py
```

- **Runtime:** ~3–5 minutes
- **Output:** `src/gps2asp/data/index/`
- **Verify:** `src/gps2asp/data/index/build_info.json` shows `asp_segments_count` and `build_timestamp`

Rebuild whenever you want to pick up updated sign data from NYC Open Data.

## Known Limitations

### Coverage gaps

`gps2asp` uses exact boundary-to-boundary matching to associate SODA sign records with CSCL
street segments. Many NYC Open Data ASP sign records span **multiple consecutive blocks**
under a single SODA entry. When a record spans blocks A–C, only block A (the first boundary)
gets matched; blocks B and C return `"no_match"`.

**Per-borough coverage** (Phase 9 index build, March 2026):

| Borough | Coverage |
|---------|----------|
| Brooklyn | 47.9% |
| Manhattan | 29.5% |
| Bronx | 28.6% |
| Queens | 18.1% |
| Staten Island | ~0% (see below) |

Phase 11 will address multi-block spans via mid-span matching, which is expected to
significantly improve coverage in Manhattan and the Bronx.

### Staten Island

Staten Island shows ~0% coverage because the NYC Open Data SODA API contains essentially
no ASP sign records for Staten Island. This is a gap in the **source data**, not the
algorithm. `gps2asp` cannot produce schedules for blocks not present in SODA.

### Street resolution

`gps2asp` resolves GPS coordinates against the NYC CSCL dataset (NYC Street Centerline).
Points more than 164 ft from any street segment raise `NoSegmentFoundError`. Points
equidistant from two segments raise `AmbiguousResolutionError`, which is surfaced as
`resolution_failed=True` on the result (not a raised exception).

## Project Status

`gps2asp` v1.1 — active development.

- **v1.0** (2026-02-23): Full GPS → ASP schedule pipeline
- **v1.1** (2026-03): Bug fixes, confidence algorithm, pipeline stabilization, index rebuild

**Upcoming:**
- Phase 11: Mid-span coverage — address multi-block SODA span gap (expected coverage improvement in Manhattan/Bronx)
