"""Data models for ASP sign retrieval results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class SignRecord:
    """A single ASP sign description for a block-face.

    Attributes:
        sign_description: Full text of the sign (e.g.,
            "NO PARKING (SANITATION BROOM SYMBOL) MON & THURS 8-9:30AM").
    """

    sign_description: str


@dataclass(frozen=True)
class SignRetrievalSuccess:
    """Signs found for the requested block-face.

    Location fields use CSCL names from Phase 1 input, NOT SODA names.

    Attributes:
        status: Discriminator literal "signs_found".
        signs: Deduplicated list of sign records for this block-face.
        on_street: The street name in CSCL format (e.g., "PROSPECT PL").
        from_street: Cross street at one end in CSCL format.
        to_street: Cross street at the other end in CSCL format.
        side_of_street: Compass direction side - N, S, E, or W.
        soda_level: Which fallback level matched (1, 2, 3, or 4). Defaults to 1
            for any site that does not explicitly specify a level.
    """

    status: Literal["signs_found"]
    signs: list[SignRecord]
    on_street: str
    from_street: str
    to_street: str
    side_of_street: str
    soda_level: int = 1  # 1, 2, 3, or 4 — which fallback level matched


@dataclass(frozen=True)
class NoASPSigns:
    """Street segment exists in SODA but has no ASP/broom signs.

    Distinct from an empty list -- this means the location was found
    but legitimately has no alternate side parking.

    Attributes:
        status: Discriminator literal "no_asp".
    """

    status: Literal["no_asp"] = "no_asp"


@dataclass(frozen=True)
class NoMatchFound:
    """All three fallback levels exhausted; no matching segment in SODA.

    Attributes:
        status: Discriminator literal "no_match".
    """

    status: Literal["no_match"] = "no_match"


# Discriminated union of all possible sign retrieval outcomes.
SignRetrievalResult = SignRetrievalSuccess | NoASPSigns | NoMatchFound
