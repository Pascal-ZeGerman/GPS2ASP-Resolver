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

from gps2asp.resolver.exceptions import IndexNotFoundError, NoSegmentFoundError
from gps2asp.resolver.models import SegmentCandidate


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
    _lock: ClassVar[asyncio.Lock | None] = None  # lazily created to avoid pre-loop init

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
                first call; subsequent calls with the same path (or with
                ``index_dir=None``) return the existing instance. Calling
                with a DIFFERENT path raises ``ValueError`` to surface stale
                singleton bugs after an index rebuild (BUG-R-008). Call
                ``SpatialIndex.reset()`` first to load from a new path.

        Returns:
            The loaded SpatialIndex singleton.

        Raises:
            IndexNotFoundError: If the index files are not found on disk.
            ValueError: If ``index_dir`` is provided and differs from the
                already-loaded ``_index_dir`` (BUG-R-008).
        """
        if cls._instance is not None:
            if index_dir is not None and Path(index_dir) != cls._instance._index_dir:
                raise ValueError(
                    f"SpatialIndex already loaded from "
                    f"{cls._instance._index_dir}; cannot reload with "
                    f"{Path(index_dir)} — call SpatialIndex.reset() first "
                    f"(BUG-R-008)"
                )
            return cls._instance
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        async with cls._lock:
            if cls._instance is None:
                instance = cls(index_dir=index_dir)
                await instance._load()
                cls._instance = instance
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Clear the singleton instance (for testing).

        Must only be called when no coroutines are concurrently awaiting get().
        The lock is preserved intentionally — resetting it would allow concurrent
        get() calls to race past the double-checked load guard.
        """
        if cls._instance is not None and cls._instance._index is not None:
            cls._instance._index.close()
        cls._instance = None
        # _lock is intentionally NOT reset — see docstring.

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
        n: int = 25,
        max_distance_ft: float = 164.0,
    ) -> list[SegmentCandidate]:
        """Find the nearest street segments to a point.

        Queries the R-tree for the n bounding-box-nearest segments, computes
        actual Euclidean (geometry) distances, filters by max_distance, and
        returns SegmentCandidate objects sorted by geometry distance.

        Args:
            x: State Plane X coordinate (US survey feet).
            y: State Plane Y coordinate (US survey feet).
            n: Number of bounding-box-nearest candidates to oversample
                (default 25; BUG-R-005). ``rtree.nearest`` returns
                bbox-nearest, NOT geometry-nearest. Long diagonal segments
                (e.g. Broadway) have large bounding boxes that include the
                query point's bbox at small n, while the actually-nearest
                short orthogonal segment is missed. Oversampling to 25 lets
                the post-sort by geometry distance return the true nearest.
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
                        center_offset_c=float(
                            seg_data.get("center_offset_c", 0.0) or 0.0
                        ),
                        curb_width_ft=(
                            float(seg_data["curb_width_ft"])
                            if seg_data.get("curb_width_ft") is not None
                            else None
                        ),
                        spread_n=(
                            float(seg_data["spread_n"])
                            if seg_data.get("spread_n") is not None
                            else None
                        ),
                        spread_s=(
                            float(seg_data["spread_s"])
                            if seg_data.get("spread_s") is not None
                            else None
                        ),
                        calibrated=bool(seg_data.get("calibrated", False)),
                    )
                )

        results.sort(key=lambda c: c.distance_ft)

        if not results:
            raise NoSegmentFoundError(x, y, max_distance_ft)

        return results

    def query_radius(
        self,
        x: float,
        y: float,
        radius_ft: float,
    ) -> list[SegmentCandidate]:
        """Return every segment whose centerline is within radius_ft of (x, y).

        Args:
            x: State Plane X coordinate (US survey feet).
            y: State Plane Y coordinate (US survey feet).
            radius_ft: Inclusive upper bound on centerline distance, in feet.

        Returns:
            List of SegmentCandidate objects sorted by distance (closest first).
            Empty list if no segments are within the radius. Unlike nearest(),
            this method does NOT raise on empty result.

        Raises:
            RuntimeError: If the index has not been loaded yet.
        """
        if self._index is None or self._segments is None:
            raise RuntimeError(
                "SpatialIndex not loaded. Call await SpatialIndex.get() first."
            )

        # Query R-tree for candidates intersecting the radius bounding box
        candidate_ids = self._index.intersection(
            (x - radius_ft, y - radius_ft, x + radius_ft, y + radius_ft)
        )
        point = Point(x, y)

        results: list[SegmentCandidate] = []
        for seg_id in candidate_ids:
            seg_key = str(seg_id)
            if seg_key not in self._segments:
                continue

            seg_data = self._segments[seg_key]
            geometry = wkt.loads(seg_data["geometry_wkt"])
            distance_ft = point.distance(geometry)

            if distance_ft <= radius_ft:
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
                        center_offset_c=float(
                            seg_data.get("center_offset_c", 0.0) or 0.0
                        ),
                        curb_width_ft=(
                            float(seg_data["curb_width_ft"])
                            if seg_data.get("curb_width_ft") is not None
                            else None
                        ),
                        spread_n=(
                            float(seg_data["spread_n"])
                            if seg_data.get("spread_n") is not None
                            else None
                        ),
                        spread_s=(
                            float(seg_data["spread_s"])
                            if seg_data.get("spread_s") is not None
                            else None
                        ),
                        calibrated=bool(seg_data.get("calibrated", False)),
                    )
                )

        results.sort(key=lambda c: c.distance_ft)

        return results

    def get_segment_geometry_wkt(self, segment_id: object) -> str | None:
        """Return the raw ``geometry_wkt`` for one segment id, or ``None``.

        Reuses the already-loaded ``_segments`` metadata (the same dict
        ``nearest()``/``query_radius()`` read) instead of re-parsing
        segments.json. Callers that already resolved a point through this
        singleton (e.g. dataset dumpers deriving a matched segment's display
        geometry) get the lookup for free rather than paying a second,
        independent full parse of the multi-megabyte index file.

        Args:
            segment_id: A segment id as returned on ``SegmentCandidate.segment_id``
                (int or str; looked up via ``str(segment_id)``, matching the
                string keys segments.json is loaded into).

        Returns:
            The segment's ``geometry_wkt``, or ``None`` if unloaded or not found.
        """
        if self._segments is None:
            return None
        seg_data = self._segments.get(str(segment_id))
        return seg_data.get("geometry_wkt") if seg_data else None
