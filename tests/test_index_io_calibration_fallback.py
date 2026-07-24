"""Proof that a from-source rebuild is the safe non-calibrated (c=0) fallback.

Phase 40 Plan 07 (SC-4 — "no segment silently miscalibrated"). The in-HA
from-source path (``_sync_build_from_source``) does NOT bulk-download the
citywide curb layer, so it emits segments with no calibration keys. This test
proves end-to-end that:

  1. ``build_info.json`` for a from-source build records ``"calibrated": false``
     alongside ``"source": "cscl_api"`` (explicit provenance, not implicit).
  2. Loading such a build through ``SpatialIndex`` yields a ``SegmentCandidate``
     with ``calibrated is False`` and ``center_offset_c == 0.0`` — the documented
     plain-CSCL fallback (Plan 04 absent-key defaulting), never a silently-wrong
     calibration.

Fully offline: reuses the respx-mocked CSCL/SODA harness from
``tests/test_index_io_build_from_source.py`` (no network).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import respx
from shapely import wkt

from custom_components.asp_parking.const import (
    CSCL_GEOJSON_URL,
    SODA_PARKING_SIGNS_URL,
)
from custom_components.asp_parking.index_io import _sync_build_from_source
from gps2asp.resolver.spatial_index import SpatialIndex

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_cscl_fixture() -> dict:
    return json.loads((FIXTURE_DIR / "cscl_geojson_sample.json").read_text())


def _load_soda_fixture() -> list[dict]:
    return json.loads((FIXTURE_DIR / "soda_asp_signs_sample.json").read_text())


def _empty_cscl_page() -> dict:
    return {"type": "FeatureCollection", "features": []}


def _route_cscl_two_pages(fixture_body: dict) -> respx.Route:
    """First CSCL fetch returns the fixture; the next returns an empty page."""
    return respx.get(CSCL_GEOJSON_URL).mock(
        side_effect=[
            httpx.Response(200, json=fixture_body),
            httpx.Response(200, json=_empty_cscl_page()),
        ]
    )


def _route_soda_ok() -> respx.Route:
    return respx.get(SODA_PARKING_SIGNS_URL).mock(
        side_effect=[
            httpx.Response(200, json=_load_soda_fixture()),
            httpx.Response(200, json=[]),
        ]
    )


@respx.mock
def test_build_info_records_calibrated_false(tmp_path: Path, monkeypatch) -> None:
    """A from-source build_info.json must record calibrated=false + source=cscl_api."""
    monkeypatch.delenv("NYC_OPEN_DATA_APP_TOKEN", raising=False)
    _route_cscl_two_pages(_load_cscl_fixture())
    _route_soda_ok()

    index_dir = tmp_path / "idx"
    _sync_build_from_source(index_dir)

    bi = json.loads((tmp_path / "idx_tmp" / "build_info.json").read_text())
    assert bi["source"] == "cscl_api"
    assert bi["calibrated"] is False, (
        "from-source build_info must explicitly record calibrated=false (SC-4)"
    )


async def test_from_source_segment_loads_non_calibrated_c0(
    tmp_path: Path, monkeypatch
) -> None:
    """A from-source segment loads with calibrated=False and center_offset_c==0.0."""
    monkeypatch.delenv("NYC_OPEN_DATA_APP_TOKEN", raising=False)

    with respx.mock:
        _route_cscl_two_pages(_load_cscl_fixture())
        _route_soda_ok()

        index_dir = tmp_path / "idx"
        _sync_build_from_source(index_dir)

    # _sync_build_from_source writes into <index_dir>_tmp; point SpatialIndex there.
    built_dir = tmp_path / "idx_tmp"
    segments = json.loads((built_dir / "segments.json").read_text())
    assert segments, "fixture build must yield at least one vehicular segment"

    # Derive an on-segment query point (EPSG:2263 feet) from the first segment's
    # centerline so the loaded candidate set is guaranteed non-empty.
    first_geom = wkt.loads(next(iter(segments.values()))["geometry_wkt"])
    midpoint = first_geom.interpolate(0.5, normalized=True)

    # reset() first to avoid singleton bleed from any prior loaded index.
    SpatialIndex.reset()
    try:
        idx = await SpatialIndex.get(index_dir=str(built_dir))
        results = idx.query_radius(midpoint.x, midpoint.y, 500.0)

        assert results, "an on-segment point must return at least one candidate"
        # Every from-source candidate is the documented non-calibrated fallback.
        for candidate in results:
            assert candidate.calibrated is False, (
                "from-source segments must load as calibrated=False (SC-4 fallback)"
            )
            assert candidate.center_offset_c == 0.0, (
                "non-calibrated segments must resolve at c=0 (plain-CSCL fallback)"
            )
    finally:
        SpatialIndex.reset()
