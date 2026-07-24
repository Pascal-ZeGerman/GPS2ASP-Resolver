#!/usr/bin/env python3
"""Fail-closed calibration gate + flat ``index.zip`` packager.

Reads ``<index-dir>/build_info.json`` and REFUSES to publish (exits non-zero,
writing no zip) unless ``calibrated_count > 0`` — an uncalibrated or broken
build must never ship to the Home Assistant fast-path downloader.  On success
it writes a FLAT ``index.zip`` (bare-basename arcnames) containing exactly the
files ``_sync_extract_zip`` / ``_index_has_graph_file`` in
``custom_components/asp_parking/index_io.py`` expect:

    segments.idx, segments.dat, segments.json,
    one graph file (prefer graph.json.zst, fall back to graph.json),
    build_info.json

Pure stdlib only (json, zipfile, pathlib, argparse, sys) so it runs even
without the project's ``.[build]`` extra installed — do NOT import geopandas
or any resolver module here.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import NoReturn

# Core spatial index files that must always be present.
# Mirrors custom_components/asp_parking/index_io.py INDEX_FILES.
REQUIRED_INDEX_FILES = ("segments.idx", "segments.dat", "segments.json")
BUILD_INFO_FILENAME = "build_info.json"
# Graph file: prefer the compressed form, fall back to uncompressed.
# Mirrors _index_has_graph_file() (graph loader is zst-first with json fallback).
GRAPH_FILE_CANDIDATES = ("graph.json.zst", "graph.json")


def _refuse(message: str) -> NoReturn:
    """Print an explicit refusal and abort (fail-closed) without writing a zip."""
    print(
        f"package_index_release: REFUSING to publish — {message}",
        file=sys.stderr,
    )
    sys.exit(1)


def package_index(index_dir: Path, out: Path) -> Path:
    """Gate on ``calibrated_count`` then write a flat ``index.zip``.

    Raises ``SystemExit`` (non-zero) and writes nothing if the build is
    uncalibrated or any required file is missing.
    """
    index_dir = Path(index_dir)
    out = Path(out)

    # 1. Fail-closed calibration gate — BEFORE writing any zip.
    build_info_path = index_dir / BUILD_INFO_FILENAME
    if not build_info_path.exists():
        _refuse(f"missing {BUILD_INFO_FILENAME} in {index_dir}")
    try:
        build_info = json.loads(build_info_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        _refuse(f"could not read {build_info_path}: {exc}")

    calibrated_count = int(build_info.get("calibrated_count", 0) or 0)
    if calibrated_count <= 0:
        _refuse(
            f"calibrated_count is {calibrated_count} (<= 0) — an uncalibrated "
            "index must never be published"
        )

    # 2. Assemble the file list: required index files + build_info + one graph.
    files: list[Path] = []
    for name in REQUIRED_INDEX_FILES:
        path = index_dir / name
        if not path.exists():
            _refuse(f"missing required index file: {name}")
        files.append(path)

    files.append(build_info_path)

    graph_path: Path | None = None
    for name in GRAPH_FILE_CANDIDATES:
        candidate = index_dir / name
        if candidate.exists():
            graph_path = candidate
            break
    if graph_path is None:
        _refuse(f"no graph file found (expected {' or '.join(GRAPH_FILE_CANDIDATES)})")
    files.append(graph_path)

    # 3. Write the flat zip (basename arcnames consumed by _sync_extract_zip).
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zf.write(path, arcname=path.name)

    print(
        f"package_index_release: wrote {out} "
        f"({len(files)} files, calibrated_count={calibrated_count})"
    )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail-closed packager: gate on build_info.json calibrated_count, "
            "then write a flat index.zip for the index-v1 rolling release."
        ),
    )
    parser.add_argument(
        "--index-dir",
        type=Path,
        default=Path("dist/index"),
        help="Directory containing the freshly built index files.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("dist/index.zip"),
        help="Output zip path.",
    )
    args = parser.parse_args(argv)
    package_index(args.index_dir, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
