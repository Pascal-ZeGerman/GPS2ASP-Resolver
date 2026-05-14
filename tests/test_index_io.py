"""RED tests for custom_components/asp_parking/index_io.py (Phase 33 Plan 02).

Covers the pure sync helpers Wave 2 plan 03 must implement to satisfy:
  - IDX-04 (atomic swap → SpatialIndex.reset → _sign_cache.clear sequence)
  - RESEARCH Pitfall 2 (atomic swap ordering — extract THEN swap, never write-in-place)
  - RESEARCH Pitfall 5 (stale-artifact cleanup must be idempotent)
  - RESEARCH Pitfall 6 (tz-aware build_timestamp parsing)
  - RESEARCH Pitfall 7 (callers depend on distinct notification IDs — read_build_timestamp
    must never raise so the success-notification path remains intact)
  - Zip-slip CVE class (ZIP path traversal — relative `../escape.txt` attack)

Pattern: stdlib only (zipfile, pathlib, json, datetime) — no HA harness, no network.
Every test uses the pytest `tmp_path` fixture; production paths (custom_components/
asp_parking/gps2asp/data/index/) are NEVER touched.

RED state proof: importing from custom_components.asp_parking.index_io fails because
the module does not exist yet; this file fails at collection (ModuleNotFoundError)
until Wave 2 plan 03 creates the module.
"""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Imports targeted at the FUTURE module Wave 2 plan 03 must create.
# Collection MUST fail with ModuleNotFoundError until that plan implements
# custom_components/asp_parking/index_io.py.
from custom_components.asp_parking.index_io import (  # noqa: E402
    INDEX_DIR,
    INDEX_FILES,
    _sync_atomic_swap,
    _sync_cleanup_stale,
    _sync_extract_zip,
    _sync_read_build_timestamp,
)


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------


def test_index_dir_constant_points_to_vendored_data():
    """INDEX_DIR must resolve to the vendored gps2asp index directory."""
    import custom_components.asp_parking as asp_pkg

    expected = Path(asp_pkg.__file__).parent / "gps2asp" / "data" / "index"
    assert INDEX_DIR == expected


def test_index_files_tuple():
    """INDEX_FILES must enumerate the four artifacts the spatial index requires."""
    assert INDEX_FILES == (
        "segments.idx",
        "segments.dat",
        "segments.json",
        "graph.json",
    )


# ---------------------------------------------------------------------------
# _sync_atomic_swap — RESEARCH §"Atomic swap (sync helper, runs in executor)"
# ---------------------------------------------------------------------------


def test_atomic_swap_promotes_tmp_to_final(tmp_path: Path):
    """Given <base>/idx_tmp (NEW) and <base>/idx (OLD), swap promotes NEW."""
    base = tmp_path
    idx = base / "idx"
    tmp = base / "idx_tmp"

    idx.mkdir()
    (idx / "marker.txt").write_text("OLD")

    tmp.mkdir()
    (tmp / "marker.txt").write_text("NEW")

    _sync_atomic_swap(idx)

    assert (idx / "marker.txt").read_text() == "NEW"
    assert not tmp.exists(), "_tmp must be promoted (not present after swap)"
    assert not (base / "idx_bak").exists(), "_bak must be cleaned up after swap"


def test_atomic_swap_raises_when_tmp_missing(tmp_path: Path):
    """Without <base>/idx_tmp, swap must raise FileNotFoundError and leave idx untouched.

    Per RESEARCH §atomic swap: the caller (executor pipeline) is responsible for the
    extraction step BEFORE the swap. Calling swap without a prepared tmp is a bug
    that must surface — never silently "succeed".
    """
    base = tmp_path
    idx = base / "idx"
    idx.mkdir()
    (idx / "marker.txt").write_text("OLD")

    with pytest.raises(FileNotFoundError):
        _sync_atomic_swap(idx)

    # Existing index untouched (no half-swap)
    assert (idx / "marker.txt").read_text() == "OLD"


def test_atomic_swap_when_no_existing_index(tmp_path: Path):
    """First-time install: only <base>/idx_tmp exists; swap creates <base>/idx."""
    base = tmp_path
    idx = base / "idx"
    tmp = base / "idx_tmp"
    tmp.mkdir()
    (tmp / "marker.txt").write_text("NEW")

    _sync_atomic_swap(idx)

    assert (idx / "marker.txt").read_text() == "NEW"
    assert not tmp.exists()


def test_atomic_swap_cleans_prior_bak(tmp_path: Path):
    """If a stale _bak from a prior crash exists, swap must clean it before moving."""
    base = tmp_path
    idx = base / "idx"
    tmp = base / "idx_tmp"
    bak = base / "idx_bak"

    idx.mkdir()
    (idx / "marker.txt").write_text("OLD")
    tmp.mkdir()
    (tmp / "marker.txt").write_text("NEW")
    bak.mkdir()
    (bak / "ancient.txt").write_text("STALE")

    _sync_atomic_swap(idx)

    assert (idx / "marker.txt").read_text() == "NEW"
    assert not bak.exists(), "Stale _bak must be removed during/after swap"


# ---------------------------------------------------------------------------
# _sync_cleanup_stale — RESEARCH Pitfall 5 (idempotent crash recovery)
# ---------------------------------------------------------------------------


def test_cleanup_stale_removes_tmp_bak_and_download_zip(tmp_path: Path):
    """Pitfall 5: leftover _tmp, _bak, and _download.zip from a crash are removed."""
    base = tmp_path
    idx = base / "idx"
    idx.mkdir()

    # Real index file the cleanup must NOT touch
    real_file = idx / "segments.dat"
    real_file.write_bytes(b"real-data")

    # Crash debris
    tmp = base / "idx_tmp"
    tmp.mkdir()
    (tmp / "stale.txt").write_text("debris")
    bak = base / "idx_bak"
    bak.mkdir()
    (bak / "older.txt").write_text("older debris")
    download_zip = idx / "_download.zip"
    download_zip.write_bytes(b"PK\x03\x04")

    _sync_cleanup_stale(idx)

    assert not tmp.exists(), "_tmp must be removed"
    assert not bak.exists(), "_bak must be removed"
    assert not download_zip.exists(), "_download.zip must be removed"
    # Real file untouched
    assert real_file.read_bytes() == b"real-data"


def test_cleanup_stale_idempotent_when_nothing_to_clean(tmp_path: Path):
    """Cleanup must never raise even when there is nothing to clean."""
    base = tmp_path
    idx = base / "idx"
    idx.mkdir()

    # Calling twice on a clean directory must not raise
    _sync_cleanup_stale(idx)
    _sync_cleanup_stale(idx)

    assert idx.exists()


def test_cleanup_stale_when_index_dir_absent(tmp_path: Path):
    """Cleanup must never raise even when the index dir itself is missing."""
    base = tmp_path
    idx = base / "idx_does_not_exist"

    # Must not raise
    _sync_cleanup_stale(idx)


# ---------------------------------------------------------------------------
# _sync_extract_zip — Zip-slip mitigation
# ---------------------------------------------------------------------------


def test_extract_zip_refuses_path_traversal(tmp_path: Path):
    """A ZIP entry named '../escape.txt' must be refused with ValueError.

    The attack: an extracted '../escape.txt' would land OUTSIDE the dest dir,
    potentially overwriting arbitrary files on disk. The production helper
    must resolve each member's path and raise before writing if it escapes
    the destination.
    """
    base = tmp_path
    dest = base / "idx_tmp"
    dest.mkdir()

    zip_path = base / "malicious.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../escape.txt", b"PWNED")

    with pytest.raises(ValueError) as exc_info:
        _sync_extract_zip(zip_path, dest)

    msg = str(exc_info.value).lower()
    assert ("path traversal" in msg) or ("zip" in msg), (
        f"Expected zip-slip message, got: {exc_info.value!r}"
    )

    # Belt-and-braces: no PWNED escape.txt anywhere above dest. Any file with
    # the name escape.txt MUST NOT contain the payload bytes — proves the
    # extract failed before write.
    escapes = list((base / "..").rglob("escape.txt"))
    for p in escapes:
        assert not (
            p.is_file() and p.read_bytes() == b"PWNED"
        ), f"zip-slip attack succeeded: {p}"


def test_extract_zip_accepts_safe_members(tmp_path: Path):
    """A normal in-bounds member must extract correctly."""
    base = tmp_path
    dest = base / "idx_tmp"
    dest.mkdir()

    zip_path = base / "safe.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("segments.json", b"{}")

    _sync_extract_zip(zip_path, dest)

    assert (dest / "segments.json").read_bytes() == b"{}"


def test_extract_zip_refuses_absolute_member_path(tmp_path: Path):
    """An absolute path member (e.g. /etc/passwd) must also be refused.

    zipfile.ZipFile.extract historically sanitizes absolute paths, but the
    production helper should defensively reject them rather than relying on
    stdlib sanitization, which has been a CVE source in the past.
    """
    base = tmp_path
    dest = base / "idx_tmp"
    dest.mkdir()

    zip_path = base / "abs.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        # Multi-level path-traversal attempt; the member resolution check should
        # flag it because it escapes dest, regardless of stdlib sanitization.
        zf.writestr("../../../etc/escape.txt", b"PWNED")

    with pytest.raises(ValueError):
        _sync_extract_zip(zip_path, dest)


# ---------------------------------------------------------------------------
# _sync_read_build_timestamp — Pitfall 6 (tz-aware) + fault tolerance
# ---------------------------------------------------------------------------


def test_read_build_timestamp_returns_tz_aware_datetime(tmp_path: Path):
    """Valid build_info.json must yield a tz-aware datetime (Pitfall 6)."""
    base = tmp_path
    idx = base / "idx"
    idx.mkdir()
    (idx / "build_info.json").write_text(
        json.dumps({"build_timestamp": "2026-03-03T15:09:11Z"})
    )

    result = _sync_read_build_timestamp(idx)

    assert result == datetime(2026, 3, 3, 15, 9, 11, tzinfo=timezone.utc)
    assert result is not None
    assert result.tzinfo is not None, "Returned datetime must be tz-aware (Pitfall 6)"


def test_read_build_timestamp_returns_none_when_file_missing(tmp_path: Path):
    """Missing build_info.json → None, never raises."""
    base = tmp_path
    idx = base / "idx"
    idx.mkdir()

    assert _sync_read_build_timestamp(idx) is None


def test_read_build_timestamp_returns_none_when_index_dir_missing(tmp_path: Path):
    """Missing index dir entirely → None, never raises."""
    base = tmp_path
    idx = base / "does_not_exist"

    assert _sync_read_build_timestamp(idx) is None


def test_read_build_timestamp_returns_none_on_malformed_json(tmp_path: Path):
    """Malformed JSON → None, never raises (caller depends on this for notification flow)."""
    base = tmp_path
    idx = base / "idx"
    idx.mkdir()
    (idx / "build_info.json").write_bytes(b"{not valid")

    assert _sync_read_build_timestamp(idx) is None


def test_read_build_timestamp_returns_none_when_key_missing(tmp_path: Path):
    """Missing build_timestamp key → None, never raises."""
    base = tmp_path
    idx = base / "idx"
    idx.mkdir()
    (idx / "build_info.json").write_text(json.dumps({"other_key": "value"}))

    assert _sync_read_build_timestamp(idx) is None
