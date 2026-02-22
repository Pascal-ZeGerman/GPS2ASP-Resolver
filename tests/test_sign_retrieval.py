"""Integration tests for sign retrieval against live SODA API.

These tests require network access to data.cityofnewyork.us and are
skipped when the endpoint is unreachable. Marked with @pytest.mark.integration.

All tests are async (pytest-asyncio with asyncio_mode = auto).
"""

from __future__ import annotations

import socket

import pytest

from gps2asp.signs import (
    NoASPSigns,
    NoMatchFound,
    SignRetrievalSuccess,
    retrieve_signs,
)


def _soda_reachable() -> bool:
    """Check if the SODA API endpoint is reachable."""
    try:
        socket.create_connection(("data.cityofnewyork.us", 443), timeout=5)
        return True
    except OSError:
        return False


skip_no_network = pytest.mark.skipif(
    not _soda_reachable(),
    reason="SODA API unreachable (data.cityofnewyork.us:443)",
)

integration = pytest.mark.integration


# ── Known ASP block ──────────────────────────────────────────────────


@skip_no_network
@integration
async def test_retrieve_signs_known_asp_block() -> None:
    """Prospect Place between Carlton Ave and Vanderbilt Ave (North side).

    Known to have ASP broom signs. Validates SIGN-01 (query works).
    """
    result = await retrieve_signs(
        on_street="PROSPECT PLACE",
        from_street="CARLTON AVENUE",
        to_street="VANDERBILT AVENUE",
        side_of_street="N",
    )

    assert isinstance(result, SignRetrievalSuccess), (
        f"Expected SignRetrievalSuccess, got {type(result).__name__}"
    )
    assert result.status == "signs_found"
    assert len(result.signs) >= 1

    # Verify at least one sign mentions broom
    descriptions = [s.sign_description for s in result.signs]
    assert any(
        "BROOM" in desc.upper() for desc in descriptions
    ), f"No broom sign found in: {descriptions}"


# ── Name normalization fallback ──────────────────────────────────────


@skip_no_network
@integration
async def test_retrieve_signs_name_normalization() -> None:
    """Call with CSCL abbreviated names -- fallback should still find signs.

    Uses abbreviated forms (PL, AVE) instead of full SODA names.
    """
    result = await retrieve_signs(
        on_street="PROSPECT PL",
        from_street="CARLTON AVE",
        to_street="VANDERBILT AVE",
        side_of_street="N",
    )

    assert isinstance(result, SignRetrievalSuccess), (
        f"Expected SignRetrievalSuccess with abbreviated names, "
        f"got {type(result).__name__}"
    )
    assert len(result.signs) >= 1


# ── Deduplication ────────────────────────────────────────────────────


@skip_no_network
@integration
async def test_retrieve_signs_deduplication() -> None:
    """Block with multiple identical sign posts should be deduplicated.

    Research shows blocks can have up to 46 identical sign records.
    The deduplicated count should be small (typically 1-2 per block).
    """
    result = await retrieve_signs(
        on_street="PROSPECT PLACE",
        from_street="CARLTON AVENUE",
        to_street="VANDERBILT AVENUE",
        side_of_street="N",
    )

    assert isinstance(result, SignRetrievalSuccess)
    # Deduplicated: should have far fewer records than raw SODA output
    # Typically 1-2 unique sign descriptions per block-face
    assert len(result.signs) <= 5, (
        f"Expected <= 5 unique signs after dedup, got {len(result.signs)}"
    )


# ── No ASP street ───────────────────────────────────────────────────


@skip_no_network
@integration
async def test_retrieve_signs_no_asp_street() -> None:
    """A street name unlikely to have ASP signs should return NoASPSigns or NoMatchFound.

    Use a fabricated street name that should not exist in SODA.
    """
    result = await retrieve_signs(
        on_street="NONEXISTENT FAKE STREET ZZZZZ",
        from_street="ALSO FAKE AVENUE ZZZZZ",
        to_street="ANOTHER FAKE BLVD ZZZZZ",
        side_of_street="N",
    )

    assert not isinstance(result, SignRetrievalSuccess), (
        f"Expected NoASPSigns or NoMatchFound for fake street, "
        f"got SignRetrievalSuccess with {len(result.signs)} signs"
    )
    assert isinstance(result, (NoASPSigns, NoMatchFound))


# ── No voided signs ─────────────────────────────────────────────────


@skip_no_network
@integration
async def test_retrieve_signs_no_voided_signs() -> None:
    """Returned signs should not contain voided/superseded designs (SIGN-02).

    Check that no sign descriptions contain "SUPERSEDED BY" text.
    """
    result = await retrieve_signs(
        on_street="PROSPECT PLACE",
        from_street="CARLTON AVENUE",
        to_street="VANDERBILT AVENUE",
        side_of_street="N",
    )

    assert isinstance(result, SignRetrievalSuccess)
    for sign in result.signs:
        assert "SUPERSEDED" not in sign.sign_description.upper(), (
            f"Voided sign found: {sign.sign_description}"
        )


# ── Result uses input names ─────────────────────────────────────────


@skip_no_network
@integration
async def test_retrieve_signs_result_uses_input_names() -> None:
    """Result should use CSCL input names, not SODA-converted names.

    When calling with abbreviated CSCL names, the returned result
    should preserve those original input names.
    """
    result = await retrieve_signs(
        on_street="PROSPECT PL",
        from_street="CARLTON AVE",
        to_street="VANDERBILT AVE",
        side_of_street="N",
    )

    assert isinstance(result, SignRetrievalSuccess)
    # Result should reflect the input names, NOT the expanded SODA names
    assert result.on_street == "PROSPECT PL"
    assert result.from_street == "CARLTON AVE"
    assert result.to_street == "VANDERBILT AVE"
    assert result.side_of_street == "N"
