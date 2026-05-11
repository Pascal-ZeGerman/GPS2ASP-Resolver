<!-- generated-by: gsd-doc-writer -->
# GPS2ASP Testing Guide

---

## Table of Contents

- [Test Framework and Setup](#test-framework-and-setup)
- [Running Tests](#running-tests)
- [Test Markers](#test-markers)
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
which is bundled in the `dev` extras group.

Install all test dependencies:

```bash
.venv/bin/python -m pip install -e ".[dev]"
```

The `tests/conftest.py` file provides two `autouse` fixtures that run before every test:

- `reset_spatial_index` — calls `SpatialIndex.reset()` to clear the singleton between tests,
  preventing index state from leaking across test cases.
- `reset_street_graph` — sets `StreetGraph._instance = None` for the same reason.

A third session-scoped fixture, `spatial_index_dir`, is used by integration tests. It skips the
entire session if the spatial index files (`segments.idx`, `segments.dat`, `segments.json`) have
not been built. Build the index before running integration tests:

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

**Run only fast (non-network, non-HA) tests** — the same set CI runs:

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

Apply a marker to a test class or function:

```python
@pytest.mark.integration
class TestResolveProspectHeights:
    ...
```

Tests without either marker are pure unit tests that run offline and complete in milliseconds.

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
(declare as function parameters).

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
| `manhattan_coverage.json` | Coverage integration tests — Manhattan borough sample coordinates |
| `manhattan_coverage_50.json` | Coverage integration tests — 50-coordinate Manhattan sample |
| `queens_coverage.json` | Coverage integration tests — Queens borough sample coordinates |
| `queens_coverage_50.json` | Coverage integration tests — 50-coordinate Queens sample |
| `sample_asp_2026.ics` | `test_suspension.py` — a real ASP holiday calendar ICS file for 2026 |

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

**Trigger:** Every push and pull request to any branch.

**Jobs:**

| Job | What it does |
|---|---|
| `dependencies` | Installs `.[dev]` on Python 3.14 and verifies `import gps2asp` and `import custom_components.asp_parking` succeed |
| `pytest` | Runs `python -m pytest tests/ -v --tb=short -m "not integration"` — integration tests are excluded in CI because network access to the SODA API and the spatial index are unavailable in the runner |
| `lint` | Runs `ruff check .`, `ruff format --check .`, `mypy src/gps2asp/`, and `mypy custom_components/asp_parking/` |

The `pytest` and `lint` jobs both `needs: dependencies`, so they run in parallel only after the
import verification step passes.
