"""Shared constants for the offline dataset dumper scripts.

``build_coverage_dataset.py`` and ``build_demo_dataset.py`` are both
presentation-layer snapshot dumpers that reproject EPSG:2263 geometry to
WGS84 and label CSCL borough codes. This module is the single source for
that shared, non-resolver-logic plumbing so the two dumpers never drift.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path
from typing import TypeVar

from pyproj import Transformer

from gps2asp.dataset_labels import (
    BOROUGH_NAMES,
    SIDE_LABELS,
    borough_name,
    cleaning_day_names,
)
from gps2asp.resolver.spatial_index import SpatialIndex

__all__ = [
    "BOROUGH_NAMES",
    "SIDE_LABELS",
    "TO_WGS84",
    "bounded_gather",
    "borough_name",
    "cleaning_day_names",
    "load_segment_records_with_raw_count",
]

_T = TypeVar("_T")
_R = TypeVar("_R")

# Reverse of resolver/converter.py's forward transform: EPSG:2263 -> WGS84.
# always_xy=True yields (lon, lat) — exactly GeoJSON coordinate order.
TO_WGS84 = Transformer.from_crs("EPSG:2263", "EPSG:4326", always_xy=True)


def _default_segments_path() -> Path:
    """Default ``segments.json`` location, honoring ``GPS2ASP_INDEX_DIR``.

    Reuses ``SpatialIndex.resolve_index_dir``'s own precedence (env var, then
    the package-bundled default) so this dumper never reads a different
    index than the live resolver path ``build_demo_dataset.py`` uses via
    ``SpatialIndex.get()``.
    """
    return SpatialIndex.resolve_index_dir() / "segments.json"


def _load_raw_segments(path: Path | None = None) -> dict:
    return json.loads((path or _default_segments_path()).read_text())


def load_segment_records_with_raw_count(
    path: Path | None = None,
) -> tuple[dict[str, dict], int]:
    """Load ``segments.json`` into a filtered record map, plus the pre-filter
    raw count, from a single parse of ``segments.json``.

    Filters to dict records carrying ``geometry_wkt`` — the only records
    either dumper can use (for a map midpoint/render or a schedule resolve).
    Callers that need both the filtered records and the raw count (e.g. a
    "never omit a segment" self-check) should use this rather than parsing
    the (multi-MB) index file twice.
    """
    raw = _load_raw_segments(path)
    filtered = {
        str(seg_id): rec
        for seg_id, rec in raw.items()
        if isinstance(rec, dict) and "geometry_wkt" in rec
    }
    return filtered, len(raw)


async def bounded_gather(
    items: Iterable[_T],
    worker: Callable[[_T], Awaitable[_R]],
    concurrency: int,
) -> list[_R]:
    """Run ``worker`` over every item concurrently, bounded by ``concurrency``.

    Both offline dataset dumpers need the same semaphore-bounded-gather
    idiom (each item is an independent I/O-bound resolve: one point resolve
    for the demo dumper, one SODA group fetch for the coverage dumper).
    Factored here so a future fix to the bounded-concurrency pattern (e.g.
    propagating the first exception, adding a timeout) doesn't have to be
    hand-ported between the two dumper scripts.

    Args:
        items: The items to process; result order matches ``items`` order.
        worker: Async callable applied to each item under the semaphore.
        concurrency: Maximum number of ``worker`` calls in flight at once.

    Returns:
        Results in the same order as ``items``.
    """
    semaphore = asyncio.Semaphore(concurrency)

    async def _bounded(item: _T) -> _R:
        async with semaphore:
            return await worker(item)

    return await asyncio.gather(*(_bounded(item) for item in items))
