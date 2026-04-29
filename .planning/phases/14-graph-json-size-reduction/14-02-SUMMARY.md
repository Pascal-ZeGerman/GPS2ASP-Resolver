---
phase: 14-graph-json-size-reduction
plan: 02
subsystem: infra
tags: [zstandard, compression, graph, decompression, streaming]

# Dependency graph
requires:
  - phase: 14-01
    provides: "graph.json.zst compressed file output from build_index.py"
provides:
  - "StreetGraph.load() with zstandard decompression and .json fallback"
  - "zstandard runtime dependency in pyproject.toml and manifest.json"
affects: [15-queens-manhattan-coverage-fix]

# Tech tracking
tech-stack:
  added: [zstandard>=0.21.0]
  patterns: [streaming decompression via ZstdDecompressor.stream_reader()]

key-files:
  created: []
  modified:
    - src/gps2asp/signs/graph.py
    - custom_components/asp_parking/gps2asp/signs/graph.py
    - pyproject.toml
    - custom_components/asp_parking/manifest.json

key-decisions:
  - "zstandard stream_reader with TextIOWrapper for memory-efficient decompression of graph.json.zst"

patterns-established:
  - "Compressed data loading: try .zst first, fall back to plain .json for dev convenience"

requirements-completed: [PERF-01]

# Metrics
duration: 5min
completed: 2026-03-17
---

# Phase 14 Plan 02: Runtime .zst Decompression Summary

**StreetGraph.load() reads graph.json.zst via zstandard streaming decompression with plain .json fallback for local dev**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-17T02:06:11Z
- **Completed:** 2026-03-17T02:11:22Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- StreetGraph.load() detects and decompresses graph.json.zst using zstandard stream_reader
- Falls back to plain graph.json when .zst is absent (local dev without rebuild)
- Returns None when neither file exists (existing behavior preserved)
- zstandard>=0.21.0 added to pyproject.toml (main + build) and manifest.json
- Vendored graph.py byte-identical to src copy

## Task Commits

Each task was committed atomically:

1. **Task 1: Update StreetGraph.load() for .zst support + add dependencies** - `827a52e` (feat)
2. **Task 2: Mirror graph.py changes to vendored HA copy** - `75dc07a` (chore)

## Files Created/Modified
- `src/gps2asp/signs/graph.py` - Added import io, zstandard; replaced load() with .zst-first, .json-fallback logic
- `custom_components/asp_parking/gps2asp/signs/graph.py` - Vendored mirror (byte-identical)
- `pyproject.toml` - Added zstandard>=0.21.0 to dependencies and build optional-dependencies
- `custom_components/asp_parking/manifest.json` - Added zstandard>=0.21.0 to HA requirements

## Decisions Made
None - followed plan as specified.

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 14 complete: graph.json is filtered (Plan 01) and compressed (Plan 01 build-time, Plan 02 runtime)
- Ready for Phase 15 (Queens and Manhattan Coverage Fix) when needed
- Next spatial index rebuild will produce a filtered, compressed graph.json.zst

---
*Phase: 14-graph-json-size-reduction*
*Completed: 2026-03-17*
