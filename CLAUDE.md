# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`gps2asp` converts GPS coordinates to NYC Alternate Side Parking (ASP) schedules. It is both a standalone Python library and a Home Assistant custom integration.

Pipeline: `GPS (lat, lon) → NY State Plane → CSCL spatial index → street segment + side → SODA API signs → parsed schedule → next move datetime`

## Development Commands

Always use `.venv/bin/python` and `.venv/bin/pytest` — system Python is externally managed (PEP 668).

```bash
# Install (dev deps including pytest, mypy, HA test fixtures)
.venv/bin/python -m pip install -e ".[dev]"

# Install build tools (geopandas, requests — needed for build_index.py)
.venv/bin/python -m pip install -e ".[build]"

# Run all tests
.venv/bin/pytest

# Run a single test file
.venv/bin/pytest tests/test_resolver.py

# Run a single test
.venv/bin/pytest tests/test_resolver.py::test_name

# Run only fast (non-network) tests
.venv/bin/pytest -m "not integration and not ha_integration"

# Build the spatial index (required before first use, ~3-5 min, needs internet)
.venv/bin/python scripts/build_index.py
```

## Architecture

### Three-stage pipeline (`src/gps2asp/`)

**Stage 1 — `resolver/`**: GPS → street segment + side
- `converter.py`: WGS84 → NY State Plane (feet) via `pyproj`
- `spatial_index.py`: Lazy-loaded singleton R-tree index (`rtree`/`shapely`) querying ~160K NYC street segments from `data/index/segments.{idx,dat,json}`
- `side_resolver.py`: Cross-product geometry to determine N/S/E/W side of street
- `confidence.py`: Scores resolution quality (distance, street width, ASP presence)
- `models.py`: `ResolutionResult`, `SegmentCandidate` (frozen dataclasses)
- `exceptions.py`: `OutsideNYCError`, `NoSegmentFoundError`, `AmbiguousResolutionError`, `IndexNotFoundError`

**Stage 2 — `signs/`**: Street segment → SODA API signs
- `client.py`: `SODAClient` — async httpx client for [NYC Open Data parking signs](https://data.cityofnewyork.us/resource/nfid-uabd.json), 3-level fallback query strategy (exact 4-field → relaxed cross-street swapped → on_street-only + client-side filter), pagination + exponential backoff
- `graph.py`: `StreetGraph` — street adjacency graph from `data/index/graph.json` for Level 4 mid-span BFS matching (Phase 11)
- `normalize.py`: Street name normalization between CSCL and SODA formats
- `models.py`: `SignRetrievalResult`, `SignRetrievalSuccess`, `NoMatch` (frozen dataclasses)

**Stage 3 — `schedule/`**: Signs → parsed schedule + next move
- `parser.py`: Regex parser for SODA sign description text → `TimeWindow` objects
- `merge.py`: Deduplicates overlapping time windows across multiple signs
- `next_move.py`: Computes next upcoming cleaning window (NYC-local timezone)
- `summary.py`: Human-readable schedule string (e.g., `"Mon 8–9:30 AM, Thu 11:30 AM–1 PM"`)
- `models.py`: `ScheduleResult` union (`ScheduleFound`, `ASPActiveNow`, `NoASP`, `NoMatch`, `AllUnparseable`)

**Entry point — `pipeline.py`**: `resolve_asp(lat, lon, debug=False)` wires all three stages. Returns `ASPResult` (lean) or `ASPDebugResult` (full intermediate state).

### Home Assistant integration (`custom_components/asp_parking/`)

- `coordinator.py`: `ASPParkingCoordinator` — event-driven (not polled), subscribes to `device_tracker` state changes, debounces GPS jitter via HA `Debouncer`, checks movement threshold, runs the three-stage pipeline inline
- `sensor.py`: Next move datetime sensor, schedule summary sensor
- `binary_sensor.py`: "ASP active now" binary sensor
- `config_flow.py`: UI config flow (device_tracker selection + options for threshold/refresh/stale timeout)
- `const.py`: All domain constants and defaults

The coordinator does **not** use `DataUpdateCoordinator` — it is event-driven. Entities register callbacks directly via `async_add_update_callback()`.

### Spatial index (`scripts/build_index.py`)

Builds `data/index/` from NYC Open Data CSCL dataset:
- `segments.idx` + `segments.dat`: R-tree files
- `segments.json`: Segment attribute data (geometry WKT, street names, ASP presence flags, `streetwidth`, `borocode`)
- `graph.json`: Street adjacency graph for mid-span BFS
- `build_info.json`: Build timestamp and coverage stats

Index files are gitignored and must be built locally.

## Conventions

- Data models: frozen dataclasses (`@dataclass(frozen=True)`)
- Type hints throughout; `from __future__ import annotations` in every module
- Each pipeline stage is a standalone library — no HA imports in `src/gps2asp/`
- NYC Open Data SODA API is the external data source for sign data
- Borough codes: 1=Manhattan, 2=Bronx, 3=Brooklyn, 4=Queens, 5=Staten Island
- Street names use CSCL format (e.g., `"PROSPECT PLACE"`, `"VANDERBILT AVENUE"`)
- SODA queries always include `sign_description LIKE '%SANITATION BROOM%'` and `sign_design_voided_on_date IS NULL`
- `SpatialIndex` is a singleton; call `SpatialIndex.reset()` between tests that need a fresh instance
- Index directory can be overridden via `GPS2ASP_INDEX_DIR` env var or `SpatialIndex(index_dir=...)`
- SODA app token: optional `NYC_OPEN_DATA_APP_TOKEN` env var for dedicated rate limit pool

## Test Markers

- `integration`: requires network access to NYC Open Data SODA API
- `ha_integration`: requires `pytest-homeassistant-custom-component`

## Known Coverage Gaps

SODA sign records often span multiple consecutive blocks under a single entry. Only the first boundary block matches; mid-span blocks return `"no_match"`. Per-borough coverage as of Phase 9 index build: Brooklyn 47.9%, Manhattan 29.5%, Bronx 28.6%, Queens 18.1%, Staten Island ~0% (no SODA data). Phase 11 addresses mid-span coverage via `StreetGraph` BFS matching.
