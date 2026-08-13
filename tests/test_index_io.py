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
    IndexIntegrityError,
    _index_has_graph_file,
    _sync_atomic_swap,
    _sync_cleanup_stale,
    _sync_download_and_extract,
    _sync_extract_zip,
    _sync_read_build_timestamp,
    _sync_verify_index,
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
    """INDEX_FILES must enumerate the three non-graph artifacts the spatial index requires."""
    assert INDEX_FILES == (
        "segments.idx",
        "segments.dat",
        "segments.json",
    )


def test_index_has_graph_file_zst(tmp_path):
    """_index_has_graph_file returns True when graph.json.zst is present."""
    (tmp_path / "graph.json.zst").write_bytes(b"fake")
    assert _index_has_graph_file(tmp_path) is True


def test_index_has_graph_file_json(tmp_path):
    """_index_has_graph_file returns True when graph.json is present."""
    (tmp_path / "graph.json").write_text("{}")
    assert _index_has_graph_file(tmp_path) is True


def test_index_has_graph_file_absent(tmp_path):
    """_index_has_graph_file returns False when neither graph file is present."""
    assert _index_has_graph_file(tmp_path) is False


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
        assert not (p.is_file() and p.read_bytes() == b"PWNED"), (
            f"zip-slip attack succeeded: {p}"
        )


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


# ---------------------------------------------------------------------------
# _sync_download_and_extract — failure paths
# ---------------------------------------------------------------------------


def test_sync_download_and_extract_http_error_cleans_zip(tmp_path: Path) -> None:
    """HTTP error propagates; zip file is removed by the finally block."""
    import httpx
    from unittest.mock import MagicMock, patch

    index_dir = tmp_path / "index"
    zip_path = tmp_path / "index_tmp" / "_download.zip"

    # Build a mock streaming response that raises on raise_for_status.
    mock_resp = MagicMock()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "403 Forbidden", request=MagicMock(), response=MagicMock()
    )

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.stream.return_value = mock_resp

    with patch(
        "custom_components.asp_parking.index_io.httpx.Client", return_value=mock_client
    ):
        with pytest.raises(httpx.HTTPStatusError):
            _sync_download_and_extract(index_dir, "https://example.com/index.zip")

    # The finally block must have removed the (never-written) zip path.
    assert not zip_path.exists()


def test_sync_download_and_extract_extraction_failure_propagates(
    tmp_path: Path,
) -> None:
    """If _sync_extract_zip raises, the exception propagates and the zip is removed."""
    from unittest.mock import MagicMock, patch

    index_dir = tmp_path / "index"

    # Build a mock streaming response that succeeds but yields no bytes.
    mock_resp = MagicMock()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.raise_for_status.return_value = None
    mock_resp.iter_bytes.return_value = iter([])  # no chunks → empty zip file

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.stream.return_value = mock_resp

    with patch(
        "custom_components.asp_parking.index_io.httpx.Client", return_value=mock_client
    ):
        with patch(
            "custom_components.asp_parking.index_io._sync_extract_zip",
            side_effect=ValueError("bad zip"),
        ):
            with pytest.raises(ValueError, match="bad zip"):
                _sync_download_and_extract(index_dir, "https://example.com/index.zip")

    # The finally block must have removed the zip even after extraction failure.
    zip_path = tmp_path / "index_tmp" / "_download.zip"
    assert not zip_path.exists()


# ---------------------------------------------------------------------------
# _sync_cleanup_stale — crash-recovery: _bak restore / wipe behaviour
# ---------------------------------------------------------------------------


def test_sync_cleanup_stale_restores_bak_when_index_absent(tmp_path: Path) -> None:
    """If index_dir is missing but _bak exists, restore _bak to index_dir.

    This recovers from the crash window in _sync_atomic_swap where index_dir
    was moved to _bak but _tmp was never promoted — leaving _bak as the only
    viable copy of the index.
    """
    index_dir = tmp_path / "index"
    bak = tmp_path / "index_bak"
    bak.mkdir()
    (bak / "segments.idx").write_text("data")

    assert not index_dir.exists()
    _sync_cleanup_stale(index_dir)

    assert index_dir.exists()
    assert (index_dir / "segments.idx").read_text() == "data"
    assert not bak.exists()


def test_sync_cleanup_stale_wipes_bak_when_index_present(tmp_path: Path) -> None:
    """If both index_dir and _bak exist, _bak is the stale copy and gets wiped."""
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    bak = tmp_path / "index_bak"
    bak.mkdir()

    _sync_cleanup_stale(index_dir)

    assert index_dir.exists()
    assert not bak.exists()


# ---------------------------------------------------------------------------
# 9 new edge-case tests
# ---------------------------------------------------------------------------


def test_download_and_extract_bad_zip_propagates_and_cleans_up(tmp_path: Path) -> None:
    """BadZipFile raised by _sync_extract_zip propagates; _download.zip is removed.

    Edge-case 1: the finally block in _sync_download_and_extract must unlink
    the zip file even when extraction raises zipfile.BadZipFile.
    """
    from unittest.mock import MagicMock, patch

    index_dir = tmp_path / "index"
    tmp_dir = tmp_path / "index_tmp"
    zip_path = tmp_dir / "_download.zip"

    mock_resp = MagicMock()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.raise_for_status.return_value = None
    mock_resp.iter_bytes.return_value = iter([b"PK garbage"])

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.stream.return_value = mock_resp

    with patch(
        "custom_components.asp_parking.index_io.httpx.Client", return_value=mock_client
    ):
        with patch(
            "custom_components.asp_parking.index_io._sync_extract_zip",
            side_effect=zipfile.BadZipFile("File is not a zip file"),
        ):
            with pytest.raises(zipfile.BadZipFile):
                _sync_download_and_extract(index_dir, "https://example.com/index.zip")

    # The finally block must have removed the zip even though extraction failed.
    assert not zip_path.exists(), "_download.zip must be cleaned up by finally block"


def test_download_and_extract_zip_with_no_index_files(tmp_path: Path) -> None:
    """A ZIP containing only README.txt (no index files) extracts without error.

    Edge-case 2: documents the missing validation gap — _sync_download_and_extract
    has no post-extraction check for INDEX_FILES presence. The call completes
    successfully and _tmp exists but contains no index artifacts.
    """
    import io
    from unittest.mock import MagicMock, patch

    index_dir = tmp_path / "index"
    tmp_dir = tmp_path / "index_tmp"

    # Build a real zip containing only README.txt.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("README.txt", "This is not an index.")
    zip_bytes = buf.getvalue()

    mock_resp = MagicMock()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.raise_for_status.return_value = None
    mock_resp.iter_bytes.return_value = iter([zip_bytes])

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.stream.return_value = mock_resp

    with patch(
        "custom_components.asp_parking.index_io.httpx.Client", return_value=mock_client
    ):
        # Must NOT raise — gap: no INDEX_FILES validation after extraction.
        _sync_download_and_extract(index_dir, "https://example.com/index.zip")

    assert tmp_dir.exists(), "_tmp directory must exist after extraction"
    for fname in INDEX_FILES:
        assert not (tmp_dir / fname).exists(), (
            f"INDEX_FILE {fname!r} must NOT be present (gap: no validation)"
        )


def test_atomic_swap_propagates_oserror_from_os_replace(tmp_path: Path) -> None:
    """OSError from os.replace propagates out of _sync_atomic_swap.

    Edge-case 3: if the filesystem rejects the rename (e.g. EBUSY, EXDEV),
    the raw OSError must surface to the caller rather than being swallowed.
    """
    from unittest.mock import patch

    index_dir = tmp_path / "index"
    index_dir.mkdir()
    tmp_dir = tmp_path / "index_tmp"
    tmp_dir.mkdir()

    with patch(
        "custom_components.asp_parking.index_io.os.replace",
        side_effect=OSError("EBUSY"),
    ):
        with pytest.raises(OSError, match="EBUSY"):
            _sync_atomic_swap(index_dir)


def test_cleanup_stale_restores_empty_bak_when_index_absent(tmp_path: Path) -> None:
    """Empty _bak is restored to index_dir when index_dir is absent.

    Edge-case 4: the crash-recovery path in _sync_cleanup_stale calls
    os.replace(bak, index_dir) even when _bak is an empty directory. The
    result is that index_dir exists (as an empty dir) and _bak is gone.
    """
    index_dir = tmp_path / "index"
    bak = tmp_path / "index_bak"
    bak.mkdir()  # empty — no files inside

    assert not index_dir.exists()

    _sync_cleanup_stale(index_dir)

    assert index_dir.exists(), "index_dir must be restored from _bak (even if empty)"
    assert not bak.exists(), "_bak must be gone after restore"


def test_cleanup_stale_copytree_fallback_recovers_index_when_os_replace_raises(
    tmp_path: Path,
) -> None:
    """WR-05 (38-REVIEW.md): when os.replace raises OSError during _bak
    restore, _sync_cleanup_stale falls back to shutil.copytree instead of
    immediately discarding the LAST viable copy of the index. If the copy
    succeeds, index_dir ends up populated and _bak is wiped (now redundant).

    Supersedes the old "always wipe _bak on os.replace failure" contract —
    the review flagged that behavior as trading a recoverable state (rebuild
    forced) for an avoidable one, since a same-filesystem `rename` failure
    (e.g. transient EBUSY) does not necessarily mean a `copytree` would also
    fail.
    """
    from unittest.mock import patch

    index_dir = tmp_path / "index"
    bak = tmp_path / "index_bak"
    bak.mkdir()
    (bak / "segments.idx").write_text("data")

    assert not index_dir.exists()

    with patch(
        "custom_components.asp_parking.index_io.os.replace",
        side_effect=OSError("EBUSY"),
    ):
        # Must not raise. Only os.replace is patched to fail — the
        # shutil.copytree fallback runs for real against tmp_path.
        _sync_cleanup_stale(index_dir)

    assert index_dir.exists(), (
        "index_dir must be recovered via the copytree fallback"
    )
    assert (index_dir / "segments.idx").read_text() == "data"
    assert not bak.exists(), "_bak must be wiped once the copy fallback succeeds"


def test_cleanup_stale_wipes_bak_when_both_replace_and_copytree_raise(
    tmp_path: Path,
) -> None:
    """WR-05 (38-REVIEW.md): when BOTH os.replace and the copytree fallback
    raise OSError, _bak is wiped as a last resort (unusable either way) and
    index_dir remains absent. The function must not re-raise.
    """
    from unittest.mock import patch

    index_dir = tmp_path / "index"
    bak = tmp_path / "index_bak"
    bak.mkdir()
    (bak / "segments.idx").write_text("data")

    assert not index_dir.exists()

    with patch(
        "custom_components.asp_parking.index_io.os.replace",
        side_effect=OSError("EBUSY"),
    ):
        with patch(
            "custom_components.asp_parking.index_io.shutil.copytree",
            side_effect=OSError("disk full"),
        ):
            # Must not raise.
            _sync_cleanup_stale(index_dir)

    assert not bak.exists(), "_bak must be wiped after both fallbacks fail"
    assert not index_dir.exists(), "index_dir must remain absent"


def test_read_build_timestamp_raises_on_integer_value(tmp_path: Path) -> None:
    """build_timestamp integer value causes TypeError from dt_util.parse_datetime.

    Edge-case 6: dt_util.parse_datetime() requires a str argument and raises
    TypeError when given an int. _sync_read_build_timestamp does not catch
    TypeError, so it propagates to the caller. This is a latent bug — the
    function contract says "never raises", but an integer build_timestamp
    violates that contract.
    """
    index_dir = tmp_path / "idx"
    index_dir.mkdir()
    (index_dir / "build_info.json").write_text(
        json.dumps({"build_timestamp": 1716019200})
    )

    with pytest.raises(TypeError):
        _sync_read_build_timestamp(index_dir)


def test_read_build_timestamp_returns_none_for_json_list(tmp_path: Path) -> None:
    """build_info.json containing a JSON list (not dict) → None, never raises.

    Edge-case 7: isinstance(data, dict) guard catches this and returns None.
    """
    index_dir = tmp_path / "idx"
    index_dir.mkdir()
    (index_dir / "build_info.json").write_text(json.dumps([1, 2, 3]))

    assert _sync_read_build_timestamp(index_dir) is None


def test_extract_zip_duplicate_entries_last_writer_wins(tmp_path: Path) -> None:
    """A ZIP with two identically-named entries extracts without error.

    Edge-case 8: last-writer-wins — the second entry overwrites the first.
    The function must not raise; a UserWarning from stdlib is acceptable.
    """
    import io

    base = tmp_path
    dest = base / "idx_tmp"
    dest.mkdir()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("segments.json", b"first-content")
        zf.writestr("segments.json", b"second-content")
    zip_path = base / "dup.zip"
    zip_path.write_bytes(buf.getvalue())

    # Must not raise — stdlib emits UserWarning for duplicate names, not an error.
    _sync_extract_zip(zip_path, dest)

    assert (dest / "segments.json").exists()
    # Last entry wins (stdlib last-writer-wins semantics).
    assert (dest / "segments.json").read_bytes() == b"second-content"


# ---------------------------------------------------------------------------
# Phase 38 Plan 01 D-04/D-05: build_info.json source-field patch coverage
# ---------------------------------------------------------------------------


def _build_zip_bytes(entries: dict[str, bytes]) -> bytes:
    """Return in-memory zip containing ``entries`` (filename → bytes)."""
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_download_and_extract_patches_source_github_release(tmp_path: Path) -> None:
    """D-04: extracted build_info.json must be patched with source=github_release.

    After ``_sync_download_and_extract`` returns, the on-disk ``build_info.json``
    inside ``<index_dir>_tmp`` must contain ``source = "github_release"`` even
    when the release archive did not include that field. The existing
    ``build_timestamp`` MUST be preserved.
    """
    from unittest.mock import MagicMock, patch

    zip_bytes = _build_zip_bytes(
        {
            "build_info.json": json.dumps(
                {"build_timestamp": "2026-05-01T00:00:00Z"}
            ).encode("utf-8")
        }
    )

    mock_resp = MagicMock()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.raise_for_status.return_value = None
    mock_resp.iter_bytes.return_value = iter([zip_bytes])

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.stream.return_value = mock_resp

    index_dir = tmp_path / "idx"
    with patch(
        "custom_components.asp_parking.index_io.httpx.Client",
        return_value=mock_client,
    ):
        _sync_download_and_extract(index_dir, "https://example.com/index.zip")

    bi_path = tmp_path / "idx_tmp" / "build_info.json"
    assert bi_path.exists(), "build_info.json must exist after extract"
    data = json.loads(bi_path.read_text())
    assert isinstance(data, dict)
    assert data.get("source") == "github_release"
    assert data.get("build_timestamp") == "2026-05-01T00:00:00Z"


def test_download_and_extract_silent_skip_when_build_info_missing(
    tmp_path: Path,
) -> None:
    """D-05: an extracted zip without build_info.json must NOT raise.

    The patch step inside ``_sync_download_and_extract`` reads
    ``build_info.json`` opportunistically; if it does not exist after the
    extract, the call still completes successfully and no
    ``build_info.json`` file is created.
    """
    from unittest.mock import MagicMock, patch

    zip_bytes = _build_zip_bytes({"segments.idx": b"placeholder"})

    mock_resp = MagicMock()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.raise_for_status.return_value = None
    mock_resp.iter_bytes.return_value = iter([zip_bytes])

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.stream.return_value = mock_resp

    index_dir = tmp_path / "idx"
    with patch(
        "custom_components.asp_parking.index_io.httpx.Client",
        return_value=mock_client,
    ):
        _sync_download_and_extract(index_dir, "https://example.com/index.zip")

    # Silent skip — no build_info.json fabricated when extract did not provide one.
    assert not (tmp_path / "idx_tmp" / "build_info.json").exists()


def test_extract_zip_windows_backslash_traversal_is_safe_on_linux(
    tmp_path: Path,
) -> None:
    """Windows-style '..\\\\escape.txt' entry is NOT a traversal attack on Linux.

    Edge-case 9: on Linux, '\\\\' is NOT a path separator, so '..\\\\ escape.txt'
    is treated as a single opaque filename component. Path.is_relative_to()
    returns True (the literal filename lives inside dest_dir), so no ValueError
    is raised and the file is extracted safely into dest_dir with the backslash
    as part of its name.

    This test documents the platform-specific behavior: the Windows-style attack
    vector is neutralised on Linux by the OS, not by the zip-slip guard.
    """
    import io

    base = tmp_path
    dest = base / "idx_tmp"
    dest.mkdir()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(r"..\escape.txt", b"CONTENT")
    zip_path = base / "win_traversal.zip"
    zip_path.write_bytes(buf.getvalue())

    # On Linux: no ValueError — backslash is a valid filename character,
    # not a path separator. The entry resolves inside dest_dir.
    _sync_extract_zip(zip_path, dest)

    # The file must land INSIDE dest_dir (not in dest_dir.parent).
    extracted = list(dest.iterdir())
    assert len(extracted) == 1, f"Expected 1 file inside dest_dir, got: {extracted}"
    # The file must NOT escape to the parent directory.
    assert not (base / "escape.txt").exists(), (
        "File must not escape to parent directory"
    )


# ---------------------------------------------------------------------------
# _sync_verify_index — quick task 260601-aru Layer 1 (integrity check)
# ---------------------------------------------------------------------------
#
# Three unit-level tests (no `hass`, no network) cover:
#   - Happy path: a minimal valid rtree + graph.json.zst opens cleanly.
#   - Corrupt rtree: writing 4-byte garbage to segments.dat raises
#     IndexIntegrityError.
#   - Corrupt graph.json.zst: garbage bytes raise IndexIntegrityError via
#     zstandard.ZstdError.
#
# The helper opens the rtree by STEM (str(index_dir / "segments")) — never
# with the ``.idx`` suffix — mirroring index_io.py:769.


def _build_minimal_valid_index(index_dir: Path) -> None:
    """Build a minimal valid rtree + graph.json.zst inside ``index_dir``.

    Uses the production rtree open pattern (Property() + Index(stem)) so the
    resulting on-disk files (.idx + .dat) are byte-compatible with what
    _sync_verify_index will later try to re-open.
    """
    import zstandard
    from rtree import index as rtree_index

    index_dir.mkdir(parents=True, exist_ok=True)

    p = rtree_index.Property()
    p.overwrite = True
    idx = rtree_index.Index(str(index_dir / "segments"), properties=p)
    try:
        # One real insertion so the rtree has non-empty pages.
        idx.insert(1, (0.0, 0.0, 1.0, 1.0))
    finally:
        idx.close()

    # segments.json — not strictly required by _sync_verify_index, but written
    # so the on-disk state mirrors a real index.
    (index_dir / "segments.json").write_text("{}")

    # graph.json.zst — a valid zstd-compressed minimal JSON object.
    cctx = zstandard.ZstdCompressor()
    (index_dir / "graph.json.zst").write_bytes(cctx.compress(b"{}"))


def test_verify_index_passes_on_valid_index(tmp_path: Path):
    """A freshly built rtree + valid graph.json.zst passes integrity check."""
    index_dir = tmp_path / "idx"
    _build_minimal_valid_index(index_dir)

    # Must not raise.
    result = _sync_verify_index(index_dir)
    assert result is None


def test_verify_index_raises_on_corrupt_rtree(tmp_path: Path):
    """4-byte garbage in segments.dat triggers IndexIntegrityError."""
    index_dir = tmp_path / "idx"
    _build_minimal_valid_index(index_dir)

    # Truncate segments.dat to 4 bytes of garbage — rtree page reads will fail.
    (index_dir / "segments.dat").write_bytes(b"\x00\x01\x02\x03")

    with pytest.raises(IndexIntegrityError):
        _sync_verify_index(index_dir)


def test_verify_index_raises_on_corrupt_graph_zst(tmp_path: Path):
    """Garbage bytes in graph.json.zst (rtree valid) raises IndexIntegrityError."""
    index_dir = tmp_path / "idx"
    _build_minimal_valid_index(index_dir)

    # Overwrite graph.json.zst with non-zstd bytes. zstd magic is 0x28B52FFD;
    # 16 bytes of 0xFF triggers ZstdError on stream_reader.read(1).
    (index_dir / "graph.json.zst").write_bytes(b"\xff" * 16)

    with pytest.raises(IndexIntegrityError):
        _sync_verify_index(index_dir)


def test_verify_index_passes_when_only_plain_graph_json(tmp_path: Path):
    """If graph.json exists (uncompressed) and rtree is valid, integrity passes.

    Mirrors the _sync_verify_index OSError-only check on the uncompressed
    graph.json variant.
    """
    index_dir = tmp_path / "idx"
    _build_minimal_valid_index(index_dir)
    # Drop the zst variant and replace with a plain readable graph.json.
    (index_dir / "graph.json.zst").unlink()
    (index_dir / "graph.json").write_bytes(b'{"adjacency": {}}')

    result = _sync_verify_index(index_dir)
    assert result is None
