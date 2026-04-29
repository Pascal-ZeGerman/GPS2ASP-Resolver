[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration) [![GitHub release](https://img.shields.io/github/v/release/Pascal-ZeGerman/GPS2ASP-Resolver)](https://github.com/Pascal-ZeGerman/GPS2ASP-Resolver/releases) [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE) [![GitHub issues](https://img.shields.io/github/issues/Pascal-ZeGerman/GPS2ASP-Resolver)](https://github.com/Pascal-ZeGerman/GPS2ASP-Resolver/issues)

# ASP Parking — NYC Alternate Side Parking for Home Assistant

Never miss an alternate side parking window again. **ASP Parking** watches your car's GPS position via any Home Assistant device tracker, looks up the parking-regulation signs for your exact block, and tells you the next time you need to move — as a sensor you can put on your dashboard, use in automations, or push as a notification.

Supports all five NYC boroughs. Data is fetched live from NYC Open Data.

## What You Get

Three sensors are created for each tracked device:

| Sensor | What it shows |
|--------|---------------|
| Next move time | The datetime when alternate side parking begins on your block |
| Schedule summary | Human-readable schedule, e.g. "Mon 8–9:30 AM, Thu 11:30 AM–1 PM" |
| ASP active now | Binary sensor — ON while street cleaning is currently in progress |

## Requirements

- Home Assistant 2024.1 or later
- A device tracker entity with GPS coordinates (e.g. the HA Companion app, OwnTracks, iCloud, or the Google Maps integration)
- Your vehicle must be parked in New York City

No Python knowledge or terminal access required.

## Installation

### Via HACS (recommended)

1. Open HACS in your Home Assistant sidebar.
2. Click **Integrations**, then click the three-dot menu (top-right) and choose **Custom repositories**.
3. Enter `https://github.com/Pascal-ZeGerman/GPS2ASP-Resolver` and select **Integration**, then click **Add**.
4. Search for **ASP Parking** and click **Download**.
5. Restart Home Assistant.

### Manual installation

1. Download the latest release from the [Releases page](https://github.com/Pascal-ZeGerman/GPS2ASP-Resolver/releases).
2. Copy the `custom_components/asp_parking/` folder into your HA config directory under `custom_components/`.
3. Restart Home Assistant.

## Configuration

After installation, set up the integration from the HA UI — no YAML required.

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **ASP Parking** and click it.
3. Select the **device tracker** entity that follows your car.
4. (Optional) Adjust advanced options:

| Option | Default | Description |
|--------|---------|-------------|
| Movement threshold | 50 m | Minimum distance the car must move before re-fetching the schedule |
| Stale timeout | 30 min | How long to keep the last known schedule after the tracker goes unavailable |

5. Click **Submit**. The three sensors appear immediately under the new device.

## Known Limitations

**Coverage varies by borough.** ASP Parking matches your GPS location against NYC's official sign database. Some blocks — especially in Queens, the Bronx, and Manhattan — may return "schedule not found" because the city's open-data records don't always include every block. Coverage is best in Brooklyn.

**Staten Island** has very limited data in the city's sign database. Most Staten Island locations will show "no schedule found" through no fault of the integration.

**Suspended days.** The integration is aware of citywide ASP suspension days (holidays, snow emergencies). When ASP is suspended, the sensors reflect that automatically.

**Accuracy.** Results depend on your device tracker's GPS precision. Indoors or in parking garages, the GPS fix may point to the wrong block.

## FAQ

**Q: The sensor shows "schedule not found" — what does that mean?**
Your block's sign data isn't in NYC's open database yet, or the GPS fix landed on a block without ASP restrictions. Try moving a few meters outside and triggering a refresh.

**Q: How often does the data update?**
The schedule is re-fetched each time your car moves more than the movement threshold (default 50 m). There is no fixed polling interval.

**Q: Can I use this outside NYC?**
No. The integration is hard-coded to NYC's street database and sign API.

**Q: Where do I report bugs or request features?**
Please open an issue on the [GitHub issue tracker](https://github.com/Pascal-ZeGerman/GPS2ASP-Resolver/issues).

## For Developers

If you want to understand the three-stage pipeline (GPS → spatial index → sign API → schedule parser), the suspension calendar subsystem, or how to contribute, see the in-depth reference:

[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
