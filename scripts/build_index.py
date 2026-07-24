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

import json
import logging
import math
import os
import statistics
import sys
import time
from collections import Counter, deque
from pathlib import Path

import geopandas as gpd
import requests
import zstandard
from rtree import index as rtree_index
from shapely.geometry import LineString, box
from shapely.ops import unary_union
from shapely.strtree import STRtree

from gps2asp.resolver.curb_calibration import (
    SegmentCalibration,
    derive_segment_calibration,
)
from gps2asp.resolver.side_resolver import signed_offset
from gps2asp.signs.normalize import normalize_to_soda

logger = logging.getLogger("gps2asp.build")

# NYC Open Data SODA GeoJSON endpoint for the Centerline dataset.
# Dataset inkn-q76z is the actual data table (3mf9-qshr is just the map view).
CSCL_GEOJSON_URL = "https://data.cityofnewyork.us/resource/inkn-q76z.geojson"
# Metadata URL uses the map view identifier (works for rowsUpdatedAt).
CSCL_METADATA_URL = "https://data.cityofnewyork.us/api/views/3mf9-qshr.json"

PARKING_SIGNS_SODA_URL = "https://data.cityofnewyork.us/resource/nfid-uabd.json"

# NYC planimetric curb + roadbed layers for per-segment side-of-street
# calibration (SC-1/SC-5). Both are BULK-downloaded ONCE at build time and
# processed offline -- never queried per-segment at runtime.
#
# Curbs live in the backing view 5xvt-8cbk (the public map view ikvd-dex8 has
# no queryable columns); .geojson (NOT .json) returns real geometry. Only
# feat_code 2250 rows are true curb lines. Roadbed i36f-5ih7 is a build-time
# cross-validator polygon layer (an independent second source): a segment whose
# curb-derived c disagrees with the roadbed-derived c beyond
# ROADBED_DISAGREEMENT_FT is downgraded to non-calibrated.
CURB_GEOJSON_URL = "https://data.cityofnewyork.us/resource/5xvt-8cbk.geojson"
ROADBED_GEOJSON_URL = "https://data.cityofnewyork.us/resource/i36f-5ih7.geojson"
CURB_FEAT_CODE = "2250"
ROADBED_DISAGREEMENT_FT = 4.0

# Vehicular road types to include
VEHICULAR_RW_TYPES = {1, 2, 3, 4, 5}

# SODA API batch sizes for pagination
CSCL_BATCH_SIZE = 10000
SIGNS_BATCH_SIZE = 50000

# Pagination batch size + hard page cap for the curb/roadbed GeoJSON downloads.
# The page cap bounds a runaway or adversarial endpoint (T-40-08-02 DoS) so the
# one-time bulk download cannot spin forever.
GEOJSON_PAGE_SIZE = 10000
MAX_GEOJSON_PAGES = 500

# Bbox padding (feet) when querying the roadbed STRtree for a segment's flanking
# pavement. ~260 m (spike 007 roadbed radius); the skill requires >=150 m so the
# block's (large, sparse) polygon is captured. NY State Plane is US survey feet.
ROADBED_QUERY_PAD_FT = 850.0


def _normalize_street_name(name: str) -> str:
    """Normalize a street name by expanding abbreviations and directional prefixes.

    Delegates to normalize_to_soda() for exact parity with the runtime
    normalization used in sign queries (CSCL abbreviated format ->
    SODA full-word format).

    Args:
        name: Street name from the centerline dataset.

    Returns:
        Normalized street name in SODA format.
    """
    return normalize_to_soda(name)


def _setup_logging() -> None:
    """Configure build logging to stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
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
            f for f in features if f.get("geometry") is not None and f.get("properties")
        ]
        all_features.extend(valid)

        logger.info(
            "Downloaded %d features (offset=%d, valid=%d, total so far=%d)",
            len(features),
            offset,
            len(valid),
            len(all_features),
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
        filtered_count,
        total_count,
        100 * filtered_count / total_count,
    )

    return gdf


def _paginate_geojson(
    url: str,
    page_size: int = GEOJSON_PAGE_SIZE,
    page_cap: int = MAX_GEOJSON_PAGES,
) -> list[dict]:
    """Bulk-download a SODA GeoJSON layer via $limit/$offset pagination.

    Mirrors _download_cscl_geojson's pagination (headers via _get_headers so an
    optional X-App-Token from the environment lifts throttling). The download is
    bounded by ``page_cap`` pages so a runaway/adversarial endpoint cannot spin
    forever (T-40-08-02).

    Args:
        url: The .geojson resource endpoint.
        page_size: Rows per page ($limit).
        page_cap: Maximum number of pages to fetch (hard bound).

    Returns:
        List of GeoJSON feature dicts with non-null geometry.
    """
    headers = _get_headers()
    all_features: list[dict] = []
    offset = 0

    for page in range(page_cap):
        params = {"$limit": str(page_size), "$offset": str(offset)}
        response = requests.get(url, params=params, headers=headers, timeout=120)
        response.raise_for_status()

        data = response.json()
        features = data.get("features", [])
        valid = [f for f in features if f.get("geometry") is not None]
        all_features.extend(valid)

        logger.info(
            "Downloaded %d features from %s (page=%d, offset=%d, total=%d)",
            len(features),
            url.rsplit("/", 1)[-1],
            page,
            offset,
            len(all_features),
        )

        if len(features) < page_size:
            break
        offset += page_size
    else:
        logger.warning(
            "Hit page cap (%d) downloading %s -- stopping pagination",
            page_cap,
            url,
        )

    return all_features


def _load_geojson_features(cache_path: Path) -> list[dict]:
    """Load GeoJSON features from a local cache file.

    Accepts either a FeatureCollection dict (``{"features": [...]}``) or a bare
    list of features. Used so an offline / re-runnable build can reuse a
    previously-downloaded layer instead of re-fetching hundreds of MB.
    """
    with open(cache_path) as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return data.get("features", [])


def _write_geojson_cache(cache_path: Path, features: list[dict]) -> None:
    """Persist downloaded features to a local cache for re-runnable builds."""
    cache_path = Path(cache_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)


def _features_to_gdf_2263(features: list[dict]) -> gpd.GeoDataFrame:
    """Build an EPSG:2263 GeoDataFrame from WGS84 GeoJSON features.

    SODA .geojson endpoints serve geometry in WGS84 regardless of the stored
    CRS, so we tag the frame EPSG:4326 and reproject to EPSG:2263 (mirror
    _filter_and_reproject), dropping null/empty geometry.
    """
    if not features:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:2263")
    gdf = gpd.GeoDataFrame.from_features(
        {"type": "FeatureCollection", "features": features},
        crs="EPSG:4326",
    )
    gdf = gdf[gdf.geometry.notna()].copy()
    gdf = gdf[~gdf.geometry.is_empty].copy()
    gdf = gdf.to_crs(epsg=2263)
    return gdf


def _download_curbs(cache_path: Path | None = None) -> gpd.GeoDataFrame:
    """Bulk-download the NYC curb layer (5xvt-8cbk), feat_code 2250, EPSG:2263.

    This is a ONE-TIME bulk download of the whole curb layer -- NOT a per-segment
    within_circle query (that pattern is fine for spikes but does not scale to a
    ~105k-segment build). If ``cache_path`` exists it is loaded instead of
    hitting the network; if it is provided but absent, the freshly-downloaded raw
    features are written to it so subsequent builds re-run without re-fetching.

    Args:
        cache_path: Optional local GeoJSON cache path.

    Returns:
        GeoDataFrame of curb LineStrings (feat_code 2250) in EPSG:2263.
    """
    if cache_path is not None and Path(cache_path).exists():
        logger.info("Loading curb layer from cache %s", cache_path)
        features = _load_geojson_features(Path(cache_path))
    else:
        logger.info("Bulk-downloading curb layer (dataset 5xvt-8cbk)...")
        features = _paginate_geojson(CURB_GEOJSON_URL)
        if cache_path is not None:
            _write_geojson_cache(Path(cache_path), features)

    # Keep only true curb lines (feat_code 2250); the layer also carries other
    # planimetric edge types.
    curb_features = [
        f
        for f in features
        if str((f.get("properties") or {}).get("feat_code")) == CURB_FEAT_CODE
    ]
    logger.info(
        "Curb layer: %d features, %d are curb lines (feat_code %s)",
        len(features),
        len(curb_features),
        CURB_FEAT_CODE,
    )
    return _features_to_gdf_2263(curb_features)


def _download_roadbed(cache_path: Path | None = None) -> gpd.GeoDataFrame:
    """Bulk-download the NYC roadbed polygon layer (i36f-5ih7), EPSG:2263.

    Build-time cross-validator only (never read at runtime). Same cache
    semantics as :func:`_download_curbs`.

    Returns:
        GeoDataFrame of roadbed polygons in EPSG:2263.
    """
    if cache_path is not None and Path(cache_path).exists():
        logger.info("Loading roadbed layer from cache %s", cache_path)
        features = _load_geojson_features(Path(cache_path))
    else:
        logger.info("Bulk-downloading roadbed layer (dataset i36f-5ih7)...")
        features = _paginate_geojson(ROADBED_GEOJSON_URL)
        if cache_path is not None:
            _write_geojson_cache(Path(cache_path), features)

    logger.info("Roadbed layer: %d polygon features", len(features))
    return _features_to_gdf_2263(features)


def _build_curb_strtree(
    curbs: gpd.GeoDataFrame,
) -> tuple[STRtree, list[LineString]]:
    """Build an STRtree of curb LineStrings for flanking-curb bbox queries.

    MultiLineStrings are exploded into their constituent LineStrings so each
    curb segment is independently query-able.

    Returns:
        (STRtree, lines) where lines[i] corresponds to STRtree query index i.
    """
    lines: list[LineString] = []
    for geom in curbs.geometry:
        if geom is None or geom.is_empty:
            continue
        if geom.geom_type == "MultiLineString":
            lines.extend(g for g in geom.geoms)
        elif geom.geom_type == "LineString":
            lines.append(geom)
    return STRtree(lines), lines


def _build_roadbed_strtree(
    roadbed: gpd.GeoDataFrame,
) -> tuple[STRtree, list]:
    """Build an STRtree of roadbed polygons for per-segment pavement queries.

    MultiPolygons are exploded into constituent Polygons.

    Returns:
        (STRtree, polys) where polys[i] corresponds to STRtree query index i.
    """
    polys: list = []
    for geom in roadbed.geometry:
        if geom is None or geom.is_empty:
            continue
        if geom.geom_type == "MultiPolygon":
            polys.extend(g for g in geom.geoms)
        elif geom.geom_type == "Polygon":
            polys.append(geom)
    return STRtree(polys), polys


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
        Cross street name, or '' (empty string) if no cross street found.
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
        return ""

    # Pick the most common cross street name
    counts = Counter(cross_streets)
    return counts.most_common(1)[0][0]


def _compute_cross_streets(
    gdf: gpd.GeoDataFrame,
    node_lookup: dict[tuple[float, float], list[tuple[int, str]]] | None = None,
) -> dict[int, tuple[str, str]]:
    """Pre-compute from_street and to_street cross streets for each segment.

    Args:
        gdf: Filtered GeoDataFrame of street segments.
        node_lookup: Pre-built node lookup dict. If None, builds one internally.
            Pass the result of _build_node_lookup() to avoid computing it twice
            when the caller also needs it for graph construction.

    Returns:
        Dict mapping physicalid to (from_street, to_street).
    """
    if node_lookup is None:
        logger.info("Building node lookup for cross-street computation...")
        node_lookup = _build_node_lookup(gdf)
        logger.info("Node lookup built with %d unique nodes", len(node_lookup))
    else:
        logger.info(
            "Using pre-built node lookup (%d unique nodes) for cross-street computation...",
            len(node_lookup),
        )

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
    dead_end_count = sum(1 for fs, ts in cross_streets.values() if fs == "" or ts == "")
    logger.info(
        "Dead ends: %d segments have at least one dead-end node",
        dead_end_count,
    )

    return cross_streets


def _build_street_adjacency(
    node_lookup: dict[tuple[float, float], list[tuple[int, str]]],
) -> dict[int, set[int]]:
    """Build a segment adjacency graph for same-street connectivity.

    Two segments are adjacent if they share a node coordinate (within a 3x3
    foot neighborhood) AND have the same normalized street name. This reuses
    the same coordinate-rounding and 3x3 tolerance pattern as
    _find_cross_street().

    Args:
        node_lookup: Dict mapping rounded (x, y) to list of (physicalid, street_name).

    Returns:
        Dict mapping physicalid to the set of adjacent physicalids (same street,
        shared node). Bidirectional.
    """
    adjacency: dict[int, set[int]] = {}

    # For each node, find all segments within the 3x3 neighborhood and group
    # by normalized street name. Connect all same-street segments at that node.
    processed_pairs: set[frozenset] = set()

    for node, segments in node_lookup.items():
        # Gather all segments within the 3x3 neighborhood
        neighborhood_segments: list[tuple[int, str]] = []
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                neighbor_node = (node[0] + dx, node[1] + dy)
                if neighbor_node in node_lookup:
                    neighborhood_segments.extend(node_lookup[neighbor_node])

        # Group by normalized street name
        by_street: dict[str, list[int]] = {}
        for pid, name in neighborhood_segments:
            normalized = _normalize_street_name(name)
            if normalized:
                by_street.setdefault(normalized, []).append(pid)

        # Connect all segments with the same street name
        for _street, pids in by_street.items():
            unique_pids = list(dict.fromkeys(pids))  # deduplicate, preserve order
            for i, pid_a in enumerate(unique_pids):
                for pid_b in unique_pids[i + 1 :]:
                    pair = frozenset((pid_a, pid_b))
                    if pair not in processed_pairs:
                        processed_pairs.add(pair)
                        adjacency.setdefault(pid_a, set()).add(pid_b)
                        adjacency.setdefault(pid_b, set()).add(pid_a)

    return adjacency


def _build_intersection_index(
    cross_streets: dict[int, tuple[str, str]],
    gdf_street_names: dict[int, str],
) -> dict[tuple[str, str], set[int]]:
    """Build a lookup from (on_street, cross_street) to segment PIDs.

    For each segment, maps both (on_street, from_street) and
    (on_street, to_street) to the segment's PID. All names are normalized
    via _normalize_street_name() for parity with SODA span endpoint names.

    This index is used by _propagate_asp_to_interior_blocks() to find the
    starting and ending segments for BFS traversal.

    Args:
        cross_streets: Dict mapping physicalid to (from_street, to_street).
        gdf_street_names: Dict mapping physicalid to full_street_name.

    Returns:
        Dict mapping (normalized_on_street, normalized_cross_street) to set of PIDs.
    """
    index: dict[tuple[str, str], set[int]] = {}

    for pid, (from_cs, to_cs) in cross_streets.items():
        on_street = _normalize_street_name(gdf_street_names.get(pid, ""))
        if not on_street:
            continue
        for cs in (from_cs, to_cs):
            cs_norm = _normalize_street_name(cs)
            if cs_norm:
                index.setdefault((on_street, cs_norm), set()).add(pid)

    return index


def _bfs_between(
    start_pids: set[int],
    end_pids: set[int],
    adjacency: dict[int, set[int]],
    max_depth: int = 30,
) -> set[int]:
    """BFS from start_pids toward end_pids using the adjacency graph.

    Traverses the street adjacency graph from ``start_pids`` toward
    ``end_pids``. Stops expanding past any endpoint segment (does not
    traverse *beyond* the span boundary). Respects ``max_depth`` to
    prevent runaway traversal on long avenues (e.g., Broadway).

    If BFS never reaches any ``end_pid``, the traversal is considered
    invalid and an empty set is returned (Pitfall 4: discard incomplete
    traversals to avoid overcounting ASP segments).

    Args:
        start_pids: Set of starting segment PIDs (span from-street intersections).
        end_pids: Set of ending segment PIDs (span to-street intersections).
        adjacency: Dict mapping physicalid to its adjacent physicalids.
        max_depth: Maximum BFS depth to prevent runaway on long streets.

    Returns:
        Set of all visited PIDs including start and end if reachable.
        Empty set if end_pids are never reached.
    """
    visited: set[int] = set()
    queue: deque[tuple[int, int]] = deque()  # (pid, depth)

    for pid in start_pids:
        if pid not in visited:
            visited.add(pid)
            queue.append((pid, 0))

    reached_end = any(pid in end_pids for pid in start_pids)

    while queue:
        current, depth = queue.popleft()
        if current in end_pids:
            reached_end = True
            continue  # reached endpoint, don't traverse beyond
        if depth >= max_depth:
            continue  # safety limit -- stop expanding, but keep visited
        for neighbor in adjacency.get(current, set()):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, depth + 1))

    if not reached_end:
        return set()

    return visited


def _propagate_asp_to_interior_blocks(
    asp_lookup: set[tuple[str, str, str, str]],
    adjacency: dict[int, set[int]],
    intersection_index: dict[tuple[str, str], set[int]],
    cross_streets: dict[int, tuple[str, str]],
    gdf_street_names: dict[int, str],
) -> tuple[set[tuple[str, str, str, str]], dict]:
    """Expand asp_lookup to include interior blocks of multi-block SODA spans.

    For each unique SODA span (on_street, from_street, to_street), performs
    BFS along the street adjacency graph from the from_street intersection to
    the to_street intersection. All interior segment PIDs found are added to
    asp_lookup with the same side(s) as the original span.

    This is the build-time fix for the mid-span coverage gap: SODA stores signs
    that span multiple CSCL blocks, but _check_has_asp() does exact matching.
    Interior blocks (e.g., 73rd-74th within a 72nd-86th SODA span) would
    otherwise get has_asp=False and never be queried at runtime.

    Args:
        asp_lookup: Current set of (on_street, from_street, to_street, side) tuples.
        adjacency: Street adjacency graph from _build_street_adjacency().
        intersection_index: Intersection lookup from _build_intersection_index().
        cross_streets: Dict mapping physicalid to (from_street, to_street).
        gdf_street_names: Dict mapping physicalid to full_street_name.

    Returns:
        Tuple of (expanded_asp_lookup, propagation_stats_dict) where:
        - expanded_asp_lookup includes all original tuples plus interior blocks
        - propagation_stats_dict has keys: spans_processed, spans_resolved,
          interior_blocks_added
    """
    # Collect unique (on_street, from_street, to_street) spans with their sides
    span_sides: dict[tuple[str, str, str], set[str]] = {}
    for on_street, from_street, to_street, side in asp_lookup:
        key = (on_street, from_street, to_street)
        span_sides.setdefault(key, set()).add(side)

    expanded = set(asp_lookup)
    spans_processed = 0
    spans_resolved = 0
    interior_blocks_added = 0

    for (on_street, from_street, to_street), sides in span_sides.items():
        spans_processed += 1

        # Look up starting segments at (on_street, from_street)
        start_pids = intersection_index.get((on_street, from_street), set())
        # Look up ending segments at (on_street, to_street)
        end_pids = intersection_index.get((on_street, to_street), set())

        if not start_pids or not end_pids:
            continue  # Cannot resolve span endpoints -- skip

        # BFS between the two endpoint sets
        visited = _bfs_between(start_pids, end_pids, adjacency)

        if not visited:
            continue  # BFS failed to reach endpoint -- discard

        spans_resolved += 1

        # Add interior block tuples to asp_lookup for all sides the span had
        for pid in visited:
            pid_from, pid_to = cross_streets.get(pid, ("", ""))
            pid_from_norm = _normalize_street_name(pid_from)
            pid_to_norm = _normalize_street_name(pid_to)

            if not pid_from_norm and not pid_to_norm:
                continue

            for side in sides:
                new_tuple = (on_street, pid_from_norm, pid_to_norm, side)
                if new_tuple not in expanded:
                    expanded.add(new_tuple)
                    interior_blocks_added += 1

    logger.info(
        "ASP propagation: %d spans processed, %d resolved, %d interior blocks added",
        spans_processed,
        spans_resolved,
        interior_blocks_added,
    )

    stats = {
        "spans_processed": spans_processed,
        "spans_resolved": spans_resolved,
        "interior_blocks_added": interior_blocks_added,
    }
    return expanded, stats


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
                " AND sign_design_voided_on_date IS NULL"
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
                "Failed to fetch ASP signs (offset=%d): %s",
                offset,
                e,
            )
            logger.warning(
                "Continuing without ASP data -- has_asp will default to False"
            )
            break

        records = response.json()
        if not records:
            break

        for record in records:
            # Normalize SODA street names through _normalize_street_name() to
            # match the format used in intersection_index and segments.json.
            # This handles both whitespace collapsing and SODA fixed-width
            # formatting (e.g., "EAST   22 STREET" -> "EAST   22 STREET").
            on_street = _normalize_street_name(record.get("on_street") or "")
            from_street = _normalize_street_name(record.get("from_street") or "")
            to_street = _normalize_street_name(record.get("to_street") or "")
            side = (record.get("side_of_street") or "").upper().strip()

            if on_street and side:
                asp_tuples.add((on_street, from_street, to_street, side))

        logger.info(
            "Fetched %d ASP records (offset=%d, batch=%d)",
            len(records),
            offset,
            SIGNS_BATCH_SIZE,
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


def _roadbed_center_offset(
    centerline: LineString,
    roadbed_tree: STRtree,
    roadbed_polys: list,
) -> float | None:
    """Independent roadbed-derived centre offset ``c`` (build-time cross-check).

    Ports spike 007's ``roadbed_c``: cast a perpendicular transect at each of 39
    interior samples along the centerline, clip it to the flanking pavement
    polygon, take the signed offset of each clipped mid-span, and return the
    median. This is a SECOND authoritative source, independent of the curb lines;
    the caller downgrades a segment whose curb ``c`` disagrees with this value by
    more than ``ROADBED_DISAGREEMENT_FT``.

    Args:
        centerline: CSCL segment centerline (EPSG:2263).
        roadbed_tree: STRtree of roadbed polygons.
        roadbed_polys: Polygon list aligned with ``roadbed_tree`` query indices.

    Returns:
        Median roadbed centre offset (feet, same sign convention as the curb
        ``c``), or ``None`` when the pavement is absent/too thin to trust.
    """
    minx, miny, maxx, maxy = centerline.bounds
    qbox = box(
        minx - ROADBED_QUERY_PAD_FT,
        miny - ROADBED_QUERY_PAD_FT,
        maxx + ROADBED_QUERY_PAD_FT,
        maxy + ROADBED_QUERY_PAD_FT,
    )
    idxs = roadbed_tree.query(qbox)
    polys = [roadbed_polys[i] for i in idxs]
    if not polys:
        return None

    pavement = unary_union(polys)
    length = centerline.length
    mids: list[float] = []
    for i in range(1, 40):
        frac = i / 40.0
        cp = centerline.interpolate(frac, normalized=True)
        a = centerline.interpolate(max(0.0, frac * length - 1.0))
        b = centerline.interpolate(min(length, frac * length + 1.0))
        tx, ty = b.x - a.x, b.y - a.y
        tn = math.hypot(tx, ty) or 1.0
        px, py = -ty / tn, tx / tn
        transect = LineString(
            [(cp.x - px * 80, cp.y - py * 80), (cp.x + px * 80, cp.y + py * 80)]
        )
        clip = transect.intersection(pavement)
        if clip.is_empty or clip.length < 8:
            continue
        mids.append(signed_offset(clip.centroid.x, clip.centroid.y, centerline))

    if len(mids) < 5:
        return None
    return round(statistics.median(mids), 2)


def _derive_segment_fields(
    geom: LineString,
    cscl_width_ft: float,
    curb_tree: STRtree,
    curb_lines: list[LineString],
    roadbed_tree: STRtree,
    roadbed_polys: list,
) -> SegmentCalibration:
    """Derive one segment's calibration, spread-gated and roadbed-cross-checked.

    1. Query the curb STRtree for lines within a bbox of ``max(160, width*4)`` ft
       around the segment.
    2. Derive ``c`` / width / spreads via :func:`derive_segment_calibration`
       (spread gate applied inside).
    3. For a calibrated result, compute an independent roadbed ``c`` and DOWNGRADE
       to non-calibrated when the two authoritative sources disagree by more than
       ``ROADBED_DISAGREEMENT_FT`` (the measured spreads are retained so the
       rejection reason stays inspectable).

    Returns:
        A :class:`SegmentCalibration` (calibrated flag drives the runtime fallback
        chain).
    """
    query_pad = max(160.0, cscl_width_ft * 4.0)
    minx, miny, maxx, maxy = geom.bounds
    qbox = box(minx - query_pad, miny - query_pad, maxx + query_pad, maxy + query_pad)
    flanking = [curb_lines[i] for i in curb_tree.query(qbox)]

    cal = derive_segment_calibration(geom, flanking, cscl_width_ft)
    if not cal.calibrated:
        return cal

    roadbed_c = _roadbed_center_offset(geom, roadbed_tree, roadbed_polys)
    if (
        roadbed_c is not None
        and abs(cal.center_offset_c - roadbed_c) > ROADBED_DISAGREEMENT_FT
    ):
        # Two authoritative sources disagree -> do not trust c. Downgrade to
        # non-calibrated (plain-CSCL fallback) but keep the measured spreads.
        return SegmentCalibration(
            center_offset_c=0.0,
            curb_width_ft=None,
            spread_n=cal.spread_n,
            spread_s=cal.spread_s,
            calibrated=False,
        )

    return cal


def _build_rtree_and_metadata(
    gdf: gpd.GeoDataFrame,
    cross_streets: dict[int, tuple[str, str]],
    asp_lookup: set[tuple[str, str, str, str]],
    output_dir: Path,
    *,
    curb_calibration_enabled: bool = False,
    curb_tree: STRtree | None = None,
    curb_lines: list[LineString] | None = None,
    roadbed_tree: STRtree | None = None,
    roadbed_polys: list | None = None,
) -> dict:
    """Build the R-tree index and save segment metadata.

    CRITICAL: Uses index.insert() in a loop, NOT stream/generator loading
    (produces empty files per rtree bug #159).

    Args:
        gdf: Filtered GeoDataFrame of street segments in EPSG:2263.
        cross_streets: Pre-computed cross streets mapping.
        asp_lookup: ASP sign tuples for has_asp flagging.
        output_dir: Directory to write index files.
        curb_calibration_enabled: When True (and the curb/roadbed trees are
            provided), derive per-segment calibration and write the five
            calibration keys with measured values; otherwise write the
            non-calibrated defaults.
        curb_tree: STRtree of curb LineStrings (flanking-curb bbox queries).
        curb_lines: Curb LineString list aligned with ``curb_tree`` indices.
        roadbed_tree: STRtree of roadbed polygons (build-time cross-validator).
        roadbed_polys: Roadbed polygon list aligned with ``roadbed_tree`` indices.

    Returns:
        Build statistics dict (includes calibrated_count / non_calibrated_count).
    """
    logger.info("Building R-tree index...")
    output_dir.mkdir(parents=True, exist_ok=True)

    calibrate = bool(
        curb_calibration_enabled
        and curb_tree is not None
        and curb_lines is not None
        and roadbed_tree is not None
        and roadbed_polys is not None
    )
    logger.info(
        "Per-segment curb calibration: %s", "ENABLED" if calibrate else "disabled"
    )

    index_path = str(output_dir / "segments")

    # Create R-tree with disk persistence
    p = rtree_index.Property()
    p.overwrite = True
    idx = rtree_index.Index(index_path, properties=p)

    segments: dict[str, dict] = {}
    asp_count = 0
    insert_count = 0
    skipped = 0
    calibrated_count = 0
    non_calibrated_count = 0

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
            full_street_name,
            from_street,
            to_street,
            asp_lookup,
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

        # Per-segment curb calibration (SC-1/SC-5). Derive c/width from flanking
        # curbs, spread-gated (40-05) and roadbed-cross-checked; fall back to the
        # non-calibrated defaults when disabled, geometry is missing, or the two
        # sources disagree. The five keys use the EXACT 40-04 name contract.
        if calibrate and geom.geom_type == "LineString":
            cal = _derive_segment_fields(
                geom,
                streetwidth if streetwidth > 0 else 30.0,
                curb_tree,
                curb_lines,
                roadbed_tree,
                roadbed_polys,
            )
        else:
            cal = SegmentCalibration(
                center_offset_c=0.0,
                curb_width_ft=None,
                spread_n=None,
                spread_s=None,
                calibrated=False,
            )
        if cal.calibrated:
            calibrated_count += 1
        else:
            non_calibrated_count += 1

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
            "center_offset_c": cal.center_offset_c,
            "curb_width_ft": cal.curb_width_ft,
            "spread_n": cal.spread_n,
            "spread_s": cal.spread_s,
            "calibrated": cal.calibrated,
        }

    # Flush and close the R-tree index to ensure files are written
    idx.close()
    logger.info(
        "R-tree index built with %d segments (skipped %d)",
        insert_count,
        skipped,
    )
    logger.info(
        "Curb calibration: %d calibrated, %d non-calibrated",
        calibrated_count,
        non_calibrated_count,
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
        idx_size / (1024 * 1024),
        dat_size / (1024 * 1024),
    )

    return {
        "filtered_count": insert_count,
        "asp_segments_count": asp_count,
        "calibrated_count": calibrated_count,
        "non_calibrated_count": non_calibrated_count,
        "index_file_sizes": {
            "segments.idx": idx_size,
            "segments.dat": dat_size,
            "segments.json": int(meta_size * 1024 * 1024),
        },
    }


def _filter_2hop_neighborhood(
    adjacency: dict[int, set[int]],
    asp_pids: set[int],
) -> set[int]:
    """Return PIDs reachable within 2 hops from any ASP segment."""
    retained: set[int] = set()
    seeds = asp_pids & set(adjacency.keys())
    retained.update(seeds)

    hop1_new: set[int] = set()
    for pid in seeds:
        for neighbor in adjacency.get(pid, set()):
            if neighbor not in retained:
                hop1_new.add(neighbor)
    retained.update(hop1_new)

    for pid in hop1_new:
        for neighbor in adjacency.get(pid, set()):
            retained.add(neighbor)

    return retained


def build_index(
    output_dir: Path | None = None,
    *,
    no_curb_calibration: bool = False,
    curb_cache: Path | None = None,
    roadbed_cache: Path | None = None,
) -> None:
    """Build the spatial index from NYC CSCL data.

    Downloads CSCL data via the SODA GeoJSON API, filters to vehicular
    streets, pre-computes cross streets and ASP flags, builds the R-tree
    index, and saves all metadata.

    When curb calibration is enabled (the default) the build ALSO bulk-downloads
    the NYC curb + roadbed planimetric layers ONCE, derives each segment's centre
    offset ``c`` / true width via :func:`derive_segment_calibration`, cross-checks
    ``c`` against the roadbed polygon, and writes the calibration fields into
    ``segments.json`` (SC-1/SC-5).

    Args:
        output_dir: Output directory for index files. Defaults to
            src/gps2asp/data/index/ relative to the project root.
        no_curb_calibration: When True, skip the curb/roadbed download and write
            the non-calibrated defaults for every segment (calibration-free
            index).
        curb_cache: Optional local GeoJSON cache for the curb layer.
        roadbed_cache: Optional local GeoJSON cache for the roadbed layer.
    """
    _setup_logging()

    if output_dir is None:
        output_dir = Path(__file__).parent.parent / "src" / "gps2asp" / "data" / "index"

    logger.info("Building spatial index -> %s", output_dir)
    start_time = time.time()

    # Step A + B: Download and filter CSCL data
    gdf_raw = _download_cscl_geojson()
    total_cscl_rows = len(gdf_raw)
    gdf = _filter_and_reproject(gdf_raw)

    # Step C: Build node lookup once, reuse for both cross streets and graph
    logger.info("Building node lookup...")
    node_lookup = _build_node_lookup(gdf)
    logger.info("Node lookup built with %d unique nodes", len(node_lookup))
    cross_streets = _compute_cross_streets(gdf, node_lookup=node_lookup)

    # Step D: Fetch ASP signs
    asp_lookup = _fetch_asp_signs()

    # Step D1: Bulk-download the curb + roadbed planimetric layers ONCE and build
    # the spatial-lookup trees. Skipped entirely when --no-curb-calibration is
    # set (calibration-free index). Roadbed is a build-time cross-validator only.
    curb_tree: STRtree | None = None
    curb_lines: list[LineString] | None = None
    roadbed_tree: STRtree | None = None
    roadbed_polys: list | None = None
    if not no_curb_calibration:
        curbs = _download_curbs(curb_cache)
        curb_tree, curb_lines = _build_curb_strtree(curbs)
        logger.info("Curb STRtree built with %d curb lines", len(curb_lines))
        roadbed = _download_roadbed(roadbed_cache)
        roadbed_tree, roadbed_polys = _build_roadbed_strtree(roadbed)
        logger.info("Roadbed STRtree built with %d polygons", len(roadbed_polys))
    else:
        logger.info("Curb calibration DISABLED (--no-curb-calibration)")

    # Step D2: Build graph and propagate ASP flags to interior blocks
    logger.info("Building street adjacency graph...")
    gdf_street_names: dict[int, str] = {
        int(row["physicalid"]): str(row.get("full_street_name", ""))
        for _, row in gdf.iterrows()
    }
    adjacency = _build_street_adjacency(node_lookup)
    logger.info(
        "Adjacency graph built: %d segments with at least one neighbor",
        len(adjacency),
    )
    intersection_index = _build_intersection_index(cross_streets, gdf_street_names)
    logger.info(
        "Intersection index built: %d (on_street, cross_street) entries",
        len(intersection_index),
    )
    asp_lookup, propagation_stats = _propagate_asp_to_interior_blocks(
        asp_lookup,
        adjacency,
        intersection_index,
        cross_streets,
        gdf_street_names,
    )

    # Step E + F: Build R-tree and save metadata (using expanded asp_lookup)
    stats = _build_rtree_and_metadata(
        gdf,
        cross_streets,
        asp_lookup,
        output_dir,
        curb_calibration_enabled=not no_curb_calibration,
        curb_tree=curb_tree,
        curb_lines=curb_lines,
        roadbed_tree=roadbed_tree,
        roadbed_polys=roadbed_polys,
    )

    # Step F2: Write graph.json.zst (2-hop filtered + zstandard compressed)
    logger.info("Writing graph.json.zst (2-hop filtered)...")
    asp_pids: set[int] = set()
    for on_street, from_cs, to_cs, _side in asp_lookup:
        # Collect all PIDs mentioned in the intersection index entries for this street
        for cs in (from_cs, to_cs):
            for pid in intersection_index.get((on_street, cs), set()):
                asp_pids.add(pid)

    # Supplement asp_pids with dead-end ASP segments not reachable via intersection_index
    # (segments where both cross streets are empty strings miss the lookup above)
    for _, row in gdf.iterrows():
        pid = int(row["physicalid"])
        if pid in asp_pids or pid not in adjacency:
            continue
        full_street_name = str(row.get("full_street_name", ""))
        from_street, to_street = cross_streets.get(pid, ("", ""))
        has_asp_left, has_asp_right = _check_has_asp(
            full_street_name,
            from_street,
            to_street,
            asp_lookup,
        )
        if has_asp_left or has_asp_right:
            asp_pids.add(pid)

    retained_pids = _filter_2hop_neighborhood(adjacency, asp_pids)
    logger.info(
        "Graph filter: %d -> %d segments (2-hop from %d ASP seeds)",
        len(adjacency),
        len(retained_pids),
        len(asp_pids & set(adjacency.keys())),
    )

    graph_adjacency: dict[str, list[int]] = {}
    graph_segment_streets: dict[str, str] = {}
    graph_segment_cross_streets: dict[str, list[str]] = {}

    for pid in retained_pids:
        pid_str = str(pid)
        neighbors = adjacency.get(pid, set())
        graph_adjacency[pid_str] = sorted(n for n in neighbors if n in retained_pids)
        graph_segment_streets[pid_str] = gdf_street_names.get(pid, "")
        pid_from, pid_to = cross_streets.get(pid, ("", ""))
        graph_segment_cross_streets[pid_str] = [pid_from, pid_to]

    graph_data = {
        "adjacency": graph_adjacency,
        "segment_streets": graph_segment_streets,
        "segment_cross_streets": graph_segment_cross_streets,
    }

    json_bytes = json.dumps(graph_data, separators=(",", ":")).encode("utf-8")
    cctx = zstandard.ZstdCompressor()
    compressed = cctx.compress(json_bytes)

    graph_path = output_dir / "graph.json.zst"
    with open(graph_path, "wb") as f:
        f.write(compressed)

    graph_size_mb = graph_path.stat().st_size / (1024 * 1024)
    logger.info(
        "graph.json.zst written: %.2f MB (%d segments)",
        graph_size_mb,
        len(graph_adjacency),
    )
    if graph_size_mb > 4.0:
        logger.warning("graph.json.zst exceeds 4 MB target: %.2f MB", graph_size_mb)

    # Step G: Save build metadata
    elapsed = time.time() - start_time
    build_info = {
        "build_timestamp": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(),
        ),
        "cscl_row_count": total_cscl_rows,
        "filtered_count": stats["filtered_count"],
        "asp_segments_count": stats["asp_segments_count"],
        "calibrated_count": stats["calibrated_count"],
        "non_calibrated_count": stats["non_calibrated_count"],
        "index_file_sizes": stats["index_file_sizes"],
        "build_duration_seconds": round(elapsed, 1),
        "propagation_stats": propagation_stats,
        "graph_json_zst_size": graph_path.stat().st_size,
        "graph_segment_count": len(graph_adjacency),
    }

    build_info_path = output_dir / "build_info.json"
    with open(build_info_path, "w") as f:
        json.dump(build_info, f, indent=2)

    logger.info("Build complete in %.1f seconds", elapsed)
    logger.info(
        "Segments: %d, ASP segments: %d",
        stats["filtered_count"],
        stats["asp_segments_count"],
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
        help=("Output directory for index files (default: src/gps2asp/data/index/)"),
    )
    parser.add_argument(
        "--no-curb-calibration",
        action="store_true",
        help=(
            "Skip the curb/roadbed bulk download and build a calibration-free "
            "index (all segments written as non-calibrated, center_offset_c=0)."
        ),
    )
    parser.add_argument(
        "--curb-cache",
        type=Path,
        default=None,
        help=(
            "Local GeoJSON cache for the curb layer (5xvt-8cbk). Loaded if it "
            "exists; otherwise the download is written to it for re-runnable "
            "offline builds."
        ),
    )
    parser.add_argument(
        "--roadbed-cache",
        type=Path,
        default=None,
        help=(
            "Local GeoJSON cache for the roadbed layer (i36f-5ih7). Same "
            "load/write semantics as --curb-cache."
        ),
    )
    args = parser.parse_args()

    build_index(
        output_dir=args.output_dir,
        no_curb_calibration=args.no_curb_calibration,
        curb_cache=args.curb_cache,
        roadbed_cache=args.roadbed_cache,
    )
