"""Presentation-label constants shared by the live HA integration and the
offline dataset dumper scripts.

Split out of ``dataset_common`` so importing these plain dicts (from
``coordinator.py`` and ``sensor.py``) doesn't also pull in that module's
pyproj/asyncio dumper plumbing, which HA never uses.
"""

from __future__ import annotations

# CSCL borough code -> human name. Single source of truth shared by
# coordinator.py and both offline dataset dumpers so the three never drift.
BOROUGH_NAMES: dict[str, str] = {
    "1": "Manhattan",
    "2": "Bronx",
    "3": "Brooklyn",
    "4": "Queens",
    "5": "Staten Island",
}


def borough_name(borocode: str | None) -> str | None:
    """Map a CSCL borough code to its human name, or None when unknown."""
    if borocode is None:
        return None
    return BOROUGH_NAMES.get(str(borocode))


# side_of_street letter -> display label. Single source of truth shared by
# sensor.py and build_demo_dataset.py so the two never drift.
SIDE_LABELS: dict[str, str] = {
    "N": "North side",
    "S": "South side",
    "E": "East side",
    "W": "West side",
}
