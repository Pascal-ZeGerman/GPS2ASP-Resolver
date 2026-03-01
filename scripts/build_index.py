"""Build the spatial index from NYC CSCL centerline data.

Downloads the NYC Street Centerline (CSCL) data from NYC Open Data via
the SODA GeoJSON API, filters to vehicular streets, pre-computes cross
streets and has_asp flags, and builds a persistent R-tree index for
sub-millisecond nearest-neighbor queries at runtime.

Usage:
    python scripts/build_index.py
    python scripts/build_index.py --output-dir /path/to/index

Produces:
    - segments.idx + segments.dat  (R-tree index files)
    - segments.json                (segment metadata with cross streets and has_asp)
    - build_info.json              (build metadata and statistics)
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import sys
import time
from collections import Counter
from pathlib import Path

import geopandas as gpd
import requests
from pyproj import Transformer
from rtree import index as rtree_index
from shapely.geometry import MultiLineString, shape

logger = logging.getLogger("gps2asp.build")

# NYC Open Data SODA GeoJSON endpoint for the Centerline dataset.
# Dataset inkn-q76z is the actual data table (3mf9-qshr is just the map view).
CSCL_GEOJSON_URL = (
    "https://data.cityofnewyork.us/resource/inkn-q76z.geojson"
)
# Metadata URL uses the map view identifier (works for rowsUpdatedAt).
CSCL_METADATA_URL = "https://data.cityofnewyork.us/api/views/3mf9-qshr.json"

PARKING_SIGNS_SODA_URL = (
    "https://data.cityofnewyork.us/resource/nfid-uabd.json"
)

# Vehicular road types to include
VEHICULAR_RW_TYPES = {1, 2, 3, 4, 5}

# SODA API batch sizes for pagination
CSCL_BATCH_SIZE = 10000
SIGNS_BATCH_SIZE = 50000

# WGS84 to EPSG:2263 transformer for reprojecting GeoJSON (which arrives in WGS84)
_transformer = Transformer.from_crs("EPSG:4326", "EPSG:2263", always_xy=True)

# Street name abbreviation expansions.
# The CSCL centerline uses abbreviations (AVE, ST, PL) while the parking
# signs dataset uses full names (AVENUE, STREET, PLACE). We expand centerline
# abbreviations to match the parking signs format for ASP matching.
_STREET_TYPE_EXPANSIONS = {
    " AVE": " AVENUE",
    " ST": " STREET",
    " PL": " PLACE",
    " BLVD": " BOULEVARD",
    " DR": " DRIVE",
    " CT": " COURT",
    " RD": " ROAD",
    " LN": " LANE",
    " TER": " TERRACE",
    " PKWY": " PARKWAY",
    " EXPY": " EXPRESSWAY",
    " HWY": " HIGHWAY",
    " SQ": " SQUARE",
    " CIR": " CIRCLE",
}


def _normalize_street_name(name: str) -> str:
    """Normalize a street name by expanding abbreviations.

    Converts centerline-style abbreviations (AVE, ST, PL) to full names
    (AVENUE, STREET, PLACE) to match the parking signs dataset format.

    Args:
        name: Street name from the centerline dataset (uppercase).

    Returns:
        Normalized street name with expanded abbreviations.
    """
    name = name.upper().strip()
    for abbrev, full in _STREET_TYPE_EXPANSIONS.items():
        if name.endswith(abbrev):
            name = name[: -len(abbrev)] + full
            break
    return name


def _setup_logging() -> None:
    """Configure build logging to stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _get_headers() -> dict:
    """Return request headers, including app token if available."""
    headers = {}
    app_token = os.environ.get("NYC_OPEN_DATA_APP_TOKEN")
    if app_token:
        headers["X-App-Token"] = app_token
    return headers


def _download_cscl_geojson() -> gpd.GeoDataFrame:
    """Download CSCL data via SODA GeoJSON API with pagination.

    The SODA API returns GeoJSON in WGS84. We paginate through all records
    (the dataset has ~122K segments) and combine into a single GeoDataFrame.

    Returns:
        GeoDataFrame with all CSCL segments in WGS84.
    """
    logger.info("Downloading CSCL data via SODA GeoJSON API...")
    headers = _get_headers()

    all_features: list[dict] = []
    offset = 0

    while True:
        params = {
            "$limit": str(CSCL_BATCH_SIZE),
            "$offset": str(offset),
            "$order": "physicalid",
        }

        response = requests.get(
            CSCL_GEOJSON_URL,
            params=params,
            headers=headers,
            timeout=120,
        )
        response.raise_for_status()

        data = response.json()
        features = data.get("features", [])

        # Filter out features with no geometry or no properties
        valid = [
            f for f in features
            if f.get("geometry") is not None and f.get("properties")
        ]
        all_features.extend(valid)

        logger.info(
            "Downloaded %d features (offset=%d, valid=%d, total so far=%d)",
            len(features), offset, len(valid), len(all_features),
        )

        if len(features) < CSCL_BATCH_SIZE:
            break

        offset += CSCL_BATCH_SIZE

    logger.info("Total features downloaded: %d", len(all_features))

    # Build GeoDataFrame from features
    geojson = {"type": "FeatureCollection", "features": all_features}
    gdf = gpd.GeoDataFrame.from_features(geojson, crs="EPSG:4326")

    return gdf


def _filter_and_reproject(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Filter to vehicular streets and reproject to EPSG:2263.

    Args:
        gdf: Raw GeoDataFrame from the SODA API (WGS84).

    Returns:
        Filtered GeoDataFrame in EPSG:2263 (NY State Plane, US survey feet).
    """
    total_count = len(gdf)
    logger.info("Loaded %d total segments", total_count)

    # Normalize column names to lowercase
    gdf.columns = [c.lower() for c in gdf.columns]

    # Convert rw_type to int (may come as string from JSON)
    gdf["rw_type_int"] = gdf["rw_type"].apply(
        lambda x: int(x) if x is not None and str(x).strip().isdigit() else 0
    )

    # Filter to vehicular streets
    gdf = gdf[gdf["rw_type_int"].isin(VEHICULAR_RW_TYPES)].copy()
    gdf = gdf[gdf["trafdir"] != "NV"].copy()

    # Drop rows with null geometry
    gdf = gdf[gdf.geometry.notna()].copy()

    # Convert MultiLineString to LineString where possible (single-part lines)
    def _to_linestring(geom):
        if geom is None:
            return None
        if geom.geom_type == "MultiLineString" and len(geom.geoms) == 1:
            return geom.geoms[0]
        if geom.geom_type == "MultiLineString":
            # Merge multi-part into single line by concatenating coords
            from shapely.ops import linemerge
            merged = linemerge(geom)
            return merged
        return geom

    gdf["geometry"] = gdf.geometry.apply(_to_linestring)
    gdf = gdf[gdf.geometry.notna()].copy()

    # Reproject to EPSG:2263 (NY State Plane)
    logger.info("Reprojecting to EPSG:2263 (NY State Plane)...")
    gdf = gdf.to_crs(epsg=2263)

    filtered_count = len(gdf)
    logger.info(
        "Filtered to %d vehicular segments (from %d total, %.1f%% retained)",
        filtered_count, total_count, 100 * filtered_count / total_count,
    )

    return gdf


def _build_node_lookup(
    gdf: gpd.GeoDataFrame,
) -> dict[tuple[float, float], list[tuple[int, str]]]:
    """Build a spatial lookup from node coordinates to segment info.

    For each segment, extracts the first and last coordinate (from_node
    and to_node) and maps them to (physicalid, street_name) pairs. Rounds
    coordinates to whole feet to handle slight misalignments.

    Args:
        gdf: Filtered GeoDataFrame of street segments.

    Returns:
        Dict mapping rounded (x, y) to list of (physicalid, street_name).
    """
    node_lookup: dict[tuple[float, float], list[tuple[int, str]]] = {}

    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None:
            continue

        try:
            coords = list(geom.coords)
        except NotImplementedError:
            # MultiLineString that could not be merged -- skip
            continue

        if len(coords) < 2:
            continue

        pid = int(row["physicalid"])
        name = str(row.get("full_street_name", ""))

        # Round to nearest foot for tolerance-based matching
        from_node = (round(coords[0][0]), round(coords[0][1]))
        to_node = (round(coords[-1][0]), round(coords[-1][1]))

        for node in (from_node, to_node):
            if node not in node_lookup:
                node_lookup[node] = []
            node_lookup[node].append((pid, name))

    return node_lookup


def _find_cross_street(
    node: tuple[float, float],
    own_pid: int,
    own_name: str,
    node_lookup: dict[tuple[float, float], list[tuple[int, str]]],
) -> str:
    """Find the cross street name at a node.

    Searches the node lookup for segments at this node that have a
    different name from the current segment. If multiple cross streets
    exist, picks the most common one.

    Args:
        node: Rounded (x, y) coordinates of the node.
        own_pid: Physical ID of the current segment.
        own_name: Street name of the current segment.
        node_lookup: The node-to-segments lookup.

    Returns:
        Cross street name, or "DEAD END" if no cross street found.
    """
    # Check a small neighborhood around the rounded node for tolerance
    candidates: list[tuple[int, str]] = []
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            check_node = (node[0] + dx, node[1] + dy)
            if check_node in node_lookup:
                candidates.extend(node_lookup[check_node])

    # Filter out the current segment and segments with the same name
    own_name_upper = own_name.upper().strip()
    cross_streets: list[str] = []
    for pid, name in candidates:
        if pid == own_pid:
            continue
        name_upper = name.upper().strip()
        if name_upper and name_upper != own_name_upper:
            cross_streets.append(name_upper)

    if not cross_streets:
        return "DEAD END"

    # Pick the most common cross street name
    counts = Counter(cross_streets)
    return counts.most_common(1)[0][0]


def _compute_cross_streets(
    gdf: gpd.GeoDataFrame,
) -> dict[int, tuple[str, str]]:
    """Pre-compute from_street and to_street cross streets for each segment.

    Args:
        gdf: Filtered GeoDataFrame of street segments.

    Returns:
        Dict mapping physicalid to (from_street, to_street).
    """
    logger.info("Building node lookup for cross-street computation...")
    node_lookup = _build_node_lookup(gdf)
    logger.info("Node lookup built with %d unique nodes", len(node_lookup))

    logger.info("Computing cross streets for each segment...")
    cross_streets: dict[int, tuple[str, str]] = {}
    count = 0

    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None:
            continue

        try:
            coords = list(geom.coords)
        except NotImplementedError:
            continue

        if len(coords) < 2:
            continue

        pid = int(row["physicalid"])
        name = str(row.get("full_street_name", ""))

        from_node = (round(coords[0][0]), round(coords[0][1]))
        to_node = (round(coords[-1][0]), round(coords[-1][1]))

        from_street = _find_cross_street(from_node, pid, name, node_lookup)
        to_street = _find_cross_street(to_node, pid, name, node_lookup)

        cross_streets[pid] = (from_street, to_street)
        count += 1

    logger.info("Computed cross streets for %d segments", count)
    dead_end_count = sum(
        1 for fs, ts in cross_streets.values()
        if fs == "DEAD END" or ts == "DEAD END"
    )
    logger.info(
        "Dead ends: %d segments have at least one dead-end node",
        dead_end_count,
    )

    return cross_streets


def _fetch_asp_signs() -> set[tuple[str, str, str, str]]:
    """Fetch ASP sign locations from the Parking Signs SODA API.

    Queries for all current SANITATION BROOM signs and returns a set of
    (on_street, from_street, to_street, side) tuples that have ASP signs.

    Returns:
        Set of (on_street, from_street, to_street, side_of_street) tuples.
    """
    logger.info("Fetching ASP sign locations from Parking Signs API...")
    headers = _get_headers()

    asp_tuples: set[tuple[str, str, str, str]] = set()
    offset = 0

    while True:
        params = {
            "$where": (
                "sign_description LIKE '%SANITATION BROOM%'"
                " AND record_type='Current'"
            ),
            "$select": "on_street,from_street,to_street,side_of_street",
            "$group": "on_street,from_street,to_street,side_of_street",
            "$limit": str(SIGNS_BATCH_SIZE),
            "$offset": str(offset),
        }

        try:
            response = requests.get(
                PARKING_SIGNS_SODA_URL,
                params=params,
                headers=headers,
                timeout=120,
            )
            response.raise_for_status()
        except requests.RequestException as e:
            logger.warning(
                "Failed to fetch ASP signs (offset=%d): %s", offset, e,
            )
            logger.warning(
                "Continuing without ASP data -- has_asp will default to False"
            )
            break

        records = response.json()
        if not records:
            break

        for record in records:
            on_street = (record.get("on_street") or "").upper().strip()
            from_street = (record.get("from_street") or "").upper().strip()
            to_street = (record.get("to_street") or "").upper().strip()
            side = (record.get("side_of_street") or "").upper().strip()

            if on_street and side:
                asp_tuples.add((on_street, from_street, to_street, side))

        logger.info(
            "Fetched %d ASP records (offset=%d, batch=%d)",
            len(records), offset, SIGNS_BATCH_SIZE,
        )

        if len(records) < SIGNS_BATCH_SIZE:
            break

        offset += SIGNS_BATCH_SIZE

    logger.info("Total unique ASP block-face tuples: %d", len(asp_tuples))
    return asp_tuples


def _check_has_asp(
    street_name: str,
    from_street: str,
    to_street: str,
    asp_lookup: set[tuple[str, str, str, str]],
) -> tuple[bool, bool]:
    """Check if a segment has ASP signs on left and/or right side.

    Normalizes street names (expanding abbreviations) and checks both
    (street, from, to) and (street, to, from) orderings since the sign
    data might have a different from/to direction than the centerline.

    Args:
        street_name: The segment's street name (from centerline, may be abbreviated).
        from_street: Cross street at from-node (may be abbreviated).
        to_street: Cross street at to-node (may be abbreviated).
        asp_lookup: Set of (on_street, from_street, to_street, side) tuples
            from the parking signs dataset (uses full names).

    Returns:
        (has_asp_left, has_asp_right) booleans.
    """
    # Normalize centerline names to match parking signs format
    name = _normalize_street_name(street_name)
    fs = _normalize_street_name(from_street)
    ts = _normalize_street_name(to_street)

    has_left = False
    has_right = False

    # Check both orderings of from/to for each compass side
    for side_char in ("N", "S", "E", "W"):
        key1 = (name, fs, ts, side_char)
        key2 = (name, ts, fs, side_char)
        if key1 in asp_lookup or key2 in asp_lookup:
            # Flag both sides if any ASP sign exists for the segment.
            # We cannot reliably map compass-side to left/right without
            # knowing segment orientation, so we conservatively flag both.
            has_left = True
            has_right = True
            break

    return has_left, has_right


def _build_rtree_and_metadata(
    gdf: gpd.GeoDataFrame,
    cross_streets: dict[int, tuple[str, str]],
    asp_lookup: set[tuple[str, str, str, str]],
    output_dir: Path,
) -> dict:
    """Build the R-tree index and save segment metadata.

    CRITICAL: Uses index.insert() in a loop, NOT stream/generator loading
    (produces empty files per rtree bug #159).

    Args:
        gdf: Filtered GeoDataFrame of street segments in EPSG:2263.
        cross_streets: Pre-computed cross streets mapping.
        asp_lookup: ASP sign tuples for has_asp flagging.
        output_dir: Directory to write index files.

    Returns:
        Build statistics dict.
    """
    logger.info("Building R-tree index...")
    output_dir.mkdir(parents=True, exist_ok=True)

    index_path = str(output_dir / "segments")

    # Create R-tree with disk persistence
    p = rtree_index.Property()
    p.overwrite = True
    idx = rtree_index.Index(index_path, properties=p)

    segments: dict[str, dict] = {}
    asp_count = 0
    insert_count = 0
    skipped = 0

    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None:
            skipped += 1
            continue

        pid = int(row["physicalid"])
        bbox = geom.bounds  # (minx, miny, maxx, maxy)

        # Insert into R-tree (MUST use insert loop, not generator)
        idx.insert(pid, bbox)
        insert_count += 1

        full_street_name = str(row.get("full_street_name", ""))

        # Cross streets
        from_street, to_street = cross_streets.get(pid, ("", ""))

        # ASP flags
        has_asp_left, has_asp_right = _check_has_asp(
            full_street_name, from_street, to_street, asp_lookup,
        )
        if has_asp_left or has_asp_right:
            asp_count += 1

        # Get streetwidth safely (handle None, NaN, and non-numeric from CSCL source)
        # Store 0.0 for missing/corrupt values — confidence.py applies rw_type fallback
        # at runtime via _NYC_DEFAULT_WIDTHS (per CONTEXT.md: fallback logic lives there)
        sw_raw = row.get("streetwidth", None)
        try:
            sw = float(sw_raw) if sw_raw is not None else None
            if sw is None or math.isnan(sw) or sw <= 0:
                streetwidth = 0.0
            else:
                streetwidth = sw
        except (ValueError, TypeError):
            streetwidth = 0.0

        # Build segment metadata
        segments[str(pid)] = {
            "geometry_wkt": geom.wkt,
            "full_street_name": full_street_name,
            "from_street": from_street,
            "to_street": to_street,
            "trafdir": str(row.get("trafdir", "")),
            "nominaldir": str(row.get("nominaldir", "") or ""),
            "rw_type": int(row.get("rw_type_int", row.get("rw_type", 0))),
            "streetwidth": streetwidth,
            "borocode": str(row.get("boroughcode", row.get("borocode", ""))),
            "has_asp_left": has_asp_left,
            "has_asp_right": has_asp_right,
        }

    # Flush and close the R-tree index to ensure files are written
    idx.close()
    logger.info(
        "R-tree index built with %d segments (skipped %d)",
        insert_count, skipped,
    )

    # Save segment metadata as JSON
    meta_path = output_dir / "segments.json"
    logger.info("Saving segment metadata to %s...", meta_path)
    with open(meta_path, "w") as f:
        json.dump(segments, f)

    meta_size = meta_path.stat().st_size / (1024 * 1024)
    logger.info("Segment metadata: %.1f MB", meta_size)

    # Check index file sizes
    idx_size = (output_dir / "segments.idx").stat().st_size
    dat_size = (output_dir / "segments.dat").stat().st_size
    logger.info(
        "R-tree files: segments.idx=%.1f MB, segments.dat=%.1f MB",
        idx_size / (1024 * 1024), dat_size / (1024 * 1024),
    )

    return {
        "filtered_count": insert_count,
        "asp_segments_count": asp_count,
        "index_file_sizes": {
            "segments.idx": idx_size,
            "segments.dat": dat_size,
            "segments.json": int(meta_size * 1024 * 1024),
        },
    }


async def build_index(output_dir: Path | None = None) -> None:
    """Build the spatial index from NYC CSCL data.

    Downloads CSCL data via the SODA GeoJSON API, filters to vehicular
    streets, pre-computes cross streets and ASP flags, builds the R-tree
    index, and saves all metadata.

    Args:
        output_dir: Output directory for index files. Defaults to
            src/gps2asp/data/index/ relative to this package.
    """
    _setup_logging()

    if output_dir is None:
        package_dir = Path(__file__).parent.parent
        output_dir = package_dir / "data" / "index"

    logger.info("Building spatial index -> %s", output_dir)
    start_time = time.time()

    # Step A + B: Download and filter CSCL data
    gdf_raw = _download_cscl_geojson()
    total_cscl_rows = len(gdf_raw)
    gdf = _filter_and_reproject(gdf_raw)

    # Step C: Pre-compute cross streets
    cross_streets = _compute_cross_streets(gdf)

    # Step D: Fetch ASP signs and pre-compute has_asp
    asp_lookup = _fetch_asp_signs()

    # Step E + F: Build R-tree and save metadata
    stats = _build_rtree_and_metadata(
        gdf, cross_streets, asp_lookup, output_dir,
    )

    # Step G: Save build metadata
    elapsed = time.time() - start_time
    build_info = {
        "build_timestamp": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
        ),
        "cscl_row_count": total_cscl_rows,
        "filtered_count": stats["filtered_count"],
        "asp_segments_count": stats["asp_segments_count"],
        "index_file_sizes": stats["index_file_sizes"],
        "build_duration_seconds": round(elapsed, 1),
    }

    build_info_path = output_dir / "build_info.json"
    with open(build_info_path, "w") as f:
        json.dump(build_info, f, indent=2)

    logger.info("Build complete in %.1f seconds", elapsed)
    logger.info(
        "Segments: %d, ASP segments: %d",
        stats["filtered_count"], stats["asp_segments_count"],
    )
    logger.info("Build info saved to %s", build_info_path)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Build GPS2ASP spatial index from NYC CSCL data",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "Output directory for index files "
            "(default: src/gps2asp/data/index/)"
        ),
    )
    args = parser.parse_args()

    asyncio.run(build_index(output_dir=args.output_dir))
