# GPS2ASP Resolver

## What This Is

A Python tool and Home Assistant custom integration that resolves a car's GPS coordinates to Alternate Side Parking (ASP) rules for that specific curb location in NYC. Given lat/long from a VW CarNet device_tracker entity, it determines which side of the street the car is on, looks up the ASP schedule for that block segment from NYC Open Data, parses the sign descriptions, computes the next cleaning window, and exposes "next time to move" as an HA sensor entity.

## Core Value

Tell the user exactly when they need to move their car for ASP — "next time to move is [datetime]" — so they never get a ticket.

## Current Milestone: v2.0 Full Borough Coverage

**Goal:** Push all boroughs to target ASP coverage — close the Manhattan gap, lift Queens from 36.8%, add Level 4 observability, and shrink graph.json startup cost.

**Target features:**
- Manhattan coverage ≥60% via improved BFS span resolution
- Queens coverage ≥50% via borough-specific normalization audit
- Level 4 observability (structured logs + soda_level in HA sensor attributes)
- graph.json reduced from 7.9 MB to ≤4 MB (filter ASP-relevant segments only)

## Current State

**Shipped:** v1.1 Bug Fixes (2026-03-07) | **Active:** v1.2 Coverage & Performance
**Code:** 7,585 lines Python, 37 files, 273 tests
**Stack:** Python 3.11+, pyproj, shapely, rtree, httpx, Home Assistant custom component

The full pipeline is operational with a clean public API: `resolve_asp(lat, lon)` → `ASPResult`. The spatial index covers 26,374 ASP segments (+44% from v1.0) with BFS graph propagation covering 62,455 interior mid-span blocks. ASP coverage: Manhattan 58.2%, Brooklyn 74.1%, Bronx 52.4%, Queens 36.8%.

## Requirements

### Validated

- ✓ GPS-01: WGS84 to NY State Plane coordinate conversion — v1.0
- ✓ GPS-02: GPS point to street segment + side resolution — v1.0
- ✓ GPS-03: Confidence scoring for GPS accuracy limitations — v1.0 (improved v1.1: width-relative formula)
- ✓ SIGN-01: SODA API query for ASP/broom signs — v1.0 (improved v1.1: voided sign filter fixed, Level 4 mid-span fallback added)
- ✓ SIGN-02: Filter current signs only (exclude voided/superseded) — v1.0 (fixed v1.1: was using record_type='Current' no-op)
- ✓ SIGN-03: SODA API pagination handling — v1.0
- ✓ SCHED-01: Parse cleaning days from sign descriptions — v1.0
- ✓ SCHED-02: Parse time windows from sign descriptions — v1.0
- ✓ SCHED-03: Handle sign format variations (EXCEPT, dash ranges, etc.) — v1.0
- ✓ SCHED-04: Compute next upcoming ASP window datetime — v1.0 (fixed v1.1: CleaningWindow|None type mismatch)
- ✓ HA-01: Read GPS from VW CarNet device_tracker entity — v1.0
- ✓ HA-02: Expose sensor with datetime value for next move time — v1.0
- ✓ HA-03: Expose sensor attributes with schedule details — v1.0
- ✓ HA-04: Auto re-resolve on GPS movement >50m — v1.0
- ✓ API-01: Single importable `resolve_asp(lat, lon, debug=False)` function — v1.1
- ✓ COV-01: BFS graph propagation for mid-span ASP coverage (Manhattan ≥50%, Brooklyn ≥50%) — v1.1
- ✓ COV-02: Queens coverage normalization fix (TPKE/CRES) — v2.0 Phase 15 (20% L1+2; remaining gap is structural CSCL/SODA boundary mismatch)
- ✓ COV-04: Manhattan coverage normalization fix (AVE A prefix) — v2.0 Phase 15+17 (11.1% L1+2; remaining gap is geometric/alias mismatches)

### Active

- [ ] COV-03: Migrate HA coordinator to use `resolve_asp()` (currently calls three stages manually)
- [ ] COV-03: Migrate HA coordinator to use `resolve_asp()` (currently calls three stages manually)
- [ ] CACHE-01: Cache ASP sign data per block segment in SQLite with weekly refresh
- [ ] CACHE-02: Configurable caching area (center + radius) for pre-seeding
- [ ] CACHE-03: Fall back to live SODA API on cache miss
- [ ] SUSP-01: NYC holiday ASP suspension calendar
- [ ] SUSP-02: Weather/emergency suspension polling via 311 API
- [ ] SUSP-03: Merge suspension status with schedule for single authoritative answer
- [ ] SUSP-04: Bridge with ha-nyc311 integration for suspension binary sensors
- [ ] NOTIF-01: HA actionable notification with configurable lead time
- [ ] NOTIF-02: Automation-ready structured output

### Out of Scope

- Real-time parking availability / spot finding — different data problem, no public API
- Full parking regulation support (meters, no standing, hydrants) — ASP signs have consistent patterns, others are far more varied
- Mobile app or web UI — HA dashboard and companion app ARE the UI
- Multi-vehicle support — single car for now; design doesn't preclude but not implemented
- Parking guidance (where to move TO) — requires spot availability data that doesn't exist
- AI/ML suspension predictions — official announcements are the data
- OpenCurb API — only covers Midtown Manhattan, not Brooklyn

## Context

- **Data source**: NYC Open Data `nfid-uabd` via SODA API. ASP signs identifiable by `"SANITATION BROOM SYMBOL"` in `sign_description`.
- **Coordinate systems**: GPS WGS84 → NY State Plane (EPSG:2263) via pyproj. R-tree spatial index with 26,374 ASP vehicular segments.
- **Street name normalization**: CSCL format (abbreviated) to SODA format (expanded) with three-level fallback + directional prefix/suffix expansion.
- **Coverage**: Manhattan 58.2%, Brooklyn 74.1%, Bronx 52.4%, Queens 36.8% (BFS graph propagation active, graph.json 7.9 MB).
- **Primary area**: Prospect Heights, Brooklyn and surrounding neighborhoods. Works for all NYC.
- **Integration**: VW CarNet / WeConnect HA integration provides `device_tracker` entity with `latitude`/`longitude` attributes.
- **Known tech debt**: HA coordinator uses manual three-stage pipeline (not `resolve_asp()`), SODA app_token not in config flow, Queens 36.8% coverage below target.

## Constraints

- **Runtime**: Python 3.11+ — native HA integration language
- **Platform**: Home Assistant custom component with HACS support
- **Data freshness**: ASP signs rarely change (~yearly). Live SODA query per resolve (caching deferred to v2).
- **Network**: SODA API is free, no auth required (optional app_token for rate limits)
- **Accuracy**: GPS accuracy (~3-5m) sufficient for street-side determination with confidence scoring

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| NYC Open Data as primary source | Parseable ASP schedules in sign descriptions, all boroughs, free SODA API | ✓ Good — 95%+ sign format coverage |
| Python 3.11+ with pyproj/shapely/rtree | Native HA language, strong geospatial libraries | ✓ Good — clean async pipeline |
| Exceptions over Result objects | Cleaner for async pipeline with distinct error types | ✓ Good — OutsideNYC, NoSegment, Ambiguous all distinct |
| 4-phase linear pipeline | GPS → Signs → Schedule → HA derived from data dependencies | ✓ Good — each phase independently testable |
| Suspensions/caching deferred to v2 | Core value delivered without them; adds complexity | ✓ Good — shipped faster, v2 scope clear |
| Custom coordinator (not DataUpdateCoordinator) | GPS events are the data source, not polling | ✓ Good — natural fit for event-driven model |
| Conservative window merging | Earliest start, latest end when overlapping (safer for tickets) | ✓ Good — user won't miss a window |
| 50m movement threshold with 5s debounce | Filters GPS jitter while catching real movement | — Pending (needs real-world testing) |
| Retain last known state on errors | SODA errors don't clear schedule; user keeps useful data | ✓ Good — graceful degradation |
| Entity ID via has_entity_name=True | HA recommended pattern; generates sensor.asp_parking_next_move_time | — Pending (docs say sensor.asp_next_move_time) |
| Width-relative confidence threshold (v1.1) | Street width varies 20-60ft in NYC; absolute 10ft guard too sensitive on narrow streets | ✓ Good — PROSPECT PL case fixed |
| resolve_asp() as single public API (v1.1) | Callers shouldn't wire three pipeline stages; debug flag enables introspection | ✓ Good — clean ergonomics, @overload stubs |
| BFS graph propagation for mid-span coverage (v1.1) | SODA spans cover multiple CSCL blocks; interior blocks were missing has_asp flags | ✓ Good — near-doubles Manhattan coverage |
| SODA voided sign filter IS NULL (v1.1) | record_type='Current' was a no-op (all records have that type) | ✓ Good — fixes false negatives |
| graph.json covers all segments (not ASP-only) (v1.1) | Level 4 must navigate between any adjacent blocks to find covering span | ✓ Good — correct for BFS traversal |

---
*Last updated: 2026-03-25 after Phase 15 completion*
