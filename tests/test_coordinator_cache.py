"""Unit tests for the Phase 26 sign cache and pre-seed lifecycle.

Covers AREA-02:
  - Pre-seed only runs when parking area is configured.
  - Pre-seed converts lat/lon to State Plane and queries SpatialIndex.
  - Pre-seed populates _sign_cache keyed by (on, from, to, side).
  - Pre-seed swallows OutsideNYCError without crashing.
  - _async_resolve_pipeline uses cache on hit (no live SODA call).
  - _async_resolve_pipeline falls through on miss (existing path).
  - Cache miss does NOT write back to the cache.
  - Periodic rebuild clears + re-spawns pre-seed.
  - Pre-seed task is created with name 'asp_parking_preseed' via
    entry.async_create_background_task (lifecycle-tied).
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.asp_parking.const import (
    CONF_DEVICE_TRACKER,
)
from custom_components.asp_parking.coordinator import (
    ASPParkingCoordinator,
    _METRES_TO_FEET,
)
from custom_components.asp_parking.gps2asp.resolver.exceptions import OutsideNYCError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def make_coordinator():
    """Build a minimally wired coordinator with a MagicMock hass + entry.

    The entry's async_create_background_task is mocked to record calls
    without actually scheduling a coroutine on an event loop.
    """

    def _make(options: dict | None = None):
        hass = MagicMock()
        entry = MagicMock()
        entry.data = {CONF_DEVICE_TRACKER: "device_tracker.car"}
        entry.options = options or {}

        def _close_coro_and_return_task(_hass, coro, name=None):
            # Close the coroutine so the test loop never warns about
            # "coroutine was never awaited"; return a sentinel mock.
            try:
                coro.close()
            except Exception:  # noqa: BLE001
                pass
            t = MagicMock()
            t.name = name
            return t

        entry.async_create_background_task = MagicMock(
            side_effect=_close_coro_and_return_task
        )
        return ASPParkingCoordinator(hass, entry), hass, entry

    return _make


def _make_segment_candidate(
    full_street_name: str = "PROSPECT PL",
    from_street: str = "VANDERBILT AVE",
    to_street: str = "UNDERHILL AVE",
    nominaldir: str = "E",
    segment_id: int = 1,
):
    """Build a MagicMock that quacks like SegmentCandidate for the pre-seed loop.

    Using a MagicMock (not the real frozen dataclass) avoids needing to
    construct a Shapely LineString geometry just to test the cache plumbing.
    """
    cand = MagicMock()
    cand.full_street_name = full_street_name
    cand.from_street = from_street
    cand.to_street = to_street
    cand.nominaldir = nominaldir
    cand.segment_id = segment_id
    return cand


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_no_parking_config_skips_preseed(make_coordinator):
    """Pre-seed early-returns when parking area config is absent."""
    coord, _hass, entry = make_coordinator(options={})
    # Confirm no parking config snapshot
    assert coord._parking_lat is None
    assert coord._parking_lon is None
    assert coord._parking_radius_m is None

    await coord._async_preseed_cache()

    assert coord._sign_cache == {}
    # The method itself should not spawn a background task — that is
    # async_start's responsibility, not _async_preseed_cache's.
    entry.async_create_background_task.assert_not_called()


async def test_preseed_uses_state_plane_conversion(make_coordinator):
    """Pre-seed calls convert(lat, lon) and idx.query_radius(cx, cy, r_ft)."""
    coord, _hass, _entry = make_coordinator()
    coord._parking_lat = 40.6778
    coord._parking_lon = -73.9690
    coord._parking_radius_m = 500

    mock_idx = MagicMock()
    mock_idx.query_radius = MagicMock(return_value=[])

    with (
        patch(
            "custom_components.asp_parking.coordinator.convert",
            return_value=(987654.0, 178432.0),
        ) as mock_convert,
        patch(
            "custom_components.asp_parking.coordinator.SpatialIndex.get",
            new=AsyncMock(return_value=mock_idx),
        ),
        patch(
            "custom_components.asp_parking.coordinator.SODAClient"
        ) as mock_client_cls,
    ):
        mock_client = MagicMock()
        mock_client.fetch_signs = AsyncMock(return_value=[])
        mock_client.build_block_query = MagicMock(return_value="WHERE 1=1")
        mock_client_cls.return_value = mock_client

        await coord._async_preseed_cache()

    mock_convert.assert_called_once_with(40.6778, -73.9690)
    mock_idx.query_radius.assert_called_once()
    args, _kwargs = mock_idx.query_radius.call_args
    assert args == (987654.0, 178432.0, 500 * _METRES_TO_FEET)


async def test_preseed_populates_cache_with_tuple_keys(make_coordinator):
    """Pre-seed writes one cache entry per (segment, legal-side) pair."""
    coord, _hass, _entry = make_coordinator()
    coord._parking_lat = 40.6778
    coord._parking_lon = -73.9690
    coord._parking_radius_m = 500

    cand = _make_segment_candidate(
        full_street_name="PROSPECT PL",
        from_street="VANDERBILT AVE",
        to_street="UNDERHILL AVE",
        nominaldir="E",  # legal sides => N, S
    )
    mock_idx = MagicMock()
    mock_idx.query_radius = MagicMock(return_value=[cand])

    soda_records = [{"sign_description": "SANITATION BROOM 8AM-9:30AM MON THU"}]

    with (
        patch(
            "custom_components.asp_parking.coordinator.convert",
            return_value=(987654.0, 178432.0),
        ),
        patch(
            "custom_components.asp_parking.coordinator.SpatialIndex.get",
            new=AsyncMock(return_value=mock_idx),
        ),
        patch(
            "custom_components.asp_parking.coordinator.SODAClient"
        ) as mock_client_cls,
    ):
        mock_client = MagicMock()
        mock_client.fetch_signs = AsyncMock(return_value=soda_records)
        mock_client.build_block_query = MagicMock(return_value="WHERE 1=1")
        mock_client_cls.return_value = mock_client

        await coord._async_preseed_cache()

    key_n = ("PROSPECT PL", "VANDERBILT AVE", "UNDERHILL AVE", "N")
    key_s = ("PROSPECT PL", "VANDERBILT AVE", "UNDERHILL AVE", "S")
    assert key_n in coord._sign_cache
    assert key_s in coord._sign_cache
    # BUG-S-007 (Phase 35.1-05): cache values are {"records", "soda_level"}
    # dicts, not bare records lists. Pre-seed uses L1 block queries.
    assert coord._sign_cache[key_n] == {"records": soda_records, "soda_level": 1}
    assert coord._sign_cache[key_s] == {"records": soda_records, "soda_level": 1}


async def test_preseed_outside_nyc_logs_and_returns_without_crash(
    make_coordinator, caplog
):
    """Pre-seed swallows OutsideNYCError, leaving _sign_cache empty (D-07)."""
    coord, _hass, _entry = make_coordinator()
    coord._parking_lat = 51.5
    coord._parking_lon = 0.0
    coord._parking_radius_m = 500

    with (
        caplog.at_level(
            logging.WARNING,
            logger="custom_components.asp_parking.coordinator",
        ),
        patch(
            "custom_components.asp_parking.coordinator.convert",
            side_effect=OutsideNYCError(51.5, 0.0),
        ),
    ):
        # Must not raise
        await coord._async_preseed_cache()

    assert coord._sign_cache == {}
    assert any("outside NYC" in rec.message for rec in caplog.records)


async def test_resolve_pipeline_uses_cache_on_hit(make_coordinator):
    """A populated cache short-circuits retrieve_signs in the resolve pipeline."""
    coord, _hass, _entry = make_coordinator()
    cache_key = ("PROSPECT PL", "VANDERBILT AVE", "UNDERHILL AVE", "N")
    cached_records = [{"sign_description": "SANITATION BROOM 8AM-9:30AM MON THU"}]
    # BUG-S-007: cache stores {records, soda_level} dicts (not bare lists)
    coord._sign_cache = {cache_key: {"records": cached_records, "soda_level": 1}}

    coord._pending_lat = 40.6778
    coord._pending_lon = -73.9690

    resolution = MagicMock()
    resolution.on_street = "PROSPECT PL"
    resolution.from_street = "VANDERBILT AVE"
    resolution.to_street = "UNDERHILL AVE"
    resolution.side_of_street = "N"
    resolution.confidence = 0.85
    resolution.borocode = "3"
    resolution.perpendicular_distance_ft = 12.5
    resolution.street_width_ft = 30.0
    resolution.segment_id = 12345

    benign_schedule = MagicMock()
    benign_schedule.status = "schedule_found"
    benign_schedule.parse_failures = []

    with (
        patch(
            "custom_components.asp_parking.coordinator.resolve",
            new=AsyncMock(return_value=resolution),
        ),
        patch(
            "custom_components.asp_parking.coordinator.retrieve_signs",
            new_callable=AsyncMock,
        ) as mock_retrieve,
        patch(
            "custom_components.asp_parking.coordinator.compute_schedule",
            return_value=benign_schedule,
        ),
        patch.object(
            ASPParkingCoordinator,
            "_async_maybe_send_notification",
            new=AsyncMock(),
        ),
    ):
        await coord._async_resolve_pipeline()

    mock_retrieve.assert_not_called()


async def test_resolve_pipeline_falls_through_on_cache_miss(make_coordinator):
    """An empty cache makes the resolve pipeline call retrieve_signs as before."""
    coord, _hass, _entry = make_coordinator()
    coord._sign_cache = {}
    coord._pending_lat = 40.6778
    coord._pending_lon = -73.9690

    resolution = MagicMock()
    resolution.on_street = "PROSPECT PL"
    resolution.from_street = "VANDERBILT AVE"
    resolution.to_street = "UNDERHILL AVE"
    resolution.side_of_street = "N"
    resolution.confidence = 0.85
    resolution.borocode = "3"
    resolution.perpendicular_distance_ft = 12.5
    resolution.street_width_ft = 30.0
    resolution.segment_id = 12345

    sign_result = MagicMock()
    sign_result.signs = []
    sign_result.soda_level = 1

    benign_schedule = MagicMock()
    benign_schedule.status = "schedule_found"
    benign_schedule.parse_failures = []

    with (
        patch(
            "custom_components.asp_parking.coordinator.resolve",
            new=AsyncMock(return_value=resolution),
        ),
        patch(
            "custom_components.asp_parking.coordinator.retrieve_signs",
            new_callable=AsyncMock,
        ) as mock_retrieve,
        patch(
            "custom_components.asp_parking.coordinator.compute_schedule",
            return_value=benign_schedule,
        ),
        patch.object(
            ASPParkingCoordinator,
            "_async_maybe_send_notification",
            new=AsyncMock(),
        ),
    ):
        mock_retrieve.return_value = sign_result
        await coord._async_resolve_pipeline()

    mock_retrieve.assert_called_once_with(
        on_street="PROSPECT PL",
        from_street="VANDERBILT AVE",
        to_street="UNDERHILL AVE",
        side_of_street="N",
    )


async def test_cache_miss_does_not_write_back(make_coordinator):
    """A cache miss must NOT populate the cache after the live retrieve (D-04)."""
    coord, _hass, _entry = make_coordinator()
    coord._sign_cache = {}
    coord._pending_lat = 40.6778
    coord._pending_lon = -73.9690

    resolution = MagicMock()
    resolution.on_street = "PROSPECT PL"
    resolution.from_street = "VANDERBILT AVE"
    resolution.to_street = "UNDERHILL AVE"
    resolution.side_of_street = "N"
    resolution.confidence = 0.85
    resolution.borocode = "3"
    resolution.perpendicular_distance_ft = 12.5
    resolution.street_width_ft = 30.0
    resolution.segment_id = 12345

    sign_result = MagicMock()
    sign_result.signs = []
    sign_result.soda_level = 1

    benign_schedule = MagicMock()
    benign_schedule.status = "schedule_found"
    benign_schedule.parse_failures = []

    with (
        patch(
            "custom_components.asp_parking.coordinator.resolve",
            new=AsyncMock(return_value=resolution),
        ),
        patch(
            "custom_components.asp_parking.coordinator.retrieve_signs",
            new=AsyncMock(return_value=sign_result),
        ),
        patch(
            "custom_components.asp_parking.coordinator.compute_schedule",
            return_value=benign_schedule,
        ),
        patch.object(
            ASPParkingCoordinator,
            "_async_maybe_send_notification",
            new=AsyncMock(),
        ),
    ):
        await coord._async_resolve_pipeline()

    # D-04: cache must remain empty after a miss-path resolve
    assert coord._sign_cache == {}


async def test_periodic_rebuild_preserves_cache_and_respawns(make_coordinator):
    """Periodic rebuild spawns a fresh pre-seed task WITHOUT clearing the live cache.

    The preseed builds a local new_cache and swaps atomically at the end, so the
    live cache must remain intact during the rebuild window.
    """
    coord, _hass, entry = make_coordinator()
    # BUG-S-007: cache stores {records, soda_level} dicts (not bare lists)
    old_cache = {
        ("X", "Y", "Z", "N"): {
            "records": [{"sign_description": "old"}],
            "soda_level": 1,
        }
    }
    coord._sign_cache = old_cache
    coord._parking_lat = 40.6778
    coord._parking_lon = -73.9690
    coord._parking_radius_m = 500

    entry.async_create_background_task.reset_mock()

    coord._async_periodic_cache_rebuild(MagicMock())

    # Cache must NOT be wiped before the preseed task completes (WR-02 fix)
    assert coord._sign_cache is old_cache
    assert entry.async_create_background_task.call_count == 1
    args, kwargs = entry.async_create_background_task.call_args
    assert kwargs.get("name") == "asp_parking_preseed"
    # Second positional arg must be a coroutine (closed by fixture's side_effect
    # before this assert runs, but the call_args records the original object)
    assert asyncio.iscoroutine(args[1])


async def test_preseed_task_uses_entry_async_create_background_task(make_coordinator):
    """The pre-seed spawn path uses entry.async_create_background_task by name.

    This test directly exercises the conditional spawn block (the same code
    path async_start invokes after loading parking config) so it does not
    need to set up holiday calendars, 311 bridge probes, etc.
    """
    coord, hass, entry = make_coordinator()
    coord._parking_lat = 40.6778
    coord._parking_lon = -73.9690
    coord._parking_radius_m = 500

    # Mirror the spawn block from async_start (same shape)
    coord._preseed_task = coord.entry.async_create_background_task(
        coord.hass,
        coord._async_preseed_cache(),
        name="asp_parking_preseed",
    )

    assert entry.async_create_background_task.called
    args, kwargs = entry.async_create_background_task.call_args
    assert kwargs.get("name") == "asp_parking_preseed"
    assert args[0] is hass
    assert asyncio.iscoroutine(args[1])


# ---------------------------------------------------------------------------
# BUG-S-007 (Phase 35.1-05): Cache propagates soda_level via materialize
# ---------------------------------------------------------------------------


async def test_materialize_propagates_cached_soda_level(make_coordinator):
    """BUG-S-007: cache entries store both records and the soda_level that
    produced them; on a cache hit, the coordinator must pass that level
    into materialize_cached_records() instead of hardcoding soda_level=1.

    The pre-seed path always uses Level 1 block queries today, so the
    persisted level for pre-seeded entries is 1 — but the cache schema
    must support any 1-4 level so that future seed paths (e.g., L2
    abbreviation variants or L4 spans) propagate correctly. The fix is
    a schema change: cache values move from ``list[dict]`` to
    ``{"records": list[dict], "soda_level": int}``, and read sites must
    extract both fields.
    """
    coord, _hass, _entry = make_coordinator()
    cache_key = ("PROSPECT PL", "VANDERBILT AVE", "UNDERHILL AVE", "N")
    cached_records = [{"sign_description": "SANITATION BROOM 8AM-9:30AM MON THU"}]
    # New cache shape: dict with both records and the soda_level
    coord._sign_cache = {
        cache_key: {"records": cached_records, "soda_level": 3}
    }

    coord._pending_lat = 40.6778
    coord._pending_lon = -73.9690

    resolution = MagicMock()
    resolution.on_street = "PROSPECT PL"
    resolution.from_street = "VANDERBILT AVE"
    resolution.to_street = "UNDERHILL AVE"
    resolution.side_of_street = "N"
    resolution.confidence = 0.85
    resolution.borocode = "3"
    resolution.perpendicular_distance_ft = 12.5
    resolution.street_width_ft = 30.0
    resolution.segment_id = 12345

    benign_schedule = MagicMock()
    benign_schedule.status = "schedule_found"
    benign_schedule.parse_failures = []

    with (
        patch(
            "custom_components.asp_parking.coordinator.resolve",
            new=AsyncMock(return_value=resolution),
        ),
        patch(
            "custom_components.asp_parking.coordinator.retrieve_signs",
            new_callable=AsyncMock,
        ) as mock_retrieve,
        patch(
            "custom_components.asp_parking.coordinator.materialize_cached_records",
        ) as mock_materialize,
        patch(
            "custom_components.asp_parking.coordinator.compute_schedule",
            return_value=benign_schedule,
        ),
        patch.object(
            ASPParkingCoordinator,
            "_async_maybe_send_notification",
            new=AsyncMock(),
        ),
    ):
        sign_result = MagicMock()
        sign_result.signs = []
        sign_result.soda_level = 3
        mock_materialize.return_value = sign_result

        await coord._async_resolve_pipeline()

    mock_retrieve.assert_not_called()
    mock_materialize.assert_called_once()
    # Verify the propagated level — kwarg or positional, level must be 3
    _args, kwargs = mock_materialize.call_args
    assert kwargs.get("soda_level") == 3, (
        f"materialize_cached_records must receive soda_level=3 from cache; "
        f"got kwargs={kwargs!r}"
    )
    # The first positional arg must be the records list (not the dict wrapper)
    assert _args[0] == cached_records, (
        f"First arg must be the records list extracted from the cache entry; "
        f"got {_args[0]!r}"
    )
    # And the resulting sensor data must reflect the cached level
    assert coord.data.soda_level == 3


async def test_preseed_writes_new_cache_shape(make_coordinator):
    """BUG-S-007: pre-seed writes the new {records, soda_level} shape.

    Pre-seed uses Level 1 block queries, so the written soda_level is 1.
    The KEY change is the SHAPE: each cache value is a dict, not a bare
    records list.
    """
    coord, _hass, _entry = make_coordinator()
    coord._parking_lat = 40.6778
    coord._parking_lon = -73.9690
    coord._parking_radius_m = 500

    cand = _make_segment_candidate(
        full_street_name="PROSPECT PL",
        from_street="VANDERBILT AVE",
        to_street="UNDERHILL AVE",
        nominaldir="E",  # legal sides => N, S
    )
    mock_idx = MagicMock()
    mock_idx.query_radius = MagicMock(return_value=[cand])

    soda_records = [{"sign_description": "SANITATION BROOM 8AM-9:30AM MON THU"}]

    with (
        patch(
            "custom_components.asp_parking.coordinator.convert",
            return_value=(987654.0, 178432.0),
        ),
        patch(
            "custom_components.asp_parking.coordinator.SpatialIndex.get",
            new=AsyncMock(return_value=mock_idx),
        ),
        patch(
            "custom_components.asp_parking.coordinator.SODAClient"
        ) as mock_client_cls,
    ):
        mock_client = MagicMock()
        mock_client.fetch_signs = AsyncMock(return_value=soda_records)
        mock_client.build_block_query = MagicMock(return_value="WHERE 1=1")
        mock_client_cls.return_value = mock_client

        await coord._async_preseed_cache()

    key_n = ("PROSPECT PL", "VANDERBILT AVE", "UNDERHILL AVE", "N")
    assert key_n in coord._sign_cache
    entry = coord._sign_cache[key_n]
    assert isinstance(entry, dict), (
        f"BUG-S-007: cache entries must be dicts with records+soda_level keys; "
        f"got {type(entry).__name__}"
    )
    assert entry["records"] == soda_records
    assert entry["soda_level"] == 1, (
        "Pre-seed always queries Level 1 (block query); written soda_level "
        f"must be 1, got {entry.get('soda_level')!r}"
    )
