# Requirements: GPS2ASP Resolver

**Defined:** 2026-03-30
**Core Value:** Tell the user exactly when they need to move their car for ASP — or that they don't need to move because ASP is suspended.

## v3.0 Requirements

Requirements for suspension handling. Each maps to roadmap phases.

### Suspension Calendar

- [x] **SUSP-01**: User can see when ASP is suspended for NYC holidays (~43 annual dates) — holiday calendar loaded from official NYC DOT ICS data, distinguishing legal holidays (all rules suspended) from cleaning-only suspensions

### Emergency Polling

- [x] **SUSP-02**: User receives same-day weather/emergency ASP suspension status via NYC 311 API polling — 60-minute default interval, fail-open on API errors (schedule shown, not suppressed)

### Schedule Merge

- [x] **SUSP-03**: User sees a single authoritative answer combining schedule and suspension — "move at X" when active, "suspended, no move needed" when suspended, with `suspension_reason` attribute explaining why

### HA Integration Bridge

- [ ] **SUSP-04**: User with ha-nyc311 installed gets suspension status bridged automatically — no duplicate API calls, auto-detected via HA state machine, graceful fallback to direct 311 polling if not installed

## Future Requirements

Deferred to future milestone. Tracked but not in current roadmap.

### Notifications

- **NOTIF-01**: HA actionable notification with configurable lead time
- **NOTIF-02**: Automation-ready structured output

### Coordinator Refactor

- **COV-03**: Migrate HA coordinator to use `resolve_asp()` (currently calls three stages manually)

### Caching

- **CACHE-01**: Cache ASP sign data per block segment in SQLite with weekly refresh
- **CACHE-02**: Configurable caching area (center + radius) for pre-seeding
- **CACHE-03**: Fall back to live SODA API on cache miss

## Out of Scope

| Feature | Reason |
|---------|--------|
| nyc311calendar library as dependency | aiohttp conflicts with httpx; alpha quality with breaking changes expected |
| Meter suspension handling | ASP-only scope; meters have different rules |
| Suspension prediction/forecasting | Official announcements are the authoritative data source |
| Multi-day suspension look-ahead | v3.0 covers today/tomorrow only; weekly view deferred |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| SUSP-01 | Phase 19 | Complete |
| SUSP-02 | Phase 21 | Complete |
| SUSP-03 | Phase 20 (library), Phase 22 (HA) | Complete |
| SUSP-04 | Phase 23 | Pending |

**Coverage:**
- v3.0 requirements: 4 total
- Mapped to phases: 4
- Unmapped: 0

---
*Requirements defined: 2026-03-30*
*Last updated: 2026-03-31 after v3.0 roadmap creation*
