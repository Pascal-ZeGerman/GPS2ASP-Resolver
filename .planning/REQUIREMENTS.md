# Requirements: GPS2ASP Resolver

**Defined:** 2026-03-13
**Core Value:** Tell the user exactly when they need to move their car for ASP — "next time to move is [datetime]"

## v2.0 Requirements

Requirements for the v2.0 Full Borough Coverage milestone.

### Coverage

- [x] **COV-02**: User gets ASP result for Queens locations at ≥50% success rate (runtime Level 1/2 SODA query success, verified by GPS spot-check fixture set)
- [x] **COV-04**: User gets ASP result for Manhattan locations at ≥60% success rate (verified after index rebuild; expected side effect of Queens normalization fix)

### Observability

- [x] **OBS-01**: HA sensor `extra_state_attributes` includes `soda_level` integer (1–4) indicating which API fallback level resolved the parking data
- [x] **OBS-02**: Level 4 fallback emits structured INFO log entries at entry, match (Case A), and both miss cases (Case B: no covering span; Case C: no SODA records)

### Performance

- [x] **PERF-01**: `graph.json` file size is ≤4 MB at build time (ASP-reachable segment filter preserving full BFS traversal correctness)

## v2.x Requirements

Deferred from v2.0. Tracked but not in current roadmap.

### Coordinator Refactor

- **COV-03**: Migrate HA coordinator to use `resolve_asp()` instead of manually calling three pipeline stages (tech debt; soda_level achievable without migration)

### Caching

- **CACHE-01**: Cache ASP sign data per block segment in SQLite with weekly refresh
- **CACHE-02**: Configurable caching area (center + radius) for pre-seeding
- **CACHE-03**: Fall back to live SODA API on cache miss

## v3+ Requirements

Separate milestones — different data sources and problem scope.

### Suspension Handling

- **SUSP-01**: NYC holiday ASP suspension calendar
- **SUSP-02**: Weather/emergency suspension polling via 311 API
- **SUSP-03**: Merge suspension status with schedule for single authoritative answer
- **SUSP-04**: Bridge with ha-nyc311 integration for suspension binary sensors

### Notifications

- **NOTIF-01**: HA actionable notification with configurable lead time
- **NOTIF-02**: Automation-ready structured output

## Out of Scope

| Feature | Reason |
|---------|--------|
| COV-03 coordinator migration | soda_level achievable without it; migration risks behavioral regressions if rushed |
| BFS tuning as Queens fix | Normalization audit replaces this approach; BFS max_depth already at 30 (validated) |
| zstandard compression (default) | Only add if ASP segment filtering alone exceeds 4 MB; avoid dependency unless needed |
| Per-borough normalize_to_soda() branching | Global normalization function; borough-specific flags add complexity; fix table gaps globally |
| Staten Island coverage | SODA data gap confirmed in v1.1; no actionable fix from code side |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| OBS-02 | Phase 12 | Complete |
| OBS-01 | Phase 13 | In Progress (tests only, Plan 02 pending) |
| PERF-01 | Phase 14 | Complete |
| COV-02 | Phase 15 | Complete |
| COV-04 | Phase 15 | Complete |

**Coverage:**
- v2.0 requirements: 5 total
- Mapped to phases: 5
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-13*
*Last updated: 2026-03-13 after v2.0 roadmap creation — all 5 requirements mapped*
