[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration) [![GitHub release](https://img.shields.io/github/v/release/Pascal-ZeGerman/GPS2ASP-Resolver)](https://github.com/Pascal-ZeGerman/GPS2ASP-Resolver/releases) [![GitHub issues](https://img.shields.io/github/issues/Pascal-ZeGerman/GPS2ASP-Resolver)](https://github.com/Pascal-ZeGerman/GPS2ASP-Resolver/issues)

# ASP Parking — NYC Alternate Side Parking for Home Assistant

Never miss an alternate side parking window again. **ASP Parking** watches your car's GPS position via any Home Assistant device tracker, looks up the parking-regulation signs for your exact block, and tells you the next time you need to move — as a sensor you can put on your dashboard, use in automations, or push as a notification.

Supports all five NYC boroughs. Data is fetched live from NYC Open Data.

---

## Table of Contents

- [Live Demo](#live-demo)
- [Installation](#installation)
- [Configuration](#configuration)
- [Requirements](#requirements)
- [What You Get](#what-you-get)
- [Dashboard](#dashboard)
- [CalDAV Calendar Sync](#caldav-calendar-sync)
- [Suspension Awareness](#suspension-awareness)
- [Upgrade Notes](#upgrade-notes)
- [Known Limitations](#known-limitations)
- [FAQ](#faq)
- [For Developers](#for-developers)

---

## Live Demo

Want to see what the integration produces before installing anything? Two static pages are
hosted at **<https://pascal-zegerman.github.io/GPS2ASP-Resolver/>** — pick the one for you:

- **[Try the demo](https://pascal-zegerman.github.io/GPS2ASP-Resolver/demo/)** — for everyone.
  Click a block on the Leaflet map and see exactly what ASP Parking resolves for that location:
  the parking rule for the block, the next time you'd need to move your car, the exact Home
  Assistant sensor entities and states it would create, and an animated calendar of the weekly
  cleaning windows.
- **[Explore sign coverage](https://pascal-zegerman.github.io/GPS2ASP-Resolver/explorer/)** —
  for maintainers and technical users. A citywide map of all ~105K street segments colored by
  SODA-match confidence, with filters by borough/tier/level and GeoJSON export, for inspecting
  data coverage and gaps.

Both are plain HTML/CSS/JS pages under [`docs/`](docs/) — no build step, no install, no
server-side code. [`docs/index.html`](docs/index.html) is the landing page linking to both.

**Where the data comes from.** The demo does **not** call any live API from the browser.
It reads a **dated snapshot** committed to the repo at
[`docs/demo/data/demo.json`](docs/demo/data/demo.json) (snapshot date: **2026-08-02**),
plus the matched segment geometries in `docs/demo/data/demo-segments.geojson`. The snapshot
stores *weekly recurring patterns* rather than absolute datetimes, and the page recomputes the
next move time in your browser at NYC time — so the "next move" stays correct even though the
underlying data is frozen. Because it's a static snapshot, the demo works offline and never
needs a token.

**Regenerating the snapshot.** The dataset is produced offline (not in CI) by
`scripts/build_demo_dataset.py`. From a checkout with the project installed:

```bash
.venv/bin/python scripts/build_demo_dataset.py --out-dir docs/demo/data
```

This requires two things the demo page itself does not: the **spatial index** must be present
locally, and the script needs **network access to the NYC Open Data (SODA) API**. The index is
gitignored (~95 MB), so build it once with `.venv/bin/python scripts/build_index.py` **or** download the
released `index-v1` asset from the [Releases page](https://github.com/Pascal-ZeGerman/GPS2ASP-Resolver/releases).
Setting a `NYC_OPEN_DATA_APP_TOKEN` environment variable is optional but helps avoid SODA rate
limiting. The generated `demo.json`/`demo-segments.geojson` are the only files committed — the
index never is.

**Running it locally.** Serve the whole `docs/` tree over HTTP (opening `index.html` via `file://`
won't let the page `fetch()` its JSON, and serving `docs/demo` alone 404s on the shared
`../common.js`/`../common.css` the page loads):

```bash
.venv/bin/python -m http.server --directory docs 8000
```

Then visit <http://localhost:8000/> for the landing page (or `/demo/`, `/explorer/` directly).

**Hosting it.** The repo ships a [`.github/workflows/pages.yml`](.github/workflows/pages.yml)
workflow that publishes the committed `docs/` tree to **GitHub Pages** on every push to `docs/`
(and on demand via *workflow_dispatch*). The workflow publishes the snapshot as-is and never
runs the precompute. Pages is already enabled for this repo (**Settings → Pages → Source: GitHub
Actions**), so every push to `docs/` on `main` redeploys automatically.

---

## Installation

### Via HACS (recommended)

The fastest way to install. Click the button below, then **Download** and restart Home Assistant.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Pascal-ZeGerman&repository=GPS2ASP-Resolver&category=integration)

1. Click the button above — it opens this repository directly inside HACS.
2. Click **Download**.
3. Restart Home Assistant.

Prefer to add it by hand? In HACS, open the three-dot menu (top-right) and choose **Custom repositories**, paste `https://github.com/Pascal-ZeGerman/GPS2ASP-Resolver`, select **Integration**, click **Add**, then search for **ASP Parking** and click **Download**. Restart Home Assistant when finished.

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

### Changing settings after setup

ASP Parking splits post-setup changes across two different menus on the integration's card
under **Settings → Devices & Services → ASP Parking** — look for the right one or the option
you want won't be there:

| Menu | How to open it | What it changes |
|------|-----------------|------------------|
| **Configure** | Click the gear icon | Movement threshold, refresh interval, stale timeout, NYC 311 API key/entity, push notification service, parking area, CalDAV sync |
| **Reconfigure** | Click the **⋮** (three-dot) menu → **Reconfigure** | Only the device tracker — swap which entity's GPS the integration follows (e.g. after switching phones, renaming a tracker entity, or moving to a different GPS source) |

The device tracker picker is **only** under Reconfigure, not Configure — this is the most common
place people get stuck looking for it.

---

## Requirements

- Home Assistant 2025.1.0 or later
- A device tracker entity with GPS coordinates (e.g. the HA Companion app, OwnTracks, iCloud, or the Google Maps integration)
- Your vehicle must be parked in New York City

No Python knowledge or terminal access required.

---

## What You Get

Three main entities are created for each tracked device:

| Entity | Type | What it shows |
|--------|------|---------------|
| Next move time | Sensor | The datetime when alternate side parking begins on your block |
| ASP active now | Binary sensor | ON while street cleaning is currently in progress |
| Debug mode | Switch (diagnostic) | Toggle debug/simulation mode from the dashboard |

The next move time sensor also carries rich attributes including `schedule_summary` (e.g., `"Mon 8–9:30 AM, Thu 11:30 AM–1 PM"`), `cleaning_days`, `side_of_street`, `urgency`, and suspension state.

Eleven additional **diagnostic sensors** are created automatically: car name, VIN, latitude, longitude, resolved street, resolution status, confidence score, SODA level, last resolved timestamp, last error, and index last rebuilt. These are hidden from the default dashboard but available for advanced automations and troubleshooting.

**Car Name** and **VIN** are read directly from your device tracker entity — Car Name from its friendly name, VIN from a `vin` attribute if the entity exposes one. Vehicle-specific integrations (like a manufacturer's connected-car integration) typically provide both. Phone-based trackers (Companion app, OwnTracks, iCloud, Google Maps) usually don't expose a VIN, so that sensor will simply show unavailable — this doesn't affect any other functionality.

Two additional diagnostic binary sensors track background health: **Index rebuilding** (ON while a spatial-index rebuild is in progress) and **GPS pipeline healthy** (ON while the resolution pipeline is functioning normally). A **Rebuild index** button is also available for triggering an on-demand index rebuild.

---

## Dashboard

Add the **Next move time** sensor to an Entities or Entity card for an at-a-glance reminder. The sensor's `urgency` attribute (`high` when the next window is today, otherwise `normal`) and the `next_move_is_today` / `next_move_is_tomorrow` boolean attributes are ideal for conditional card styling or for triggering notifications.

---

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

---

## Suspension Awareness

The integration is aware of citywide ASP suspension days. It checks the NYC DOT holiday calendar automatically on startup. If you provide an NYC311 API key, it also polls for real-time emergency suspensions (weather events, sanitation emergencies) every 60 minutes. When ASP is suspended, the next move sensor shows "Suspended" and the binary sensor turns off automatically.

If you have the companion [ha-nyc311](https://github.com/Pascal-ZeGerman/ha-nyc311) integration installed, ASP Parking can subscribe to its `binary_sensor.nyc311_parking_exception_today` entity for real-time suspension updates without requiring a separate API key.

---

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

---

## Known Limitations

**Coverage varies by borough.** ASP Parking matches your GPS location against NYC's official sign database. Based on the initial index build, approximate borough coverage was: Brooklyn ~47.9%, Manhattan ~29.5%, Bronx ~28.6%, Queens ~18.1%, Staten Island ~0%. The index now rebuilds automatically on a monthly schedule, so actual coverage may have improved since; these figures are a rough baseline rather than a live measurement. The integration uses graph-based BFS matching to improve coverage for mid-block locations that fall in the middle of a sign record rather than at its boundary cross-streets.

**Staten Island** has very limited data in the city's sign database. Most Staten Island locations will show "no schedule found" through no fault of the integration.

**Accuracy.** Results depend on your device tracker's GPS precision. Indoors or in parking garages, the GPS fix may point to the wrong block.

---

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

---

## For Developers

If you want to understand the three-stage pipeline (GPS → spatial index → sign API → schedule parser), the suspension calendar subsystem, or how to contribute, see the in-depth reference:

[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
