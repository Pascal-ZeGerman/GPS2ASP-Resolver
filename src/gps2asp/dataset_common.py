"""Shared constants for the offline dataset dumper scripts.

``build_coverage_dataset.py`` and ``build_demo_dataset.py`` are both
presentation-layer snapshot dumpers that reproject EPSG:2263 geometry to
WGS84 and label CSCL borough codes. This module is the single source for
that shared, non-resolver-logic plumbing so the two dumpers never drift.
"""

from __future__ import annotations

from pyproj import Transformer

# Reverse of resolver/converter.py's forward transform: EPSG:2263 -> WGS84.
# always_xy=True yields (lon, lat) — exactly GeoJSON coordinate order.
TO_WGS84 = Transformer.from_crs("EPSG:2263", "EPSG:4326", always_xy=True)

# CSCL borough code -> human name (mirrors coordinator._BOROUGH_NAMES).
BOROUGH_NAMES: dict[str, str] = {
    "1": "Manhattan",
    "2": "Bronx",
    "3": "Brooklyn",
    "4": "Queens",
    "5": "Staten Island",
}


def borough_name(borocode: str | None) -> str | None:
    """Map a CSCL borough code to its human name, or None when unknown."""
    if borocode is None:
        return None
    return BOROUGH_NAMES.get(str(borocode))
