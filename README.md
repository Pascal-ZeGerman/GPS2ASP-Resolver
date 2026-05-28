<!-- generated-by: gsd-doc-writer -->
[![GitHub release](https://img.shields.io/github/v/release/Pascal-ZeGerman/GPS2ASP-Resolver)](https://github.com/Pascal-ZeGerman/GPS2ASP-Resolver/releases) [![GitHub issues](https://img.shields.io/github/issues/Pascal-ZeGerman/GPS2ASP-Resolver)](https://github.com/Pascal-ZeGerman/GPS2ASP-Resolver/issues)

# ASP Parking — NYC Alternate Side Parking for Home Assistant

Never miss an alternate side parking window again. **ASP Parking** watches your car's GPS position via any Home Assistant device tracker, looks up the parking-regulation signs for your exact block, and tells you the next time you need to move — as a sensor you can put on your dashboard, use in automations, or push as a notification.

Supports all five NYC boroughs. Data is fetched live from NYC Open Data.

## What You Get

Three main entities are created for each tracked device:

| Entity | Type | What it shows |
|--------|------|---------------|
| Next move time | Sensor | The datetime when alternate side parking begins on your block |
| ASP active now | Binary sensor | ON while street cleaning is currently in progress |
| Debug mode | Switch (diagnostic) | Toggle debug/simulation mode from the dashboard |

The next move time sensor also carries rich attributes including `schedule_summary` (e.g., `"Mon 8–9:30 AM, Thu 11:30 AM–1 PM"`), `cleaning_days`, `side_of_street`, `urgency`, and suspension state.

Ten additional **diagnostic sensors** are created automatically: car name, VIN, latitude, longitude, resolved street, resolution status, confidence score, SODA level, last resolved timestamp, and last error. These are hidden from the default dashboard but available for advanced automations and troubleshooting.

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
3. **Step 1:** Select the **device tracker** entity that follows your car.
4. **Step 2:** Adjust thresholds (optional):

| Option | Default | Description |
|--------|---------|-------------|
| Movement threshold | 50 m | Minimum distance the car must move before re-fetching the schedule |
| Refresh interval | 8 h | Periodic forced refresh, even without GPS movement |
| Stale timeout | 8 h | How long to keep the last known schedule after the tracker goes unavailable |

5. **Step 3:** Optionally enter an **NYC311 API key** to receive real-time weather and emergency suspension alerts.
6. Click **Submit**. The sensors appear immediately under the new device.

After setup you can also configure a **parking area** (lat/lon/radius) and a **push notification service** (e.g., `notify.mobile_app_my_phone` with a configurable lead time) via **Settings → Devices & Services → ASP Parking → Configure**.

## CalDAV Calendar Sync

ASP Parking can write your next-move events to a CalDAV calendar so the event appears automatically in your calendar app whenever a new cleaning window is detected. Supported servers include Nextcloud, Fastmail, iCloud, and any other standards-compliant CalDAV server.

**Setup:** Go to **Settings → Devices & Services → ASP Parking → Configure**, then open the **CalDAV** step. Enter your server URL, username, and password and click Submit. On the next screen, choose which calendar should receive events.

### Event title template

The title of each calendar event is generated from a template. The default template is `ASP: {street}`, which produces titles like `ASP: VANDERBILT AVENUE`. You can customise it using the following placeholders:

| Placeholder | Inserts | Example value |
|-------------|---------|---------------|
| `{street}` | The street name where your car is parked | `VANDERBILT AVENUE` |
| `{side}` | The side of the street (compass direction) | `N`, `S`, `E`, or `W` |
| `{time}` | The full cleaning schedule for that block | `Mon 8–9:30 AM, Thu 11:30 AM–1 PM` |

**Example templates:**

| Template | Produces |
|----------|----------|
| `ASP: {street}` *(default)* | `ASP: VANDERBILT AVENUE` |
| `Move car — {street} ({side} side)` | `Move car — VANDERBILT AVENUE (N side)` |
| `ASP {street}: {time}` | `ASP VANDERBILT AVENUE: Mon 8–9:30 AM, Thu 11:30 AM–1 PM` |

Plain text with no placeholders is also valid (e.g., just `Move car`). Unknown placeholders are preserved literally so a typo like `{streeet}` appears as-is rather than causing an error.

**Safety window:** Position changes within the configured safety window (default: 15 minutes) before the next move time will not delete the calendar event — this prevents the reminder from disappearing just before you need to act.

## Suspension Awareness

The integration is aware of citywide ASP suspension days. It checks the NYC DOT holiday calendar automatically on startup. If you provide an NYC311 API key, it also polls for real-time emergency suspensions (weather events, sanitation emergencies) every 60 minutes. When ASP is suspended, the next move sensor shows "Suspended" and the binary sensor turns off automatically.

If you have the companion [ha-nyc311](https://github.com/Pascal-ZeGerman/ha-nyc311) integration installed, ASP Parking can subscribe to its `binary_sensor.nyc311_parking_exception_today` entity for real-time suspension updates without requiring a separate API key.

## Upgrade Notes

### v3.2 — Sensor Display Format (Breaking change)

**What changed.** Before this release, the `sensor.asp_parking_next_move_time` state used a short format like `"Mon 8:30 AM"` (or `"⚠ Today 8:30 AM"` when the next window was less than 12 hours away). After this release, the state uses a three-tier date-aware format:

- **Today**: `"⚠ Today, 8:30 AM"` — when the next move is today in Home Assistant's configured local timezone
- **Tomorrow**: `"Tomorrow, 8:30 AM"` — when the next move is tomorrow
- **Other day**: `"Thursday (5/3), 8:30 AM"` — full weekday name plus unpadded `M/D` for any other day

The "Today" gate now compares the move's local date against Home Assistant's configured local timezone. Previously it used a 12-hour seconds-until threshold, which could mislabel an 8 AM move shown at 11 PM the night before as "Today" instead of "Tomorrow". The new gate is wall-clock-correct for any HA install regardless of where the user (or their HA instance) sits.

**Templates affected.** Any Lovelace card or automation that did state-string matching on the prior format will break, for example:

- `{% if states.sensor.asp_parking_next_move_time.state.startswith('Mon ') %}`
- `{% if '⚠ Today' in states.sensor.asp_parking_next_move_time.state %}`

**Migration.**

- Replace state-string matching with the new boolean attributes on the next-move sensor:
  - `next_move_is_today` — `True` when the next move is today in HA's local timezone, `False` otherwise
  - `next_move_is_tomorrow` — `True` when the next move is tomorrow, `False` otherwise

  Both attributes are always present (`False` when no move datetime exists), so templates can read them safely without `| default(false)`.
- For raw datetime access, the existing `next_window_start` attribute (ISO 8601 string) is preserved unchanged — it remains the stable programmatic-access surface for templates and automations that need the underlying timestamp rather than the rendered label.

## Known Limitations

**Coverage varies by borough.** ASP Parking matches your GPS location against NYC's official sign database. As of the current index build, approximate borough coverage is: Brooklyn ~47.9%, Manhattan ~29.5%, Bronx ~28.6%, Queens ~18.1%, Staten Island ~0%. The integration uses graph-based BFS matching to improve coverage for mid-block locations that fall in the middle of a sign record rather than at its boundary cross-streets.

**Staten Island** has very limited data in the city's sign database. Most Staten Island locations will show "no schedule found" through no fault of the integration.

**Accuracy.** Results depend on your device tracker's GPS precision. Indoors or in parking garages, the GPS fix may point to the wrong block.

## FAQ

**Q: The sensor shows "No restrictions" — what does that mean?**
Your block either has no alternate side parking restrictions, or the block's sign data isn't in NYC's open database yet. Try moving a few meters outside and waiting for a GPS update.

**Q: The sensor shows "No street match" — what does that mean?**
The GPS coordinates resolved to a location that couldn't be matched to a street segment in the spatial index. This can happen if the GPS fix is very imprecise or lands on a non-street area.

**Q: How often does the data update?**
The schedule is re-fetched each time your car moves more than the movement threshold (default 50 m) and on a periodic forced refresh (default every 8 hours). There is no fixed short-interval polling.

**Q: Can I use this outside NYC?**
No. The integration is built exclusively for NYC's street database and sign API.

**Q: Where do I report bugs or request features?**
Please open an issue on the [GitHub issue tracker](https://github.com/Pascal-ZeGerman/GPS2ASP-Resolver/issues).

## For Developers

If you want to understand the three-stage pipeline (GPS → spatial index → sign API → schedule parser), the suspension calendar subsystem, or how to contribute, see the in-depth reference:

[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
