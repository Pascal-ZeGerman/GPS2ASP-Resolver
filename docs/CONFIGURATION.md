<!-- generated-by: gsd-doc-writer -->
# Configuration

`gps2asp` uses a combination of environment variables and — when running as a Home Assistant integration — UI-configured options stored in the config entry. No config files exist beyond `pyproject.toml`.

---

## Environment Variables

These variables are read at process startup and take effect immediately. None are required; the library ships with safe defaults for all of them.

| Variable | Required | Default | Description |
|---|---|---|---|
| `GPS2ASP_INDEX_DIR` | Optional | `src/gps2asp/data/index/` | Absolute path to the directory containing the pre-built spatial index files (`segments.idx`, `segments.dat`, `segments.json`, `graph.json`). Override when the index is stored outside the package tree (e.g., a mounted volume, a custom build output directory). Read in `src/gps2asp/resolver/spatial_index.py`. |
| `NYC_OPEN_DATA_APP_TOKEN` | Optional | _(none)_ | NYC Open Data application token. When set, `SODAClient` (`src/gps2asp/signs/client.py`) and `scripts/build_index.py` send it as the `X-App-Token` HTTP header for a dedicated rate-limit pool. Without a token, requests share the anonymous pool and may be throttled during peak usage. Obtain one at <!-- VERIFY: https://opendata.cityofnewyork.us/overview/ --> |
| `NYC_311_API_KEY` | Optional | _(none)_ | Subscription key for the NYC 311 `GetCalendar` API (`https://api.nyc.gov/public/api/GetCalendar`). Enables real-time weather/emergency ASP suspension detection. When absent the `NYC311Client` skips all network calls and returns `is_suspended=False` (fail-open). When present but invalid, `fetch_status()` raises `NYC311AuthError` on HTTP 401/403. Sent as the `Ocp-Apim-Subscription-Key` request header. <!-- VERIFY: obtain from https://api-portal.nyc.gov/ --> |

### Precedence for `GPS2ASP_INDEX_DIR`

The `SpatialIndex` resolves its index directory in this order:

1. Constructor argument: `SpatialIndex(index_dir="/path/to/index")`
2. Environment variable: `GPS2ASP_INDEX_DIR`
3. Default: `src/gps2asp/data/index/` relative to the installed package

### Precedence for API keys (Home Assistant)

`NYC311Client(api_key=...)` falls back to the `NYC_311_API_KEY` environment variable only when no explicit key is passed. In the Home Assistant integration, the coordinator reads the key from the config entry option `nyc311_api_key` and passes it to the client, so the UI-configured value takes precedence over the environment variable. `SODAClient` follows the same pattern for the `NYC_OPEN_DATA_APP_TOKEN` token.

---

## Required vs Optional Settings

### Application startup

None of the three environment variables are mandatory. The library starts successfully when all three are unset:

- `GPS2ASP_INDEX_DIR` absent → uses the package-bundled default path. Raises `IndexNotFoundError` only if the index files have not been built yet (`scripts/build_index.py` must run first).
- `NYC_OPEN_DATA_APP_TOKEN` absent → SODA queries proceed without a token, subject to the shared anonymous rate limit.
- `NYC_311_API_KEY` absent → suspension checks are skipped; ASP status is determined from sign data alone.

### Home Assistant config entry

When using the `asp_parking` custom integration, the fields below are set through the UI config flow (Settings → Devices & Services → ASP Parking Monitor) and are not environment variables. They are persisted in the HA config entry — `device_tracker` lives in the entry `data`, all other fields in the entry `options` dict. The setup wizard runs in three steps (device tracker → thresholds → NYC 311 key); the remaining options are configured through the multi-step options flow (thresholds/notifications → parking area → CalDAV credentials → CalDAV calendar).

| Option key | Required | Default | Description |
|---|---|---|---|
| `device_tracker` | **Required** | _(none)_ | Entity ID of the `device_tracker` whose GPS coordinates are resolved. Selected in the first setup step; stored in the config entry `data`. |
| `movement_threshold` | Optional | `50.0` m | Minimum GPS displacement (metres) before the pipeline re-runs. Suppresses redundant API calls for minor GPS jitter. Valid range: 1–10 000 m. |
| `refresh_interval` | Optional | `8` h | Hours between forced periodic refreshes even when the vehicle has not moved. Valid range: 1–168 h. |
| `stale_timeout` | Optional | `8` h | Hours after which sensors are marked `unavailable` if no successful resolve has occurred. Valid range: 1–168 h. |
| `nyc311_api_key` | Optional | _(none)_ | NYC 311 API subscription key entered in the setup wizard. Stored in the HA config entry; takes precedence over `NYC_311_API_KEY` env var when set via the UI. Validated against the live API during setup — an invalid key surfaces an `invalid_api_key` form error. |
| `nyc311_entity` | Optional | `""` | Entity ID of a `binary_sensor` that already tracks the NYC 311 suspension state (e.g., from another integration). Used as an alternative to direct API polling. |
| `notify_service` | Optional | `""` | HA `notify.*` service to call when an upcoming ASP cleaning window is approaching. Example: `notify.mobile_app_my_phone`. |
| `notify_lead_time` | Optional | `120` min | Minutes before a cleaning window starts at which the advance notification fires. Valid range: 15–480 min. |
| `parking_lat` | Optional | _(none)_ | Latitude of the home parking area (−90 to 90). Both `parking_lat` and `parking_lon` must be set together; a partial pair is silently discarded and all three parking keys are removed. |
| `parking_lon` | Optional | _(none)_ | Longitude of the home parking area (−180 to 180). See `parking_lat`. |
| `parking_radius` | Optional | `500` m | Radius in metres around the home parking area used for SODA cache pre-seeding. Valid range: 50–5 000 m, step 50. |

#### CalDAV calendar sync (optional, Phase 34)

The CalDAV step in the options flow lets the integration publish upcoming ASP cleaning windows to an external calendar. Submitting an empty `caldav_url` is a complete no-op — all CalDAV keys are stripped from the entry options. When a URL is provided, the integration probes the server during setup; any failure (auth, network, DNS, TLS) maps to a single `caldav_auth_failed` error and bad credentials are never persisted.

| Option key | Required | Default | Description |
|---|---|---|---|
| `caldav_url` | Optional | _(none)_ | CalDAV server URL. Empty value disables CalDAV sync entirely. |
| `caldav_username` | Optional | `""` | CalDAV account username. |
| `caldav_password` | Optional | `""` | CalDAV account password. Stored in the entry options; the form never echoes the stored value back on re-render. |
| `caldav_calendar` | Optional (required once a URL is set) | `""` | Target calendar, selected from a dropdown populated by the server after credentials validate. |
| `caldav_safety_window` | Optional | `15` min | Minutes of safety margin applied around a cleaning window when creating calendar events. Valid range: 0–240 min. |
| `caldav_event_title_template` | Optional | `ASP: {street}` | Event title template. Only `{placeholder}` substitutions are allowed; attribute (`{x.y}`) and index (`{x[y]}`) access are rejected. |

---

## Defaults

| Setting | Default value | Source |
|---|---|---|
| `movement_threshold` | `50.0` m | `custom_components/asp_parking/const.py` — `DEFAULT_MOVEMENT_THRESHOLD` |
| `refresh_interval` | `8` h | `custom_components/asp_parking/const.py` — `DEFAULT_REFRESH_INTERVAL` |
| `stale_timeout` | `8` h | `custom_components/asp_parking/const.py` — `DEFAULT_STALE_TIMEOUT` |
| `parking_radius` | `500` m | `custom_components/asp_parking/const.py` — `DEFAULT_PARKING_RADIUS` |
| `notify_lead_time` | `120` min | `custom_components/asp_parking/const.py` — `DEFAULT_NOTIFY_LEAD_TIME` |
| `notify_service` | `""` | `custom_components/asp_parking/const.py` — `DEFAULT_NOTIFY_SERVICE` |
| `nyc311_entity` | `""` | `custom_components/asp_parking/const.py` — `DEFAULT_NYC311_ENTITY` |
| `caldav_safety_window` | `15` min | `custom_components/asp_parking/const.py` — `DEFAULT_CALDAV_SAFETY_WINDOW` |
| `caldav_event_title_template` | `ASP: {street}` | `custom_components/asp_parking/const.py` — `DEFAULT_CALDAV_EVENT_TITLE_TEMPLATE` |
| SODA batch size | `1 000` records/page | `src/gps2asp/signs/client.py` — `SODAClient.DEFAULT_BATCH_SIZE` |
| SODA max retries | `3` | `src/gps2asp/signs/client.py` — `SODAClient.MAX_RETRIES` |
| SODA base retry delay | `1.0` s (exponential) | `src/gps2asp/signs/client.py` — `SODAClient.BASE_DELAY` |
| NYC 311 max retries | `3` | `custom_components/asp_parking/gps2asp/suspension/poller.py` — `NYC311Client.MAX_RETRIES` |
| NYC 311 base retry delay | `1.0` s (exponential) | `custom_components/asp_parking/gps2asp/suspension/poller.py` — `NYC311Client.BASE_DELAY` |
| Spatial snap distance | `164.0` ft (~50 m) | `src/gps2asp/resolver/spatial_index.py` — `max_distance_ft` default |
| GPS debounce cooldown | `5.0` s | `custom_components/asp_parking/const.py` — `GPS_DEBOUNCE_COOLDOWN` |
| Suspension poll interval | `60` min | `custom_components/asp_parking/const.py` — `DEFAULT_SUSPENSION_INTERVAL` |
| Stale index threshold | `60` days | `custom_components/asp_parking/const.py` — `STALE_INDEX_DAYS` |
| Remote-fresh threshold | `30` days | `custom_components/asp_parking/const.py` — `REMOTE_FRESH_DAYS` |
| Stale-check interval | `24` h | `custom_components/asp_parking/const.py` — `STALE_CHECK_INTERVAL_HOURS` |

---

## Per-Environment Overrides

There are no `.env.development` / `.env.production` files. Environment-specific configuration is handled as follows:

**Standalone library / scripts:**

Set shell environment variables before running. For example:

```bash
export GPS2ASP_INDEX_DIR=/data/gps2asp/index
export NYC_OPEN_DATA_APP_TOKEN=your_token_here
.venv/bin/python -c "import asyncio; from gps2asp.pipeline import resolve_asp; ..."
```

**Home Assistant:**

Environment variables are set in the HA process environment (e.g., `homeassistant.env` on supervised installs, or the Docker container's environment). `NYC_311_API_KEY` and `NYC_OPEN_DATA_APP_TOKEN` may alternatively be entered through the HA UI config flow, in which case the stored option takes precedence over the environment variable.

**Testing:**

Override the index directory per-test using either the `index_dir` constructor argument or `GPS2ASP_INDEX_DIR`. Call `SpatialIndex.reset()` between tests that need a fresh instance to clear the singleton.

```python
import os
os.environ["GPS2ASP_INDEX_DIR"] = str(tmp_path / "index")
SpatialIndex.reset()
```

---

## Spatial Index Location

The index files are **not included in the repository** (gitignored). They must be built locally before first use:

```bash
.venv/bin/python scripts/build_index.py
# Optional: write to a custom directory
.venv/bin/python scripts/build_index.py --output-dir /path/to/index
```

The build downloads the NYC Street Centerline (CSCL) dataset from NYC Open Data (`inkn-q76z`, ~122 K total rows, filtered to ~105 K vehicular segments; requires internet, ~4 min). The output is written to `src/gps2asp/data/index/` by default, which is the package-default path read at runtime. The build also writes a `build_info.json` with row counts and timing statistics.

For Home Assistant installs without a local Python environment, the index is downloaded from the GitHub release defined by `INDEX_DOWNLOAD_URL` in `custom_components/asp_parking/const.py` (`https://github.com/Pascal-ZeGerman/GPS2ASP-Resolver/releases/download/index-v1/index.zip`) and extracted to the path pointed to by `GPS2ASP_INDEX_DIR`. The integration tracks index staleness using the thresholds listed in the Defaults table (`STALE_INDEX_DAYS`, `REMOTE_FRESH_DAYS`) and re-checks once per `STALE_CHECK_INTERVAL_HOURS`.

---

## Debug Options (Home Assistant)

The coordinator exposes debug overrides via the HA config entry options. These are not environment variables and are intended for development use only.

| Option key | Default | Description |
|---|---|---|
| `debug_lat` | `None` | Override latitude fed to the pipeline (ignores device tracker). |
| `debug_lon` | `None` | Override longitude fed to the pipeline (ignores device tracker). |
| `debug_datetime` | `None` | Override the current datetime used for next-move calculations. |
| `suppress_notifications` | `False` | Suppress HA notifications during debug sessions. Resets to `False` on every HA restart. |

Debug mode is toggled at runtime via the `asp_parking` switch entity — it is not persisted to the config entry options. The coordinator unconditionally resets `_debug_enabled = False` on `async_start`, so the switch is the sole runtime setter. There is no `debug_enabled` config option (removed in an earlier phase).
