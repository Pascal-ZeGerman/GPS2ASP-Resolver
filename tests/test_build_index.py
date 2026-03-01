"""Unit tests for scripts/build_index.py bug fixes.

Tests for three fixed functions:
1. _normalize_street_name() — directional prefix expansion (Bug 1)
2. _find_cross_street() — dead-end returns "" not "DEAD END" (Bug 3)
3. _fetch_asp_signs() — voided sign filter (Bug 2)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add scripts/ to sys.path so we can import build_index
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from build_index import _find_cross_street, _normalize_street_name


class TestNormalizeStreetName:
    def test_directional_east(self):
        assert _normalize_street_name("E 100 ST") == "EAST 100 STREET"

    def test_directional_west(self):
        assert _normalize_street_name("W 4 ST") == "WEST 4 STREET"

    def test_directional_north(self):
        assert _normalize_street_name("N 10 AVE") == "NORTH 10 AVENUE"

    def test_suffix_only(self):
        assert _normalize_street_name("PROSPECT PL") == "PROSPECT PLACE"

    def test_no_false_positive_essex(self):
        # "ESSEX ST" starts with "E" but next char is "S" not a digit -- no expansion
        assert _normalize_street_name("ESSEX ST") == "ESSEX STREET"

    def test_empty_string(self):
        assert _normalize_street_name("") == ""

    def test_lowercase_input(self):
        # Function should uppercase internally
        assert _normalize_street_name("e 100 st") == "EAST 100 STREET"


class TestFindCrossStreet:
    def test_dead_end_returns_empty_string(self):
        # Empty node_lookup means no cross streets found -- should return ""
        result = _find_cross_street(
            node=(100, 200),
            own_pid=42,
            own_name="MAIN STREET",
            node_lookup={},
        )
        assert result == ""
        assert result != "DEAD END"

    def test_cross_street_found(self):
        # Node lookup has a different street at the same node
        node_lookup = {(100, 200): [(99, "BROADWAY")]}
        result = _find_cross_street(
            node=(100, 200),
            own_pid=42,
            own_name="MAIN STREET",
            node_lookup=node_lookup,
        )
        assert result == "BROADWAY"


class TestFetchAspSignsFilter:
    def test_uses_voided_date_filter(self, monkeypatch):
        """_fetch_asp_signs() must use sign_design_voided_on_date IS NULL filter."""
        from build_index import _fetch_asp_signs
        import requests

        captured_params = {}

        class MockResponse:
            def raise_for_status(self): pass
            def json(self): return []  # empty list stops the loop

        def mock_get(url, params=None, headers=None, timeout=None):
            captured_params.update(params or {})
            return MockResponse()

        monkeypatch.setattr(requests, "get", mock_get)
        _fetch_asp_signs()

        where_clause = captured_params.get("$where", "")
        assert "sign_design_voided_on_date IS NULL" in where_clause
        assert "record_type" not in where_clause
