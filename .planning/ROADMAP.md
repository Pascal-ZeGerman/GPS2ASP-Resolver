# Roadmap: GPS2ASP Resolver

## Milestones

- ✅ **v1.0 MVP** — Phases 1-4 (shipped 2026-02-23)
- ✅ **v1.1 Bug Fixes** — Phases 5-11 (shipped 2026-03-07)
- ✅ **v2.0 Full Borough Coverage** — Phases 12-18 (shipped 2026-03-30)
- 🔄 **v3.0 Suspension Handling** — Phases 19-23 (in progress)

## Phases

<details>
<summary>✅ v1.0 MVP (Phases 1-4) — SHIPPED 2026-02-23</summary>

- [x] Phase 1: GPS-to-Street Resolution (2/2 plans) — completed 2026-02-21
- [x] Phase 2: ASP Sign Retrieval (2/2 plans) — completed 2026-02-22
- [x] Phase 3: Schedule Parsing and Next-Move Computation (2/2 plans) — completed 2026-02-22
- [x] Phase 4: Home Assistant Integration (3/3 plans) — completed 2026-02-23

Full details: `.planning/milestones/v1.0-ROADMAP.md`

</details>

<details>
<summary>✅ v1.1 Bug Fixes (Phases 5-11) — SHIPPED 2026-03-07</summary>

- [x] Phase 5: Bug Fixes and Tech Debt (1/1 plans) — completed 2026-02-27
- [x] Phase 6: Improve Confidence Scoring for NYC Street Widths (1/1 plans) — completed 2026-02-28
- [x] Phase 7: Pipeline Stabilization — Importable Function with Debug Flag (2/2 plans) — completed 2026-02-28
- [x] Phase 8: Refactor Architecture and Streamline Pipeline (3/3 plans) — completed 2026-03-01
- [x] Phase 9: Rebuild the Spatial Index (2/2 plans) — completed 2026-03-01
- [x] Phase 10: Update Documentation (1/1 plans) — completed 2026-03-02
- [x] Phase 11: Improve ASP Coverage Through Mid-Span Coverage (3/3 plans) — completed 2026-03-03

Full details: `.planning/milestones/v1.1-ROADMAP.md`

</details>

<details>
<summary>✅ v2.0 Full Borough Coverage (Phases 12-18) — SHIPPED 2026-03-30</summary>

- [x] Phase 12: Structured Level 4 Logging (1/1 plans) — completed 2026-03-15
- [x] Phase 13: soda_level Propagation to HA Sensor (2/2 plans) — completed 2026-03-16
- [x] Phase 14: graph.json Size Reduction (2/2 plans) — completed 2026-03-17
- [x] Phase 15: Queens and Manhattan Coverage Fix (2/2 plans) — completed 2026-03-25
- [x] Phase 16: Queens Coverage Fix — Geocoded Fixtures (2/2 plans) — completed 2026-03-19
- [x] Phase 17: Manhattan Coverage Fix — Geocoded Fixtures (2/2 plans) — completed 2026-03-19
- [x] Phase 18: Vendored Signs Sync + Docs Cleanup (1/1 plans) — completed 2026-03-29

Full details: `.planning/milestones/v2.0-ROADMAP.md`

</details>

### v3.0 Suspension Handling (Phases 19-23) — IN PROGRESS

- [x] **Phase 19: Suspension Package Foundation** - SuspensionStatus model + NYC holiday calendar; zero network dependencies (completed 2026-03-31)
- [x] **Phase 20: Suspension Merge Layer and Pipeline Wiring** - Pure apply_suspension() function + optional suspension parameter on resolve_asp() (completed 2026-04-02)
- [x] **Phase 21: Direct 311 API Poller** - httpx-based fetch_suspension_status() for weather/emergency suspensions; fail-open (completed 2026-04-03)
- [ ] **Phase 22: HA Coordinator and Sensor Integration** - Wire suspension state into coordinator, sensor attributes, and binary sensor
- [ ] **Phase 23: ha-nyc311 Bridge** - Optional auto-detection of ha-nyc311 entities; eliminates duplicate API polling

## Phase Details

### Phase 19: Suspension Package Foundation
**Goal**: Users see holiday ASP suspensions reflected in the sensor with no network call required
**Depends on**: Nothing (self-contained library, no I/O)
**Requirements**: SUSP-01
**Success Criteria** (what must be TRUE):
  1. User can confirm all 43 annual NYC DOT holiday suspension dates are recognized by the library
  2. User sees suspension correctly identified for a date like Memorial Day with the holiday name as the reason
  3. User sees a non-suspension date (e.g., a normal Tuesday) return is_suspended=False correctly
  4. User verifies vendored copy at custom_components/asp_parking/gps2asp/suspension/ is in sync with src/gps2asp/suspension/
**Plans**: 1 plan

Plans:
- [x] 19-01-PLAN.md — Suspension package: SuspensionInfo + HolidayCalendar + ICS fetch/parse + fallback + tests + vendor sync

### Phase 20: Suspension Merge Layer and Pipeline Wiring
**Goal**: Users get a single authoritative schedule result that incorporates suspension — "suspended, no move needed" when suspended, "move at X" when not
**Depends on**: Phase 19
**Requirements**: SUSP-03 (library half)
**Success Criteria** (what must be TRUE):
  1. User calling resolve_asp() with a suspended SuspensionStatus sees the result's suspended field set to True with a suspension_reason populated
  2. User calling resolve_asp() with no suspension_status gets identical behavior to the pre-v3.0 pipeline (backwards compatible)
  3. User can distinguish "suspended holiday" from "no ASP on this block" via a resolution_reason attribute — they are not conflated
  4. User sees NOT_IN_EFFECT (normal Sunday, no cleaning) never treated as a suspension — suspension_reason remains None
**Plans**: 2 plans

Plans:
- [x] 20-01-PLAN.md — Suspension merge layer: schema changes (SuspensionInfo.source, ScheduleFound/ASPActiveNow fields) + apply_suspension() TDD
- [x] 20-02-PLAN.md — Pipeline wiring: Stage 4 in resolve_asp() + vendored copy sync

### Phase 21: Direct 311 API Poller
**Goal**: Users receive same-day weather and emergency suspension status via the NYC 311 API, with graceful degradation if the API is unreachable
**Depends on**: Phase 19
**Requirements**: SUSP-02
**Success Criteria** (what must be TRUE):
  1. User sees a snow-day suspension announced on the 311 API reflected in the sensor within the 60-minute poll interval
  2. User's sensor continues showing the schedule (not suppressed) when the 311 API returns a network error — system fails open
  3. User who omits the API key from config still gets holiday-calendar suspensions; only weather/emergency polling is skipped
  4. User who provides an invalid API key sees a config error surfaced, not a silent fail-open
**Plans**: 2 plans

Plans:
- [x] 21-01-PLAN.md — NYC311Client TDD: tests/test_poller.py (RED) + src/gps2asp/suspension/poller.py (GREEN)
- [x] 21-02-PLAN.md — Export wiring + vendored sync: suspension/__init__.py + custom_components copy

### Phase 22: HA Coordinator and Sensor Integration
**Goal**: Users see suspension status as a live HA sensor attribute — "Suspended" state text, suspension_reason, and is_on=False during active suspensions
**Depends on**: Phase 20, Phase 21
**Requirements**: SUSP-03 (HA half)
**Success Criteria** (what must be TRUE):
  1. User sees sensor state change to "Suspended" on a holiday with the holiday name in the suspension_reason attribute
  2. User sees binary sensor is_on return False when inside an otherwise-active ASP window on a suspended day
  3. User sees suspension status update independently of GPS movement — a suspension poll firing at :00 updates the sensor without requiring the car to move
  4. User who restarts Home Assistant sees correct suspension status immediately on first entity read, not only after the next poll interval
  5. User can add the optional NYC311 API key via the config flow without needing to delete and re-add the integration
**Plans**: 2 plans

Plans:
- [ ] 22-01-PLAN.md — Core suspension wiring: coordinator suspension_state + timer + startup, sensor "Suspended" branch, binary sensor guard
- [ ] 22-02-PLAN.md — Config flow api_keys step + VERSION bump + options flow API key + migration + translations

### Phase 23: ha-nyc311 Bridge
**Goal**: Users who have ha-nyc311 installed get suspension status bridged automatically with no duplicate API calls and no manual configuration
**Depends on**: Phase 22
**Requirements**: SUSP-04
**Success Criteria** (what must be TRUE):
  1. User with ha-nyc311 installed sees suspension state update immediately when the ha-nyc311 binary sensor changes — no waiting for the 60-minute poll
  2. User with ha-nyc311 installed sees no redundant direct 311 API calls in the logs — the bridge takes priority
  3. User without ha-nyc311 installed sees no configuration change required — system silently falls back to direct 311 polling
  4. User who renames the ha-nyc311 entity can specify the custom entity name in config flow and the bridge still works
**Plans**: TBD
**UI hint**: yes

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1-4 | v1.0 | 9/9 | Complete | 2026-02-23 |
| 5-11 | v1.1 | 12/12 | Complete | 2026-03-07 |
| 12-18 | v2.0 | 12/12 | Complete | 2026-03-30 |
| 19. Suspension Package Foundation | v3.0 | 1/1 | Complete    | 2026-03-31 |
| 20. Suspension Merge Layer and Pipeline Wiring | v3.0 | 2/2 | Complete    | 2026-04-02 |
| 21. Direct 311 API Poller | v3.0 | 2/2 | Complete    | 2026-04-03 |
| 22. HA Coordinator and Sensor Integration | v3.0 | 0/2 | Not started | - |
| 23. ha-nyc311 Bridge | v3.0 | 0/? | Not started | - |
