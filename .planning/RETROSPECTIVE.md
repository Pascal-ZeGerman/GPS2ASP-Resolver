# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v3.2 — UX Improvements and Monthly Updates

**Shipped:** 2026-05-19
**Phases:** 4 (31–34) | **Plans:** 14 | **Timeline:** 7 days (2026-05-10 → 2026-05-17) | **Commits:** 96

### What Was Built

- `vendor-guard.yml` + `scripts/sync_vendored.py` — automated CI drift detection for vendored gps2asp mirror; 27-test TDD suite; strings.json byte-sync
- Three-tier date-aware sensor format ("⚠ Today, H:MM AM" / "Tomorrow, H:MM AM" / "Weekday (M/D), H:MM AM"); HA-local timezone Today gate; `now_ha_local()` helper
- `index_io.py` + three new HA entities — download-from-GitHub-releases, atomic dir swap, zip-slip refusal, `asyncio.Lock` concurrency guard, `SpatialIndex.reset()`
- `caldav_sync.py` — pure async CalDAV glue (SHA-256 UID, VEVENT build, validate/list/write/delete); coordinator suspension choke-point; Store-persisted UID; `async_remove_entry` cleanup; credentials redacted from diagnostics

### What Worked

- **CI guard shipped first (Phase 31)** — all subsequent phases inherited vendored-mirror protection automatically; zero drift incidents in Phases 32-34
- **now_ha_local() extracted early** — Phase 32 introduced the helper; Phase 34 reused it without duplication; forward-planned dependencies paid off
- **Suspension choke-point refactor (Phase 34)** — consolidating 6 scattered suspension-mutation sites into one method (`_async_apply_suspension_state`) eliminated Pitfall 8 entirely; clean and testable
- **SHA-256 deterministic UID** — decided before any code was written; persists correctly across restarts without storing state in options (which would trigger reload)

### What Was Inefficient

- **ROADMAP.md and STATE.md not updated after Phase 34 execution** — milestone was marked "shipped" in STATE.md but internal position and CALDAV requirements were left stale; forensic audit at milestone close caught it
- **Phase 33 live-HA UAT deferred again** — same pattern as Phase 25 (Phase 22 before that); human UAT requiring a live HA instance continues to be deferred rather than integrated
- **HANDOFF.json from Phase 17 was never cleaned up** — orphaned for 7+ weeks across two milestone closings; forensic audit finally surfaced it

### Patterns Established

- CI guard ships first in a milestone — protects all subsequent phases automatically
- Suspension choke-point pattern — single method owns all suspension-state mutation; never scatter suspension writes
- `Store` for cross-restart UID persistence — `entry.options` triggers reload; `hass.data` is lost on restart; `Store` is the right tool
- `caldav_sync.py` as HA-specific glue NOT mirrored — CalDAV is integration-only; keep the CI guard clean by not adding exception lists

### Key Lessons

1. **Update tracking files at execution time, not at milestone close** — Phase 34's ROADMAP.md progress row and CALDAV-* requirements checkboxes were left stale for days; update the row in ROADMAP.md when you write the SUMMARY
2. **Clean up HANDOFF.json at the end of every session** — if work was paused and then resumed from a different entry point, delete the old handoff immediately
3. **Schedule live-HA UAT as a concrete calendar item** — three milestones running, live-HA scenarios keep being deferred; it won't happen unless it's explicitly scheduled
4. **forensic --forensic catches what yolo mode skips** — the forensic progress check found 4 issues that would have been invisible in a standard progress check

### Cost Observations

- Model mix: claude-sonnet-4-6 throughout (switched from opus to reduce cost)
- Sessions: ~8 distinct execution sessions over 7 days
- Notable: 96 commits in 7 days — highest commit velocity of any milestone; indicates tight TDD discipline (RED/GREEN/commit rhythm)

---

## Milestone: v3.0 — Suspension Handling

**Shipped:** 2026-04-30
**Phases:** 6 (19–24) | **Plans:** 11 | **Timeline:** 25 days (2026-03-31 → 2026-04-25)

### What Was Built

- `HolidayCalendar` — async ICS fetch with 39-date `FALLBACK_2026`, `is_suspended()` API, and `icalendar` parsing
- `apply_suspension()` pure function — annotates `ScheduleFound`/`ASPActiveNow` with `suspension_reason` and `resolution_reason`; Stage 4 pipeline wiring via `resolve_asp(suspension_status=...)`
- `NYC311Client` — fail-open async 311 poller with auth error escalation and 13-test TDD suite
- HA coordinator suspension wiring — 60-min poll timer, startup holiday check, lazy merge at sensor read time
- ha-nyc311 bridge — immediate propagation via `async_track_state_change_event`; poll short-circuit when bridge healthy
- HA debug interface — GPS/datetime override via `_get_now()` abstraction, `ASPDebugModeSensor`, notification service config

### What Worked

- **Fail-open design** — decided early that 311 errors show schedule, not suppress it; implementation was straightforward because the contract was clear
- **Pure function `apply_suspension()`** — placing merge logic in a pure function made it trivially testable and reusable across sensor, binary sensor, and coordinator
- **`_get_now()` abstraction** — single-point datetime injection enabled debug override without touching coordinator internals; clean and testable
- **Vendor sync discipline** — keeping `custom_components/asp_parking/gps2asp/` byte-identical to `src/gps2asp/` prevented coordinator/library drift
- **Phase 22 Nyquist validation** — 58/58 tests green before formal verification run; Nyquist compliance meant the verification gap was documentary only

### What Was Inefficient

- **Phase 22 VERIFICATION.md never run** — 58/58 tests green and Nyquist compliant but `/gsd-verify-work 22` was never invoked; creates a formal audit gap that slows milestone close
- **INT-01 (ha_nyc311 misclassification)** — Phase 23 added a new `source` Literal to `SuspensionInfo` but didn't update the `apply_suspension()` else-branch; caught by audit but not by tests (no test covered `resolution_reason` for `ha_nyc311` source)
- **Phases 23/24 human UAT outstanding** — live-HA tests need a running HA instance; these were deferred rather than integrated into the development cycle
- **wave_0_complete=false on Phases 19-21** — VALIDATION.md files show Nyquist partial; completing Wave 0 tests was deferred

### Patterns Established

- Fail-open suspension: all 311 API error paths return `_NOT_SUSPENDED` — schedule always shown
- Lazy merge pattern: `apply_suspension()` called at read time (not coordinator update time) avoids double-mutation
- `_get_now()` as a single datetime injection point — enables debug override without coordinator surgery
- Bridge poll short-circuit: when ha-nyc311 entity is healthy, skip the 60-min 311 poll entirely
- Vendor sync: `custom_components/asp_parking/gps2asp/` kept byte-identical to `src/gps2asp/` via explicit sync phases

### Key Lessons

1. **Run `/gsd-verify-work` immediately after implementation** — Phase 22 was complete for weeks but no VERIFICATION.md existed; the formal verification step takes minutes and prevents audit gaps
2. **Update all source references when adding a new Literal variant** — adding `'ha_nyc311'` to `SuspensionInfo.source` required updating `apply_suspension()`'s else-branch; write tests for the new value at the same time
3. **Human UAT requires a live HA instance — schedule it explicitly** — don't treat it as "can be done anytime"; it's a hard dependency that should be a phase checkpoint
4. **Audit before claiming milestone complete** — v3 audit at 2026-04-26 found INT-01 and Phase 22 gap; auditing earlier (mid-development, after Phase 22) would have caught these while still in flow

### Cost Observations

- Model mix: claude-opus-4-x executor for all phases
- Sessions: ~12 distinct planning/execution sessions over 25 days
- Notable: Phase 21 (NYC311Client) had cleanest TDD execution — 13 tests written RED before a line of implementation; zero regressions through all subsequent phases

---

## Milestone: v1.1 — Bug Fixes

**Shipped:** 2026-03-07
**Phases:** 7 | **Plans:** 13 | **Timeline:** 5 days (2026-02-27 → 2026-03-03)

### What Was Built

- Width-relative confidence algorithm — fixed false confidence=0.0 on narrow streets by using rw_type-aware `_NYC_DEFAULT_WIDTHS` fallback
- `resolve_asp(lat, lon, debug=False)` — single importable function with `@overload` stubs, TDD RED/GREEN, clean ergonomics
- Restructured module layout: `pipeline.py`, thin `__init__.py`, build tools in `scripts/`
- Rebuilt spatial index to 26,374 ASP segments (+44%), fixed 3 bugs in `build_index.py` (voided sign filter, directional normalization, dead-end sentinel)
- BFS graph propagation for mid-span ASP coverage — 62,455 interior blocks added; Manhattan 29.5%→58.2%, Brooklyn 47.9%→74.1%

### What Worked

- TDD RED/GREEN pattern (Phase 7) — wrote 8 failing tests first, then implemented `resolve_asp()` to pass them; zero regressions
- Phased refactoring (Phase 8) — split into API surface, must-fix quality, and nice-to-have swept cleanly without regressions
- Rebuilding the index as a separate phase (Phase 9) from fixing the bugs — separation let us validate fixes before measuring coverage
- BFS graph approach for mid-span coverage — elegant solution to the multi-block SODA span problem; achieves near-double coverage improvement in one phase

### What Was Inefficient

- Audit (v1.1-MILESTONE-AUDIT.md) was done after only phases 5-7; phases 8-11 were added without a re-audit — created a stale audit gap
- Phase 8 (refactor) generated many small commits; could have been batched into 2 commits
- REQUIREMENTS.md deleted before v1.1 started — v1.1 requirements were tracked ad-hoc (no REQ-IDs), making formal traceability impossible
- ROADMAP.md headers for phases 8-11 were inconsistently marked (plans shown as unchecked `[ ]` even after completion)

### Patterns Established

- `build_index.py` → normalize using `normalize_to_soda()` at build time (same normalization as runtime)
- Voided sign filter: `sign_design_voided_on_date IS NULL` (not `record_type='Current'`)
- Dead-end sentinel: `""` empty string (matches SODA API format)
- Street width confidence: `parking_lane_fraction * effective_width / 2` threshold
- graph.json covers all segments (not ASP-only) — Level 4 BFS needs to navigate through non-ASP blocks
- Level 4 fires only when `any_soda_results is False` (not when records exist but have no broom signs)

### Key Lessons

1. **Audit milestones at their final scope, not mid-development** — the v1.1 audit covered 3 of 7 phases; do audit after all phases are planned
2. **Keep REQUIREMENTS.md alive through the milestone** — ad-hoc tracking works but loses traceability; register REQ-IDs early
3. **Coverage metrics need context** — "29.5% Manhattan" sounds bad but is a data structure issue (multi-block spans), not a code bug; BFS propagation solved it structurally
4. **Spatial index rebuild should always follow bug fixes** — never ship index fixes without re-running the build and validating per-borough counts

### Cost Observations

- Model mix: quality profile (claude-opus-4-x executor)
- Sessions: ~10 distinct planning/execution sessions
- Notable: Phase 11 (BFS) was the most complex — 3 plans, multiple new functions, graph output — but executed cleanly due to thorough upfront plan

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v1.0 | 4 | 9 | Initial pipeline — greenfield build |
| v1.1 | 7 | 13 | Bug fixes + coverage improvement; TDD for API phase |
| v2.0 | 7 | 12 | Full borough coverage; BFS graph propagation; structured logging |
| v3.0 | 6 | 11 | Suspension calendar; 311 polling; ha-nyc311 bridge; debug interface |

### Cumulative Quality

| Milestone | Tests | LOC | Notable |
|-----------|-------|-----|---------|
| v1.0 | 213 | 7,314 | Full pipeline operational |
| v1.1 | 273 | 7,585 | +60 tests, spatial index +44%, ASP coverage doubled |
| v2.0 | ~310 | ~8,800 | Level 4 logging, BFS graph, Queens/Manhattan coverage |
| v3.0 | 58+ new | 10,205 | Suspension pipeline, 311 client, HA wiring, debug interface |
