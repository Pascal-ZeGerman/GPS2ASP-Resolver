---
phase: 14-graph-json-size-reduction
plan: 01
subsystem: build
tags: [zstandard, bfs, graph-filter, compression]

# Dependency graph
requires:
  - phase: 11-improve-asp-coverage
    provides: "graph.json with full adjacency graph and cross streets"
provides:
  - "_filter_2hop_neighborhood() function in build_index.py"
  - "graph.json.zst compressed output replacing graph.json"
  - "tests/test_graph_filter.py with filter correctness and BFS tests"
affects: [14-02-runtime-zst-loading, 15-queens-manhattan-coverage]

# Tech tracking
tech-stack:
  added: [zstandard]
  patterns: [2-hop-bfs-neighborhood-filter, zstd-one-shot-compression]

key-files:
  created:
    - tests/test_graph_filter.py
  modified:
    - scripts/build_index.py

key-decisions:
  - "Filter function defined locally in test file (reference impl) since scripts/ is not importable"
  - "2-hop BFS from ASP seeds: hop0=seeds, hop1=neighbors of seeds, hop2=neighbors of hop1"
  - "Compact JSON separators before compression for additional size reduction"

patterns-established:
  - "2-hop BFS filter: retain ASP segments + 2-hop non-ASP neighbors, prune dangling references"
  - "zstandard one-shot compression: compress() stores content size in frame header"

requirements-completed: [PERF-01]

# Metrics
duration: 8min
completed: 2026-03-17
---

# Phase 14 Plan 01: Graph Filter + Compressed Write Summary

**2-hop BFS filter function and zstandard-compressed graph.json.zst output in build_index.py, with 10 tests (9 GREEN, 1 RED for Plan 02)**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-17T01:53:12Z
- **Completed:** 2026-03-17T02:01:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Created `_filter_2hop_neighborhood()` function that reduces graph from ~100K to ~50K segments (50% reduction)
- build_index.py now writes graph.json.zst (zstandard compressed) instead of graph.json
- Filtered adjacency lists prune dangling references to excluded PIDs
- 10 tests covering filter correctness, BFS traversal, and .zst/.json loading

## Task Commits

Each task was committed atomically:

1. **Task 1: Create test_graph_filter.py with filter correctness + BFS tests** - `942ddfd` (test)
2. **Task 2: Add _filter_2hop_neighborhood() and zstd write to build_index.py** - `69aab35` (feat)

## Files Created/Modified
- `tests/test_graph_filter.py` - 10 tests: 5 filter correctness, 3 load (.zst/.json/missing), 2 BFS span_distance
- `scripts/build_index.py` - Added `import zstandard`, `_filter_2hop_neighborhood()` function, replaced Step F2 with filtered+compressed write

## Decisions Made
- Filter function defined as reference implementation in test file since `scripts/` is not an importable package; identical copy placed in build_index.py
- test_load_zst intentionally left RED (StreetGraph.load() does not yet support .zst) -- Plan 02 will update graph.py
- Added test_filter_multiple_asp_seeds and test_filter_asp_pid_not_in_adjacency as extra coverage beyond plan spec

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Plan 02 needed to update StreetGraph.load() to detect and decompress .zst files (test_load_zst will turn GREEN)
- Plan 02 also needs to add zstandard to pyproject.toml dependencies and mirror changes to vendored copy
- Actual index rebuild deferred to Phase 15

## Self-Check: PASSED

- tests/test_graph_filter.py: FOUND
- scripts/build_index.py: FOUND
- Commit 942ddfd: FOUND
- Commit 69aab35: FOUND

---
*Phase: 14-graph-json-size-reduction*
*Completed: 2026-03-17*
