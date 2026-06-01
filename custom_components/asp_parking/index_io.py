"""Sync helpers for spatial-index lifecycle (Phase 33 D-01).

Single source of truth for the download / extract / atomic-swap / build_info-parse
logic shared between first-time setup (``custom_components/asp_parking/__init__.py``)
and the manual rebuild flow (``custom_components/asp_parking/coordinator.py``). All
functions here are pure sync; the executor dispatch happens at the caller via
``hass.async_add_executor_job``.

Security note (zip-slip CVE class): ``_sync_extract_zip`` resolves every member
path against the destination root and refuses any entry whose resolved path is
not contained by ``dest_dir``. Uses ``Path.is_relative_to`` (Python 3.9+, HA
requires 3.12+) to correctly handle both ``/`` and ``\\`` separators AND to
accept directory entries that equal the base path. Exercised by the RED test
``tests/test_index_io.py::test_extract_zip_refuses_path_traversal``.

Atomic swap (POSIX rename(2) / Windows MoveFileExW): ``_sync_atomic_swap`` uses
``os.replace`` so the on-disk index directory is either fully old or fully new.
There is a narrow crash window between the two ``os.replace`` calls (step 3 and
step 4): if a crash occurs after ``<index_dir>`` has been moved to
``<index_dir>_bak`` but before ``<index_dir>_tmp`` has been promoted, the live
index will be absent. ``_sync_cleanup_stale`` detects this and restores
``<index_dir>_bak`` rather than wiping it. Per RESEARCH §"Atomic swap (sync
helper)", the caller is responsible for preparing ``<index_dir>_tmp`` BEFORE
calling swap; calling swap without a prepared tmp raises ``FileNotFoundError``
rather than silently succeeding.
"""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
import time
import zipfile
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import zstandard
from pyproj import Transformer
from rtree import index as rtree_index
from shapely.geometry import shape
from shapely.ops import linemerge

from homeassistant.util import dt as dt_util

from .const import (
    CSCL_BATCH_SIZE,
    CSCL_GEOJSON_URL,
    MAX_CSCL_PAGES,
    SIGNS_BATCH_SIZE,
    SODA_PARKING_SIGNS_URL,
    VEHICULAR_RW_TYPES,
)

logger = logging.getLogger(__name__)


# Module constants — byte-equivalent to the originals in __init__.py lines 24-25.
INDEX_DIR = Path(__file__).parent / "gps2asp" / "data" / "index"
# Core spatial index files (always required, format is fixed).
# The graph file is intentionally absent here: the from-source rebuild writes
# graph.json.zst while the GitHub-release zip ships graph.json (uncompressed).
# Use _index_has_graph_file() to check for either format.
INDEX_FILES = ("segments.idx", "segments.dat", "segments.json")


def _index_has_graph_file(index_dir: Path) -> bool:
    """Return True if either graph.json.zst or graph.json exists in index_dir.

    The from-source rebuild (_sync_build_from_source) writes graph.json.zst.
    The GitHub release zip ships graph.json (uncompressed).  The graph.py
    loader handles both formats natively (zst-first with json fallback).
    This helper lets _async_ensure_index accept either without hardcoding one
    extension, preventing a ConfigEntryNotReady boot-loop after any rebuild.
    """
    return (index_dir / "graph.json.zst").exists() or (index_dir / "graph.json").exists()



class IndexIntegrityError(Exception):
    """Raised by ``_sync_verify_index`` when on-disk index files are corrupt.

    Files may pass an ``.exists()`` check yet still be truncated, garbage, or
    otherwise unreadable (interrupted download, truncated zip extraction, disk
    corruption). Callers re-download the index when this is raised; see
    ``custom_components/asp_parking/__init__.py::_async_ensure_index``.
    """

# Module-level pyproj Transformer (thread-safe, created once per process — see
# src/gps2asp/resolver/converter.py for the pattern). EPSG:4326 (WGS84) →
# EPSG:2263 (NY State Plane Long Island, US survey feet). always_xy=True keeps
# the (lon, lat) input order consistent across all callers.
_TRANSFORMER_4326_TO_2263 = Transformer.from_crs(
    "EPSG:4326",
    "EPSG:2263",
    always_xy=True,
)


def _sync_atomic_swap(index_dir: Path) -> None:
    """Promote ``<index_dir>_tmp`` to ``<index_dir>`` atomically.

    Algorithm:
      1. If ``<index_dir>_tmp`` does not exist, raise ``FileNotFoundError``
         (caller must run extract BEFORE swap).
      2. If a stale ``<index_dir>_bak`` exists, remove it.
      3. If ``<index_dir>`` exists, move it to ``<index_dir>_bak`` via
         ``os.replace`` (POSIX rename(2) atomicity).
      4. Move ``<index_dir>_tmp`` to ``<index_dir>`` via ``os.replace``.
      5. Best-effort remove ``<index_dir>_bak`` (``ignore_errors=True``).

    Crash window: a crash between steps 3 and 4 leaves ``<index_dir>``
    absent (moved to ``_bak``) with ``_tmp`` still present. Call
    ``_sync_cleanup_stale`` on startup to detect and recover from this
    state — it restores ``_bak`` to ``<index_dir>`` rather than wiping it.
    """
    tmp = index_dir.parent / (index_dir.name + "_tmp")
    bak = index_dir.parent / (index_dir.name + "_bak")

    if not tmp.exists():
        raise FileNotFoundError(
            f"atomic swap precondition violated: {tmp} does not exist "
            "(caller must run extract before swap)"
        )

    # Clean any stale _bak from a prior crashed swap
    if bak.exists():
        shutil.rmtree(bak, ignore_errors=True)

    # Move current index aside (only if present — first-time install has no current)
    if index_dir.exists():
        os.replace(index_dir, bak)

    # Promote tmp to live
    os.replace(tmp, index_dir)

    # Best-effort cleanup of the moved-aside copy
    shutil.rmtree(bak, ignore_errors=True)


def _sync_cleanup_stale(index_dir: Path) -> None:
    """Remove stale rebuild artifacts; restore backup if live index is missing.

    Handles RESEARCH Pitfall 5 (crash-recovery idempotency):

    * ``<index_dir>_tmp`` — always wiped (stale extraction debris).
    * ``<index_dir>_bak`` — behavior depends on whether ``<index_dir>`` exists:

      - ``index_dir`` **present**: ``_bak`` is genuinely stale (swap completed
        before the crash, or a prior cleanup left it). Wipe it.
      - ``index_dir`` **absent** but ``_bak`` present: the crash hit the narrow
        window in ``_sync_atomic_swap`` between the two ``os.replace`` calls —
        ``index_dir`` was moved to ``_bak`` but ``_tmp`` was never promoted.
        ``_bak`` is the LAST viable copy; restore it via ``os.replace``.

    * ``<index_dir>/_download.zip`` — wiped if present (partial download).

    Safe to call when the index dir itself does not exist. Never raises.
    """
    tmp = index_dir.parent / (index_dir.name + "_tmp")
    bak = index_dir.parent / (index_dir.name + "_bak")
    download_zip = index_dir / "_download.zip"

    shutil.rmtree(tmp, ignore_errors=True)

    if bak.exists():
        if index_dir.exists():
            # Normal case: live index is present, _bak is genuinely stale.
            shutil.rmtree(bak, ignore_errors=True)
        else:
            # Crash between the two os.replace calls — _bak is the only copy.
            try:
                os.replace(bak, index_dir)
            except OSError as exc:
                logger.error(
                    "cleanup_stale: could not restore backup index from %s to %s (%s) — "
                    "destroying backup; the index will need to be rebuilt",
                    bak,
                    index_dir,
                    exc,
                    exc_info=True,
                )
                shutil.rmtree(bak, ignore_errors=True)

    try:
        download_zip.unlink(missing_ok=True)
    except OSError:
        # download_zip lives inside index_dir; if index_dir is missing the
        # unlink may raise on some platforms — swallow per "never raises".
        logger.debug("cleanup_stale: ignored OSError unlinking %s", download_zip)


def _sync_verify_index(index_dir: Path) -> None:
    """Integrity-check the on-disk index — re-open rtree + decompress 1 graph byte.

    Files passing the ``Path.exists()`` check used by ``_async_ensure_index``
    may still be truncated, corrupt, or otherwise unreadable (interrupted
    download, partial extraction, disk corruption). This helper actually
    OPENS the rtree and decompresses one byte of the graph file to confirm
    they are usable BEFORE the coordinator depends on them.

    Behavior:
      * Opens the rtree by STEM ``str(index_dir / "segments")`` (the rtree
        convention — NEVER pass ``segments.idx`` directly). Mirrors the
        production pattern at ``_build_rtree_and_metadata`` (line 769).
      * If ``graph.json.zst`` exists, opens it and decompresses 1 byte via
        ``zstandard.ZstdDecompressor().stream_reader(...)``. Raises on
        ``zstandard.ZstdError`` / ``OSError``.
      * Otherwise, if plain ``graph.json`` exists, opens and reads 1 byte
        (OSError-only check — no decompression).
      * If neither graph file exists, the rtree check alone determines
        success; this is intentional and matches ``StreetGraph.load`` which
        treats missing graph files as "Level 4 unavailable" (not corrupt).

    Raises ``IndexIntegrityError`` on any failure; never swallows it.
    Returns ``None`` on success.
    """
    # --- rtree check ----------------------------------------------------------
    try:
        p = rtree_index.Property()
        idx = rtree_index.Index(str(index_dir / "segments"), properties=p)
        try:
            # Force at least one bbox query so the page-cache actually reads
            # bytes from segments.dat — a successful open alone is not always
            # enough to surface truncation (rtree lazy-loads pages).
            _ = list(idx.intersection((-1e9, -1e9, 1e9, 1e9)))
        finally:
            try:
                idx.close()
            except Exception:  # noqa: BLE001 — close failure is itself integrity-relevant
                logger.warning(
                    "rtree index close failed during integrity check",
                    exc_info=True,
                )
    except Exception as err:  # noqa: BLE001 — rtree raises a variety of native errors
        raise IndexIntegrityError(
            f"rtree index at {index_dir / 'segments'} failed to open: {err}"
        ) from err

    # --- graph file check -----------------------------------------------------
    # Prefer the compressed .zst variant — that is what the production
    # download path writes (_write_graph_zst). Fall back to plain graph.json
    # for local-dev installs that have not run a zstd rebuild.
    zst_path = index_dir / "graph.json.zst"
    json_path = index_dir / "graph.json"

    if zst_path.exists():
        try:
            dctx = zstandard.ZstdDecompressor()
            with zst_path.open("rb") as fh:
                with dctx.stream_reader(fh) as reader:
                    chunk = reader.read(1)
            if not chunk:
                raise IndexIntegrityError(
                    f"graph.json.zst at {zst_path} decompressed to 0 bytes"
                )
        except IndexIntegrityError:
            raise
        except (zstandard.ZstdError, OSError) as err:
            raise IndexIntegrityError(
                f"graph.json.zst at {zst_path} is unreadable: {err}"
            ) from err
    elif json_path.exists():
        try:
            with json_path.open("rb") as fh:
                chunk = fh.read(1)
            if not chunk:
                raise IndexIntegrityError(
                    f"graph.json at {json_path} is empty (0 bytes)"
                )
        except IndexIntegrityError:
            raise
        except OSError as err:
            raise IndexIntegrityError(
                f"graph.json at {json_path} is unreadable: {err}"
            ) from err
    # else: no graph file — treat as "Level 4 unavailable" not "corrupt".


def _sync_extract_zip(zip_path: Path, dest_dir: Path) -> None:
    """Extract ``zip_path`` into ``dest_dir`` with zip-slip protection.

    For every member, resolves ``(dest_dir / name)`` and asserts the result is
    contained by ``dest_dir.resolve()`` using ``Path.is_relative_to`` (Python
    3.9+, HA requires 3.12+). This correctly handles both ``/`` and ``\\``
    path separators, so a Windows-style entry like ``..\\escape.txt`` is
    caught on Linux where ``os.sep`` is ``/`` and the old ``startswith`` check
    would have passed. Directory entries equal to the base path are also
    accepted (``is_relative_to`` returns ``True`` for equal paths).

    Refuses path-traversal entries (e.g. ``../escape.txt`` or
    ``../../../etc/passwd``) with ``ValueError`` BEFORE writing anything to
    disk.
    """
    resolved_base = Path(dest_dir).resolve()
    resolved_base.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            member_path = (resolved_base / name).resolve()
            if not member_path.is_relative_to(resolved_base):
                raise ValueError(f"ZIP path traversal attempt: {name!r}")
            # Extract to resolved_base (not raw dest_dir) so the validated
            # path and the written path are always the same directory (CR-02).
            zf.extract(name, resolved_base)


def _sync_download_and_extract(index_dir: Path, url: str) -> None:
    """Download a zip from ``url`` into ``<index_dir>_tmp`` and extract it.

    Streams via ``httpx.Client`` (300 s timeout, follow_redirects=True) to
    ``<index_dir>_tmp/_download.zip``, then calls ``_sync_extract_zip`` to
    populate ``<index_dir>_tmp`` with the zip contents. The zip file is
    removed in a ``finally`` block whether extraction succeeded or not.

    The caller is responsible for running ``_sync_atomic_swap`` afterwards
    to promote ``<index_dir>_tmp`` into the live ``<index_dir>``.
    """
    tmp = index_dir.parent / (index_dir.name + "_tmp")
    tmp.mkdir(parents=True, exist_ok=True)
    zip_path = tmp / "_download.zip"

    try:
        with httpx.Client(timeout=300, follow_redirects=True) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(zip_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        f.write(chunk)
        _sync_extract_zip(zip_path, tmp)

        # Phase 38 D-04 / D-05: stamp source=github_release into the extracted
        # build_info.json so the coordinator can distinguish releases from
        # CSCL-API rebuilds (which write source=cscl_api in _sync_build_from_source).
        # D-05: a missing or malformed build_info.json is silently skipped — the
        # caller (download path) does not require provenance metadata to succeed.
        bi_path = tmp / "build_info.json"
        if bi_path.exists():
            try:
                bi = json.loads(bi_path.read_text())
                if isinstance(bi, dict):
                    bi["source"] = "github_release"
                    bi_path.write_text(json.dumps(bi, indent=2))
            except (OSError, json.JSONDecodeError) as exc:
                logger.debug(
                    "download_and_extract: skipping build_info.json source patch (%s)",
                    exc,
                )
    finally:
        zip_path.unlink(missing_ok=True)


def _sync_read_build_timestamp(index_dir: Path) -> datetime | None:
    """Read ``<index_dir>/build_info.json`` → tz-aware datetime, or ``None``.

    Returns ``None`` (never raises) on:
      - missing index dir
      - missing build_info.json
      - JSON parse errors
      - missing or empty ``build_timestamp`` key
      - OS-level read errors

    RESEARCH Pitfall 6: result MUST be tz-aware so downstream sensor
    comparisons (HA stores timestamps in UTC) do not blow up with
    ``TypeError: can't compare offset-naive and offset-aware datetimes``.
    The build_info.json format uses a trailing ``Z`` so ``dt_util.parse_datetime``
    naturally returns tz-aware. As a defensive fallback for any future naive
    output we normalize via ``replace(tzinfo=dt_util.UTC)``.

    Callers (success/error notification paths) depend on this never raising —
    see RESEARCH Pitfall 7.
    """
    build_info = index_dir / "build_info.json"
    try:
        raw_bytes = build_info.read_bytes()
    except (OSError, FileNotFoundError):
        return None

    try:
        data = json.loads(raw_bytes)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    raw = data.get("build_timestamp")
    if not raw:
        return None

    parsed = dt_util.parse_datetime(raw)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        # Defensive: current build_info files include "Z", but normalize any
        # legacy/naive output to UTC so the sensor is always tz-aware.
        parsed = parsed.replace(tzinfo=dt_util.UTC)
    return parsed


# ---------------------------------------------------------------------------
# Phase 38 IDX-06 — from-source CSCL rebuild
#
# `_sync_build_from_source` is the pure-python sibling of scripts/build_index.py
# that the coordinator can dispatch via `hass.async_add_executor_job` without
# requiring geopandas (a heavy GDAL dependency that violates the V12 manifest
# constraint for HA custom integrations). It produces the same 5-file output
# layout as the GitHub release zip — segments.idx, segments.dat, segments.json,
# graph.json.zst, build_info.json — written ONLY into ``<index_dir>_tmp``. The
# caller is responsible for running ``_sync_atomic_swap`` afterwards to promote
# the tmp directory to the live index.
#
# Threat-model touchstones (38-01 STRIDE register):
#   - T-38-01-01 / T-38-01-02: defensive input parsing (shape() in try, missing
#     key tolerance) for the untrusted CSCL/SODA JSON payloads
#   - T-38-01-03: V12 enforcement — writes ONLY to ``<index_dir>_tmp``
#   - T-38-01-04: MAX_CSCL_PAGES DoS guard
#   - T-38-01-05: X-App-Token from env var only (never persisted to disk)
#   - T-38-01-07: degenerate-bbox skip
#   - T-38-01-08: provenance stamp ``source: "cscl_api"``
# ---------------------------------------------------------------------------


def _build_headers() -> dict[str, str]:
    """Return HTTP headers for SODA endpoints, attaching the app token if set.

    Mirrors the pattern in ``src/gps2asp/signs/client.py`` and
    ``scripts/build_index.py::_get_headers`` — the env var is read here so
    individual callers do not need to repeat the lookup.
    """
    headers: dict[str, str] = {}
    token = os.environ.get("NYC_OPEN_DATA_APP_TOKEN")
    if token:
        headers["X-App-Token"] = token
    return headers


def _normalize_street_name(name: str) -> str:
    """Normalize a CSCL street name to SODA format.

    Delegates to the vendored ``gps2asp.signs.normalize.normalize_to_soda``
    for parity with the runtime sign lookup. The import is lazy so the
    HA-side module does not pull the resolver stack at import time.
    """
    try:
        from gps2asp.signs.normalize import normalize_to_soda
    except ImportError:  # pragma: no cover — vendored package always present
        return name.upper().strip()
    return normalize_to_soda(name)


def _sync_fetch_cscl_features(headers: dict[str, str]) -> list[dict[str, Any]]:
    """Paginate the CSCL GeoJSON endpoint and return raw Features.

    Filters out features with missing geometry/properties at fetch time so the
    downstream filter loop does not need to defend against the empty case.
    Raises ``RuntimeError`` if pagination exceeds ``MAX_CSCL_PAGES`` (T-38-01-04
    DoS guard). CSCL HTTP errors propagate (fail-hard semantics).
    """
    all_features: list[dict[str, Any]] = []
    offset = 0
    page_count = 0

    with httpx.Client(timeout=300, headers=headers, follow_redirects=True) as client:
        while True:
            if page_count >= MAX_CSCL_PAGES:
                raise RuntimeError(
                    f"CSCL pagination exceeded MAX_CSCL_PAGES={MAX_CSCL_PAGES} "
                    f"(offset={offset}, accumulated features={len(all_features)})"
                )

            params = {
                "$limit": str(CSCL_BATCH_SIZE),
                "$offset": str(offset),
                "$order": "physicalid",
            }
            resp = client.get(CSCL_GEOJSON_URL, params=params)
            resp.raise_for_status()
            body = resp.json()
            features = body.get("features", []) if isinstance(body, dict) else []

            valid = [
                f
                for f in features
                if isinstance(f, dict)
                and f.get("geometry") is not None
                and f.get("properties")
            ]
            all_features.extend(valid)
            page_count += 1

            if len(features) < CSCL_BATCH_SIZE:
                break
            offset += CSCL_BATCH_SIZE

    logger.info(
        "CSCL: fetched %d features across %d page(s)",
        len(all_features),
        page_count,
    )
    return all_features


def _sync_filter_and_reproject(
    features: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filter CSCL Features to vehicular streets and reproject to EPSG:2263.

    Pitfall 8: CSCL property keys may arrive UPPERCASE (PHYSICALID, RW_TYPE,
    TRAFDIR, …) — normalize to lowercase before reading. Pitfall 9: filter
    rw_type BEFORE the TRAFDIR=="NV" exclusion (preserves parity with the
    scripts/build_index.py pipeline). Single-element MultiLineString is
    collapsed; multi-element MultiLineString is fed through ``linemerge``;
    if the merge still yields a MultiLineString the feature is dropped
    (matches the build_index.py NotImplementedError skip path).

    Returns a list of dicts with keys: ``physicalid`` (int), ``geometry``
    (shapely LineString in EPSG:2263), and lowercase property mirror.
    """
    out: list[dict[str, Any]] = []
    for feat in features:
        props_raw = feat.get("properties") or {}
        # Pitfall 8: normalize key casing.
        props = {str(k).lower(): v for k, v in props_raw.items()}

        # Pitfall 9: rw_type filter BEFORE TRAFDIR exclusion.
        raw_rw = props.get("rw_type")
        if raw_rw is None or not str(raw_rw).strip().lstrip("-").isdigit():
            continue
        rw_int = int(str(raw_rw).strip())
        if rw_int not in VEHICULAR_RW_TYPES:
            continue

        if str(props.get("trafdir", "")).strip().upper() == "NV":
            continue

        try:
            geom = shape(feat.get("geometry"))
        except (ValueError, AttributeError, TypeError):
            continue
        if geom is None or geom.is_empty:
            continue

        # MultiLineString collapse / linemerge (matches scripts/build_index.py
        # _to_linestring, lines 176-187).
        if geom.geom_type == "MultiLineString":
            if len(geom.geoms) == 1:
                geom = geom.geoms[0]
            else:
                geom = linemerge(geom)
            if geom.geom_type != "LineString":
                # Could not collapse — skip (parity with build_index.py
                # NotImplementedError handling).
                continue

        try:
            coords = list(geom.coords)
        except NotImplementedError:
            continue
        if len(coords) < 2:
            continue

        # Reproject WGS84 → EPSG:2263 (NY State Plane Long Island, feet).
        xs, ys = _TRANSFORMER_4326_TO_2263.transform(
            [c[0] for c in coords],
            [c[1] for c in coords],
        )
        # pyproj returns lists; cast to tuple of (x, y) pairs.
        projected_coords = list(zip(xs, ys))
        # Drop degenerate geometries (all points identical) — they would
        # produce a zero-area bbox and confuse the rtree insert.
        if len(set(projected_coords)) < 2:
            continue

        from shapely.geometry import LineString  # local: shapely 2.x fast path

        projected_geom = LineString(projected_coords)

        raw_pid = props.get("physicalid")
        if raw_pid is None or not str(raw_pid).strip().lstrip("-").isdigit():
            continue
        pid = int(str(raw_pid).strip())

        props["geometry"] = projected_geom
        props["physicalid"] = pid
        props["rw_type"] = rw_int
        out.append(props)

    logger.info("CSCL: %d vehicular segments after filter+reproject", len(out))
    return out


def _build_node_lookup(
    segments: list[dict[str, Any]],
) -> dict[tuple[int, int], list[tuple[int, str]]]:
    """Map rounded (x, y) node coordinates → [(physicalid, street_name), …].

    Replicates ``scripts/build_index.py::_build_node_lookup`` semantics. The
    1-foot rounding tolerance matches the runtime resolver's coordinate
    accuracy.
    """
    node_lookup: dict[tuple[int, int], list[tuple[int, str]]] = {}
    for row in segments:
        geom = row["geometry"]
        coords = list(geom.coords)
        if len(coords) < 2:
            continue
        pid = row["physicalid"]
        name = str(row.get("full_street_name", "") or "")
        from_node = (round(coords[0][0]), round(coords[0][1]))
        to_node = (round(coords[-1][0]), round(coords[-1][1]))
        for node in (from_node, to_node):
            node_lookup.setdefault(node, []).append((pid, name))
    return node_lookup


def _find_cross_street(
    node: tuple[int, int],
    own_pid: int,
    own_name: str,
    node_lookup: dict[tuple[int, int], list[tuple[int, str]]],
) -> str:
    """Most common cross-street name at a node within a 3×3-ft tolerance."""
    own_upper = own_name.upper().strip()
    cross: list[str] = []
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            check = (node[0] + dx, node[1] + dy)
            for pid, name in node_lookup.get(check, ()):
                if pid == own_pid:
                    continue
                upper = name.upper().strip()
                if upper and upper != own_upper:
                    cross.append(upper)
    if not cross:
        return ""
    return Counter(cross).most_common(1)[0][0]


def _compute_cross_streets(
    segments: list[dict[str, Any]],
    node_lookup: dict[tuple[int, int], list[tuple[int, str]]],
) -> dict[int, tuple[str, str]]:
    """Pre-compute (from_street, to_street) cross streets for each segment."""
    cross: dict[int, tuple[str, str]] = {}
    for row in segments:
        coords = list(row["geometry"].coords)
        pid = row["physicalid"]
        name = str(row.get("full_street_name", "") or "")
        from_node = (round(coords[0][0]), round(coords[0][1]))
        to_node = (round(coords[-1][0]), round(coords[-1][1]))
        from_street = _find_cross_street(from_node, pid, name, node_lookup)
        to_street = _find_cross_street(to_node, pid, name, node_lookup)
        cross[pid] = (from_street, to_street)
    return cross


def _build_street_adjacency(
    node_lookup: dict[tuple[int, int], list[tuple[int, str]]],
) -> dict[int, set[int]]:
    """Build same-street adjacency from the node lookup (parity with build_index.py)."""
    adjacency: dict[int, set[int]] = {}
    processed: set[frozenset[int]] = set()

    for node, _segments in node_lookup.items():
        neighborhood: list[tuple[int, str]] = []
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                check = (node[0] + dx, node[1] + dy)
                neighborhood.extend(node_lookup.get(check, ()))

        by_street: dict[str, list[int]] = {}
        for pid, name in neighborhood:
            norm = _normalize_street_name(name)
            if norm:
                by_street.setdefault(norm, []).append(pid)

        for pids in by_street.values():
            unique = list(dict.fromkeys(pids))
            for i, pid_a in enumerate(unique):
                for pid_b in unique[i + 1 :]:
                    pair = frozenset((pid_a, pid_b))
                    if pair in processed:
                        continue
                    processed.add(pair)
                    adjacency.setdefault(pid_a, set()).add(pid_b)
                    adjacency.setdefault(pid_b, set()).add(pid_a)
    return adjacency


def _build_intersection_index(
    cross_streets: dict[int, tuple[str, str]],
    street_names: dict[int, str],
) -> dict[tuple[str, str], set[int]]:
    """Lookup (on_street, cross_street) → segment PID set (normalized names)."""
    index: dict[tuple[str, str], set[int]] = {}
    for pid, (from_cs, to_cs) in cross_streets.items():
        on_street = _normalize_street_name(street_names.get(pid, ""))
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
    """BFS from start_pids toward end_pids; empty set if unreached (parity)."""
    visited: set[int] = set()
    queue: deque[tuple[int, int]] = deque()
    for pid in start_pids:
        if pid not in visited:
            visited.add(pid)
            queue.append((pid, 0))
    reached_end = any(pid in end_pids for pid in start_pids)
    while queue:
        current, depth = queue.popleft()
        if current in end_pids:
            reached_end = True
            continue
        if depth >= max_depth:
            continue
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
) -> set[tuple[str, str, str, str]]:
    """Expand asp_lookup to cover interior blocks of multi-block SODA spans."""
    span_sides: dict[tuple[str, str, str], set[str]] = {}
    for on_street, from_street, to_street, side in asp_lookup:
        span_sides.setdefault((on_street, from_street, to_street), set()).add(side)

    expanded = set(asp_lookup)
    for (on_street, from_street, to_street), sides in span_sides.items():
        start_pids = intersection_index.get((on_street, from_street), set())
        end_pids = intersection_index.get((on_street, to_street), set())
        if not start_pids or not end_pids:
            continue
        visited = _bfs_between(start_pids, end_pids, adjacency)
        if not visited:
            continue
        for pid in visited:
            pid_from, pid_to = cross_streets.get(pid, ("", ""))
            pid_from_norm = _normalize_street_name(pid_from)
            pid_to_norm = _normalize_street_name(pid_to)
            if not pid_from_norm and not pid_to_norm:
                continue
            for side in sides:
                expanded.add((on_street, pid_from_norm, pid_to_norm, side))
    return expanded


def _sync_fetch_asp_signs(
    headers: dict[str, str],
) -> set[tuple[str, str, str, str]]:
    """Fetch ASP sign block-faces. Fail-soft on httpx.HTTPError (T-38-01-02)."""
    asp_tuples: set[tuple[str, str, str, str]] = set()
    offset = 0

    try:
        with httpx.Client(
            timeout=300, headers=headers, follow_redirects=True
        ) as client:
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
                resp = client.get(SODA_PARKING_SIGNS_URL, params=params)
                resp.raise_for_status()
                records = resp.json()
                if not records:
                    break
                for record in records:
                    on_street = _normalize_street_name(record.get("on_street") or "")
                    from_street = _normalize_street_name(
                        record.get("from_street") or ""
                    )
                    to_street = _normalize_street_name(record.get("to_street") or "")
                    side = (record.get("side_of_street") or "").upper().strip()
                    if on_street and side:
                        asp_tuples.add((on_street, from_street, to_street, side))
                if len(records) < SIGNS_BATCH_SIZE:
                    break
                offset += SIGNS_BATCH_SIZE
    except (
        httpx.HTTPError,
        httpx.TransportError,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as exc:
        # Fail-soft: SODA outages must NOT block a CSCL rebuild. The
        # downstream segments simply get has_asp=False, mirroring the
        # scripts/build_index.py behavior (lines 633-642).
        logger.warning(
            "SODA ASP signs fetch failed (offset=%d): %s — continuing without ASP data",
            offset,
            exc,
        )
    return asp_tuples


def _check_has_asp(
    street_name: str,
    from_street: str,
    to_street: str,
    asp_lookup: set[tuple[str, str, str, str]],
) -> tuple[bool, bool]:
    """Return (has_asp_left, has_asp_right) for a segment (parity helper)."""
    name = _normalize_street_name(street_name)
    fs = _normalize_street_name(from_street)
    ts = _normalize_street_name(to_street)
    for side_char in ("N", "S", "E", "W"):
        if (name, fs, ts, side_char) in asp_lookup or (
            name,
            ts,
            fs,
            side_char,
        ) in asp_lookup:
            return True, True
    return False, False


def _filter_2hop_neighborhood(
    adjacency: dict[int, set[int]],
    asp_pids: set[int],
) -> set[int]:
    """Return PIDs reachable within 2 hops from any ASP segment."""
    retained: set[int] = set()
    seeds = asp_pids & set(adjacency.keys())
    retained.update(seeds)
    hop1: set[int] = set()
    for pid in seeds:
        for neighbor in adjacency.get(pid, set()):
            if neighbor not in retained:
                hop1.add(neighbor)
    retained.update(hop1)
    for pid in hop1:
        for neighbor in adjacency.get(pid, set()):
            retained.add(neighbor)
    return retained


def _build_rtree_and_metadata(
    segments: list[dict[str, Any]],
    cross_streets: dict[int, tuple[str, str]],
    asp_lookup: set[tuple[str, str, str, str]],
    tmp: Path,
) -> int:
    """Write R-tree + segments.json; return inserted count (parity helper).

    Pitfall 7: uses ``idx.insert(pid, bbox)`` in a loop and closes the index
    in a ``finally`` block — NEVER the generator-constructor form (rtree
    bug #159 produces empty files).
    """
    p = rtree_index.Property()
    p.overwrite = True
    idx = rtree_index.Index(str(tmp / "segments"), properties=p)

    segments_meta: dict[str, dict[str, Any]] = {}
    insert_count = 0
    try:
        for row in segments:
            geom = row["geometry"]
            bbox = geom.bounds  # (minx, miny, maxx, maxy)
            if len(bbox) != 4:
                continue
            pid = row["physicalid"]
            idx.insert(pid, bbox)
            insert_count += 1

            full_name = str(row.get("full_street_name", "") or "")
            from_street, to_street = cross_streets.get(pid, ("", ""))
            has_left, has_right = _check_has_asp(
                full_name, from_street, to_street, asp_lookup
            )

            sw_raw = row.get("streetwidth")
            try:
                sw = float(sw_raw) if sw_raw is not None else None
                if sw is None or math.isnan(sw) or sw <= 0:
                    streetwidth = 0.0
                else:
                    streetwidth = sw
            except (ValueError, TypeError):
                streetwidth = 0.0

            segments_meta[str(pid)] = {
                "geometry_wkt": geom.wkt,
                "full_street_name": full_name,
                "from_street": from_street,
                "to_street": to_street,
                "trafdir": str(row.get("trafdir", "") or ""),
                "nominaldir": str(row.get("nominaldir", "") or ""),
                "rw_type": int(row.get("rw_type", 0)),
                "streetwidth": streetwidth,
                "borocode": str(row.get("boroughcode", row.get("borocode", "")) or ""),
                "has_asp_left": has_left,
                "has_asp_right": has_right,
            }
    finally:
        try:
            idx.close()
        except Exception:  # noqa: BLE001
            logger.warning(
                "rtree index close failed; index file may be incomplete",
                exc_info=True,
            )

    (tmp / "segments.json").write_text(json.dumps(segments_meta))
    return insert_count


def _write_graph_zst(
    adjacency: dict[int, set[int]],
    cross_streets: dict[int, tuple[str, str]],
    street_names: dict[int, str],
    intersection_index: dict[tuple[str, str], set[int]],
    asp_lookup: set[tuple[str, str, str, str]],
    segments: list[dict[str, Any]],
    tmp: Path,
) -> int:
    """Write the 2-hop-filtered, zstandard-compressed adjacency graph."""
    asp_pids: set[int] = set()
    for on_street, from_cs, to_cs, _side in asp_lookup:
        for cs in (from_cs, to_cs):
            for pid in intersection_index.get((on_street, cs), set()):
                asp_pids.add(pid)

    # Supplement with dead-end ASP segments (cross streets both empty).
    for row in segments:
        pid = row["physicalid"]
        if pid in asp_pids or pid not in adjacency:
            continue
        full_name = str(row.get("full_street_name", "") or "")
        from_street, to_street = cross_streets.get(pid, ("", ""))
        has_left, has_right = _check_has_asp(
            full_name, from_street, to_street, asp_lookup
        )
        if has_left or has_right:
            asp_pids.add(pid)

    retained = _filter_2hop_neighborhood(adjacency, asp_pids)

    graph_adjacency: dict[str, list[int]] = {}
    graph_segment_streets: dict[str, str] = {}
    graph_segment_cross_streets: dict[str, list[str]] = {}
    for pid in retained:
        pid_str = str(pid)
        neighbors = adjacency.get(pid, set())
        graph_adjacency[pid_str] = sorted(n for n in neighbors if n in retained)
        graph_segment_streets[pid_str] = street_names.get(pid, "")
        pid_from, pid_to = cross_streets.get(pid, ("", ""))
        graph_segment_cross_streets[pid_str] = [pid_from, pid_to]

    payload = {
        "adjacency": graph_adjacency,
        "segment_streets": graph_segment_streets,
        "segment_cross_streets": graph_segment_cross_streets,
    }
    json_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    compressed = zstandard.ZstdCompressor().compress(json_bytes)
    (tmp / "graph.json.zst").write_bytes(compressed)
    return len(graph_adjacency)


def _sync_build_from_source(index_dir: Path) -> None:
    """Build the spatial index from the live CSCL + SODA APIs.

    Writes 5 files to ``<index_dir>_tmp`` (V12 T-38-01-03 constraint):
    ``segments.idx``, ``segments.dat``, ``segments.json``, ``graph.json.zst``,
    ``build_info.json``. The caller is responsible for calling
    ``_sync_atomic_swap(index_dir)`` afterwards to promote the tmp directory.

    Behavior summary (IDX-06):
      * CSCL HTTP failures propagate (fail-hard).
      * SODA HTTP failures are logged + swallowed (fail-soft); resulting
        ``segments.json`` simply has ``has_asp_left/right`` False everywhere.
      * Pagination is capped by ``MAX_CSCL_PAGES`` (DoS guard).
      * ``NYC_OPEN_DATA_APP_TOKEN`` env var, if set, is forwarded as the
        ``X-App-Token`` header to BOTH endpoints.
      * ``build_info.json["source"] = "cscl_api"`` records provenance so the
        coordinator (Plan 02) can distinguish CSCL builds from release pulls.
      * The function is sync; the executor dispatch happens at the caller via
        ``hass.async_add_executor_job``.

    Raises:
        RuntimeError: pagination cap exceeded.
        httpx.HTTPError: CSCL endpoint failure (fail-hard).
        OSError: filesystem write failure.
    """
    tmp = index_dir.parent / (index_dir.name + "_tmp")
    tmp.mkdir(parents=True, exist_ok=True)

    headers = _build_headers()
    start = time.time()

    # Step 1: Fetch + filter + reproject CSCL features.
    raw_features = _sync_fetch_cscl_features(headers)
    segments = _sync_filter_and_reproject(raw_features)
    street_names = {
        row["physicalid"]: str(row.get("full_street_name", "") or "")
        for row in segments
    }

    # Step 2: Build the node lookup once, reuse for cross streets + graph.
    node_lookup = _build_node_lookup(segments)
    cross_streets = _compute_cross_streets(segments, node_lookup)

    # Step 3: Fetch ASP signs (fail-soft) and propagate to interior blocks.
    asp_lookup = _sync_fetch_asp_signs(headers)
    adjacency = _build_street_adjacency(node_lookup)
    intersection_index = _build_intersection_index(cross_streets, street_names)
    asp_lookup = _propagate_asp_to_interior_blocks(
        asp_lookup, adjacency, intersection_index, cross_streets
    )

    # Step 4: R-tree + segments.json + graph.json.zst.
    insert_count = _build_rtree_and_metadata(segments, cross_streets, asp_lookup, tmp)
    graph_segment_count = _write_graph_zst(
        adjacency,
        cross_streets,
        street_names,
        intersection_index,
        asp_lookup,
        segments,
        tmp,
    )

    # Step 5: build_info.json with provenance + timing.
    elapsed = round(time.time() - start, 1)
    build_info = {
        "build_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "cscl_api",
        "filtered_count": insert_count,
        "build_duration_seconds": elapsed,
        "graph_segment_count": graph_segment_count,
    }
    (tmp / "build_info.json").write_text(json.dumps(build_info, indent=2))
    logger.info(
        "_sync_build_from_source complete: %d segments, %d graph nodes, %.1fs",
        insert_count,
        graph_segment_count,
        elapsed,
    )
