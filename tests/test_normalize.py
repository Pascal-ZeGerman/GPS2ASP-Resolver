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
        # Internal whitespace is collapsed before expansion so double-space
        # in CSCL "E  100 ST" is normalized to single-space "EAST 100 STREET".
        assert normalize_to_soda("E  100 ST") == "EAST 100 STREET"

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

    def test_whitespace_internal_collapsed(self) -> None:
        """Internal multiple spaces are collapsed to single space.

        CSCL uses variable spacing (e.g., "E  100 ST" with two spaces) but
        SODA uses different variable spacing (e.g., "EAST   100 STREET" with
        three spaces). Collapsing to single spaces ensures consistent matching.
        """
        assert normalize_to_soda("E  100 ST") == "EAST 100 STREET"

    def test_lowercase_input(self) -> None:
        assert normalize_to_soda("prospect pl") == "PROSPECT PLACE"

    def test_mixed_case_input(self) -> None:
        assert normalize_to_soda("Court St") == "COURT STREET"

    # Named directional prefix cases (prefix + named street, not prefix + digit)
    def test_named_directional_prefix_w_broadway(self) -> None:
        """W BROADWAY should become WEST BROADWAY."""
        assert normalize_to_soda("W BROADWAY") == "WEST BROADWAY"

    def test_named_directional_prefix_e_broadway(self) -> None:
        """E BROADWAY should become EAST BROADWAY."""
        assert normalize_to_soda("E BROADWAY") == "EAST BROADWAY"

    def test_named_directional_prefix_n_henry_st(self) -> None:
        """N HENRY ST should become NORTH HENRY STREET."""
        assert normalize_to_soda("N HENRY ST") == "NORTH HENRY STREET"

    def test_named_directional_prefix_s_elliott_pl(self) -> None:
        """S ELLIOTT PL should become SOUTH ELLIOTT PLACE."""
        assert normalize_to_soda("S ELLIOTT PL") == "SOUTH ELLIOTT PLACE"

    def test_named_directional_prefix_w_end_ave(self) -> None:
        """W END AVE should become WEST END AVENUE."""
        assert normalize_to_soda("W END AVE") == "WEST END AVENUE"

    # Named directional suffix cases (street name + directional suffix)
    def test_named_directional_suffix_central_park_w(self) -> None:
        """CENTRAL PARK W should become CENTRAL PARK WEST."""
        assert normalize_to_soda("CENTRAL PARK W") == "CENTRAL PARK WEST"

    def test_named_directional_suffix_central_park_s(self) -> None:
        """CENTRAL PARK S should become CENTRAL PARK SOUTH."""
        assert normalize_to_soda("CENTRAL PARK S") == "CENTRAL PARK SOUTH"

    # No false positives for words that begin with directional letters
    def test_no_false_positive_northern_blvd(self) -> None:
        """NORTHERN BLVD should NOT expand N prefix."""
        assert normalize_to_soda("NORTHERN BLVD") == "NORTHERN BOULEVARD"

    def test_no_false_positive_western_ave(self) -> None:
        """WESTERN AVE should NOT expand W prefix."""
        assert normalize_to_soda("WESTERN AVE") == "WESTERN AVENUE"


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
