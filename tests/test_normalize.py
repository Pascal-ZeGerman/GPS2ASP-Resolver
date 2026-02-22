"""Unit tests for street name normalization (CSCL to SODA format).

No network required -- these test pure string transformations.
"""

from __future__ import annotations

from gps2asp.signs.normalize import escape_soql, name_variants, normalize_to_soda


# ── normalize_to_soda ────────────────────────────────────────────────


class TestNormalizeToSoda:
    """Tests for CSCL -> SODA street name conversion."""

    def test_suffix_expansion_ave(self) -> None:
        assert normalize_to_soda("3 AVE") == "3 AVENUE"

    def test_suffix_expansion_pl(self) -> None:
        assert normalize_to_soda("PROSPECT PL") == "PROSPECT PLACE"

    def test_suffix_expansion_blvd(self) -> None:
        assert normalize_to_soda("ATLANTIC BLVD") == "ATLANTIC BOULEVARD"

    def test_suffix_expansion_st(self) -> None:
        assert normalize_to_soda("COURT ST") == "COURT STREET"

    def test_suffix_expansion_dr(self) -> None:
        assert normalize_to_soda("OCEAN DR") == "OCEAN DRIVE"

    def test_suffix_expansion_rd(self) -> None:
        assert normalize_to_soda("FLATBUSH RD") == "FLATBUSH ROAD"

    def test_suffix_expansion_ln(self) -> None:
        assert normalize_to_soda("AMBOY LN") == "AMBOY LANE"

    def test_suffix_expansion_ter(self) -> None:
        assert normalize_to_soda("PARK TER") == "PARK TERRACE"

    def test_directional_expansion_east(self) -> None:
        assert normalize_to_soda("E  100 ST") == "EAST  100 STREET"

    def test_directional_expansion_west(self) -> None:
        assert normalize_to_soda("W 4 ST") == "WEST 4 STREET"

    def test_directional_expansion_north(self) -> None:
        assert normalize_to_soda("N 6 ST") == "NORTH 6 STREET"

    def test_directional_expansion_south(self) -> None:
        assert normalize_to_soda("S 5 PL") == "SOUTH 5 PLACE"

    def test_directional_not_expanded_essex(self) -> None:
        """ESSEX ST should NOT become EASTSSEX STREET."""
        assert normalize_to_soda("ESSEX ST") == "ESSEX STREET"

    def test_directional_not_expanded_sterling(self) -> None:
        """STERLING PL should NOT be affected by S-prefix rule."""
        assert normalize_to_soda("STERLING PL") == "STERLING PLACE"

    def test_directional_not_expanded_west_word(self) -> None:
        """WESTERN BLVD should NOT expand W prefix (not followed by digit)."""
        # "WESTERN" doesn't start with "W " (no space after W)
        assert normalize_to_soda("WESTERN BLVD") == "WESTERN BOULEVARD"

    def test_already_expanded_passthrough(self) -> None:
        assert normalize_to_soda("3 AVENUE") == "3 AVENUE"

    def test_already_expanded_place(self) -> None:
        assert normalize_to_soda("PROSPECT PLACE") == "PROSPECT PLACE"

    def test_already_expanded_street(self) -> None:
        assert normalize_to_soda("BROADWAY") == "BROADWAY"

    def test_whitespace_leading_trailing_stripped(self) -> None:
        assert normalize_to_soda("  3 AVE  ") == "3 AVENUE"

    def test_whitespace_internal_preserved(self) -> None:
        """Internal whitespace is preserved (SODA may have extra spaces)."""
        assert normalize_to_soda("E  100 ST") == "EAST  100 STREET"

    def test_lowercase_input(self) -> None:
        assert normalize_to_soda("prospect pl") == "PROSPECT PLACE"

    def test_mixed_case_input(self) -> None:
        assert normalize_to_soda("Court St") == "COURT STREET"


# ── name_variants ────────────────────────────────────────────────────


class TestNameVariants:
    """Tests for name variant generation."""

    def test_returns_two_variants_when_different(self) -> None:
        variants = name_variants("3 AVE")
        assert variants == ["3 AVENUE", "3 AVE"]

    def test_soda_format_first(self) -> None:
        variants = name_variants("PROSPECT PL")
        assert variants[0] == "PROSPECT PLACE"

    def test_returns_one_variant_when_same(self) -> None:
        variants = name_variants("BROADWAY")
        assert variants == ["BROADWAY"]

    def test_returns_one_when_already_expanded(self) -> None:
        variants = name_variants("3 AVENUE")
        assert variants == ["3 AVENUE"]

    def test_directional_produces_two_variants(self) -> None:
        variants = name_variants("E 100 ST")
        assert len(variants) == 2
        assert variants[0] == "EAST 100 STREET"
        assert variants[1] == "E 100 ST"


# ── escape_soql ──────────────────────────────────────────────────────


class TestEscapeSoql:
    """Tests for SoQL string escaping."""

    def test_single_quote_escaped(self) -> None:
        assert escape_soql("O'BRIEN") == "O''BRIEN"

    def test_no_quotes_unchanged(self) -> None:
        assert escape_soql("BERGEN STREET") == "BERGEN STREET"

    def test_multiple_quotes(self) -> None:
        assert escape_soql("D'A'COSTA") == "D''A''COSTA"

    def test_empty_string(self) -> None:
        assert escape_soql("") == ""
