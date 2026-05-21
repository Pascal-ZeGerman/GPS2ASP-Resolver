"""Street adjacency graph for Level 4 mid-span sign retrieval.

Loads the graph.json produced by the build_index.py script and provides
graph-distance scoring to identify the best-covering SODA span for
mid-span blocks (blocks whose CSCL cross streets don't match any SODA
record's cross streets verbatim).
"""

from __future__ import annotations

import collections
import io
import json
import logging
from pathlib import Path

import zstandard

from .normalize import normalize_to_soda

logger = logging.getLogger("gps2asp.signs")

# BFS depth limit -- prevents runaway search on very long avenues.
_BFS_DEPTH_LIMIT = 30


def _default_index_dir() -> Path:
    """Return the default index directory (same as segments.json)."""
    return Path(__file__).parent.parent / "data" / "index"


class StreetGraph:
    """Street adjacency graph loaded from graph.json.

    Attributes:
        adjacency: Maps segment PID string -> list of adjacent PID ints.
        segment_streets: Maps segment PID string -> on-street name (SODA format).
        segment_cross_streets: Maps segment PID string -> list of cross-street names
            (SODA format).
    """

    _instance: StreetGraph | None = None

    def __init__(
        self,
        adjacency: dict[str, list[int]],
        segment_streets: dict[str, str],
        segment_cross_streets: dict[str, list[str]],
    ) -> None:
        self.adjacency = adjacency
        self.segment_streets = segment_streets
        self.segment_cross_streets = segment_cross_streets

    @classmethod
    def load(cls, index_dir: Path | None = None) -> StreetGraph | None:
        """Load StreetGraph from graph.json.zst (or graph.json fallback).

        Tries graph.json.zst first (zstandard compressed). Falls back to
        plain graph.json for local development without a rebuild.

        Args:
            index_dir: Directory containing graph file. Defaults to
                src/gps2asp/data/index/.

        Returns:
            StreetGraph instance, or None if no graph file exists.
        """
        if index_dir is None:
            index_dir = _default_index_dir()

        zst_path = index_dir / "graph.json.zst"
        json_path = index_dir / "graph.json"

        # BUG-S-004: Wrap decode in try/except so a corrupt graph.json(.zst)
        # degrades to "Level 4 unavailable" (same contract as the file-missing
        # path) instead of raising and being swallowed by the coordinator's
        # broad `except Exception`. Catches both json.JSONDecodeError and
        # zstandard.ZstdError; OSError is included for read-time disk errors.
        try:
            if zst_path.exists():
                dctx = zstandard.ZstdDecompressor()
                with zst_path.open("rb") as fh:
                    with dctx.stream_reader(fh) as reader:
                        data = json.load(io.TextIOWrapper(reader, encoding="utf-8"))
            elif json_path.exists():
                with json_path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
            else:
                logger.debug(
                    "No graph file found at %s -- Level 4 unavailable",
                    index_dir,
                )
                return None
        except (json.JSONDecodeError, zstandard.ZstdError, OSError) as exc:
            logger.error(
                "graph.json corrupt or unreadable at %s (%s: %s); "
                "Level 4 disabled until next rebuild",
                index_dir,
                type(exc).__name__,
                exc,
            )
            return None

        adjacency: dict[str, list[int]] = data.get("adjacency", {})
        raw_streets: dict[str, str] = data.get("segment_streets", {})
        raw_cross: dict[str, list[str]] = data.get("segment_cross_streets", {})

        # Normalize all street names to SODA format at load time.
        segment_streets = {
            pid: normalize_to_soda(name) for pid, name in raw_streets.items()
        }
        segment_cross_streets = {
            pid: [normalize_to_soda(cs) for cs in cross_list]
            for pid, cross_list in raw_cross.items()
        }

        logger.debug(
            "Loaded graph: %d segments, %d adjacency entries",
            len(segment_streets),
            len(adjacency),
        )
        return cls(
            adjacency=adjacency,
            segment_streets=segment_streets,
            segment_cross_streets=segment_cross_streets,
        )

    @classmethod
    def get(cls) -> StreetGraph | None:
        """Return the singleton StreetGraph, lazy-loading on first call.

        Returns:
            StreetGraph instance, or None if graph.json is absent.
        """
        if cls._instance is None:
            cls._instance = cls.load()
        return cls._instance

    def _pids_with_cross_street(self, cross_street: str) -> set[str]:
        """Return all segment PIDs whose cross_streets include the given street."""
        normalized = normalize_to_soda(cross_street)
        return {
            pid
            for pid, cross_list in self.segment_cross_streets.items()
            if normalized in cross_list
        }

    def _bfs_min_hops(self, start_pids: set[str], target_pids: set[str]) -> int | float:
        """BFS from any start PID to any target PID, returning minimum hop count.

        Args:
            start_pids: Set of source segment PIDs.
            target_pids: Set of destination segment PIDs.

        Returns:
            Minimum number of hops, or float('inf') if unreachable within depth limit.
        """
        if not start_pids or not target_pids:
            return float("inf")

        # Check immediate overlap (0 hops)
        if start_pids & target_pids:
            return 0

        visited: set[str] = set(start_pids)
        queue: collections.deque[tuple[str, int]] = collections.deque()
        for pid in start_pids:
            queue.append((pid, 0))

        while queue:
            pid, depth = queue.popleft()
            if depth >= _BFS_DEPTH_LIMIT:
                continue

            for neighbor_int in self.adjacency.get(pid, []):
                neighbor = str(neighbor_int)
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                if neighbor in target_pids:
                    return depth + 1
                queue.append((neighbor, depth + 1))

        return float("inf")

    def span_distance(
        self,
        block_from: str,
        block_to: str,
        span_from: str,
        span_to: str,
    ) -> int | float:
        """Compute graph-distance between a block and a SODA span.

        The distance measures how far the span's endpoints are from the
        block's endpoints in terms of adjacency hops in the street graph.
        A lower score means the span covers our block more tightly.

        Tries both orderings (span_from, span_to) and (span_to, span_from)
        and returns the minimum, since SODA may store segments in either
        direction.

        Args:
            block_from: from_street of our block (CSCL or SODA format).
            block_to: to_street of our block.
            span_from: from_street of the SODA span record.
            span_to: to_street of the SODA span record.

        Returns:
            Integer hop count, or float('inf') if span is unreachable.
        """
        block_from_pids = self._pids_with_cross_street(block_from)
        block_to_pids = self._pids_with_cross_street(block_to)
        span_from_pids = self._pids_with_cross_street(span_from)
        span_to_pids = self._pids_with_cross_street(span_to)

        # Forward ordering: span_from -> block_from, span_to -> block_to
        d_from_fwd = self._bfs_min_hops(block_from_pids, span_from_pids)
        d_to_fwd = self._bfs_min_hops(block_to_pids, span_to_pids)
        fwd_total: int | float = (
            float("inf")
            if d_from_fwd == float("inf") or d_to_fwd == float("inf")
            else d_from_fwd + d_to_fwd
        )

        # Reverse ordering: span_to -> block_from, span_from -> block_to
        d_from_rev = self._bfs_min_hops(block_from_pids, span_to_pids)
        d_to_rev = self._bfs_min_hops(block_to_pids, span_from_pids)
        rev_total: int | float = (
            float("inf")
            if d_from_rev == float("inf") or d_to_rev == float("inf")
            else d_from_rev + d_to_rev
        )

        return min(fwd_total, rev_total)


def _find_best_covering_span(
    records: list[dict],
    from_street: str,
    to_street: str,
    graph: StreetGraph,
) -> list[dict] | None:
    """Find the SODA span whose endpoints are closest to our block.

    Groups records by (from_street, to_street) span key, scores each
    group via graph.span_distance(), and returns the records from the
    lowest-scoring (tightest-covering) span.

    Args:
        records: Raw SODA records (all on same on_street + side).
        from_street: Our block's from_street for distance scoring.
        to_street: Our block's to_street for distance scoring.
        graph: StreetGraph instance for BFS scoring.

    Returns:
        List of records for the best span, or None if all spans are
        unreachable (all distances == inf).
    """
    # Group records by span key
    groups: dict[tuple[str, str], list[dict]] = {}
    for record in records:
        key = (
            record.get("from_street", "").strip().upper(),
            record.get("to_street", "").strip().upper(),
        )
        groups.setdefault(key, []).append(record)

    best_distance: int | float = float("inf")
    best_records: list[dict] | None = None

    for (span_from, span_to), group_records in groups.items():
        dist = graph.span_distance(from_street, to_street, span_from, span_to)
        logger.debug(
            "Level 4: span (%r, %r) distance=%s",
            span_from,
            span_to,
            dist,
        )
        if dist < best_distance:
            best_distance = dist
            best_records = group_records

    if best_distance == float("inf"):
        return None

    return best_records
