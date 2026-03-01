"""Street name normalization between CSCL and SODA formats.

CSCL (Citywide Street Centerline) uses abbreviated suffixes and
directional prefixes (e.g., "3 AVE", "E 100 ST", "PROSPECT PL").
The SODA parking signs dataset uses full words (e.g., "3 AVENUE",
"EAST 100 STREET", "PROSPECT PLACE").

This module converts between the two formats for query construction.
"""

from __future__ import annotations

# Suffix mappings: CSCL abbreviation -> SODA full word
# Verified against live SODA API data (2026-02-21)
_SUFFIX_EXPANSIONS: dict[str, str] = {
    "AVE": "AVENUE",
    "ST": "STREET",
    "PL": "PLACE",
    "BLVD": "BOULEVARD",
    "DR": "DRIVE",
    "CT": "COURT",
    "RD": "ROAD",
    "LN": "LANE",
    "TER": "TERRACE",
    "PKWY": "PARKWAY",
    "EXPY": "EXPRESSWAY",
    "HWY": "HIGHWAY",
    "SQ": "SQUARE",
    "CIR": "CIRCLE",
}

# Directional prefix mappings: CSCL abbreviation -> SODA full word
_DIRECTIONAL_EXPANSIONS: dict[str, str] = {
    "E": "EAST",
    "W": "WEST",
    "N": "NORTH",
    "S": "SOUTH",
}


def normalize_to_soda(cscl_name: str) -> str:
    """Convert CSCL street name format to SODA parking signs format.

    Expansion order:
    1. Directional prefix: "E/W/N/S " followed by any non-empty continuation.
       The "abbrev + space" guard prevents false positives like ESSEX (no
       space after E) and NORTHERN (starts with "N" not "N ").
    2. Suffix abbreviation: last word matched against _SUFFIX_EXPANSIONS.
    3. Directional suffix: last word matched against _DIRECTIONAL_EXPANSIONS,
       e.g., "CENTRAL PARK W" -> "CENTRAL PARK WEST". Must run after step 2
       so "W END AVE" becomes "WEST END AVENUE", not "WEST END AVE".

    Args:
        cscl_name: Street name in CSCL format (e.g., "3 AVE").

    Returns:
        Street name in SODA format (e.g., "3 AVENUE").

    Examples:
        >>> normalize_to_soda("3 AVE")
        '3 AVENUE'
        >>> normalize_to_soda("E  100 ST")
        'EAST 100 STREET'
        >>> normalize_to_soda("PROSPECT PL")
        'PROSPECT PLACE'
        >>> normalize_to_soda("ESSEX ST")
        'ESSEX STREET'
        >>> normalize_to_soda("W BROADWAY")
        'WEST BROADWAY'
        >>> normalize_to_soda("CENTRAL PARK W")
        'CENTRAL PARK WEST'
        >>> normalize_to_soda("W END AVE")
        'WEST END AVENUE'
    """
    # Collapse internal whitespace: CSCL may have "E  100 ST" (2 spaces) and
    # SODA has "EAST   100 STREET" (3 spaces). Normalizing to single spaces
    # ensures consistent matching between the two datasets.
    name = " ".join(cscl_name.upper().split())

    # Step 1: Expand directional prefix.
    # The "abbrev + space" guard ensures "ESSEX" (no space after E) and
    # "NORTHERN" (starts with "N" not "N ") are never candidates.
    for abbrev, full in _DIRECTIONAL_EXPANSIONS.items():
        prefix = abbrev + " "
        if name.startswith(prefix):
            rest = name[len(prefix):]
            stripped_rest = rest.lstrip()
            if stripped_rest:
                name = full + " " + rest
                break

    # Step 2: Expand suffix abbreviation: match the last word against known
    # suffixes (e.g., "W END AVE" -> "WEST END AVENUE").
    parts = name.rsplit(maxsplit=1)
    if len(parts) == 2:
        prefix_part, suffix_part = parts
        if suffix_part in _SUFFIX_EXPANSIONS:
            name = prefix_part + " " + _SUFFIX_EXPANSIONS[suffix_part]

    # Step 3: Expand directional suffix: last word as standalone directional
    # token (e.g., "CENTRAL PARK W" -> "CENTRAL PARK WEST").
    # Must run after step 2 so suffix abbreviations are already expanded.
    parts = name.rsplit(maxsplit=1)
    if len(parts) == 2:
        prefix_part, last_word = parts
        if last_word in _DIRECTIONAL_EXPANSIONS:
            name = prefix_part + " " + _DIRECTIONAL_EXPANSIONS[last_word]

    return name


def name_variants(cscl_name: str) -> list[str]:
    """Generate name variants for fallback matching.

    Returns the SODA format first (since it is the format used in the
    parking signs dataset), followed by the original CSCL format if
    it differs.

    Args:
        cscl_name: Street name in CSCL format.

    Returns:
        List of 1-2 name variants, SODA format first.

    Examples:
        >>> name_variants("3 AVE")
        ['3 AVENUE', '3 AVE']
        >>> name_variants("BROADWAY")
        ['BROADWAY']
    """
    soda = normalize_to_soda(cscl_name)
    original = cscl_name.upper().strip()
    variants = [soda]
    if original != soda:
        variants.append(original)
    return variants


def escape_soql(value: str) -> str:
    """Escape a string value for use in SoQL $where clauses.

    Single quotes are the string delimiter in SoQL and must be
    doubled to be included literally (e.g., O'BRIEN -> O''BRIEN).

    Args:
        value: Raw string value to escape.

    Returns:
        Escaped string safe for SoQL interpolation.

    Examples:
        >>> escape_soql("O'BRIEN")
        "O''BRIEN"
        >>> escape_soql("BROADWAY")
        'BROADWAY'
    """
    return value.replace("'", "''")
