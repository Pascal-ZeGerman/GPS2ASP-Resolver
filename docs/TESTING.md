<!-- generated-by: gsd-doc-writer -->
# GPS2ASP Testing Guide

---

## Table of Contents

- [Test Framework and Setup](#test-framework-and-setup)
- [Running Tests](#running-tests)
- [Test Markers](#test-markers)
- [Test Suite Inventory](#test-suite-inventory)
- [Writing New Tests](#writing-new-tests)
- [Test Fixtures](#test-fixtures)
- [Coverage Requirements](#coverage-requirements)
- [CI Integration](#ci-integration)

---

## Test Framework and Setup

The project uses **pytest** with the **pytest-asyncio** plugin. All async tests run automatically
without requiring explicit `@pytest.mark.asyncio` decorators — `asyncio_mode = "auto"` is set
globally in `pyproject.toml`.

Home Assistant integration tests require the **pytest-homeassistant-custom-component** package,
which is bundled in the `dev` extras group. The CalDAV sync tests require **`caldav[async]==3.2.0`**,
also pinned in the `dev` extras.

Install all test dependencies:

```bash
.venv/bin/python -m pip install -e ".[dev]"
```

The `tests/conftest.py` file provides two `autouse` fixtures that run before AND after every test:

- `reset_spatial_index` — calls `SpatialIndex.reset()` (yield-wrapped, so it runs before and after
  each test) to clear the singleton, preventing index state from leaking across test cases.
- `reset_street_graph` — sets `StreetGraph._instance = None` before and after each test for the
  same reason. The `StreetGraph` import is deferred inside the fixture body.

A third session-scoped fixture, `spatial_index_dir`, is used by integration tests. It skips the
entire session if the spatial index files (`segments.idx`, `segments.dat`, `segments.json`) under
`src/gps2asp/data/index/` have not been built. Build the index before running integration tests:

```bash
.venv/bin/python scripts/build_index.py
```

---

## Running Tests

**Run all tests** (skips network-dependent integration tests automatically when index is absent):

```bash
.venv/bin/pytest
```

**Run all tests with verbose output:**

```bash
.venv/bin/pytest -v --tb=short
```

**Run a specific test file:**

```bash
.venv/bin/pytest tests/test_parser.py
```

**Run a specific test by name:**

```bash
.venv/bin/pytest tests/test_resolver.py::TestResolveProspectHeights::test_resolve_prospect_heights
```

**Run only fast (non-network) tests** — the same set CI runs:

```bash
.venv/bin/pytest -m "not integration"
```

**Run only unit tests, excluding both integration marker types:**

```bash
.venv/bin/pytest -m "not integration and not ha_integration"
```

**Run only integration tests** (requires built spatial index and network access):

```bash
.venv/bin/pytest -m "integration"
```

---

## Test Markers

Two custom markers are registered in `pyproject.toml`:

| Marker | When to use | Requirement |
|---|---|---|
| `integration` | Tests that call the live SODA API (`data.cityofnewyork.us`) or require the built spatial index | Network access + `scripts/build_index.py` must have been run |
| `ha_integration` | Tests for the `custom_components/asp_parking` Home Assistant integration | `pytest-homeassistant-custom-component` installed (included in `.[dev]`) |

Files that currently apply `@pytest.mark.integration`: `test_resolver.py`,
`test_spatial_index_radius.py`, `test_edge_cases.py`, `test_sign_retrieval.py`.

Files that currently apply `@pytest.mark.ha_integration`: `test_ha_integration.py`,
`test_diagnostics.py`, `test_sensor_display_format.py`, `test_options_flow.py`,
`test_options_flow_caldav.py`, `test_repair_issue.py`, `test_init_caldav_remove.py`.

Apply a marker to a test class or function:

```python
@pytest.mark.integration
class TestResolveProspectHeights:
    ...
```

Tests without either marker are pure unit tests that run offline and complete in milliseconds.

---

## Test Suite Inventory

The suite is organized into three broad groups: the core `gps2asp` resolver library, the
`custom_components/asp_parking` Home Assistant integration, and supporting `scripts/` tooling.

### Core resolver library (`gps2asp`)

| Test file | Covers |
|---|---|
| `test_converter.py` | WGS84 → NY State Plane coordinate conversion |
| `test_side_resolver.py` | Side-of-street (N/S/E/W) determination from geometry |
| `test_confidence.py` | Confidence scoring |
| `test_normalize.py` | Street-name normalization (CSCL → SODA format), pure string transforms |
| `test_parser.py` | ASP sign-description parser across all observed SODA format variations |
| `test_schedule.py` | Schedule merge, next-move computation, summary, and `compute_schedule()` |
| `test_suspension.py` | Holiday-calendar parsing and `SuspensionInfo` (uses `sample_asp_2026.ics`) |
| `test_suspension_merge.py` | `apply_suspension()` pure function |
| `test_poller.py` | `gps2asp.suspension.poller` — NYC 311 API suspension client |
| `test_graph_filter.py` | `graph.json` 2-hop BFS neighborhood filter + zstandard loading |
| `test_resolve_asp.py` | `resolve_asp()` end-to-end contract with mocked pipeline stages |
| `test_resolver_extended_fields.py` | Extended diagnostic fields on `ResolutionResult` (borocode, distance, width, segment_id) |
| `test_resolver.py` | End-to-end resolver pipeline — **integration** (needs built index) |
| `test_edge_cases.py` | Error handling and boundary conditions — **integration** |
| `test_sign_retrieval.py` | StreetGraph / Level-4 sign retrieval; live SODA API — **integration** |
| `test_spatial_index_radius.py` | `SpatialIndex.query_radius()` bounded-radius queries — **integration** |

### Home Assistant integration (`custom_components/asp_parking`)

| Test file | Covers |
|---|---|
| `test_ha_integration.py` | Coordinator data mapping, sensor/binary-sensor state derivation, movement threshold, stale timeout |
| `test_coordinator_cache.py` | Phase 26 sign-cache and pre-seed lifecycle (parking-area pre-seed) |
| `test_coordinator_borough_fields.py` | Borough mapping and 4 new diagnostic fields on `ASPParkingData` |
| `test_coordinator_boundary_timer.py` | Window-boundary timer cancel/schedule helpers (Phase 39) |
| `test_coordinator_heartbeat.py` | Periodic 8h heartbeat re-fetch + suspension re-check |
| `test_coordinator_debug_logs.py` | `async_update_listeners()` alias and debug-flag init behavior |
| `test_coordinator_integration.py` | Cross-cutting edge cases spanning rebuild + CalDAV paths |
| `test_coordinator_path_selection.py` | Dual-path rebuild routing (`RebuildPath` DOWNLOAD vs FROM_SOURCE) |
| `test_coordinator_rebuild.py` | `async_request_rebuild` lock/flag gate + `_async_do_rebuild` atomic swap |
| `test_coordinator_stale.py` | Stale-detection lifecycle (`_async_check_stale_and_rebuild`) |
| `test_coordinator_caldav.py` | Coordinator CalDAV hooks (after-resolve write, move/suspension delete gates) |
| `test_caldav_sync.py` | `caldav_sync.py` public API: UID derivation, VEVENT build, connection validation, idempotent write/delete |
| `test_options_flow.py` | Options-flow `parking_area` step — **ha_integration** |
| `test_options_flow_caldav.py` | Options-flow CalDAV + calendar-picker steps — **ha_integration** |
| `test_init_caldav_remove.py` | `async_remove_entry` CalDAV teardown — **ha_integration** |
| `test_debug_switch.py` | `ASPDebugModeSwitch` on/off toggling of `_debug_enabled` |
| `test_diagnostics.py` | Diagnostics export shape + redaction — **ha_integration** |
| `test_repair_issue.py` | ImportError repair-issue create/auto-dismiss — **ha_integration** |
| `test_sensor_display_format.py` | Next-move sensor three-tier display format — **ha_integration** |
| `test_asp_debug_result_extended_fields.py` | Extended diagnostic fields on `ASPDebugResult` |
| `test_index_io.py` | Pure sync index helpers: atomic swap, stale cleanup, zip-slip guard, timestamp parsing |
| `test_index_io_build_from_source.py` | `_sync_build_from_source` CSCL rebuild path (uses `cscl_geojson_sample.json`, `soda_asp_signs_sample.json`) |
| `test_index_last_rebuilt_sensor.py` | `ASPIndexLastRebuiltSensor` entity contract |
| `test_index_rebuild_button.py` | `ASPIndexRebuildButton` entity contract |
| `test_index_rebuilding_binary_sensor.py` | `ASPIndexRebuildingBinarySensor` entity contract |
| `test_strings_icu_escape.py` | ICU-escaping of curly placeholders in i18n strings (`strings.json` / `translations/en.json`) |
| `test_strings_step_tracker.py` | "Step N of 3:" prefix on config-flow step titles + strings file parity |

### Supporting scripts (`scripts/`)

| Test file | Covers |
|---|---|
| `test_build_index.py` | `scripts/build_index.py` bug fixes and graph construction |
| `test_audit_script.py` | `scripts/audit_queens_coverage.py` `print_report()` and helpers (synthetic data, no network) |
| `test_sync_vendored.py` | `scripts/sync_vendored.py` `normalize_source` import rewriting + integration behavior |

---

## Writing New Tests

**File naming convention:** `test_<module_or_feature>.py` in the `tests/` directory.

**Async tests:** All async tests work without any extra decorator because `asyncio_mode = "auto"`
is configured. Write `async def test_...` directly.

**Singleton reset:** Both `SpatialIndex` and `StreetGraph` are singletons. The `autouse` fixtures
in `conftest.py` reset them automatically before and after every test. If a test needs to load the
real index, request the `spatial_index_dir` fixture and pass the returned path to the constructor.

**Mocking pipeline stages:** The three pipeline stages (`resolver/`, `signs/`, `schedule/`) are
independent libraries. Unit tests patch individual stages using `unittest.mock.AsyncMock` and
`patch`. See `tests/test_resolve_asp.py` for examples of mocking the full pipeline with
structured return types.

**Test helpers:** There are no shared helper modules beyond `conftest.py`. Import fixtures
needed for a test file directly from `conftest.py` via the standard pytest fixture mechanism
(declare as function parameters). Tests that exercise `scripts/` modules add the `scripts/`
directory to `sys.path` and import the script module directly (see `tests/test_audit_script.py`).

**Marker placement:** Add `@pytest.mark.integration` to any test that reads `spatial_index_dir`
or makes HTTP calls to `data.cityofnewyork.us`. Add `@pytest.mark.ha_integration` to any test
that imports from `homeassistant.*` or `pytest_homeassistant_custom_component`.

Example unit test structure:

```python
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from gps2asp import resolve_asp


class TestMyFeature:
    async def test_expected_behavior(self) -> None:
        with patch("gps2asp.pipeline.retrieve_signs", new_callable=AsyncMock) as mock:
            mock.return_value = ...
            result = await resolve_asp(40.676, -73.969)
            assert result.street == "PROSPECT PLACE"
```

---

## Test Fixtures

Fixture files live in `tests/fixtures/` and are checked into the repository:

| File | Used by |
|---|---|
| `prospect_heights.json` | `test_resolver.py` — real Prospect Heights GPS coordinates with expected resolution results |
| `cscl_geojson_sample.json` | `test_index_io_build_from_source.py` — sample CSCL GeoJSON FeatureCollection for the from-source rebuild path |
| `soda_asp_signs_sample.json` | `test_index_io_build_from_source.py` — sample SODA ASP-sign records for the from-source rebuild path |
| `sample_asp_2026.ics` | `test_suspension.py` — a real ASP holiday calendar ICS file for 2026 |
| `manhattan_coverage.json` | Manhattan GPS-coordinate coverage sample (consumed by `scripts/` audit/geocode tooling) |
| `manhattan_coverage_50.json` | 50-coordinate Manhattan coverage sample |
| `queens_coverage.json` | Queens GPS-coordinate coverage sample |
| `queens_coverage_50.json` | 50-coordinate Queens coverage sample |

> The four `*_coverage*.json` files are GPS-coordinate datasets generated for the
> `scripts/audit_queens_coverage.py`, `scripts/geocode_fixtures.py`, and
> `scripts/generate_random_fixtures.py` tooling. `test_audit_script.py` exercises the audit
> report logic with synthetic in-memory data rather than loading these files directly.

---

## Coverage Requirements

No coverage threshold is configured. There is no `.nycrc`, `c8` configuration, or
`coverageThreshold` in `pyproject.toml`.

To generate a coverage report locally, install `pytest-cov` and run:

```bash
.venv/bin/python -m pip install pytest-cov
.venv/bin/pytest --cov=src/gps2asp --cov-report=term-missing -m "not integration"
```

---

## CI Integration

Tests run in the **`pytest + lint`** workflow defined in `.github/workflows/pytest.yml`.

**Trigger:** Every push and pull request to any branch (`branches: ["**"]`).

**Jobs:**

| Job | What it does |
|---|---|
| `dependencies` (Check dependencies) | Installs `.[dev]` on Python 3.14 and verifies `import gps2asp; import custom_components.asp_parking` succeeds |
| `test` (pytest) | Runs `python -m pytest tests/ -v --tb=short -m "not integration"` — integration tests are excluded because network access to the SODA API and the spatial index are unavailable in the runner |
| `lint` (ruff + mypy) | Runs `ruff check .`, `ruff format --check .`, `mypy src/gps2asp/`, and `mypy custom_components/asp_parking/` |

All three jobs run on `ubuntu-latest` with Python 3.14 and pip caching. The `test` and `lint`
jobs both declare `needs: dependencies`, so they run in parallel only after the import-verification
step passes.
