<!-- generated-by: gsd-doc-writer -->
# Development Guide

A reference for contributors working on `gps2asp` — the GPS-to-ASP resolver library and Home Assistant integration.

---

## Table of Contents

1. [Local Setup](#1-local-setup)
2. [Build Commands](#2-build-commands)
3. [Code Style](#3-code-style)
4. [Vendored Mirror Sync](#4-vendored-mirror-sync)
5. [CalDAV Development Notes](#5-caldav-development-notes)
6. [Branch Conventions](#6-branch-conventions)
7. [PR Process](#7-pr-process)

---

## 1. Local Setup

### Prerequisites

- Python `>= 3.11` (CI runs on Python 3.14; any 3.11+ version works locally)
- `git`
- A virtual environment — the system Python on this platform is externally managed (PEP 668) and will refuse package installs

### Steps

1. Clone the repository:

   ```bash
   git clone <repo-url>
   cd GPS2ASP-Resolver
   ```

2. Create a virtual environment:

   ```bash
   python3 -m venv .venv
   ```

3. Install the package with development dependencies:

   ```bash
   .venv/bin/python -m pip install -e ".[dev]"
   ```

   `[dev]` pulls in `pytest`, `pytest-asyncio`, `pytest-homeassistant-custom-component`, `mypy`, and `caldav[async]==3.2.0`.

4. (Optional) Install build tools, required only to rebuild the spatial index:

   ```bash
   .venv/bin/python -m pip install -e ".[build]"
   ```

   `[build]` adds `geopandas`, `requests`, and `zstandard`, used exclusively by `scripts/build_index.py`.

5. Build the spatial index (required before the resolver can run; takes 3–5 minutes and needs internet access):

   ```bash
   .venv/bin/python scripts/build_index.py
   ```

   This writes the index artifacts into `src/gps2asp/data/index/`. These files are gitignored and must be built in each local checkout.

### Environment variables

No variables are required. Two optional variables affect runtime behaviour:

| Variable | Effect |
|---|---|
| `GPS2ASP_INDEX_DIR` | Override the path to the pre-built spatial index directory |
| `NYC_OPEN_DATA_APP_TOKEN` | NYC Open Data app token for a dedicated rate-limit pool |

See `docs/CONFIGURATION.md` for the full variable reference.

---

## 2. Build Commands

All commands use `.venv/bin/python` and `.venv/bin/pytest` — never bare `python` or `pytest`.

| Command | Description |
|---|---|
| `.venv/bin/python -m pip install -e ".[dev]"` | Install package in editable mode with dev dependencies |
| `.venv/bin/python -m pip install -e ".[build]"` | Install package with index-build tools (geopandas, requests, zstandard) |
| `.venv/bin/python scripts/build_index.py` | Rebuild the spatial index from NYC Open Data CSCL dataset |
| `.venv/bin/python scripts/sync_vendored.py` | Mirror `src/gps2asp/` into `custom_components/asp_parking/gps2asp/` (write mode) |
| `.venv/bin/python scripts/sync_vendored.py --dry-run` | Check the vendored mirror for drift without writing (the CI guard) |
| `.venv/bin/pytest` | Run the full test suite |
| `.venv/bin/pytest tests/test_resolver.py` | Run a single test file |
| `.venv/bin/pytest tests/test_resolver.py::test_name` | Run a single test by name |
| `.venv/bin/pytest -m "not integration"` | Run tests without network access (matches the CI test job) |
| `.venv/bin/pytest -m "not integration and not ha_integration"` | Run only fast, offline tests, skipping HA-integration tests too |
| `ruff check .` | Lint all Python source |
| `ruff format --check .` | Check formatting without writing changes |
| `ruff format .` | Auto-format all Python source |
| `mypy src/gps2asp/` | Type-check the library package |
| `mypy custom_components/asp_parking/` | Type-check the Home Assistant integration |

CI runs `ruff check`, `ruff format --check`, and both `mypy` targets on every push and pull request (see `.github/workflows/pytest.yml`), and separately verifies the vendored mirror is in sync (see `.github/workflows/vendor-guard.yml`).

---

## 3. Code Style

### Linter and formatter: Ruff

Ruff handles both linting and formatting. It is configured in `pyproject.toml` under `[tool.ruff]`. The `.claude` directory is excluded from Ruff's scope.

Run before committing:

```bash
ruff check .
ruff format .
```

CI enforces both checks and will fail if either produces output.

### Type checker: mypy

mypy is configured in `pyproject.toml` under `[tool.mypy]`. Missing third-party stubs for `shapely`, `rtree`, and `gps2asp` itself are tolerated via an override with `ignore_missing_imports = true`.

Run:

```bash
mypy src/gps2asp/
mypy custom_components/asp_parking/
```

### Code conventions

- **Data models**: frozen dataclasses (`@dataclass(frozen=True)`) throughout — no mutable state in models.
- **Type hints**: full annotations on all functions and methods; every module begins with `from __future__ import annotations`.
- **Layering**: `src/gps2asp/` is a standalone library — it must not import anything from `custom_components/`. The HA integration imports `gps2asp`; the reverse is never allowed.
- **Async**: pipeline stages are sync; the HA coordinator is async. Keep the boundary clean.
- **Singleton reset in tests**: `SpatialIndex` is a singleton — call `SpatialIndex.reset()` between tests that need a fresh instance.

---

## 4. Vendored Mirror Sync

The Home Assistant integration cannot depend on the installed `gps2asp` package — HACS-distributed integrations must ship their dependencies in-tree. The library is therefore **vendored**: `src/gps2asp/` is the authoritative source, and a normalised copy lives at `custom_components/asp_parking/gps2asp/`.

### How the sync works

`scripts/sync_vendored.py` walks every `*.py` file under `src/gps2asp/` (excluding the `data/` subtree), rewrites column-zero `from gps2asp.X.Y import Z` imports into the correct relative form for each file's package depth, and writes the result into `custom_components/asp_parking/gps2asp/`. It also deletes any vendored `.py` file that no longer has a source counterpart.

```bash
# After editing anything under src/gps2asp/, regenerate the mirror:
.venv/bin/python scripts/sync_vendored.py
```

### The CI guard

The `vendor-guard.yml` workflow runs `python scripts/sync_vendored.py --dry-run` on every push and pull request. The dry-run writes nothing and exits non-zero if any vendored file differs from the normalised source (or if a stale vendored file remains). A drifted mirror fails CI.

**Rule of thumb:** any change to a file under `src/gps2asp/` must be followed by `python scripts/sync_vendored.py`, and the regenerated `custom_components/asp_parking/gps2asp/` files must be committed in the same change. Never hand-edit files under `custom_components/asp_parking/gps2asp/` — they are generated artifacts and will be overwritten. The `src/gps2asp/data/` directory is excluded from the sync and is not mirrored.

---

## 5. CalDAV Development Notes

`custom_components/asp_parking/caldav_sync.py` provides async CalDAV calendar synchronisation for the integration. A few project-specific facts matter when working on it:

- **Not vendored.** Unlike the `gps2asp/` library, `caldav_sync.py` lives only in the integration and is excluded from the vendored-mirror sync (it is not under `src/gps2asp/`). Editing it does not require running `sync_vendored.py`.
- **Sole caldav importer.** This module is the only place in the integration that imports `caldav`. Keep it that way so the version pin and the compatibility shim stay in one place.
- **Version divergence between manifest and dev deps.** The integration `manifest.json` pins `caldav==2.1.0`, because Home Assistant's built-in CalDAV component hard-pins that version and it takes precedence over any custom-integration requirement. The `pyproject.toml` `[dev]` extra instead installs `caldav[async]==3.2.0` for local development and tests. The module ships a `_CompatAsyncDAVClient` shim so it runs correctly against both: under the pinned 2.1.0 (which predates the `caldav.aio` submodule) the shim wraps the sync `caldav.DAVClient` in `run_in_executor` so blocking I/O never hits the HA event loop.
- **No blocking I/O on the event loop.** All network calls must remain async (or be dispatched to an executor by the shim). Do not call the synchronous `caldav.DAVClient` directly.
- **Tests.** CalDAV behaviour is covered by `tests/test_caldav_sync.py`, `tests/test_coordinator_caldav.py`, `tests/test_init_caldav_remove.py`, and `tests/test_options_flow_caldav.py`. These require `pytest-homeassistant-custom-component` and are marked `ha_integration`.

---

## 6. Branch Conventions

Branch names in this repository follow a `type/short-description` pattern:

| Type prefix | Purpose |
|---|---|
| `fix/` | Bug fixes (e.g., `fix/caldav-412-report-error`, `fix/suspension-ssl-useragent`) |
| `feat/` | New features (e.g., `feature/v3.2-ci-guard-vendor-sync`) |
| `chore/` | Maintenance and tooling (e.g., `chore/manifest-rc10`) |
| `release/` | Release candidates (e.g., `release/v3.1.0-rc.6`) |
| `docs/` | Documentation-only changes (e.g., `docs/v3.0.1`) |

The default and production branch is `main`.

Commit messages follow **Conventional Commits** format:

```
type(scope): short description
```

Examples from recent history:

```
fix(caldav): direct HTTP DELETE replaces REPORT-based lookup to fix 412 errors (CALDAV-09)
fix(caldav): remove erroneous await on principal.calendar() — caldav 3.x is sync
fix(button): grey out rebuild button while _is_rebuilding is True
fix(ci): resolve ruff, pytest, and vendor-guard failures
style: ruff format caldav_sync.py and test_caldav_sync.py
```

Common types: `fix`, `feat`, `test`, `ci`, `chore`, `style`, `docs`, `refactor`. Commits tied to a tracked issue append the issue reference in parentheses (e.g., `(CALDAV-09)`).

---

## 7. PR Process

No formal PR template exists in `.github/PULL_REQUEST_TEMPLATE.md`. Based on CI enforcement and project conventions, follow these guidelines:

- **Pass CI before requesting review.** The `pytest + lint` workflow runs `ruff check`, `ruff format --check`, `mypy` (both targets), and `pytest` (offline tests only — `-m "not integration"`) on every push. The separate `vendor-guard` workflow checks that the vendored mirror is in sync. A failing run in either workflow blocks merge.
- **Keep the vendored mirror in sync.** If you touch anything under `src/gps2asp/`, run `python scripts/sync_vendored.py` and commit the regenerated `custom_components/asp_parking/gps2asp/` files in the same PR. Otherwise `vendor-guard` will fail. See [Vendored Mirror Sync](#4-vendored-mirror-sync).
- **Do not mix concerns.** Keep linting fixes, logic changes, and documentation updates in separate commits or PRs when possible.
- **Mark network-dependent tests correctly.** Tests that hit the NYC Open Data SODA API must be decorated with `@pytest.mark.integration`. Tests that require `pytest-homeassistant-custom-component` must be decorated with `@pytest.mark.ha_integration`. CI skips only the `integration` marker; `ha_integration` tests run in CI. To skip both locally, use `-m "not integration and not ha_integration"`.
- **Keep caldav imports contained.** New CalDAV code belongs in `caldav_sync.py` so the `caldav==2.1.0` manifest pin and the compatibility shim stay in one place. See [CalDAV Development Notes](#5-caldav-development-notes).
- **Update `mypy` targets for new modules.** If you add a new module under `src/gps2asp/` or `custom_components/asp_parking/`, verify it passes `mypy` before submitting.
- **Spatial index changes.** If `scripts/build_index.py` changes, note in the PR description that existing locally-built indexes may need to be rebuilt.
