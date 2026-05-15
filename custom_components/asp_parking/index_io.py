"""Sync helpers for spatial-index lifecycle (Phase 33 D-01).

Single source of truth for the download / extract / atomic-swap / build_info-parse
logic shared between first-time setup (``custom_components/asp_parking/__init__.py``)
and the manual rebuild flow (``custom_components/asp_parking/coordinator.py``). All
functions here are pure sync; the executor dispatch happens at the caller via
``hass.async_add_executor_job``.

Security note (zip-slip CVE class): ``_sync_extract_zip`` resolves every member
path against the destination root and refuses any entry whose resolved path is
not contained by ``dest_dir``. The check is byte-equivalent to the original
implementation in ``__init__.py`` lines 90-96 and is exercised by the RED test
``tests/test_index_io.py::test_extract_zip_refuses_path_traversal``.

Atomic swap (POSIX rename(2) / Windows MoveFileExW): ``_sync_atomic_swap`` uses
``os.replace`` so the on-disk index directory is either fully old or fully new
— never half-extracted. Per RESEARCH §"Atomic swap (sync helper)", the caller
is responsible for preparing ``<index_dir>_tmp`` BEFORE calling swap; calling
swap without a prepared tmp raises ``FileNotFoundError`` rather than silently
succeeding.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

import httpx

from homeassistant.util import dt as dt_util

logger = logging.getLogger(__name__)


# Module constants — byte-equivalent to the originals in __init__.py lines 24-25.
INDEX_DIR = Path(__file__).parent / "gps2asp" / "data" / "index"
INDEX_FILES = ("segments.idx", "segments.dat", "segments.json", "graph.json")


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

    Any exception leaves ``<index_dir>`` either fully old or fully new —
    never half-extracted (D-02).
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
    """Remove stale rebuild artifacts (idempotent — never raises).

    Wipes ``<index_dir>_tmp``, ``<index_dir>_bak``, and
    ``<index_dir>/_download.zip`` if any are present. Safe to call when the
    index dir itself does not exist (RESEARCH Pitfall 5: crash-recovery
    idempotency).
    """
    tmp = index_dir.parent / (index_dir.name + "_tmp")
    bak = index_dir.parent / (index_dir.name + "_bak")
    download_zip = index_dir / "_download.zip"

    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(bak, ignore_errors=True)
    try:
        download_zip.unlink(missing_ok=True)
    except OSError:
        # download_zip lives inside index_dir; if index_dir is missing the
        # unlink may raise on some platforms — swallow per "never raises".
        logger.debug("cleanup_stale: ignored OSError unlinking %s", download_zip)


def _sync_extract_zip(zip_path: Path, dest_dir: Path) -> None:
    """Extract ``zip_path`` into ``dest_dir`` with zip-slip protection.

    For every member, resolves ``(dest_dir / name)`` and asserts the result is
    contained by ``dest_dir.resolve()``. Refuses path-traversal entries (e.g.
    ``../escape.txt`` or ``../../../etc/passwd``) with ``ValueError`` BEFORE
    writing anything to disk.

    Preserves the exact safety check from the original
    ``__init__.py::_sync_download`` (lines 90-96); only the variable name
    ``_INDEX_DIR`` changes to the parameter ``dest_dir``.
    """
    resolved_base = dest_dir.resolve()
    resolved_base.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            member_path = (resolved_base / name).resolve()
            if not str(member_path).startswith(str(resolved_base) + os.sep):
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
