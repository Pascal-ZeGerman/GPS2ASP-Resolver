"""Unit + integration tests for scripts/sync_vendored.py."""

from __future__ import annotations

# Two concerns under test:
#
# 1. ``normalize_source`` — pure function rewriting top-level absolute
#    ``from gps2asp.X import Y`` lines into the relative form appropriate for
#    the file's subpackage depth. Negative cases assert that indented imports
#    (TYPE_CHECKING / function-scope) and ``gps2asp_helpers``-prefixed
#    lookalikes are NOT touched.
#
# 2. ``main()`` CLI — exit-code contract for ``--dry-run`` (in-sync vs drift
#    vs missing-vendor) and round-trip stability of the write mode. Runs the
#    CLI in-process against ``tmp_path``-staged source and vendor trees via
#    ``monkeypatch`` of the module-level ``SRC_ROOT``/``VENDOR_ROOT``
#    constants.
#
# Tests run without network access. The 26-row oracle for normalization
# comes from ``.planning/phases/31-ci-guard-strings-json-sync/31-RESEARCH.md``
# §"Import normalization".

import sys
from pathlib import Path

import pytest

# Add scripts directory to path so we can import the module under test.
# Mirrors tests/test_audit_script.py:14-15.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sync_vendored  # noqa: E402
from sync_vendored import normalize_source  # noqa: E402


# ---------------------------------------------------------------------------
# Unit tests: normalize_source
# ---------------------------------------------------------------------------


class TestNormalizeSource:
    """Tests for the pure normalize_source(rel_path, text) function.

    Oracle: 31-RESEARCH.md §"Import normalization" (26-row table). Each
    parametrized case covers one row or category of the table.
    """

    # --- Top-level files (pkg_parts = []) ------------------------------------

    @pytest.mark.parametrize(
        "line_in,line_out",
        [
            (
                "from gps2asp.pipeline import resolve_asp",
                "from .pipeline import resolve_asp",
            ),
            (
                "from gps2asp.api_models import ASPResult, ASPDebugResult",
                "from .api_models import ASPResult, ASPDebugResult",
            ),
            (
                "from gps2asp.resolver.exceptions import OutsideNYCError",
                "from .resolver.exceptions import OutsideNYCError",
            ),
            (
                "from gps2asp.signs.exceptions import SODAAPIError, IncompleteResultsError",
                "from .signs.exceptions import SODAAPIError, IncompleteResultsError",
            ),
        ],
    )
    def test_top_level_imports_get_single_dot_prefix(
        self, line_in: str, line_out: str
    ) -> None:
        """Files at gps2asp/__init__.py level: dots = '.', tail keeps full path."""
        result = normalize_source(Path("__init__.py"), line_in + "\n")
        assert result == line_out + "\n"

    # --- Resolver subpackage (pkg_parts = ["resolver"]) ----------------------

    @pytest.mark.parametrize(
        "line_in,line_out",
        [
            (
                "from gps2asp.resolver.confidence import compute_confidence",
                "from .confidence import compute_confidence",
            ),
            (
                "from gps2asp.resolver.converter import convert",
                "from .converter import convert",
            ),
            (
                "from gps2asp.resolver.exceptions import OutsideNYCError",
                "from .exceptions import OutsideNYCError",
            ),
            (
                "from gps2asp.resolver.logging import log_resolution",
                "from .logging import log_resolution",
            ),
            (
                "from gps2asp.resolver.models import ResolutionResult",
                "from .models import ResolutionResult",
            ),
            (
                "from gps2asp.resolver.side_resolver import determine_side",
                "from .side_resolver import determine_side",
            ),
            (
                "from gps2asp.resolver.spatial_index import SpatialIndex",
                "from .spatial_index import SpatialIndex",
            ),
        ],
    )
    def test_resolver_subpackage_imports_strip_subpackage_prefix(
        self, line_in: str, line_out: str
    ) -> None:
        """resolver/X.py: pkg_parts=['resolver'], prefix_len=1, dots='.', leading 'resolver.' stripped."""
        result = normalize_source(Path("resolver/converter.py"), line_in + "\n")
        assert result == line_out + "\n"

    # --- Schedule subpackage (pkg_parts = ["schedule"]) ----------------------

    @pytest.mark.parametrize(
        "line_in,line_out",
        [
            (
                "from gps2asp.schedule.merge import merge_windows",
                "from .merge import merge_windows",
            ),
            (
                "from gps2asp.schedule.models import TimeWindow, WeeklySchedule",
                "from .models import TimeWindow, WeeklySchedule",
            ),
            (
                "from gps2asp.schedule.next_move import find_active_window, find_next_window",
                "from .next_move import find_active_window, find_next_window",
            ),
            (
                "from gps2asp.schedule.parser import parse_sign",
                "from .parser import parse_sign",
            ),
            (
                "from gps2asp.schedule.summary import format_summary",
                "from .summary import format_summary",
            ),
        ],
    )
    def test_schedule_subpackage_imports_strip_subpackage_prefix(
        self, line_in: str, line_out: str
    ) -> None:
        """schedule/X.py: pkg_parts=['schedule'], prefix_len=1, dots='.', leading 'schedule.' stripped."""
        result = normalize_source(Path("schedule/merge.py"), line_in + "\n")
        assert result == line_out + "\n"

    # --- Signs subpackage (pkg_parts = ["signs"]) ----------------------------

    @pytest.mark.parametrize(
        "line_in,line_out",
        [
            (
                "from gps2asp.signs.exceptions import IncompleteResultsError, SODAAPIError",
                "from .exceptions import IncompleteResultsError, SODAAPIError",
            ),
            (
                "from gps2asp.signs.normalize import escape_soql",
                "from .normalize import escape_soql",
            ),
        ],
    )
    def test_signs_subpackage_imports_strip_subpackage_prefix(
        self, line_in: str, line_out: str
    ) -> None:
        """signs/X.py: pkg_parts=['signs'], prefix_len=1, dots='.', leading 'signs.' stripped."""
        result = normalize_source(Path("signs/client.py"), line_in + "\n")
        assert result == line_out + "\n"

    # --- Cross-subpackage (the only `..` case in the oracle) -----------------

    def test_cross_subpackage_imports_use_double_dot_prefix(self) -> None:
        """schedule/__init__.py → signs.models: pkg_parts=['schedule'], target=['signs','models'],
        prefix_len=0, dots='..', tail='signs.models'.
        """
        line_in = "from gps2asp.signs.models import NoMatchFound, SignRetrievalResult"
        line_out = "from ..signs.models import NoMatchFound, SignRetrievalResult"
        result = normalize_source(Path("schedule/__init__.py"), line_in + "\n")
        assert result == line_out + "\n"

    # --- Parenthesized multi-line form ---------------------------------------

    def test_parenthesized_multiline_import_rewrites_only_first_line(self) -> None:
        """Only the line that starts with `from gps2asp.` is rewritten; continuation
        lines (indented) are byte-identical.
        """
        src = (
            "from gps2asp.resolver.exceptions import (\n"
            "    OutsideNYCError,\n"
            "    NoSegmentFoundError,\n"
            ")\n"
        )
        expected = (
            "from .resolver.exceptions import (\n"
            "    OutsideNYCError,\n"
            "    NoSegmentFoundError,\n"
            ")\n"
        )
        assert normalize_source(Path("__init__.py"), src) == expected

    # --- Negative: indented imports (TYPE_CHECKING + docstrings) -------------

    def test_typecheck_and_docstring_imports_untouched(self) -> None:
        """Indented `from gps2asp.X` lines (TYPE_CHECKING blocks or docstring text)
        are not matched by the column-zero regex and must round-trip unchanged.
        """
        src = (
            '"""Module docstring.\n'
            "\n"
            "Usage:\n"
            "    from gps2asp.resolver import resolve_segment\n"
            '"""\n'
            "from __future__ import annotations\n"
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from gps2asp.resolver.models import ResolutionDebugInfo\n"
        )
        # Pass a rel_path that would otherwise have rewritten these had they
        # been at column zero.
        assert normalize_source(Path("__init__.py"), src) == src

    # --- Negative: gps2asp_helpers (underscore variant must NOT match) -------

    def test_unrelated_imports_untouched(self) -> None:
        """The regex must NOT match `gps2asp_helpers` (an unrelated hypothetical
        package whose name starts with the same characters) nor any non-`gps2asp.`
        imports.
        """
        src = (
            "from __future__ import annotations\n"
            "from pathlib import Path\n"
            "import re\n"
            "from gps2asp_helpers.foo import bar\n"
        )
        assert normalize_source(Path("__init__.py"), src) == src


# ---------------------------------------------------------------------------
# Integration tests: CLI dry-run / write contract
# ---------------------------------------------------------------------------


def _stage_source(src_root: Path, rel: str, text: str) -> Path:
    """Write a source file rooted under src_root and return its path."""
    p = src_root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _stage_vendor(vendor_root: Path, rel: str, text: str) -> Path:
    """Write a vendor file rooted under vendor_root and return its path."""
    p = vendor_root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


@pytest.fixture
def staged_trees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    """Set up isolated SRC_ROOT and VENDOR_ROOT inside tmp_path and patch the module.

    Returns (src_root, vendor_root).
    """
    src_root = tmp_path / "src" / "gps2asp"
    vendor_root = tmp_path / "vendor" / "gps2asp"
    src_root.mkdir(parents=True)
    vendor_root.mkdir(parents=True)
    monkeypatch.setattr(sync_vendored, "SRC_ROOT", src_root)
    monkeypatch.setattr(sync_vendored, "VENDOR_ROOT", vendor_root)
    # argparse reads from sys.argv -- ensure no stray pytest argv leaks in.
    monkeypatch.setattr(sys, "argv", ["sync_vendored.py"])
    return src_root, vendor_root


class TestCliDryRun:
    """Integration tests for main() exit-code + stdout contract."""

    def test_dry_run_in_sync_exits_zero(
        self,
        staged_trees: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """When vendor matches normalized source, --dry-run exits 0 with the
        in-sync message.
        """
        src_root, vendor_root = staged_trees
        _stage_source(
            src_root, "__init__.py", "from gps2asp.pipeline import resolve_asp\n"
        )
        _stage_source(
            src_root,
            "resolver/converter.py",
            "from gps2asp.resolver.exceptions import OutsideNYCError\n",
        )
        # Vendor copies are the normalized form.
        _stage_vendor(vendor_root, "__init__.py", "from .pipeline import resolve_asp\n")
        _stage_vendor(
            vendor_root,
            "resolver/converter.py",
            "from .exceptions import OutsideNYCError\n",
        )

        monkeypatch.setattr(sys, "argv", ["sync_vendored.py", "--dry-run"])
        exit_code = sync_vendored.main()
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "in sync" in captured.out.lower()

    def test_dry_run_detects_drift(
        self,
        staged_trees: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Mutating one vendor file → exit 1; stdout names the drifted relative
        path and hints at the re-run command.
        """
        src_root, vendor_root = staged_trees
        _stage_source(
            src_root,
            "resolver/converter.py",
            "from gps2asp.resolver.exceptions import OutsideNYCError\n",
        )
        # Vendor file: wrong text (extra stray comment).
        _stage_vendor(
            vendor_root,
            "resolver/converter.py",
            "from .exceptions import OutsideNYCError\n# DRIFT MARKER\n",
        )

        monkeypatch.setattr(sys, "argv", ["sync_vendored.py", "--dry-run"])
        exit_code = sync_vendored.main()
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "resolver/converter.py" in captured.out
        # The re-run hint must mention the script name so CI consumers know how to fix.
        assert "sync_vendored.py" in captured.out

    def test_dry_run_detects_missing_vendor_file(
        self,
        staged_trees: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A source file with no vendor counterpart counts as drift."""
        src_root, _ = staged_trees
        _stage_source(
            src_root, "pipeline.py", "from gps2asp.api_models import ASPResult\n"
        )

        monkeypatch.setattr(sys, "argv", ["sync_vendored.py", "--dry-run"])
        exit_code = sync_vendored.main()
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "pipeline.py" in captured.out

    def test_write_mode_creates_vendor_file_and_dry_run_after_is_clean(
        self,
        staged_trees: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Write mode writes the normalized text; a subsequent --dry-run exits 0
        (round-trip stability).
        """
        src_root, vendor_root = staged_trees
        _stage_source(
            src_root, "pipeline.py", "from gps2asp.api_models import ASPResult\n"
        )

        # First call: write mode.
        monkeypatch.setattr(sys, "argv", ["sync_vendored.py"])
        exit_code = sync_vendored.main()
        capsys.readouterr()  # discard write-mode stdout
        assert exit_code == 0
        vendor_file = vendor_root / "pipeline.py"
        assert vendor_file.exists()
        assert vendor_file.read_text(encoding="utf-8") == (
            "from .api_models import ASPResult\n"
        )

        # Second call: dry-run on the post-write tree should be clean.
        monkeypatch.setattr(sys, "argv", ["sync_vendored.py", "--dry-run"])
        exit_code = sync_vendored.main()
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "in sync" in captured.out.lower()

    def test_data_subtree_is_excluded(
        self,
        staged_trees: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A .py file under ``src/gps2asp/data/`` is not considered: neither
        flagged as drift in dry-run nor written in write mode.
        """
        src_root, vendor_root = staged_trees
        _stage_source(src_root, "data/index_helper.py", "# kept under data/\n")

        # Dry-run on a tree with no src files outside data/ → in sync.
        monkeypatch.setattr(sys, "argv", ["sync_vendored.py", "--dry-run"])
        exit_code = sync_vendored.main()
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "data/index_helper.py" not in captured.out

        # Write mode → no vendor counterpart is created.
        monkeypatch.setattr(sys, "argv", ["sync_vendored.py"])
        exit_code = sync_vendored.main()
        capsys.readouterr()
        assert exit_code == 0
        assert not (vendor_root / "data" / "index_helper.py").exists()

    def test_dry_run_detects_stale_vendor_file(
        self,
        staged_trees: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A vendor .py file with no src counterpart must be flagged as drift."""
        _src_root, vendor_root = staged_trees
        # No source files — only a stale vendor file with no src counterpart.
        _stage_vendor(vendor_root, "deleted_module.py", "# stale\n")

        monkeypatch.setattr(sys, "argv", ["sync_vendored.py", "--dry-run"])
        exit_code = sync_vendored.main()
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "deleted_module.py" in captured.out

    def test_write_mode_deletes_stale_vendor_file(
        self,
        staged_trees: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Write mode must physically delete a stale vendor file that has no src
        counterpart and exit 0. Covers the vendor_py.unlink() branch."""
        src_root, vendor_root = staged_trees
        # One real source file so src_written/unchanged are non-trivial.
        _stage_source(src_root, "pipeline.py", "from gps2asp.api_models import ASPResult\n")
        _stage_vendor(vendor_root, "pipeline.py", "from .api_models import ASPResult\n")
        # Stale vendor file with no src counterpart.
        stale_file = _stage_vendor(vendor_root, "deleted_module.py", "# stale\n")
        assert stale_file.exists()

        monkeypatch.setattr(sys, "argv", ["sync_vendored.py"])
        exit_code = sync_vendored.main()
        captured = capsys.readouterr()

        assert exit_code == 0
        assert not stale_file.exists(), "stale vendor file should have been deleted"
        # Summary must mention the deleted count.
        assert "deleted 1 stale file" in captured.out
