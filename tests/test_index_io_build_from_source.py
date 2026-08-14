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
from rtree import index as rtree_index

# Imports targeted at the future symbol Plan 38-01 Task 2 must implement.
# Collection MUST fail with ImportError until Task 2 lands the function.
from custom_components.asp_parking.const import (
    CSCL_BATCH_SIZE,
    CSCL_GEOJSON_URL,
    MAX_CSCL_PAGES,
    SODA_PARKING_SIGNS_URL,
)
from custom_components.asp_parking.index_io import (
    _sync_build_from_source,
    _sync_fetch_asp_signs,
)

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
    for fname in (
        "segments.idx",
        "segments.dat",
        "segments.json",
        "graph.json.zst",
        "build_info.json",
    ):
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
def test_no_app_token_header_when_env_var_unset(tmp_path: Path, monkeypatch) -> None:
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
    responses = [httpx.Response(200, json=full_body) for _ in range(MAX_CSCL_PAGES + 2)]
    respx.get(CSCL_GEOJSON_URL).mock(side_effect=responses)
    _route_soda_ok()

    index_dir = tmp_path / "idx"
    with pytest.raises(RuntimeError, match="MAX_CSCL_PAGES"):
        _sync_build_from_source(index_dir)


@respx.mock
def test_soda_signs_pagination_cap_stops_instead_of_looping_forever(
    monkeypatch,
) -> None:
    """WR-02 (38-REVIEW.md): a misbehaving SODA endpoint that keeps returning
    full-size batches must stop at the pagination cap instead of looping
    forever.

    Unlike the CSCL fetcher (fail-hard RuntimeError), the SODA signs fetch is
    fail-soft (T-38-01-02) -- it must return partial results, not raise.

    Batch size / page cap are monkeypatched small (5 records / 3 pages) so
    this test runs fast while still exercising the real cap-check codepath
    in ``_sync_fetch_asp_signs`` (which reads the module-level constants at
    call time).
    """
    monkeypatch.delenv("NYC_OPEN_DATA_APP_TOKEN", raising=False)
    small_batch_size = 5
    small_page_cap = 3
    monkeypatch.setattr(
        "custom_components.asp_parking.index_io.SIGNS_BATCH_SIZE", small_batch_size
    )
    monkeypatch.setattr(
        "custom_components.asp_parking.index_io.MAX_SIGNS_PAGES", small_page_cap
    )

    base_record = _load_soda_fixture()[0]
    full_batch = [dict(base_record) for _ in range(small_batch_size)]

    # Mount enough full-batch responses to exceed the cap; if the guard is
    # missing, respx will exhaust these routes and raise instead of hanging,
    # which is itself proof the guard is required.
    responses = [
        httpx.Response(200, json=full_batch) for _ in range(small_page_cap + 2)
    ]
    route = respx.get(SODA_PARKING_SIGNS_URL).mock(side_effect=responses)

    result = _sync_fetch_asp_signs(headers={})

    assert route.call_count == small_page_cap, (
        f"Expected pagination to stop at exactly the page cap="
        f"{small_page_cap} requests, got {route.call_count}"
    )
    assert isinstance(result, set)


@respx.mock
def test_soda_signs_non_list_response_treated_as_no_more_data(
    monkeypatch,
) -> None:
    """WR-03 (38-REVIEW.md): a truthy non-list JSON body (e.g. an error dict on
    an HTTP-200 soft error) must be treated as "no more data", not iterated
    as if it were a list of records (which would AttributeError on
    ``record.get(...)`` when iterating a dict's string keys).
    """
    monkeypatch.delenv("NYC_OPEN_DATA_APP_TOKEN", raising=False)
    respx.get(SODA_PARKING_SIGNS_URL).mock(
        return_value=httpx.Response(200, json={"error": "soft failure"})
    )

    # Must not raise AttributeError/TypeError -- fail-soft contract (T-38-01-02).
    result = _sync_fetch_asp_signs(headers={})
    assert result == set()


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
def test_rw_type_filter_excludes_non_vehicular(tmp_path: Path, monkeypatch) -> None:
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


@respx.mock
def test_rtree_non_empty(tmp_path: Path, monkeypatch) -> None:
    """Nyquist gap 38-01-03: segments.idx/.dat must form a POPULATED R-tree.

    Guards against rtree bug #159 -- using the generator-constructor form
    (instead of an insert loop inside try/finally) silently writes an empty
    index while the .idx/.dat files still exist on disk, so a mere
    ``.exists()`` check on the files is not sufficient coverage.
    """
    monkeypatch.delenv("NYC_OPEN_DATA_APP_TOKEN", raising=False)
    _route_cscl_two_pages(_load_cscl_fixture())
    _route_soda_ok()

    index_dir = tmp_path / "idx"
    _sync_build_from_source(index_dir)

    tmp = tmp_path / "idx_tmp"
    assert (tmp / "segments.idx").exists()
    assert (tmp / "segments.dat").exists()

    idx = rtree_index.Index(str(tmp / "segments"))
    try:
        assert idx.count(idx.bounds) > 0, (
            "R-tree at "
            f"{tmp / 'segments'} is empty despite .idx/.dat files existing "
            "on disk (rtree bug #159 -- generator constructor instead of "
            "insert loop)"
        )
        hits = list(idx.intersection(idx.bounds))
        assert len(hits) > 0
    finally:
        idx.close()


@respx.mock
def test_graph_json_zst_round_trip(tmp_path: Path, monkeypatch) -> None:
    """Nyquist gap 38-01-04: graph.json.zst must be parseable by StreetGraph.load
    and contain at least one segment/adjacency entry -- not merely exist on disk.
    """
    from custom_components.asp_parking.gps2asp.signs.graph import StreetGraph

    monkeypatch.delenv("NYC_OPEN_DATA_APP_TOKEN", raising=False)
    _route_cscl_two_pages(_load_cscl_fixture())
    _route_soda_ok()

    index_dir = tmp_path / "idx"
    _sync_build_from_source(index_dir)

    tmp = tmp_path / "idx_tmp"
    assert (tmp / "graph.json.zst").exists()

    graph = StreetGraph.load(tmp)
    assert graph is not None, (
        "StreetGraph.load returned None for a freshly-built graph.json.zst "
        "-- either the file is corrupt/unreadable or empty"
    )
    assert len(graph.segment_streets) > 0, "graph has zero segment_streets entries"
    assert len(graph.adjacency) > 0, "graph has zero adjacency entries"


def test_manifest_no_heavy_gis_dependency() -> None:
    """Nyquist gap 38-01-06: manifest.json requirements must never gain a heavy
    GIS/GDAL dependency (geopandas, GDAL, fiona, pyogrio).

    Evergreen regression test -- not a git-diff/byte-identical check, which
    has no meaning outside the PR that originally introduced this plan.
    Per 38-01-SUMMARY.md: "geopandas pulls GDAL (~500MB) into the HA Python
    environment, violating the manifest.json 'no new external deps'
    constraint."
    """
    manifest_path = (
        Path(__file__).parent.parent
        / "custom_components"
        / "asp_parking"
        / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text())
    requirements = manifest.get("requirements", [])
    assert isinstance(requirements, list) and requirements, (
        "manifest.json requirements array is missing or empty"
    )

    banned_substrings = ("geopandas", "gdal", "fiona", "pyogrio")
    for req in requirements:
        req_lower = str(req).lower()
        for banned in banned_substrings:
            assert banned not in req_lower, (
                f"manifest.json requirements contains a banned heavy GIS "
                f"dependency: {req!r} (matched {banned!r})"
            )
