"""R-tree spatial index for nearest-segment queries.

Loads a pre-built R-tree index (.idx/.dat files) and segment metadata from disk,
providing sub-millisecond nearest-neighbor queries against ~160K+ NYC street
segments. The index is loaded lazily on first use and kept as a singleton
in memory for subsequent calls.

The index must be built first using the build script (Plan 02). It consists of:
- segments.idx + segments.dat: R-tree index files (libspatialindex format)
- segments.json: Segment attribute data (geometry WKT, names, metadata)
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, ClassVar

from rtree import index as rtree_index
from shapely import wkt
from shapely.geometry import Point

from .exceptions import IndexNotFoundError, NoSegmentFoundError
from .models import SegmentCandidate


class SpatialIndex:
    """Lazy-loaded singleton spatial index for nearest-segment queries.

    Usage:
        idx = await SpatialIndex.get()
        candidates = idx.nearest(x, y)

    The index directory can be configured via:
    1. Constructor argument: SpatialIndex(index_dir="/path/to/index")
    2. Environment variable: GPS2ASP_INDEX_DIR
    3. Default: src/gps2asp/data/index/ relative to package
    """

    _instance: ClassVar[SpatialIndex | None] = None  # singleton; cleared by reset()
    _lock: ClassVar[asyncio.Lock] = asyncio.Lock()

    # Instance vars — assigned in __init__ and _load()
    _index: rtree_index.Index | None
    _segments: dict[str, Any] | None
    _index_dir: Path

    def __init__(self, index_dir: str | None = None) -> None:
        self._index = None
        self._segments = None

        if index_dir is not None:
            self._index_dir = Path(index_dir)
        elif env_dir := os.environ.get("GPS2ASP_INDEX_DIR"):
            self._index_dir = Path(env_dir)
        else:
            # Default: data/index/ relative to the gps2asp package
            package_dir = Path(__file__).parent.parent
            self._index_dir = package_dir / "data" / "index"

    @classmethod
    async def get(cls, index_dir: str | None = None) -> SpatialIndex:
        """Get the singleton SpatialIndex instance, loading on first call.

        Args:
            index_dir: Optional path to the index directory. Only used on
                first call; subsequent calls return the existing instance.

        Returns:
            The loaded SpatialIndex singleton.

        Raises:
            IndexNotFoundError: If the index files are not found on disk.
        """
        if cls._instance is not None:
            return cls._instance
        async with cls._lock:
            if cls._instance is None:
                instance = cls(index_dir=index_dir)
                await instance._load()
                cls._instance = instance
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Clear the singleton instance (for testing).

        After reset, the next call to get() will create and load a fresh instance.
        """
        if cls._instance is not None and cls._instance._index is not None:
            cls._instance._index.close()
        cls._instance = None

    async def _load(self) -> None:
        """Load the R-tree index and segment metadata from disk.

        Raises:
            IndexNotFoundError: If index files (.idx, .dat) or segment
                metadata (segments.json) are not found.
        """
        index_path = self._index_dir / "segments"
        idx_file = self._index_dir / "segments.idx"
        dat_file = self._index_dir / "segments.dat"
        meta_file = self._index_dir / "segments.json"

        # Load blocking I/O off the event loop (required for Home Assistant)
        def blocking_load() -> tuple[rtree_index.Index, dict]:
            if not (idx_file.exists() and dat_file.exists() and meta_file.exists()):
                raise IndexNotFoundError(str(self._index_dir))
            idx = rtree_index.Index(str(index_path))
            with open(meta_file) as f:
                segments = json.load(f)
            return idx, segments

        self._index, self._segments = await asyncio.to_thread(blocking_load)

    def nearest(
        self,
        x: float,
        y: float,
        n: int = 5,
        max_distance_ft: float = 164.0,
    ) -> list[SegmentCandidate]:
        """Find the nearest street segments to a point.

        Queries the R-tree for the n nearest segments, computes actual
        Euclidean distances, filters by max_distance, and returns sorted
        SegmentCandidate objects.

        Args:
            x: State Plane X coordinate (US survey feet).
            y: State Plane Y coordinate (US survey feet).
            n: Number of nearest candidates to consider (default 5).
            max_distance_ft: Maximum snap distance in feet (default 164 = ~50m).

        Returns:
            List of SegmentCandidate objects sorted by distance (closest first).

        Raises:
            NoSegmentFoundError: If no segments are within max_distance_ft.
        """
        if self._index is None or self._segments is None:
            raise RuntimeError(
                "SpatialIndex not loaded. Call await SpatialIndex.get() first."
            )

        # Query R-tree for nearest candidates by bounding box
        candidate_ids = list(self._index.nearest((x, y, x, y), n))
        point = Point(x, y)

        results: list[SegmentCandidate] = []
        for seg_id in candidate_ids:
            seg_key = str(seg_id)
            if seg_key not in self._segments:
                continue

            seg_data = self._segments[seg_key]
            geometry = wkt.loads(seg_data["geometry_wkt"])
            distance_ft = point.distance(geometry)

            if distance_ft <= max_distance_ft:
                results.append(
                    SegmentCandidate(
                        segment_id=seg_id,
                        geometry=geometry,
                        full_street_name=seg_data.get("full_street_name", ""),
                        from_street=seg_data.get("from_street", ""),
                        to_street=seg_data.get("to_street", ""),
                        trafdir=seg_data.get("trafdir", ""),
                        nominaldir=seg_data.get("nominaldir", ""),
                        rw_type=int(seg_data.get("rw_type", 0)),
                        streetwidth=float(seg_data.get("streetwidth", 30.0)),
                        borocode=seg_data.get("borocode", ""),
                        has_asp_left=bool(seg_data.get("has_asp_left", False)),
                        has_asp_right=bool(seg_data.get("has_asp_right", False)),
                        distance_ft=distance_ft,
                    )
                )

        results.sort(key=lambda c: c.distance_ft)

        if not results:
            raise NoSegmentFoundError(x, y, max_distance_ft)

        return results
