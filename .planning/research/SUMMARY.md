# Project Research Summary

**Project:** GPS2ASP Resolver — GPS to NYC Alternate Side Parking Regulation Resolver
**Domain:** Home Assistant custom integration for NYC parking regulation resolution
**Researched:** 2026-02-21
**Confidence:** HIGH (stack, architecture, pitfalls); MEDIUM-HIGH (features)

## Executive Summary

The GPS2ASP Resolver is a Home Assistant custom integration that automatically resolves a parked car's GPS coordinates (from VW CarNet) to the correct Alternate Side Parking schedule for that specific curb location, computing the exact next time the car must be moved. No existing tool does this within the Home Assistant ecosystem: SpotAngels and Parkr are phone apps requiring manual interaction; the ha-nyc311 integration handles suspension status but not location-specific schedule lookup. This project fills that exact gap by combining GPS resolution, NYC Open Data sign retrieval, schedule parsing, and suspension awareness into a single automated pipeline.

The recommended approach is a two-layer architecture: a pure-Python core library (`gps2asp/`) that performs all resolution logic with zero Home Assistant dependencies, wrapped by a thin HA integration layer (`custom_components/gps2asp/`) using the standard `DataUpdateCoordinator` pattern. The core pipeline is linear — GPS coordinates enter, "next move time" exits — with each stage (coordinate conversion, sign matching, schedule parsing, suspension checking, result computation) independently testable. The stack is lean: pyproj for coordinate conversion, direct aiohttp calls to the SODA API, SQLite for caching, python-dateutil for schedule arithmetic, and nyc311calendar for suspension data.

The two highest risks are street-side resolution accuracy in urban canyons (GPS error of 10-30m in dense NYC blocks can place the car on the wrong side of a 18m-wide street) and sign description parsing correctness (the `sign_description` field is free-text with dozens of format variations that will silently produce wrong results for the long tail). Both require test-first development with real dataset samples before building the HA integration layer. A third risk — hardcoding or skipping holiday/emergency suspension logic — must be addressed in v1 because it produces wrong "next move time" on 30+ days per year.

## Key Findings

### Recommended Stack

The stack is well-determined with few tradeoffs. Python 3.12 is the minimum viable version, driven simultaneously by pyproj 3.7.2 (requires >=3.11) and Home Assistant 2025.x (targets >=3.12). The SODA API should be called directly via aiohttp — the sodapy library is archived, unmaintained since August 2022, and limited to Python <=3.10. GeoPandas and PostGIS are significant overkill for what amounts to one coordinate transform and a nearest-neighbor lookup. The nyc311calendar package provides an async-native client for the 311 API; it is alpha-quality, so pin to a specific version.

**Core technologies:**
- **Python 3.12:** Runtime — minimum driven by pyproj 3.7.2 and HA 2025.x requirements
- **pyproj 3.7.2:** WGS84 (EPSG:4326) to NY State Plane Long Island (EPSG:2263) conversion — only serious Python library for CRS transformations; `Transformer.from_crs(4326, 2263, always_xy=True)` is the correct and only acceptable pattern
- **aiohttp 3.13.2:** HTTP client — HA's native session manager via `async_get_clientsession(hass)`; custom integrations MUST use this, not httpx or requests
- **python-dateutil 2.9.0:** Schedule arithmetic — `rrule` handles recurring weekly schedules natively; standard `datetime` cannot express "every Tuesday and Friday 8:30-10AM"
- **SQLite (stdlib):** Sign data cache — zero-dependency, file-based, survives restarts, correct TTL for weekly refresh cadence
- **nyc311calendar:** Suspension data — wraps NYC 311 API auth and response normalization; alpha, pin version
- **DataUpdateCoordinator:** HA integration pattern — manages polling lifecycle, error retry, and multi-entity coordination

**What NOT to use:** sodapy (archived), requests (blocks HA event loop), GeoPandas (massive dependency for one transform), OpenCurb as primary source (no parseable schedules, Manhattan-only coverage confirmed by official docs), pyscript (cannot install pip packages).

### Expected Features

Research confirms the feature set is well-scoped. The MVP must answer one question correctly: "When do I need to move my car?" Everything in v1 serves that answer. Notifications and integrations with other HA tools are v1.x additions once correctness is validated.

**Must have (table stakes) — v1:**
- GPS-to-street-segment resolution — core function; everything else depends on this
- ASP sign data lookup via SODA API — query `nfid-uabd` for `SANITATION BROOM SYMBOL` signs at resolved location
- Sign description parser — extract structured day/time schedule from free-text sign descriptions
- Next-move-time computation — primary output: next upcoming ASP window datetime
- Holiday suspension calendar — ASP suspended 30+ days/year; wrong answers without this in v1
- Local sign data cache (SQLite, 7-day TTL) — prevents API dependency on every lookup
- Basic HA sensor entity (`sensor.asp_next_move_time`, `binary_sensor.asp_suspended`) — exposes data to HA automations

**Should have (differentiators) — v1.x, add after validation:**
- Weather/emergency suspension polling via 311 API (every 1-2 hours during weather events)
- HA actionable push notifications with configurable lead time (30-60 min before window)
- ha-nyc311 integration bridge — consume existing suspension sensors rather than reimplementing 311 polling
- Confidence level reporting — surface "UNCERTAIN: could not determine street side" rather than silently wrong answers

**Defer (v2+):**
- Multi-vehicle support — design data model to permit it; do not implement
- Other parking regulation types (meters, no-standing) — scope explosion; ASP broom signs have consistent patterns; other types do not
- Block-segment visualization on HA map card
- Advanced sign-position matching using `distance_from_intersection` + arrow direction for sub-block accuracy

**Anti-features confirmed — do not build:** Real-time spot availability, mobile/web UI (HA IS the UI), AI/ML suspension predictions, historical ticket analytics.

**Competitor gap confirmed:** No existing tool combines GPS-based automatic detection + ASP schedule lookup + suspension awareness within Home Assistant. This fills the exact gap between SpotAngels (location features, no HA) and ha-nyc311 (HA, suspension only).

### Architecture Approach

The architecture is a linear pipeline with a separated core library and HA integration wrapper. The core library (`gps2asp/`) has zero HA imports and is fully testable in isolation. The HA wrapper (`custom_components/gps2asp/`) uses `DataUpdateCoordinator` to poll the resolver and expose results as sensor entities — thin read-only views of coordinator data. Sign data is cached in SQLite keyed by `(on_street, from_street, to_street, side_of_street)` — the block segment tuple, not GPS coordinates.

**Major components:**
1. **Coordinate Converter** — `pyproj.Transformer.from_crs(4326, 2263, always_xy=True)` singleton; converts GPS (WGS84) to NY State Plane feet for matching against sign coordinates
2. **Sign Matcher** — bounding-box SODA query around converted coordinates, groups results by segment tuple, picks nearest centroid to car position; leverages dataset's own `side_of_street` field rather than geometric centerline math
3. **Schedule Parser** — regex-based parser for `sign_description` free-text; must handle 15+ known format variations; returns confidence score; logs unparseable descriptions
4. **Suspension Service** — wraps `nyc311calendar` for 311 API; merges holiday calendar and weather suspensions; exposes `is_suspended(date)` interface to scheduler
5. **Next Move Computer** — datetime arithmetic combining schedule + suspension data + current time (America/New_York via stdlib `zoneinfo`)
6. **HA Integration Layer** — `DataUpdateCoordinator` + `SensorEntity`/`BinarySensorEntity` + `ConfigFlow` for API key entry

**Key pattern — side-of-street resolution:** Do NOT use LION street centerline data or geometric perpendicular-distance calculations. The sign dataset already contains `side_of_street` per sign. Group signs by segment tuple, compute centroid per group, pick nearest centroid. GPS accuracy (3-5m good conditions) is sufficient; handle ambiguous cases (GPS near centerline) by reporting uncertainty rather than guessing.

**Build order derived from dependencies:** Phase 1 builds the four independent foundation components (converter, SODA client, parser, data models) in parallel. Phase 2 integrates them (sign matcher, cache, suspension service). Phase 3 orchestrates the full pipeline. Phase 4 wraps for Home Assistant.

### Critical Pitfalls

1. **GPS urban canyon inaccuracy degrades street-side determination** — In dense NYC blocks, GPS error reaches 10-30m (vs 18m street width), placing the car on the wrong side or wrong block. Mitigation: use wider search radius (50m) for candidate segments; report confidence level; implement manual override in notification; never silently guess when ambiguous. Address in Phase 1 before touching API integration.

2. **pyproj coordinate conversion has three silent failure modes** — Axis order confusion (lat/lon vs lon/lat), unit mismatch in legacy patterns (meters vs feet), and deprecated `Proj`+`transform()` that ignores datum shifts. All produce wrong coordinates with no errors. Mitigation: always use `Transformer.from_crs("EPSG:4326", "EPSG:2263", always_xy=True)`; write a round-trip unit test asserting State Plane output within 1 foot of known reference point before building anything else.

3. **SODA dataset includes historical/voided signs — must filter aggressively** — Dataset has 1M+ records including superseded signs. Missing `sign_design_voided_on_date IS NULL` filter means treating voided regulations as current. This single-line SoQL filter is mandatory in every query, not optional. Address in Phase 2 query builder.

4. **Sign description parsing has a long tail of format variations** — Free-text field entered by DOT workers over decades. Known variations include different day abbreviations, `&`/comma/space separators, `THRU` for day ranges, period vs colon in times, "EXCEPT HOLIDAYS"/"SCHOOL DAYS ONLY" qualifiers, multiple windows per sign. A parser handling 90% of formats will silently give wrong results for the 10% tail. Mitigation: download all BROOM SYMBOL signs from dataset first, catalog all unique patterns, build parser with confidence scoring, target >=95% coverage before shipping.

5. **Holiday and emergency suspension data requires active maintenance** — ASP suspended 30+ days/year. Holiday dates shift annually. Emergency suspensions announced same-day with no static API. Developers who hardcode holiday lists or skip emergency polling give wrong answers multiple times per year. Mitigation: parse official ICS file (refresh annually in January); poll 311 API every 1-2 hours; when suspension status unavailable, default to "ASP IN EFFECT" (safe failure). Never treat "EXCEPT HOLIDAYS" as decoration.

**Additional moderate pitfalls to plan for:**
- OpenCurb confirmed NOT viable for Brooklyn (Prospect Heights is outside its official Manhattan-only coverage) — remove from architecture entirely
- VW CarNet API rate limit (~480 calls/day) means GPS position may be 5-10 minutes stale — design for stale data; use wider search radius; do not re-query signs unless position changes >20m
- SODA API silently truncates at 1,000 records without warning — always set explicit `$limit`; assert results count < limit as sanity check

## Implications for Roadmap

Based on the architecture's explicit build-order dependency chain and the pitfall-to-phase mapping in PITFALLS.md, a 4-phase structure maps cleanly to the research findings:

### Phase 1: Foundation — Core Resolver Components

**Rationale:** The four foundation components (coordinate converter, SODA client, sign parser, data models) have no cross-dependencies and can be built and verified in isolation. Critical pitfalls #1, #2, and #11 all live here. Getting coordinate conversion and street-name matching correct is prerequisite to everything else; a bug here propagates silently through the entire pipeline.

**Delivers:** A testable Python library that can convert GPS coordinates, query SODA for signs at a location, and parse sign description text — all verified against real dataset samples with unit tests. No Home Assistant dependency.

**Addresses features:** GPS-to-street-segment resolution, ASP sign data lookup, sign description parsing (P1 features from FEATURES.md)

**Avoids:** Coordinate axis order bugs (Pitfall #2), street name format mismatches (Pitfall #11), compass direction mapping errors on diagonal Brooklyn streets (Pitfall #13), OpenCurb false reliance (Pitfall #8 — remove from design here)

**Research flag:** Standard patterns — pyproj and SODA API are well-documented; no additional research phase needed. Write conversion unit test against known reference coordinates first.

### Phase 2: Data Integration — SODA Pipeline and Cache

**Rationale:** With foundation components verified, Phase 2 integrates them into the full data retrieval pipeline. The SODA query must be built with all required filters from the start (voided sign filter, explicit pagination limit, app token auth). The SQLite cache must be implemented with the correct key structure and stale-serve fallback before the HA layer is added.

**Delivers:** A fully functional sign retrieval pipeline: GPS in, structured ASP sign records out, cached in SQLite with 7-day TTL. Cache serves stale data gracefully on API failures.

**Uses:** All Phase 1 components; SQLite stdlib; aiohttp SODA client

**Implements:** Sign Matcher, Sign Cache (Architecture components)

**Avoids:** Historical sign inclusion (Pitfall #3 — voided filter mandatory), SODA pagination truncation (Pitfall #6 — explicit $limit always), cache key correctness (Pitfall #10 — keyed by segment tuple, not GPS coordinates)

**Research flag:** Low research need — SODA API and SQLite patterns are well-documented. Key task is downloading all BROOM SYMBOL signs from the real dataset and building parser test fixtures before writing the parser itself.

### Phase 3: Schedule Computation — Next-Move-Time with Suspension Awareness

**Rationale:** With sign data retrieval working, Phase 3 builds the temporal logic: parsing structured schedules, checking suspension calendars, and computing the next move datetime. This phase closes the MVP loop. Holiday suspension MUST be in this phase (not deferred) because without it the tool gives wrong answers on 30+ days/year. The schedule parser needs comprehensive test fixtures from the real dataset before being considered done.

**Delivers:** The complete core value proposition: given GPS coordinates, return next move datetime, window description, hours until move, and suspension status. All in pure Python with no HA dependency.

**Uses:** python-dateutil rrule, zoneinfo, nyc311calendar, ICS calendar parser for annual holiday refresh

**Implements:** Schedule Parser, Suspension Service, Next Move Computer (Architecture components)

**Avoids:** Sign parsing long tail failures (Pitfall #4 — >=95% coverage target), holiday calendar drift (Pitfall #5 — parse ICS, poll 311 API, default to IN EFFECT), "EXCEPT HOLIDAYS" as decoration (Pitfall #12), edge-case times (it's 9:55AM when ASP ends at 10AM)

**Research flag:** Moderate need — sign description format variations require empirical catalog of real dataset patterns before writing the parser. Recommend downloading all BROOM SYMBOL signs (filterable SODA query) as a pre-task. The nyc311calendar alpha package API may need validation against the live 311 API.

### Phase 4: Home Assistant Integration

**Rationale:** With the core pipeline producing correct results (verified by tests), Phase 4 wraps it for Home Assistant. This is primarily boilerplate integration work following established HA patterns. The HA layer is thin by design — it reads GPS from the VW CarNet device_tracker, calls the core resolver via `async_add_executor_job` (since pyproj and sqlite3 are synchronous), and exposes results as sensor entities. VW CarNet rate limit constraints must be handled here.

**Delivers:** A working HACS-installable HA custom integration with config flow, sensor entities (`sensor.asp_next_move_time`, `sensor.asp_hours_until_move`, `sensor.asp_schedule`, `binary_sensor.asp_suspended`), and position-change-triggered re-resolution.

**Uses:** HA DataUpdateCoordinator, SensorEntity, BinarySensorEntity, ConfigFlow; `async_get_clientsession(hass)` for aiohttp; `async_add_executor_job` for sync library calls; `async_track_state_change` for GPS position monitoring

**Implements:** HA Integration Layer (Architecture component)

**Avoids:** VW CarNet rate limit exhaustion (Pitfall #9 — 10-min minimum poll interval, position-change threshold of 20m, document 480/day limit), HA event loop blocking (use executor_job for all sync code), missing unique entity IDs (deterministic IDs based on config entry)

**Research flag:** Low research need — DataUpdateCoordinator, ConfigFlow, and HA entity patterns are well-documented with official examples. The ha-nyc311 integration serves as a directly applicable reference implementation.

### Phase 5: Notifications and Suspension Monitoring

**Rationale:** Once the core pipeline is validated to produce correct data in production, add the user-facing enhancements that make the tool proactive. Emergency suspension polling (every 1-2 hours) and push notifications with configurable lead time are v1.x features that require the base sensor data to be trustworthy first.

**Delivers:** HA actionable push notifications with configurable lead time; real-time emergency suspension awareness; ha-nyc311 integration bridge (reuse existing suspension binary sensors where available); "all clear until" time in addition to "move by" time.

**Implements:** Suspension polling cron (HA `async_track_time_interval`), HA `notify.mobile_app_*` actionable notifications, ha-nyc311 bridge sensor reading

**Avoids:** UX pitfalls — notification at 8:30AM for 8:30AM window (Pitfall: configurable buffer default 30-60 min), silent failure with no confidence level reported, showing only "move by" without "all clear after"

**Research flag:** Low research need — HA actionable notifications and time tracking are standard documented patterns. The main task is tuning poll intervals and notification timing based on real-world testing from Phase 4.

### Phase Ordering Rationale

- **Phases 1-3 must precede Phase 4** because the core library is an explicit dependency of the HA integration layer. Building HA wiring around unvalidated resolution logic would hide bugs under integration complexity.
- **Phase 2 before Phase 3** because sign retrieval must work before schedule computation can be tested against real data. The parser test fixtures (real BROOM SYMBOL signs from dataset) are best built as a Phase 2 deliverable.
- **Phase 5 after Phase 4** because notifications and suspension polling require the base sensor data to be trustworthy in production. Adding polling complexity to an untested pipeline obscures root cause when things go wrong.
- **The architecture's four-phase build order** (Foundation → Integration → Orchestration → HA Layer) maps directly to this five-phase roadmap, with Phase 5 extending the HA layer with async monitoring features.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 3 (Sign parser):** Download and catalog all unique `sign_description` formats for BROOM SYMBOL signs from the live SODA dataset before writing parser code. This is empirical data collection, not library research. A pre-phase task.
- **Phase 3 (nyc311calendar):** Alpha package — validate API against live 311 endpoint before committing to it. Have fallback plan if alpha API changes. Consider vendoring a specific version.

Phases with standard patterns (skip research-phase):
- **Phase 1:** pyproj Transformer pattern is official and well-documented. SODA API is a REST GET with URL params — no client library needed.
- **Phase 2:** SQLite cache pattern is stdlib. SODA pagination is documented.
- **Phase 4:** DataUpdateCoordinator and ConfigFlow are heavily documented HA patterns. ha-nyc311 is a direct reference implementation.
- **Phase 5:** HA actionable notifications and time tracking are documented patterns.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All core libraries verified against official docs and PyPI. pyproj, aiohttp, python-dateutil, SQLite all production-stable. sodapy rejection confirmed by PyPI archived status. Only uncertainty: nyc311calendar alpha status (MEDIUM) — pin version and validate against live API. |
| Features | MEDIUM-HIGH | Table stakes and differentiators confirmed by competitor analysis. MVP scope well-defined by dependency chain. Anti-features confirmed correct to exclude. Uncertainty: sign description format variations in production may exceed cataloged patterns. |
| Architecture | HIGH | Pipeline architecture is standard for this problem class. DataUpdateCoordinator pattern is official HA documentation. Side-of-street resolution via dataset's own fields (not LION data) is validated approach. Build order is definitive given component dependencies. |
| Pitfalls | HIGH | All critical pitfalls verified against official sources (pyproj docs, SODA API docs, peer-reviewed GPS accuracy research, official OpenCurb coverage docs, VW integration community reports). Recovery strategies included. |

**Overall confidence:** HIGH

### Gaps to Address

- **Sign description format catalog:** Must download all active BROOM SYMBOL signs from the live SODA dataset and catalog actual format variations before writing the parser. Estimated ~5,000-15,000 records. This is an empirical data task, not a research gap. Schedule as first task of Phase 3.
- **nyc311calendar alpha API stability:** Package is alpha-quality. Before committing to it in Phase 3, validate the `get_calendar()` API against the live 311 endpoint. If API has broken, the `ha-nyc311` integration source code provides a working reference implementation for the 311 API calls.
- **Street-side resolution accuracy in Prospect Heights specifically:** The primary use case is Prospect Heights, Brooklyn — a neighborhood with curved streets around Prospect Park and irregular grid sections. Standard tests with Manhattan addresses will not validate this. Include at least 5 Prospect Heights addresses with known ASP schedules in the test suite.
- **VW CarNet GPS update behavior on parking:** The exact behavior of the VW CarNet HA integration when the car parks (does it send a final position fix on ignition off?) needs validation in Phase 4. Design for worst-case (position 10 minutes stale) but test actual behavior.

## Sources

### Primary (HIGH confidence)
- [pyproj 3.7.2 Documentation](https://pyproj4.github.io/pyproj/stable/) — Transformer API, axis order, gotchas
- [pyproj Issue #67](https://github.com/pyproj4/pyproj/issues/67) — Units bug in older versions, confirmed fixed in >=2.0
- [EPSG:2263 Definition](https://epsg.io/2263) — NY State Plane Long Island coordinate system
- [NYC Open Data — Parking Regulation Locations and Signs](https://data.cityofnewyork.us/Transportation/Parking-Regulation-Locations-and-Signs/nfid-uabd) — Primary data source, dataset `nfid-uabd`
- [Socrata BETWEEN function docs](https://dev.socrata.com/docs/functions/between.html) — Bounding box approach for numeric coordinate columns
- [SODA API $limit documentation](https://dev.socrata.com/docs/queries/limit.html) — Default 1,000 record truncation behavior
- [NYC DOT ASP Suspensions](https://www.nyc.gov/html/dot/html/motorist/alternate-side-parking.shtml) — Official holiday calendar, ICS download
- [NYC DOT 2026 ASP Calendar PDF](https://www.nyc.gov/html/dot/downloads/pdf/asp-calendar-2026.pdf) — Annual suspension dates
- [OpenCurb API Documentation](https://www.opencurb.nyc/doc.html) — Confirmed Manhattan-only coverage
- [HA Developer Docs — Fetching Data](https://developers.home-assistant.io/docs/integration_fetching_data/) — DataUpdateCoordinator pattern
- [HA Developer Docs — Creating Integrations](https://developers.home-assistant.io/docs/creating_component_index/) — manifest.json, async_setup structure
- [HA Developer Docs — aiohttp session](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/inject-websession/) — async_get_clientsession pattern
- [Sidewalk Matching Research](https://satellite-navigation.springeropen.com/articles/10.1186/s43020-025-00159-8) — GPS urban canyon accuracy (peer-reviewed)

### Secondary (MEDIUM confidence)
- [ha-nyc311 GitHub](https://github.com/elahd/ha-nyc311) — Reference HA integration for NYC 311; last release Feb 2023
- [nyc311calendar on PyPI](https://pypi.org/project/nyc311calendar/) — Alpha async 311 client
- [VW CarNet HA Integration](https://github.com/robinostlund/homeassistant-volkswagencarnet) — 480 calls/day VW API rate limit (community-confirmed)
- [aspnyc.info](https://www.aspnyc.info/) — Confirms 311 API works for ASP suspension status (third-party validation)
- [NYC Parking Sign Arrow Meanings](https://newyorkparkingticket.com/know-purpose-arrows-nyc-parking-sign/) — Single vs double arrow semantics
- [SpotAngels NYC ASP Map](https://www.spotangels.com/alternate-side-parking-nyc-map) — Competitor feature analysis
- [Parkr on App Store](https://apps.apple.com/us/app/parkr-alternate-side-parking/id6503993830) — Competitor feature analysis

### Tertiary (LOW confidence)
- [The NYC ASP API (GitHub)](https://github.com/erickouassi/The-NYC-ASP-API) — Community JSON API for ASP status; unknown maintenance status
- [Twitter/X @NYCASP](https://twitter.com/NYCASP) — Official daily ASP status; no structured API, fallback only

---
*Research completed: 2026-02-21*
*Ready for roadmap: yes*
