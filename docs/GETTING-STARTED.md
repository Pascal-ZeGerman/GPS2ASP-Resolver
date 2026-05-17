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

1. Open HACS in your Home Assistant sidebar.
2. Click **Integrations**, then click the three-dot menu (top-right) and choose **Custom repositories**.
3. Enter `https://github.com/Pascal-ZeGerman/GPS2ASP-Resolver` and select **Integration**, then click **Add**.
4. Search for **ASP Parking** and click **Download**.
5. Restart Home Assistant.

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

5. **Step 3:** Optionally enter an **NYC311 API key** for real-time suspension alerts. <!-- VERIFY: obtain key from https://api-portal.nyc.gov/ -->
6. Click **Submit**. Sensors appear immediately under the new device.

On first HA setup, if no local spatial index exists, the integration downloads `index.zip` from the GitHub releases page automatically. No manual build step is required.

### Python library — build the spatial index

The spatial index must be built before the resolver can run. This step downloads ~160 K street segments from NYC Open Data and takes approximately 3–5 minutes.

```bash
.venv/bin/python scripts/build_index.py
```

The index is written to `src/gps2asp/data/index/`. To use a custom output location, set `GPS2ASP_INDEX_DIR` before running the script.

### Python library — run the pipeline demo

Once the index is built, run the bundled example to confirm everything works:

```bash
.venv/bin/python examples/run_pipeline.py
```

This resolves a hardcoded Brooklyn location (Prospect Place between Vanderbilt Ave and Carlton Ave) using the live SODA API. Pass custom coordinates as arguments:

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

The spatial index has not been built yet. Run `build_index.py` before calling any resolver function. The build requires the `[build]` extras (`geopandas`, `requests`):

```bash
.venv/bin/python -m pip install -e ".[build]"
.venv/bin/python scripts/build_index.py
```

**`ModuleNotFoundError: No module named 'gps2asp'`**

The package has not been installed in editable mode. Run:

```bash
.venv/bin/python -m pip install -e ".[dev]"
```

**SODA API rate-limit errors during index build**

The NYC Open Data anonymous pool can throttle requests during peak hours. Set an app token to use a dedicated rate-limit pool: <!-- VERIFY: obtain token from https://opendata.cityofnewyork.us/overview/ -->

```bash
export NYC_OPEN_DATA_APP_TOKEN=your_token_here
.venv/bin/python scripts/build_index.py
```

**HA sensor shows "No street match" after setup**

The GPS fix may be imprecise or the tracker has not yet reported coordinates. Wait for the tracker to update, or check that the device tracker entity has `gps_accuracy` below ~50 m. Indoor or parking-garage fixes are common causes.

**`pytest-homeassistant-custom-component` install fails**

This package requires a compatible Python version. Use Python `3.11` or later and ensure you are installing into the project's `.venv/`, not the system Python (which is externally managed per PEP 668).

---

## Next Steps

- **[docs/ARCHITECTURE.md](ARCHITECTURE.md)** — In-depth reference for the three-stage pipeline (GPS → spatial index → sign API → schedule parser), suspension calendar subsystem, and Home Assistant integration internals.
- **[docs/CONFIGURATION.md](CONFIGURATION.md)** — Full reference for environment variables (`GPS2ASP_INDEX_DIR`, `NYC_OPEN_DATA_APP_TOKEN`, `NYC_311_API_KEY`) and Home Assistant config-flow options.
