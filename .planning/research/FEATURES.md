# Feature Research

**Domain:** NYC Alternate Side Parking (ASP) GPS resolver for Home Assistant
**Researched:** 2026-02-21
**Confidence:** MEDIUM-HIGH

## Feature Landscape

### Table Stakes (Users Expect These)

Features the tool must have or it is useless as an ASP resolver. These are what every competitor (SpotAngels, Parkr, ASP NYC) provides in some form, and what the PROJECT.md core value requires.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| GPS-to-street-segment resolution | Core function -- must resolve lat/long to the correct block and side of street | HIGH | Requires WGS84-to-NY-State-Plane conversion via `pyproj`, then nearest-sign matching against NYC Open Data `sign_x_coord`/`sign_y_coord`. Hardest part is correctly identifying which side of the street the car is on. |
| ASP sign data lookup | Must retrieve the actual ASP/broom sign rules for the resolved location | MEDIUM | Query SODA API dataset `nfid-uabd` filtering for `SANITATION BROOM SYMBOL` in `sign_description`. Returns day/time schedule text like `"TUESDAY FRIDAY 8:30AM-10AM"`. |
| Sign description parsing | Must extract structured schedule (days, start time, end time) from free-text sign descriptions | MEDIUM | NYC sign text follows semi-consistent patterns but has variations. Need robust parser, not brittle regex. Sign legend shows formats like `"NO PARKING [DAYS] [TIME RANGE]"` with broom symbol. |
| Next-move-time computation | The primary output: "You need to move your car by [datetime]" | MEDIUM | Given parsed schedule + current datetime, compute the next upcoming ASP window. Must handle week rollover, multiple cleaning days per week (e.g., Tue+Fri), and edge cases like "it's currently during an ASP window." |
| Holiday suspension calendar | ASP is suspended 30+ days/year for holidays -- ignoring this means false alerts | LOW | NYC DOT publishes annual ICS and PDF calendars. The NYC 311 API (`api-portal.nyc.gov`) returns structured JSON with `"status": "IN EFFECT"` or suspended status. The `ha-nyc311` integration already solves this for HA. |
| Weather/emergency suspension awareness | NYC suspends ASP for snow emergencies, sometimes announced late in the day | MEDIUM | No clean API. Sources: `@NYCASP` on X/Twitter (posts daily ~7AM), NYC 311 API status endpoint, Notify NYC alerts. Requires polling/cron since decisions are made as late as same-day. |
| Local caching of sign data | ASP signs rarely change (~yearly). Hitting the API on every lookup is wasteful and fragile | LOW | Cache sign data per block segment. Weekly refresh is sufficient per PROJECT.md. SQLite or JSON file cache. SODA API has no rate limit with app token but network dependency is a reliability concern. |

### Differentiators (Competitive Advantage)

Features that no existing ASP tool provides in the Home Assistant context. These are what make GPS2ASP Resolver worth building rather than just using SpotAngels or Parkr.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Home Assistant native integration | No existing tool resolves GPS coordinates from a car tracker entity directly to ASP rules within HA. SpotAngels/Parkr are phone apps requiring manual interaction. This is fully automated. | HIGH | Must expose sensor entities (next move time, current ASP status, suspension status). The `ha-nyc311` integration handles suspension binary sensors but does NOT do GPS resolution or schedule lookup. This fills the gap. |
| VW CarNet/WeConnect GPS auto-consumption | Automatically reads `device_tracker` entity attributes (`latitude`/`longitude`) from the VW CarNet HA integration. Zero user interaction required after parking. | LOW | Standard HA entity attribute reading. The VW integration (transitioning from `weconnect-python` to `CarConnectivity`) provides these attributes on the device tracker entity. |
| Proactive push notification with move deadline | HA actionable notifications pushed to phone at configurable lead time (e.g., 1 hour before ASP window). Includes "Snooze" or "Dismiss" actions. | MEDIUM | Uses HA `notify.mobile_app_*` service. Actionable notifications supported on both iOS and Android companion apps. Far superior to manual app-checking. |
| Automation-ready structured output | Returns machine-readable data (next move datetime, minutes until move, ASP active boolean, current side) that HA automations can consume for any downstream action. | LOW | Sensor entities with attributes. Enables things like: turn on a smart light red when move time is approaching, announce on smart speaker, etc. |
| Combined suspension + schedule intelligence | Merges the holiday/weather suspension status (from 311 API or `ha-nyc311`) with the location-specific ASP schedule to give a single authoritative answer: "Do I need to move or not?" | MEDIUM | Existing tools show suspension status OR sign rules separately. This tool combines them: if ASP is suspended tomorrow, your "next move time" shifts to the next non-suspended window. This is the killer feature. |
| Dual data source with fallback | Uses NYC Open Data (SODA) as primary with OpenCurb as validation/fallback for supported areas | LOW | OpenCurb only covers Midtown Manhattan (30th-59th St) per official docs despite user reports of Brooklyn working. Use as validation where available, not primary source. |

### Anti-Features (Commonly Requested, Often Problematic)

Features to explicitly NOT build. These are out of scope per PROJECT.md and would add complexity without serving the core value.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Real-time parking availability / spot finding | "Tell me WHERE to park" is a natural extension | Completely different data problem. Requires crowd-sourced real-time data (like SNAG Parking) or sensor networks. NYC has no public API for spot availability. Would multiply project scope 10x. | Stick to "WHEN to move" -- this is the validated need. Spot-finding apps (SpotAngels, SNAG) already exist. |
| Full parking regulation support (meters, no standing, hydrants) | "While you're at it, check all signs" | Parking regulation sign universe is enormous (~1M signs in NYC). ASP/broom signs have consistent patterns; other sign types are far more varied and complex to parse. Scope explosion. | ASP/broom signs only for v1. Other sign types could be a v2+ consideration if the ASP core proves valuable. |
| Mobile app or web UI | "I want to check on my phone" | This is a backend HA service. Building a UI duplicates SpotAngels/Parkr. HA already has a dashboard and companion app for viewing sensor states. | Use HA dashboard cards and companion app push notifications. The HA ecosystem IS the UI. |
| Multi-vehicle support | "I have two cars" | Adds state management complexity (which car is where, separate schedules). Single-car solves the immediate need. | Design data model to not preclude multi-car, but don't implement it. Single entity input, single schedule output. |
| Parking guidance (where to move TO) | "Tell me the nearest legal spot" | Requires real-time spot availability data that doesn't exist. Would need to scan multiple block segments, check their schedules, and somehow know if spots are open. | Tell the user WHEN to move. Where is their problem -- they know their neighborhood. |
| Historical ticket data / analytics | "Show me how many tickets I've avoided" | Nice vanity metric but zero practical value for the core use case. Adds database schema complexity for data that's hard to verify (did you actually avoid a ticket?). | If desired later, can be derived from notification history logs. Not worth building. |
| AI/ML predictions for suspensions | Parkr claims "AI-driven suspension predictions" but evidence of actual AI capability is thin | Weather-based suspensions are announced officially. Predicting before the official announcement is unreliable and creates false confidence. A wrong "it'll be suspended" prediction means a ticket. | Poll official sources (@NYCASP, 311 API). Faster and more reliable than predictions. The announcement IS the data. |

## Feature Dependencies

```
[GPS-to-street resolution]
    |--requires--> [Coordinate conversion (WGS84 to NY State Plane)]
    |--requires--> [SODA API connectivity]
    |--enables---> [ASP sign data lookup]
                       |--requires--> [Sign description parsing]
                                          |--enables---> [Next-move-time computation]
                                                             |--requires--> [Holiday suspension calendar]
                                                             |--requires--> [Weather suspension awareness]
                                                             |--enables---> [Push notification]
                                                             |--enables---> [Automation-ready output]

[Local caching]
    |--enhances--> [ASP sign data lookup] (reduces API calls, enables offline)

[VW CarNet GPS auto-consumption]
    |--provides input to--> [GPS-to-street resolution]

[ha-nyc311 integration]
    |--can provide--> [Holiday suspension calendar]
    |--can provide--> [Weather suspension awareness]
```

### Dependency Notes

- **GPS resolution requires coordinate conversion:** The NYC Open Data sign locations use NY State Plane (NAD83, feet). GPS from VW CarNet is WGS84. `pyproj` with `Transformer.from_crs(4326, 2263)` handles this (EPSG:2263 is NY Long Island zone covering all NYC).
- **Next-move-time requires both schedule AND suspension data:** Without suspension awareness, the tool gives wrong answers on ~30+ days per year. This must be in v1.
- **Push notifications enhance but don't block core value:** The sensor entity alone (showing next move time on HA dashboard) is useful even without push notifications. Notifications are a v1.x enhancement.
- **ha-nyc311 is complementary, not competing:** It handles the "is ASP suspended today?" question via NYC 311 API. This project handles "what is the ASP schedule for my specific curb location?" They combine to answer "when do I actually need to move?"

## MVP Definition

### Launch With (v1)

Minimum viable product -- what's needed to answer "when do I need to move my car?"

- [ ] **GPS-to-street-segment resolution** -- Core function, everything depends on this
- [ ] **SODA API sign data lookup** -- Must retrieve ASP signs for resolved location
- [ ] **Sign description parser** -- Must extract days and time windows from sign text
- [ ] **Next-move-time computation** -- The primary output: next ASP window datetime
- [ ] **Holiday suspension calendar** -- Hardcoded 2026 calendar or 311 API integration; without this, tool gives wrong answers on holidays
- [ ] **Local sign data cache** -- SQLite or JSON; prevents API dependency on every lookup
- [ ] **Basic HA sensor entity** -- Expose `sensor.asp_next_move_time` with datetime value and attributes (schedule details, suspension status)

### Add After Validation (v1.x)

Features to add once the core GPS-to-schedule pipeline is proven correct.

- [ ] **Weather/emergency suspension polling** -- Cron job checking @NYCASP or 311 API for same-day suspensions. Add once core schedule logic is validated.
- [ ] **Push notifications** -- HA actionable notifications with configurable lead time. Add once sensor entity is reliably producing correct data.
- [ ] **ha-nyc311 integration bridge** -- Consume `ha-nyc311` binary sensors for suspension status instead of implementing our own 311 polling. Reduces code, leverages existing maintained integration.
- [ ] **Dual data source validation** -- Cross-reference SODA results with OpenCurb where coverage overlaps (limited to Midtown Manhattan officially).

### Future Consideration (v2+)

Features to defer until the core product is battle-tested.

- [ ] **Multi-vehicle support** -- Only if user need emerges. Design for it, don't build it.
- [ ] **Other parking regulation types** -- Meters, no-standing zones. Massive scope increase.
- [ ] **Smart notification timing** -- Factor in walking distance to car, typical move-time patterns.
- [ ] **Block-segment visualization** -- HA map card showing the resolved block segment and sign locations.

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| GPS-to-street resolution | HIGH | HIGH | P1 |
| ASP sign data lookup (SODA) | HIGH | MEDIUM | P1 |
| Sign description parsing | HIGH | MEDIUM | P1 |
| Next-move-time computation | HIGH | MEDIUM | P1 |
| Holiday suspension calendar | HIGH | LOW | P1 |
| Local sign data cache | MEDIUM | LOW | P1 |
| Basic HA sensor entity | HIGH | LOW | P1 |
| Weather suspension polling | HIGH | MEDIUM | P2 |
| Push notifications | HIGH | LOW | P2 |
| ha-nyc311 bridge | MEDIUM | LOW | P2 |
| OpenCurb fallback | LOW | LOW | P3 |
| Multi-vehicle support | LOW | MEDIUM | P3 |
| Other sign types | LOW | HIGH | P3 |

**Priority key:**
- P1: Must have for launch -- tool is broken without these
- P2: Should have, add once P1 is validated and working
- P3: Nice to have, future consideration

## Competitor Feature Analysis

| Feature | SpotAngels | Parkr | ASP NYC | ha-nyc311 | GPS2ASP (Ours) |
|---------|------------|-------|---------|-----------|----------------|
| ASP schedule by location | Map tap to view | Map view | Status updates | No (suspension only) | GPS auto-resolve |
| Holiday suspension calendar | Yes (in-app) | Yes (daily alerts) | Yes | Yes (binary sensors) | Yes (311 API or ha-nyc311) |
| Weather suspension alerts | Yes | Yes (real-time) | Yes | Yes (binary sensors) | Yes (polling cron) |
| Push notifications | Move reminders | Daily alerts | Status updates | HA notifications | HA actionable notifications |
| GPS auto-detection | Bluetooth parking save | No | No | No | VW CarNet device tracker |
| Side-of-street resolution | No (user taps map) | No | No | No | Yes (coordinate math) |
| Home Assistant integration | No | No | No | Yes (suspension only) | Yes (full pipeline) |
| Structured API output | No (app only) | No (app only) | No | Sensor entities | Sensor entities + attributes |
| Automation capability | None | None | None | Binary sensor triggers | Full sensor + notification automation |
| Offline capability | Cached map data | Unknown | No | Cached status | Cached sign data |
| Coverage | All NYC + 200 cities | NYC + Jersey City | NYC | NYC | All NYC (SODA dataset) |
| Cost | Free (ad-supported) | Free (no ads) | Free | Free (open source) | Free (open source) |

### Key competitive insight

No existing tool combines GPS-based automatic location detection with ASP schedule lookup AND suspension awareness in a Home Assistant context. SpotAngels is closest in features but requires manual phone interaction. ha-nyc311 is closest in platform (HA) but only handles suspensions, not location-specific ASP schedules. GPS2ASP fills the exact gap between them.

## Sources

- [SpotAngels NYC ASP Map](https://www.spotangels.com/alternate-side-parking-nyc-map) -- Feature set analysis (MEDIUM confidence)
- [Parkr on App Store](https://apps.apple.com/us/app/parkr-alternate-side-parking/id6503993830) -- Feature set analysis (MEDIUM confidence)
- [Parkr on Google Play](https://play.google.com/store/apps/details?id=com.jcasp.app&hl=en_US) -- Feature set analysis (MEDIUM confidence)
- [NYC DOT ASP Suspensions](https://www.nyc.gov/html/dot/html/motorist/alternate-side-parking.shtml) -- Official suspension info, ICS calendars (HIGH confidence)
- [NYC Open Data Parking Signs](https://data.cityofnewyork.us/Transportation/Parking-Regulation-Locations-and-Signs/nfid-uabd) -- Primary data source (HIGH confidence)
- [OpenCurb API Docs](https://www.opencurb.nyc/doc.html) -- API capabilities and coverage limitations (HIGH confidence)
- [ha-nyc311 GitHub](https://github.com/elahd/ha-nyc311) -- HA integration for NYC 311 ASP status (HIGH confidence)
- [The NYC ASP API](https://github.com/erickouassi/The-NYC-ASP-API) -- Community JSON API for ASP status (MEDIUM confidence)
- [NYC DOT Data Feeds Issue #1](https://github.com/CityOfNewYork/DOT-Data-Feeds/issues/1) -- 311 API endpoint documentation (MEDIUM confidence)
- [SODA API App Tokens](https://dev.socrata.com/docs/app-tokens.html) -- Rate limit and throttling docs (HIGH confidence)
- [Twitter/X @NYCASP](https://twitter.com/NYCASP) -- Official daily ASP status source (HIGH confidence)
- [X Developer Platform NYC Parking Tutorial](https://developer.x.com/en/docs/tutorials/nyc-parking) -- Twitter API for ASP monitoring (MEDIUM confidence)
- [HA Actionable Notifications](https://companion.home-assistant.io/docs/notifications/actionable-notifications/) -- Push notification capabilities (HIGH confidence)
- [HA RESTful Sensor](https://www.home-assistant.io/integrations/sensor.rest/) -- REST sensor patterns (HIGH confidence)
- [VW CarNet HA Integration](https://github.com/robinostlund/homeassistant-volkswagencarnet) -- GPS source integration (MEDIUM confidence)

---
*Feature research for: NYC ASP GPS Resolver for Home Assistant*
*Researched: 2026-02-21*
