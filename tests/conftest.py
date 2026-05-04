"""Shared pytest fixtures for GPS2ASP tests.

Provides session-scoped index loading and per-test singleton reset.
Integration tests are skipped if the spatial index has not been built.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gps2asp.resolver.spatial_index import SpatialIndex

# Path to the pre-built spatial index
INDEX_DIR = Path(__file__).parent.parent / "src" / "gps2asp" / "data" / "index"


def _index_exists() -> bool:
    """Check if the spatial index files exist on disk."""
    return (
        (INDEX_DIR / "segments.idx").exists()
        and (INDEX_DIR / "segments.dat").exists()
        and (INDEX_DIR / "segments.json").exists()
    )


@pytest.fixture(scope="session")
def spatial_index_dir():
    """Session-scoped fixture that checks if the spatial index exists.

    Skips integration tests if the index has not been built.
    Returns the path to the index directory.
    """
    if not _index_exists():
        pytest.skip(
            "Spatial index not built. "
            "Run: python scripts/build_index.py"
        )
    return str(INDEX_DIR)


@pytest.fixture(autouse=True)
def reset_spatial_index():
    """Reset the SpatialIndex singleton before each test.

    This ensures each test starts with a clean state and does not
    inherit a loaded index from a previous test.
    """
    SpatialIndex.reset()
    yield
    SpatialIndex.reset()


@pytest.fixture(autouse=True)
def reset_street_graph():
    """Reset the StreetGraph singleton before each test.

    Mirrors reset_spatial_index: prevents a loaded graph from one test
    leaking into subsequent tests that expect a fresh singleton.
    """
    from gps2asp.signs.graph import StreetGraph
    StreetGraph._instance = None
    yield
    StreetGraph._instance = None
