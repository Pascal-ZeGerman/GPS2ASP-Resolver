<!-- generated-by: gsd-doc-writer -->
# Development Guide

A reference for contributors working on `gps2asp` — the GPS-to-ASP resolver library and Home Assistant integration.

---

## Table of Contents

1. [Local Setup](#1-local-setup)
2. [Build Commands](#2-build-commands)
3. [Code Style](#3-code-style)
4. [Branch Conventions](#4-branch-conventions)
5. [PR Process](#5-pr-process)

---

## 1. Local Setup

### Prerequisites

- Python `>= 3.11` (the CI uses Python 3.14; any 3.11+ version works locally)
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

   `[dev]` pulls in `pytest`, `pytest-asyncio`, `pytest-homeassistant-custom-component`, and `mypy`.

4. (Optional) Install build tools, required only to rebuild the spatial index:

   ```bash
   .venv/bin/python -m pip install -e ".[build]"
   ```

   `[build]` adds `geopandas` and `requests`, used exclusively by `scripts/build_index.py`.

5. Build the spatial index (required before the resolver can run; takes 3–5 minutes and needs internet access):

   ```bash
   .venv/bin/python scripts/build_index.py
   ```

   This writes `segments.idx`, `segments.dat`, `segments.json`, `graph.json`, and `build_info.json` into `src/gps2asp/data/index/`. These files are gitignored and must be built in each local checkout.

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
| `.venv/bin/python -m pip install -e ".[build]"` | Install package with index-build tools (geopandas, requests) |
| `.venv/bin/python scripts/build_index.py` | Rebuild the spatial index from NYC Open Data CSCL dataset |
| `.venv/bin/pytest` | Run the full test suite |
| `.venv/bin/pytest tests/test_resolver.py` | Run a single test file |
| `.venv/bin/pytest tests/test_resolver.py::test_name` | Run a single test by name |
| `.venv/bin/pytest -m "not integration and not ha_integration"` | Run only fast, offline tests |
| `ruff check .` | Lint all Python source |
| `ruff format --check .` | Check formatting without writing changes |
| `ruff format .` | Auto-format all Python source |
| `mypy src/gps2asp/` | Type-check the library package |
| `mypy custom_components/asp_parking/` | Type-check the Home Assistant integration |

CI runs `ruff check`, `ruff format --check`, and both `mypy` targets on every push and pull request (see `.github/workflows/pytest.yml`).

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

mypy is configured in `pyproject.toml` under `[tool.mypy]`. Third-party stubs for `shapely`, `rtree`, and `gps2asp` itself are set to `ignore_missing_imports = true`.

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

## 4. Branch Conventions

Branch names observed in this repository follow a `type/short-description` pattern:

| Type prefix | Purpose |
|---|---|
| `fix/` | Bug fixes (e.g., `fix/suspension-is-suspended-before-load`) |
| `release/` | Release candidates (e.g., `release/v3.1.0-rc.6`) |
| `docs/` | Documentation-only changes (e.g., `docs/v3.0.1`) |
| `feat/` | New features |

The default and production branch is `main`.

Commit messages follow **Conventional Commits** format:

```
type(scope): short description
```

Examples from recent history:

```
fix(codeql): suppress lgtm warnings, remove dead code, simplify elif chain
fix(mypy): resolve custom_components/asp_parking type errors
fix(ci): manifest key order, mypy type errors, repair issue test setup
test: skip build-dep tests when geopandas not installed
ci: bump hacs/action to @main and hassfest to @master
```

Common types: `fix`, `feat`, `test`, `ci`, `docs`, `refactor`.

---

## 5. PR Process

No formal PR template exists in `.github/PULL_REQUEST_TEMPLATE.md`. Based on CI enforcement and project conventions, follow these guidelines:

- **Pass CI before requesting review.** The `pytest + lint` workflow runs `ruff check`, `ruff format --check`, `mypy` (both targets), and `pytest` (offline tests only) on every push. A failing CI run blocks merge.
- **Do not mix concerns.** Keep linting fixes, logic changes, and documentation updates in separate commits or PRs when possible.
- **Mark network-dependent tests correctly.** Tests that hit the NYC Open Data SODA API must be decorated with `@pytest.mark.integration`. Tests that require `pytest-homeassistant-custom-component` must be decorated with `@pytest.mark.ha_integration`. CI skips only the `integration` marker; `ha_integration` tests run in CI. To skip both locally, use `-m "not integration and not ha_integration"`.
- **Update `mypy` targets for new modules.** If you add a new module under `src/gps2asp/` or `custom_components/asp_parking/`, verify it passes `mypy` before submitting.
- **Spatial index changes.** If `scripts/build_index.py` changes, note in the PR description that existing locally-built indexes may need to be rebuilt.
