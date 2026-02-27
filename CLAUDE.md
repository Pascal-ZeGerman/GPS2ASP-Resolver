# GPS2ASP Resolver

Python tool that converts GPS coordinates to NYC ASP (Alternate Side Parking) schedules via a linear pipeline:
GPS → State Plane → street segment/side → SODA API signs → parsed schedule → next move time → HA sensor

## Project Structure

- `src/gps2asp/` — main package
  - `resolver/` — GPS-to-street resolution (Phase 1, complete)
  - `build/` — offline build scripts (CSCL download, R-tree index)
- `tests/` — pytest tests
- `.planning/` — GSD workflow (roadmap, phases, plans)

## Development

- Python >=3.11, build system: hatchling
- Virtual env: `.venv/`
- Run tests: `pytest` (asyncio_mode = auto)
- Install dev: `pip install -e ".[dev]"`
- Install build tools: `pip install -e ".[build]"`

### pip / venv convention

Always use `python -m pip` (not `.venv/bin/pip`) when the venv was created in a
directory path that may have been renamed or moved. The `.venv/bin/pip` wrapper
script embeds an absolute shebang that becomes stale after a directory rename.

After any project directory rename, regenerate `.pth` and wrapper scripts:

```bash
python -m pip install -e ".[dev]"
```

This ensures `.venv/lib/pythonX.Y/site-packages/_gps2asp.pth` and
`.venv/bin/pip*` shebangs all point to the current path.

## Conventions

- Data models: frozen dataclasses (`@dataclass(frozen=True)`)
- Type hints throughout, `from __future__ import annotations`
- Each pipeline stage is a standalone library (no HA dependency until Phase 4)
- NYC Open Data SODA API is the external data source for sign data
- Borough codes: 1=Manhattan, 2=Bronx, 3=Brooklyn, 4=Queens, 5=Staten Island
- Street names use CSCL format (e.g., "PROSPECT PLACE", "VANDERBILT AVENUE")
