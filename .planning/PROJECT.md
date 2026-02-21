# GPS2ASP Resolver

## What This Is

A Python tool that resolves a car's GPS coordinates to Alternate Side Parking (ASP) rules for that specific curb location in NYC. Given lat/long from a VW CarNet Home Assistant integration, it determines which side of the street the car is on, looks up the ASP schedule for that block segment, and returns when the car next needs to move. It also factors in ASP suspensions (holidays, snow emergencies, etc.).

## Core Value

Tell the user exactly when they need to move their car for ASP — "next time to move is [datetime]" — so they never get a ticket.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Accept GPS coordinates (lat/long WGS84) as input from HA integration
- [ ] Convert GPS coordinates to NY State Plane to match NYC Open Data sign locations
- [ ] Resolve GPS point to nearest street segment and correct side of street
- [ ] Query NYC Open Data (SODA API) for ASP/broom signs on that block segment and side
- [ ] Parse sign descriptions to extract ASP schedule (days, time windows)
- [ ] Compute the next upcoming ASP window from current datetime
- [ ] Return "next time to move" datetime as primary output
- [ ] Cache ASP sign data per block segment with weekly refresh
- [ ] Handle NYC holiday ASP suspension calendar
- [ ] Cron job to check for weather-based ASP suspensions (snow, rain, etc.)
- [ ] Push HA notification when move time is approaching
- [ ] Return structured data for HA automation consumption

### Out of Scope

- Real-time parking availability / open spot finding — this is about ASP rules only
- Other parking regulations (meters, no standing, hydrants) — ASP/broom signs only for v1
- Mobile app or web UI — this is a backend function for Home Assistant
- Multi-vehicle support — single car for now
- Parking guidance (where to move TO) — just tells you WHEN to move

## Context

- **Data source**: NYC Open Data dataset `nfid-uabd` (Parking Regulation Locations and Signs) via SODA API. ASP signs identifiable by `"SANITATION BROOM SYMBOL"` in `sign_description`. Contains street name, from/to cross streets, side of street (N/S/E/W), and parseable schedule text like `"TUESDAY FRIDAY 8:30AM-10AM"`.
- **Coordinate systems**: GPS provides WGS84 lat/long. NYC Open Data uses NY State Plane (NAD83, feet) for `sign_x_coord`/`sign_y_coord`. Conversion needed via `pyproj`.
- **OpenCurb API** (`opencurb.nyc`): Alternative data source that accepts GPS directly and returns curb regulations as GeoJSON. Works in Brooklyn despite claiming Manhattan only. Could serve as validation or fallback, but doesn't expose raw ASP schedules in a parseable way for "next time to move" computation.
- **ASP suspensions**: NYC suspends ASP on ~30+ holidays/year. Weather-based suspensions (snow emergencies) are announced via NYC 311 / DSNY. Need a cron job to poll for these.
- **Primary area**: Prospect Heights, Brooklyn and surrounding neighborhoods. Should work for all NYC.
- **Integration**: VW CarNet / WeConnect Home Assistant integration provides `device_tracker` entity with `latitude`/`longitude` attributes.

## Constraints

- **Runtime**: Python — native HA integration language, good library ecosystem (pyproj, requests)
- **Platform**: Home Assistant — function gets called by existing automation that polls car GPS
- **Data freshness**: ASP signs rarely change (~yearly). Cache with weekly refresh is sufficient.
- **Network**: SODA API is free, no auth required. Suspension checks need periodic polling.
- **Accuracy**: GPS accuracy (~3-5m) is sufficient to place car on correct curb side per user confirmation.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| NYC Open Data as primary source | Parseable ASP schedules in sign descriptions, all boroughs, free SODA API | — Pending |
| Local cache with live fallback | ASP signs rarely change, avoid unnecessary API calls, works offline after first lookup | — Pending |
| Python for implementation | Native HA language, pyproj for coord conversion, requests for API | — Pending |
| Focus on "my side's next window" | User's primary need is knowing when to move away, not where to move to | — Pending |
| Full suspension handling | Holidays + cron for weather suspensions — avoids unnecessary moves | — Pending |

---
*Last updated: 2026-02-21 after initialization*
