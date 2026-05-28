<!-- generated-by: gsd-doc-writer -->
# Getting Started

This guide covers everything you need to go from a fresh clone to a running instance of `gps2asp`, whether you are a Home Assistant user installing the integration or a developer working on the library itself.

---

## Prerequisites

### Home Assistant users

- Home Assistant `2025.1.0` or later (as declared in `hacs.json`)
- A device tracker entity that provides GPS coordinates (e.g. the HA Companion app, OwnTracks, iCloud, or the Google Maps integration)
- Your vehicle must be parked somewhere in New York City

No Python knowledge or terminal access is required for the HA integration.

### Library / developer use

- Python `>= 3.11` (as declared in `pyproject.toml` `requires-python`)
- A virtual environment at `.venv/` (see Installation below)
- Internet access for the index build step and SODA API calls

CI runs against Python `3.14` (`.github/workflows/pytest.yml`); any `3.11+` release works locally.

---

## Installation

### Home Assistant — via HACS (recommended)

The fastest path is the one-click My Home Assistant button (the same one in the project [README](../README.md)):

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Pascal-ZeGerman&repository=GPS2ASP-Resolver&category=integration)

1. Click the button above — it opens this repository directly inside HACS.
2. Click **Download**.
3. Restart Home Assistant.

Prefer to add it by hand? Open HACS, click the three-dot menu (top-right) and choose **Custom repositories**, paste `https://github.com/Pascal-ZeGerman/GPS2ASP-Resolver`, select **Integration**, click **Add**, then search for **ASP Parking** and click **Download**. Restart Home Assistant when finished.

The integration bundles a vendored copy of the `gps2asp` library — no separate Python package install is needed.

### Home Assistant — manual installation

1. Download the latest release from the [Releases page](https://github.com/Pascal-ZeGerman/GPS2ASP-Resolver/releases).
2. Copy the `custom_components/asp_parking/` folder into your HA config directory under `custom_components/`.
3. Restart Home Assistant.

### Python library (developer / standalone use)

```bash
# Clone the repository
git clone https://github.com/Pascal-ZeGerman/GPS2ASP-Resolver.git
cd GPS2ASP-Resolver

# Create a virtual environment
python3 -m venv .venv

# Install the library and dev dependencies
.venv/bin/python -m pip install -e ".[dev]"
```

To build the spatial index (required before any resolver calls) you also need the build extras:

```bash
.venv/bin/python -m pip install -e ".[build]"
```

---

## First Run

### Home Assistant

After installation, configure the integration from the HA UI — no YAML required.

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **ASP Parking** and click it.
3. **Step 1:** Select the device tracker entity that follows your car.
4. **Step 2:** Adjust thresholds (optional — defaults work for most users):

   | Option | Default | Description |
   |--------|---------|-------------|
   | Movement threshold | 50 m | Minimum distance the car must move before re-fetching the schedule |
   | Refresh interval | 8 h | Periodic forced refresh even without GPS movement |
   | Stale timeout | 8 h | How long to keep the last known schedule after the tracker goes unavailable |

5. **Step 3:** Optionally enter an **NYC311 API key** for real-time weather and emergency suspension alerts. <!-- VERIFY: obtain key from https://api-portal.nyc.gov/ -->
6. Click **Submit**. Sensors appear immediately under the new device.

On first HA setup, if no local spatial index exists, the integration downloads `index.zip` from the GitHub releases page automatically (the `index-v1` release tag). No manual build step is required.

After setup you can configure additional options — a home **parking area** (lat/lon/radius), a **push notification service**, and **CalDAV calendar sync** — via **Settings → Devices & Services → ASP Parking → Configure**.

### Python library — build the spatial index

The spatial index must be built before the resolver can run. This step downloads the NYC Street Centerline (CSCL) dataset (~122 K segments) from NYC Open Data and takes approximately 3–5 minutes.

```bash
.venv/bin/python scripts/build_index.py
```

The index is written to `src/gps2asp/data/index/`. To write to a custom location, pass `--output-dir /path/to/index` or set the `GPS2ASP_INDEX_DIR` environment variable before running the script.

### Python library — run the pipeline demo

Once the index is built, run the bundled example to confirm everything works:

```bash
.venv/bin/python examples/run_pipeline.py
```

This resolves a hardcoded Brooklyn location (Prospect Place between Vanderbilt Ave and Carlton Ave — `40.677629, -73.968527`) using the live SODA API, printing both normal-mode and debug-mode results. Pass custom coordinates as arguments:

```bash
.venv/bin/python examples/run_pipeline.py 40.7580 -73.9855
```

### Run the test suite

```bash
# Fast tests only (no network calls, no HA fixtures)
.venv/bin/pytest -m "not integration and not ha_integration"

# Full suite (requires internet access for integration tests)
.venv/bin/pytest
```

---

## Common Setup Issues

**`IndexNotFoundError` on first run**

The spatial index has not been built yet. The error message is `Spatial index files not found in '<dir>'. Run the build script to create the index first.` Run `build_index.py` before calling any resolver function. The build requires the `[build]` extras (`geopandas`, `requests`):

```bash
.venv/bin/python -m pip install -e ".[build]"
.venv/bin/python scripts/build_index.py
```

**`ModuleNotFoundError: No module named 'gps2asp'`**

The package has not been installed in editable mode. Run:

```bash
.venv/bin/python -m pip install -e ".[dev]"
```

**`OutsideNYCError` when resolving coordinates**

The latitude/longitude you passed falls outside NYC's bounding box (`lat 40.49–40.92, lon -74.27 to -73.68`). The resolver and integration only cover the five NYC boroughs — confirm the coordinates point to a location inside the city.

**SODA API rate-limit errors during index build**

The NYC Open Data anonymous pool can throttle requests during peak hours. Set an app token to use a dedicated rate-limit pool: <!-- VERIFY: obtain token from https://opendata.cityofnewyork.us/overview/ -->

```bash
export NYC_OPEN_DATA_APP_TOKEN=your_token_here
.venv/bin/python scripts/build_index.py
```

**HA sensor shows "No street match" after setup**

This surfaces a `NoSegmentFoundError` — no street segment was found within the snap distance (~164 ft / 50 m) of the reported GPS fix. The fix may be imprecise or the tracker has not yet reported coordinates. Wait for the tracker to update, or check that the device tracker entity has `gps_accuracy` below ~50 m. Indoor or parking-garage fixes are common causes.

**`pytest-homeassistant-custom-component` install fails**

This package requires a compatible Python version. Use Python `3.11` or later and ensure you are installing into the project's `.venv/`, not the system Python (which is externally managed per PEP 668).

---

## Next Steps

- **[docs/ARCHITECTURE.md](ARCHITECTURE.md)** — In-depth reference for the three-stage pipeline (GPS → spatial index → sign API → schedule parser), suspension calendar subsystem, and Home Assistant integration internals.
- **[docs/CONFIGURATION.md](CONFIGURATION.md)** — Full reference for environment variables (`GPS2ASP_INDEX_DIR`, `NYC_OPEN_DATA_APP_TOKEN`, `NYC_311_API_KEY`) and Home Assistant config-flow options.
