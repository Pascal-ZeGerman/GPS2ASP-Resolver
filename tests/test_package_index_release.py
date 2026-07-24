"""Tests for scripts/package_index_release.py.

The packager is a pure-stdlib CLI that gates on ``build_info.json``'s
``calibrated_count`` (fail-closed) and, on success, writes a FLAT ``index.zip``
whose members are bare basenames — exactly the layout the HA fast-path
downloader's ``_sync_extract_zip`` consumes.

Tests A-D from plan 40-10 Task 1:
  A. refuse when ``calibrated_count == 0`` (write nothing)
  B. refuse when ``calibrated_count`` key is absent (treated as 0)
  C. happy path: flat 5-entry zip on ``calibrated_count > 0``
  D. graph fallback: use ``graph.json`` when ``graph.json.zst`` absent;
     refuse when neither graph file exists
"""

from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "package_index_release.py"
)


def _load_packager():
    spec = importlib.util.spec_from_file_location(
        "package_index_release", _MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


packager = _load_packager()

_EXPECTED_FLAT_ENTRIES = {
    "segments.idx",
    "segments.dat",
    "segments.json",
    "graph.json.zst",
    "build_info.json",
}


def _write_index(
    dir_path: Path,
    *,
    calibrated_count,
    include_required: bool = True,
    include_graph_zst: bool = True,
    include_graph_json: bool = False,
) -> Path:
    """Populate ``dir_path`` with a synthetic index dir for the packager."""
    dir_path.mkdir(parents=True, exist_ok=True)
    build_info: dict = {}
    if calibrated_count is not None:
        build_info["calibrated_count"] = calibrated_count
    (dir_path / "build_info.json").write_text(json.dumps(build_info))
    if include_required:
        for name in ("segments.idx", "segments.dat", "segments.json"):
            (dir_path / name).write_bytes(b"placeholder")
    if include_graph_zst:
        (dir_path / "graph.json.zst").write_bytes(b"zst-placeholder")
    if include_graph_json:
        (dir_path / "graph.json").write_bytes(b"json-placeholder")
    return dir_path


# --- Test A: refuse uncalibrated (calibrated_count == 0) --------------------


def test_refuses_when_calibrated_count_zero(tmp_path):
    index_dir = _write_index(tmp_path / "index", calibrated_count=0)
    out = tmp_path / "index.zip"

    with pytest.raises(SystemExit) as exc:
        packager.package_index(index_dir, out)

    assert exc.value.code != 0
    assert not out.exists(), "zip must NOT be written on an uncalibrated build"


# --- Test B: refuse when calibrated_count key is missing ---------------------


def test_refuses_when_calibrated_count_missing(tmp_path):
    index_dir = _write_index(tmp_path / "index", calibrated_count=None)
    out = tmp_path / "index.zip"

    with pytest.raises(SystemExit) as exc:
        packager.package_index(index_dir, out)

    assert exc.value.code != 0
    assert not out.exists()


# --- Test C: happy path — flat 5-entry zip ----------------------------------


def test_happy_path_writes_flat_five_entry_zip(tmp_path):
    index_dir = _write_index(tmp_path / "index", calibrated_count=7)
    out = tmp_path / "index.zip"

    packager.package_index(index_dir, out)

    assert out.exists()
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert set(names) == _EXPECTED_FLAT_ENTRIES
    # every entry must be a bare basename (flat archive)
    assert all("/" not in name for name in names), names
    assert len(names) == 5


# --- Test D: graph fallback --------------------------------------------------


def test_graph_json_fallback_when_zst_absent(tmp_path):
    index_dir = _write_index(
        tmp_path / "index",
        calibrated_count=3,
        include_graph_zst=False,
        include_graph_json=True,
    )
    out = tmp_path / "index.zip"

    packager.package_index(index_dir, out)

    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert "graph.json" in names
    assert "graph.json.zst" not in names
    assert names == {
        "segments.idx",
        "segments.dat",
        "segments.json",
        "graph.json",
        "build_info.json",
    }


def test_refuses_when_no_graph_file(tmp_path):
    index_dir = _write_index(
        tmp_path / "index",
        calibrated_count=5,
        include_graph_zst=False,
        include_graph_json=False,
    )
    out = tmp_path / "index.zip"

    with pytest.raises(SystemExit) as exc:
        packager.package_index(index_dir, out)

    assert exc.value.code != 0
    assert not out.exists()


def test_refuses_when_required_index_file_missing(tmp_path):
    index_dir = _write_index(
        tmp_path / "index", calibrated_count=5, include_required=False
    )
    out = tmp_path / "index.zip"

    with pytest.raises(SystemExit) as exc:
        packager.package_index(index_dir, out)

    assert exc.value.code != 0
    assert not out.exists()
