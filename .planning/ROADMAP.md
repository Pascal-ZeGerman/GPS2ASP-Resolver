# Roadmap: GPS2ASP Resolver

## Overview

This roadmap delivers a Python tool that takes GPS coordinates from a VW CarNet Home Assistant integration and returns exactly when the car needs to move for Alternate Side Parking. The pipeline flows linearly: convert GPS coordinates to NYC's coordinate system, resolve to a street segment and side, retrieve ASP sign data from NYC Open Data, parse the sign descriptions into structured schedules, compute the next move time, and expose it all through Home Assistant sensor entities. Each phase delivers the next link in this chain, with every phase independently testable before moving forward.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: GPS-to-Street Resolution** - Convert GPS coordinates to NYC State Plane and resolve to the correct street segment and side (completed 2026-02-21)
- [x] **Phase 2: ASP Sign Retrieval** - Query NYC Open Data for ASP/broom signs on the resolved block segment and filter to current signs (completed 2026-02-22)
- [ ] **Phase 3: Schedule Parsing and Next-Move Computation** - Parse sign descriptions into structured schedules and compute the next ASP window datetime
- [ ] **Phase 4: Home Assistant Integration** - Expose the full pipeline as HA sensor entities driven by VW CarNet GPS data

## Phase Details

### Phase 1: GPS-to-Street Resolution
**Goal**: Given WGS84 GPS coordinates, the system correctly identifies which NYC street segment and side of street the car is parked on
**Depends on**: Nothing (first phase)
**Requirements**: GPS-01, GPS-02, GPS-03
**Success Criteria** (what must be TRUE):
  1. Given a known GPS coordinate in Prospect Heights, the system outputs NY State Plane coordinates that match within 1 foot of independently verified reference values
  2. Given a GPS coordinate on a specific block, the system returns the correct on_street, from_street, to_street, and side_of_street (N/S/E/W) matching the NYC Open Data segment format
  3. When GPS accuracy is insufficient to confidently determine the street side (car near centerline), the system reports low confidence rather than silently guessing
  4. The coordinate converter and street resolver are usable as a standalone Python library with no Home Assistant dependency
**Plans**: 2 plans

Plans:
- [x] 01-01-PLAN.md — Core resolver library: project setup, models, coordinate converter, spatial index, side resolver, confidence scoring, public API, debug logging
- [x] 01-02-PLAN.md — Build script (CSCL download, R-tree index construction, cross-street and has_asp pre-computation) and end-to-end integration tests

### Phase 2: ASP Sign Retrieval
**Goal**: Given a resolved street segment and side, the system retrieves all current ASP/broom signs for that location from NYC Open Data
**Depends on**: Phase 1
**Requirements**: SIGN-01, SIGN-02, SIGN-03
**Success Criteria** (what must be TRUE):
  1. Given a street segment tuple (on_street, from_street, to_street, side), the system returns ASP sign records from the SODA API containing sign descriptions with broom symbol indicators
  2. The system never returns voided or superseded sign records -- only currently active signs appear in results
  3. When more signs exist than the default SODA page size, the system retrieves all matching signs without silent truncation
  4. The sign retrieval module is usable as a standalone Python library with no Home Assistant dependency
**Plans**: 2 plans

Plans:
- [x] 02-01-PLAN.md — Signs module core: data models, exceptions, street name normalization (CSCL-to-SODA), async SODA API client with pagination and retry
- [x] 02-02-PLAN.md — Three-level fallback retrieve_signs() public API, normalization unit tests, and SODA integration tests

### Phase 3: Schedule Parsing and Next-Move Computation
**Goal**: Given ASP sign records, the system extracts structured cleaning schedules and computes the exact next datetime the car must move
**Depends on**: Phase 2
**Requirements**: SCHED-01, SCHED-02, SCHED-03, SCHED-04
**Success Criteria** (what must be TRUE):
  1. Given a sign description like "SANITATION BROOM SYMBOL TUESDAY FRIDAY 8:30AM-10AM", the system correctly extracts the cleaning days (Tuesday, Friday) and time window (8:30 AM to 10:00 AM)
  2. The parser handles real-world format variations from the NYC dataset -- day ranges with "THRU", separators (&, comma, space), "EXCEPT SUNDAY", arrow directions, multiple time windows per sign -- with at least 95% coverage of actual broom symbol sign formats
  3. Given the current datetime and a parsed schedule, the system returns the correct next upcoming ASP window start time (e.g., "next move: Tuesday 2026-02-24 at 8:30 AM")
  4. The schedule parser and next-move computer are usable as a standalone Python library with no Home Assistant dependency
**Plans**: 2 plans

Plans:
- [ ] 03-01-PLAN.md — Data models (ASPDay enum, ScheduleResult union, TimeWindow, CleaningWindow, WeeklySchedule) and regex-based sign description parser with comprehensive tests
- [ ] 03-02-PLAN.md — Window merging, next-move datetime computation, human-readable summary, compute_schedule() public API, and integration tests

### Phase 4: Home Assistant Integration
**Goal**: The full GPS-to-next-move-time pipeline runs inside Home Assistant, triggered by VW CarNet GPS updates, with results exposed as sensor entities for dashboards and automations
**Depends on**: Phase 3
**Requirements**: HA-01, HA-02, HA-03, HA-04
**Success Criteria** (what must be TRUE):
  1. The integration reads GPS coordinates from a configured VW CarNet device_tracker entity and feeds them into the resolver pipeline without manual input
  2. A sensor entity `sensor.asp_next_move_time` exists with a datetime value showing when the car next needs to move for ASP
  3. The sensor exposes attributes with schedule details (cleaning days, time window, street name, side of street) for use in HA dashboards and automations
  4. When the car's GPS position changes by more than 50 meters, the system automatically re-resolves the ASP schedule for the new location
  5. The integration is installable via HACS or manual copy to `custom_components/` with a standard config flow setup
**Plans**: 3 plans

Plans:
- [ ] 04-01-PLAN.md — Foundation files (const, manifest, strings, services) and event-driven ASPParkingCoordinator with GPS subscription, movement threshold, debounce, and full pipeline orchestration
- [ ] 04-02-PLAN.md — Config flow (3-step wizard + options flow), sensor entity (ASPNextMoveTimeSensor with rich attributes), binary sensor (ASPActiveNowBinarySensor), and integration entry point
- [ ] 04-03-PLAN.md — Unit tests for state mapping and coordinator logic, HACS packaging, and full integration structure verification

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. GPS-to-Street Resolution | 2/2 | Complete    | 2026-02-21 |
| 2. ASP Sign Retrieval | 2/2 | Complete    | 2026-02-22 |
| 3. Schedule Parsing and Next-Move Computation | 0/2 | In progress | - |
| 4. Home Assistant Integration | 0/3 | Not started | - |
