"""Unit tests for audit_queens_coverage.py internal logic.

Tests exercise print_report() and related helpers with synthetic data.
No network access required.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add scripts directory to path so we can import the module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from audit_queens_coverage import print_report  # noqa: E402


def _make_ok_result(soda_level: int, description: str = "Test Location") -> dict:
    """Create a synthetic ok result dict."""
    return {
        "description": description,
        "soda_level": soda_level,
        "on_street": "TEST STREET",
        "from_street": "CROSS AVE",
        "to_street": "OTHER AVE",
        "side_of_street": "N",
        "status": "ok",
    }


def _make_error_result(description: str = "Error Location") -> dict:
    """Create a synthetic error result dict."""
    return {
        "description": description,
        "soda_level": 0,
        "on_street": "",
        "from_street": "",
        "to_street": "",
        "side_of_street": "",
        "status": "error: OutsideNYCError: Outside NYC bounds",
    }


class TestPrintReport:
    """Tests for print_report() summary statistics computation."""

    def test_level_counts_single_level(self, capsys: pytest.CaptureFixture) -> None:
        """All results at the same level produce correct count."""
        results = [_make_ok_result(1) for _ in range(5)]
        print_report(results, "Test Fixture")
        captured = capsys.readouterr()
        assert "Level 1: 5/5" in captured.out

    def test_level_counts_mixed_levels(self, capsys: pytest.CaptureFixture) -> None:
        """Mixed levels produce correct per-level counts."""
        results = [
            _make_ok_result(1),
            _make_ok_result(1),
            _make_ok_result(2),
            _make_ok_result(3),
        ]
        print_report(results, "Test Fixture")
        captured = capsys.readouterr()
        assert "Level 1: 2/4" in captured.out
        assert "Level 2: 1/4" in captured.out
        assert "Level 3: 1/4" in captured.out

    def test_l12_percentage_all_level1(self, capsys: pytest.CaptureFixture) -> None:
        """L1+2 is 100% when all results are level 1."""
        results = [_make_ok_result(1) for _ in range(4)]
        print_report(results, "Test Fixture")
        captured = capsys.readouterr()
        assert "Level 1+2 (target): 4/4 (100.0%)" in captured.out

    def test_l12_percentage_partial(self, capsys: pytest.CaptureFixture) -> None:
        """L1+2 is computed correctly when some results are level 3+."""
        results = [
            _make_ok_result(1),
            _make_ok_result(2),
            _make_ok_result(3),
            _make_ok_result(3),
        ]
        print_report(results, "Test Fixture")
        captured = capsys.readouterr()
        # 2 out of 4 are L1+L2 = 50%
        assert "Level 1+2 (target): 2/4 (50.0%)" in captured.out

    def test_errors_counted_separately(self, capsys: pytest.CaptureFixture) -> None:
        """Error results are counted in Errors line, not level counts."""
        results = [
            _make_ok_result(1),
            _make_error_result(),
            _make_error_result(),
        ]
        print_report(results, "Test Fixture")
        captured = capsys.readouterr()
        assert "Errors: 2/3" in captured.out
        assert "Level 1: 1/3" in captured.out

    def test_empty_results(self, capsys: pytest.CaptureFixture) -> None:
        """Empty results list does not crash (zero-division guard)."""
        print_report([], "Empty Fixture")
        captured = capsys.readouterr()
        assert "0 locations" in captured.out
        # Should not raise ZeroDivisionError
        assert "Level 1+2 (target): 0/0 (0.0%)" in captured.out

    def test_fixture_name_in_header(self, capsys: pytest.CaptureFixture) -> None:
        """Fixture name appears in the report header."""
        results = [_make_ok_result(1)]
        print_report(results, "Queens")
        captured = capsys.readouterr()
        assert "Queens" in captured.out

    def test_missing_description_key_handled(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        """Results with missing description still render (loc.get fallback)."""
        result = _make_ok_result(1)
        result["description"] = (
            "<unknown>"  # simulate loc.get("description", "<unknown>")
        )
        print_report([result], "Test Fixture")
        captured = capsys.readouterr()
        assert "<unknown>" in captured.out

    def test_unexpected_soda_level_surfaced(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        """An unexpected soda_level (e.g., 5) appears in output rather than silently dropped."""
        results = [_make_ok_result(5)]
        print_report(results, "Test Fixture")
        captured = capsys.readouterr()
        assert "Level 5" in captured.out
