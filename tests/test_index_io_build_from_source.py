"""RED tests for _sync_build_from_source (Phase 38 Plan 01, IDX-06).

Covers the new from-source CSCL rebuild path in
``custom_components/asp_parking/index_io.py``:

* 5-file output (segments.idx, segments.dat, segments.json, graph.json.zst,
  build_info.json) under ``<index_dir>_tmp``
* ``build_info.json["source"] == "cscl_api"`` provenance stamp
* V12 enforcement: writes ONLY to ``<index_dir>_tmp`` (never ``<index_dir>``)
* X-App-Token header forwarding from ``NYC_OPEN_DATA_APP_TOKEN`` env var
* Pagination cap via ``MAX_CSCL_PAGES`` (DoS guard)
* CSCL fail-hard / SODA fail-soft semantics
* RW_TYPE filter (vehicular only) and TRAFDIR=="NV" exclusion

Pattern: respx-mocked httpx clients (no network). All tests fail at collection
with ``ImportError`` until Task 2 (GREEN) lands ``_sync_build_from_source``.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

# Imports targeted at the future symbol Plan 38-01 Task 2 must implement.
# Collection MUST fail with ImportError until Task 2 lands the function.
from custom_components.asp_parking.const import (
    CSCL_BATCH_SIZE,
    CSCL_GEOJSON_URL,
    MAX_CSCL_PAGES,
    SODA_PARKING_SIGNS_URL,
)
from custom_components.asp_parking.index_io import _sync_build_from_source

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_cscl_fixture() -> dict:
    return json.loads((FIXTURE_DIR / "cscl_geojson_sample.json").read_text())


def _load_soda_fixture() -> list[dict]:
    return json.loads((FIXTURE_DIR / "soda_asp_signs_sample.json").read_text())


def _empty_cscl_page() -> dict:
    return {"type": "FeatureCollection", "features": []}


def _route_cscl_two_pages(fixture_body: dict) -> respx.Route:
    """Mount respx routes so the first CSCL fetch returns fixture, the rest empty.

    Returns the first route so callers can assert on captured headers.
    """
    responses = [
        httpx.Response(200, json=fixture_body),
        httpx.Response(200, json=_empty_cscl_page()),
    ]
    return respx.get(CSCL_GEOJSON_URL).mock(side_effect=responses)


def _route_soda_ok() -> respx.Route:
    return respx.get(SODA_PARKING_SIGNS_URL).mock(
        side_effect=[
            httpx.Response(200, json=_load_soda_fixture()),
            httpx.Response(200, json=[]),
        ]
    )


@respx.mock
def test_produces_all_five_files(tmp_path: Path, monkeypatch) -> None:
    """5 files must be written under <index_dir>_tmp after a successful build."""
    monkeypatch.delenv("NYC_OPEN_DATA_APP_TOKEN", raising=False)
    _route_cscl_two_pages(_load_cscl_fixture())
    _route_soda_ok()

    index_dir = tmp_path / "idx"
    _sync_build_from_source(index_dir)

    tmp = tmp_path / "idx_tmp"
    assert tmp.exists()
    for fname in ("segments.idx", "segments.dat", "segments.json",
                  "graph.json.zst", "build_info.json"):
        assert (tmp / fname).exists(), f"missing {fname} under {tmp}"


@respx.mock
def test_build_info_source_cscl_api(tmp_path: Path, monkeypatch) -> None:
    """build_info.json must record source=cscl_api with a tz-aware UTC stamp."""
    monkeypatch.delenv("NYC_OPEN_DATA_APP_TOKEN", raising=False)
    _route_cscl_two_pages(_load_cscl_fixture())
    _route_soda_ok()

    index_dir = tmp_path / "idx"
    _sync_build_from_source(index_dir)

    bi = json.loads((tmp_path / "idx_tmp" / "build_info.json").read_text())
    assert bi["source"] == "cscl_api"
    assert isinstance(bi.get("build_timestamp"), str)
    assert bi["build_timestamp"].endswith("Z"), bi["build_timestamp"]


@respx.mock
def test_writes_to_tmp_only_never_in_place(tmp_path: Path, monkeypatch) -> None:
    """V12: <index_dir> must NOT exist after the call — only <index_dir>_tmp."""
    monkeypatch.delenv("NYC_OPEN_DATA_APP_TOKEN", raising=False)
    _route_cscl_two_pages(_load_cscl_fixture())
    _route_soda_ok()

    index_dir = tmp_path / "idx"
    _sync_build_from_source(index_dir)

    assert not index_dir.exists(), "<index_dir> must not be written (caller owns swap)"
    assert (tmp_path / "idx_tmp").exists()


@respx.mock
def test_app_token_header_when_env_var_set(tmp_path: Path, monkeypatch) -> None:
    """NYC_OPEN_DATA_APP_TOKEN env var must produce an X-App-Token header on CSCL + SODA."""
    monkeypatch.setenv("NYC_OPEN_DATA_APP_TOKEN", "test-token-123")
    cscl_route = _route_cscl_two_pages(_load_cscl_fixture())
    soda_route = _route_soda_ok()

    index_dir = tmp_path / "idx"
    _sync_build_from_source(index_dir)

    assert cscl_route.called, "CSCL endpoint must have been called"
    assert soda_route.called, "SODA endpoint must have been called"
    cscl_first = cscl_route.calls[0].request
    soda_first = soda_route.calls[0].request
    assert cscl_first.headers.get("X-App-Token") == "test-token-123"
    assert soda_first.headers.get("X-App-Token") == "test-token-123"


@respx.mock
def test_no_app_token_header_when_env_var_unset(
    tmp_path: Path, monkeypatch
) -> None:
    """Without NYC_OPEN_DATA_APP_TOKEN, the X-App-Token header must be absent."""
    monkeypatch.delenv("NYC_OPEN_DATA_APP_TOKEN", raising=False)
    cscl_route = _route_cscl_two_pages(_load_cscl_fixture())
    soda_route = _route_soda_ok()

    index_dir = tmp_path / "idx"
    _sync_build_from_source(index_dir)

    assert cscl_route.called
    cscl_first = cscl_route.calls[0].request
    assert "X-App-Token" not in cscl_first.headers
    if soda_route.called:
        soda_first = soda_route.calls[0].request
        assert "X-App-Token" not in soda_first.headers


@respx.mock
def test_pagination_cap_raises(tmp_path: Path, monkeypatch) -> None:
    """If CSCL keeps returning full batches past MAX_CSCL_PAGES, raise RuntimeError."""
    monkeypatch.delenv("NYC_OPEN_DATA_APP_TOKEN", raising=False)

    # Fabricate a full-batch page so the helper keeps paginating until cap.
    base_feature = _load_cscl_fixture()["features"][0]
    fake_features = []
    for i in range(CSCL_BATCH_SIZE):
        feat = json.loads(json.dumps(base_feature))
        feat["properties"]["PHYSICALID"] = str(20000 + i)
        fake_features.append(feat)
    full_body = {"type": "FeatureCollection", "features": fake_features}

    # Mount enough full-batch responses to exceed the cap.
    responses = [
        httpx.Response(200, json=full_body) for _ in range(MAX_CSCL_PAGES + 2)
    ]
    respx.get(CSCL_GEOJSON_URL).mock(side_effect=responses)
    _route_soda_ok()

    index_dir = tmp_path / "idx"
    with pytest.raises(RuntimeError, match="MAX_CSCL_PAGES"):
        _sync_build_from_source(index_dir)


@respx.mock
def test_soda_failure_is_fail_soft(tmp_path: Path, monkeypatch) -> None:
    """SODA HTTP 500 must NOT raise — has_asp lookup is empty but the build completes."""
    monkeypatch.delenv("NYC_OPEN_DATA_APP_TOKEN", raising=False)
    _route_cscl_two_pages(_load_cscl_fixture())
    respx.get(SODA_PARKING_SIGNS_URL).mock(return_value=httpx.Response(500))

    index_dir = tmp_path / "idx"
    _sync_build_from_source(index_dir)

    tmp = tmp_path / "idx_tmp"
    assert (tmp / "build_info.json").exists()


@respx.mock
def test_cscl_failure_raises(tmp_path: Path, monkeypatch) -> None:
    """CSCL HTTP 500 must propagate (fail-hard semantics)."""
    monkeypatch.delenv("NYC_OPEN_DATA_APP_TOKEN", raising=False)
    respx.get(CSCL_GEOJSON_URL).mock(return_value=httpx.Response(500))
    # SODA not reached, but mount anyway to avoid spurious unmocked errors.
    respx.get(SODA_PARKING_SIGNS_URL).mock(return_value=httpx.Response(200, json=[]))

    index_dir = tmp_path / "idx"
    with pytest.raises((httpx.HTTPStatusError, RuntimeError)):
        _sync_build_from_source(index_dir)


@respx.mock
def test_rw_type_filter_excludes_non_vehicular(
    tmp_path: Path, monkeypatch
) -> None:
    """Fixture includes RW_TYPE=9 (FDR DRIVE) — segments.json must not contain it."""
    monkeypatch.delenv("NYC_OPEN_DATA_APP_TOKEN", raising=False)
    _route_cscl_two_pages(_load_cscl_fixture())
    _route_soda_ok()

    index_dir = tmp_path / "idx"
    _sync_build_from_source(index_dir)

    segments = json.loads((tmp_path / "idx_tmp" / "segments.json").read_text())
    assert "10005" not in segments, "RW_TYPE=9 segment must be filtered out"


@respx.mock
def test_trafdir_nv_excluded(tmp_path: Path, monkeypatch) -> None:
    """Fixture includes TRAFDIR='NV' (WALKING TRAIL) — segments.json must exclude it."""
    monkeypatch.delenv("NYC_OPEN_DATA_APP_TOKEN", raising=False)
    _route_cscl_two_pages(_load_cscl_fixture())
    _route_soda_ok()

    index_dir = tmp_path / "idx"
    _sync_build_from_source(index_dir)

    segments = json.loads((tmp_path / "idx_tmp" / "segments.json").read_text())
    assert "10006" not in segments, "TRAFDIR=NV segment must be filtered out"
