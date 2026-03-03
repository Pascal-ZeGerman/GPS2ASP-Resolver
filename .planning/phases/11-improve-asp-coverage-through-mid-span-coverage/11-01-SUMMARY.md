---
phase: 11-improve-asp-coverage-through-mid-span-coverage
plan: 01
subsystem: build
tags: [bfs, graph, adjacency, spatial-index, asp-coverage, build_index]

# Dependency graph
requires:
  - phase: 09-rebuild-the-spatial-index
    provides: build_index.py with _build_node_lookup and node_lookup pattern

provides:
  - _build_street_adjacency: coordinate-based same-street segment adjacency graph with 3x3 tolerance
  - _build_intersection_index: (on_street, cross_street) -> set[pid] lookup for BFS endpoints
  - _bfs_between: BFS traversal from start to end segments with max_depth limit; returns empty set if unreachable
  - _propagate_asp_to_interior_blocks: expands asp_lookup with interior block tuples via BFS; returns expanded set + stats
  - build_index() pipeline integration: graph construction + BFS propagation between ASP fetch and R-tree build
  - graph.json output: adjacency, segment_streets, segment_cross_streets for all segments with adjacency

affects:
  - 11-02-sign-retrieval-level4 (uses graph.json for StreetGraph runtime loading)
  - 11-03-index-rebuild (validates coverage improvement after pipeline changes)

# Tech tracking
tech-stack:
  added: ["collections.deque (stdlib BFS queue)"]
  patterns:
    - "Build-time BFS propagation: expand asp_lookup before R-tree is built so interior blocks get has_asp=True"
    - "Node lookup reuse: _build_node_lookup() called once in build_index(), passed to both _compute_cross_streets() and _build_street_adjacency()"
    - "graph.json: separate file for adjacency data (not embedded in segments.json) — clean separation, lazy-loadable at runtime"
    - "BFS safety: max_depth=30 prevents runaway on long avenues; discard traversal if end_pids never reached"

key-files:
  created: []
  modified:
    - scripts/build_index.py
    - tests/test_build_index.py

key-decisions:
  - "_compute_cross_streets() refactored to accept optional node_lookup parameter — callers can pass pre-built lookup to avoid double computation"
  - "graph.json written for ALL segments with adjacency (not just ASP segments) — ensures Level 4 can navigate between any adjacent blocks"
  - "BFS discards traversal if end_pids never reached (Pitfall 4: prevents false-positive has_asp flags)"
  - "3x3 neighborhood tolerance in _build_street_adjacency matches existing _find_cross_street() pattern for consistency"
  - "propagation_stats added to build_info.json for observability (spans_processed, spans_resolved, interior_blocks_added)"

patterns-established:
  - "TDD RED-GREEN for new graph functions: tests committed before implementation"
  - "Synthetic fixtures in tests (not real CSCL data) for fast, deterministic graph traversal tests"

requirements-completed: [MIDSPAN-BUILD]

# Metrics
duration: 25min
completed: 2026-03-03
---

# Phase 11 Plan 01: Build-Time Graph Construction and BFS Propagation Summary

**Coordinate-based street adjacency graph with BFS propagation expands asp_lookup with interior block tuples before R-tree build, fixing the multi-block SODA span coverage gap at build time**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-03-03T13:00:00Z
- **Completed:** 2026-03-03T13:25:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added four new functions to `scripts/build_index.py`: `_build_street_adjacency`, `_build_intersection_index`, `_bfs_between`, `_propagate_asp_to_interior_blocks`
- Wired graph construction into `build_index()` pipeline between ASP sign fetch and R-tree build
- `graph.json` written alongside `segments.json` with adjacency, segment_streets, and segment_cross_streets
- `propagation_stats` (spans_processed, spans_resolved, interior_blocks_added) logged and saved to `build_info.json`
- 17 new tests in `test_build_index.py` covering all four functions with synthetic fixtures; 27 total passing

## Task Commits

Each task was committed atomically:

1. **TDD RED — Task 1: Failing tests for graph functions** - `39089ae` (test)
2. **TDD GREEN — Task 1: Graph construction + BFS functions** - `a25f955` (feat)
3. **Task 2: Wire graph into pipeline + graph.json output** - `d696616` (feat)

_Note: TDD tasks have test commit before implementation commit_

## Files Created/Modified

- `/home/pascal/Vibe-Coding/VW-CarNet/GSP2ASP-Resolver/scripts/build_index.py` — Added `_build_street_adjacency`, `_build_intersection_index`, `_bfs_between`, `_propagate_asp_to_interior_blocks`; refactored `_compute_cross_streets` to accept optional `node_lookup`; wired pipeline in `build_index()` with graph.json output and propagation_stats in build_info.json
- `/home/pascal/Vibe-Coding/VW-CarNet/GSP2ASP-Resolver/tests/test_build_index.py` — Added `TestBuildStreetAdjacency` (4 tests), `TestBuildIntersectionIndex` (4 tests), `TestBfsBetween` (5 tests), `TestPropagateAspToInteriorBlocks` (3 tests), `TestGraphJson` (1 test); updated imports

## Decisions Made

- `_compute_cross_streets()` refactored to accept optional `node_lookup` to avoid computing it twice (once for cross streets, once for adjacency graph). Caller passes the result of `_build_node_lookup()` directly.
- `graph.json` written for all segments with adjacency (not filtered to ASP-only), so Level 4 runtime can navigate between any adjacent blocks when scoring spans.
- BFS discards traversal if `end_pids` never reached — prevents false-positive `has_asp` flags (Pitfall 4 from RESEARCH.md).
- `max_depth=30` for BFS to prevent runaway on long avenues like Broadway.
- `3x3` neighborhood tolerance in `_build_street_adjacency` matches the existing `_find_cross_street()` tolerance pattern for consistency.

## Deviations from Plan

None — plan executed exactly as written. All four functions implemented with TDD, pipeline wired as specified, graph.json written, propagation_stats added to build_info.json.

## Issues Encountered

None. The 6 pre-existing `test_sign_retrieval.py` failures (socket-blocked integration tests) were confirmed as pre-existing before our changes via `git stash` verification.

## User Setup Required

None — no external service configuration required. The spatial index must be rebuilt (`python scripts/build_index.py`) to generate `graph.json` and propagate interior block ASP flags.

## Next Phase Readiness

- `graph.json` output format matches spec in RESEARCH.md — ready for Phase 11-02 StreetGraph runtime loader
- `_propagate_asp_to_interior_blocks` expands `asp_lookup` before R-tree build — `has_asp_left/right` flags will be correct for interior blocks after index rebuild
- Phase 11-02 (Level 4 sign retrieval fallback) already has commits in the branch (StreetGraph class implemented)
- Phase 11-03 (index rebuild and validation) is the final step to measure coverage improvement

---
*Phase: 11-improve-asp-coverage-through-mid-span-coverage*
*Completed: 2026-03-03*
