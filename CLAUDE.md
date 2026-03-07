# GPS2ASP Resolver

Python tool that converts GPS coordinates to NYC ASP (Alternate Side Parking) schedules via a linear pipeline:
GPS → State Plane → street segment/side → SODA API signs → parsed schedule → next move time → HA sensor

## Project Structure

- `src/gps2asp/` — main package
  - `resolver/` — GPS-to-street resolution (Phase 1, complete)
- `scripts/` — offline build scripts at project root (CSCL download, R-tree index)
- `tests/` — pytest tests
- `.planning/` — GSD workflow (roadmap, phases, plans)

## Development

- Python >=3.11, build system: hatchling
- Virtual env: `.venv/` — always use `.venv/bin/python` and `.venv/bin/pytest` (system Python is externally managed)
- Run tests: `.venv/bin/pytest` (asyncio_mode = auto)
- Install dev: `.venv/bin/python -m pip install -e ".[dev]"`
- Install build tools: `.venv/bin/python -m pip install -e ".[build]"`

## Conventions

- Data models: frozen dataclasses (`@dataclass(frozen=True)`)
- Type hints throughout, `from __future__ import annotations`
- Each pipeline stage is a standalone library (no HA dependency until Phase 4)
- NYC Open Data SODA API is the external data source for sign data
- Borough codes: 1=Manhattan, 2=Bronx, 3=Brooklyn, 4=Queens, 5=Staten Island
- Street names use CSCL format (e.g., "PROSPECT PLACE", "VANDERBILT AVENUE")
