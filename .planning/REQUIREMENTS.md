# Requirements: GPS2ASP Resolver

**Defined:** 2026-02-21
**Core Value:** Tell the user exactly when they need to move their car for ASP — "next time to move is [datetime]"

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### GPS Resolution

- [x] **GPS-01**: System converts WGS84 lat/long coordinates to NY State Plane (EPSG:2263) for matching against NYC sign data
- [x] **GPS-02**: System resolves GPS point to the nearest street segment (on_street, from_street, to_street) and correct side of street (N/S/E/W)
- [x] **GPS-03**: System handles GPS accuracy limitations (~3-5m) with confidence scoring for street-side determination

### Sign Data

- [x] **SIGN-01**: System queries NYC Open Data SODA API for ASP/broom signs on the resolved block segment and side
- [x] **SIGN-02**: System filters for current signs only (excludes voided/superseded sign designs)
- [x] **SIGN-03**: System handles SODA API pagination and returns all matching signs for a block segment

### Schedule Parsing

- [x] **SCHED-01**: System parses ASP sign descriptions to extract cleaning days (e.g., "TUESDAY FRIDAY")
- [x] **SCHED-02**: System parses ASP sign descriptions to extract time windows (e.g., "8:30AM-10AM")
- [x] **SCHED-03**: System handles sign description format variations (arrow directions, "EXCEPT SUNDAY", multiple patterns)
- [x] **SCHED-04**: System computes the next upcoming ASP window datetime from current time and parsed schedule

### Home Assistant Integration

- [ ] **HA-01**: System reads GPS coordinates (latitude/longitude) from VW CarNet device_tracker entity attributes
- [ ] **HA-02**: System exposes `sensor.asp_next_move_time` with datetime value as primary output
- [ ] **HA-03**: System exposes sensor attributes with schedule details (days, time window, street, side)
- [ ] **HA-04**: System triggers re-resolve when car GPS position changes significantly (>50m movement)

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Caching

- **CACHE-01**: System caches ASP sign data per block segment in SQLite with weekly refresh
- **CACHE-02**: System supports configurable caching area (center address + radius in meters) for pre-seeding
- **CACHE-03**: System falls back to live SODA API on cache miss

### Suspension Handling

- **SUSP-01**: System factors in NYC holiday ASP suspension calendar (~30+ days/year)
- **SUSP-02**: System polls for weather/emergency ASP suspensions via cron job (311 API)
- **SUSP-03**: System merges suspension status with location schedule for single authoritative answer
- **SUSP-04**: System bridges with ha-nyc311 integration for suspension binary sensors

### Notifications

- **NOTIF-01**: System pushes HA actionable notification with configurable lead time before ASP window
- **NOTIF-02**: System provides automation-ready structured output for downstream HA automations

## Out of Scope

| Feature | Reason |
|---------|--------|
| Real-time parking availability / spot finding | Different data problem entirely; no public API for spot availability; SpotAngels/SNAG exist |
| Full parking regulation support (meters, no standing, hydrants) | Massive scope increase; ASP signs have consistent patterns, other types are far more varied |
| Mobile app or web UI | HA dashboard and companion app ARE the UI |
| Multi-vehicle support | Single car for now; design to not preclude but don't implement |
| Parking guidance (where to move TO) | Requires spot availability data that doesn't exist |
| AI/ML suspension predictions | Official announcements are the data; predictions create false confidence |
| OpenCurb API integration | Only covers Midtown Manhattan, not Brooklyn; not useful for primary area |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| GPS-01 | Phase 1 | Complete |
| GPS-02 | Phase 1 | Complete |
| GPS-03 | Phase 1 | Complete |
| SIGN-01 | Phase 2 | Complete |
| SIGN-02 | Phase 2 | Complete |
| SIGN-03 | Phase 2 | Complete |
| SCHED-01 | Phase 3 | Complete |
| SCHED-02 | Phase 3 | Complete |
| SCHED-03 | Phase 3 | Complete |
| SCHED-04 | Phase 3 | Complete |
| HA-01 | Phase 4 | Pending |
| HA-02 | Phase 4 | Pending |
| HA-03 | Phase 4 | Pending |
| HA-04 | Phase 4 | Pending |

**Coverage:**
- v1 requirements: 14 total
- Mapped to phases: 14
- Unmapped: 0

---
*Requirements defined: 2026-02-21*
*Last updated: 2026-02-21 after roadmap creation*
