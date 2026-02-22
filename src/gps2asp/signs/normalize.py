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

    Applies directional prefix expansion first (only when followed by
    a digit, to avoid false positives like "ESSEX" -> "EASTSSEX"),
    then suffix expansion.

    Args:
        cscl_name: Street name in CSCL format (e.g., "3 AVE").

    Returns:
        Street name in SODA format (e.g., "3 AVENUE").

    Examples:
        >>> normalize_to_soda("3 AVE")
        '3 AVENUE'
        >>> normalize_to_soda("E  100 ST")
        'EAST  100 STREET'
        >>> normalize_to_soda("PROSPECT PL")
        'PROSPECT PLACE'
        >>> normalize_to_soda("ESSEX ST")
        'ESSEX STREET'
    """
    name = cscl_name.upper().strip()

    # Expand directional prefix: only if the character after the
    # abbreviation + space is a digit (e.g., "E 100 ST" but NOT "ESSEX ST")
    for abbrev, full in _DIRECTIONAL_EXPANSIONS.items():
        prefix = abbrev + " "
        if name.startswith(prefix):
            rest = name[len(prefix):]
            # Check if the next non-space character is a digit
            stripped_rest = rest.lstrip()
            if stripped_rest and stripped_rest[0].isdigit():
                name = full + " " + rest
                break

    # Expand suffix abbreviation: match the last word against known suffixes
    parts = name.rsplit(maxsplit=1)
    if len(parts) == 2:
        prefix_part, suffix_part = parts
        if suffix_part in _SUFFIX_EXPANSIONS:
            name = prefix_part + " " + _SUFFIX_EXPANSIONS[suffix_part]

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
