# Milestones

## v3.0 Suspension Handling (Shipped: 2026-04-30)

**Phases completed:** 6 phases (19–24), 11 plans
**Timeline:** 25 days (2026-03-31 → 2026-04-25)
**Code:** 10,205 LOC Python | 28 files | +3,526 / -186 lines | 35 commits

**Delivered:** Complete ASP suspension calendar wired end-to-end — holiday dates from NYC DOT ICS feed, live NYC 311 emergency/weather polling, ha-nyc311 bridge for immediate propagation, and a full HA debug interface for GPS/datetime override and notification suppression.

**Key accomplishments:**

- `HolidayCalendar` with async ICS fetch, 39-date `FALLBACK_2026`, and `is_suspended()` API
- `apply_suspension()` pure function annotating `ScheduleFound`/`ASPActiveNow` with `suspension_reason` + `resolution_reason`
- `resolve_asp()` extended with optional `suspension_status` parameter — Stage 4 pipeline wiring
- `NYC311Client` with fail-open behavior on all error paths, auth error escalation, and 13-test TDD suite
- HA coordinator wired with 60-min 311 poll timer, startup holiday check, and lazy `apply_suspension()` merge at read time
- ha-nyc311 bridge entity — immediate suspension propagation via state-change subscription + poll short-circuit when bridge healthy
- Debug options flow step — GPS lat/lon override, datetime injection via `_get_now()`, notification suppression, `ASPDebugModeSensor` diagnostic entity

**Tech debt accepted:**

- INT-01: `ha_nyc311` source misclassified as `'suspended_holiday'` in `resolution_reason` attribute (semantic only — core behavior correct)
- Phase 22 VERIFICATION.md not formally created (58/58 tests green, Nyquist compliant)
- Phases 23/24 human live-HA tests outstanding (7 scenarios)
- `NYC311Client.fetch_status()` ignores debug datetime override (minor)
- NOTIF-01 lead time hardcoded at 2 hours (minor)

**Known deferred items at close: 18** (see below)

### Deferred Items (acknowledged at milestone close 2026-04-30)

| Category | Item | Status |
|----------|------|--------|
| debug_session | gps2asp-module-not-found | root_cause_found |
| uat_gap | Phase 22: 22-UAT.md | testing — 5 pending scenarios |
| uat_gap | Phase 24: 24-HUMAN-UAT.md | partial — 3 pending scenarios |
| verification_gap | Phase 23: 23-VERIFICATION.md | human_needed |
| verification_gap | Phase 24: 24-VERIFICATION.md | human_needed |
| quick_task | 1-fix-gps2asp-module-not-installed-so-pipe | missing SUMMARY |
| quick_task | 2-lower-confidence-threshold-default-to-0- | missing SUMMARY |
| quick_task | 260316-cvs-format-datetime-string-in-ha-sensor | missing SUMMARY |
| quick_task | 260424-urm-make-the-repo-hacs-ready | missing SUMMARY |
| quick_task | 260428-wf8-document-the-functioning-of-this-tool | missing SUMMARY |
| quick_task | 260429-lgy-rewrite-readme-md-for-hacs-lay-users | missing SUMMARY |
| quick_task | 3-fix-5-code-review-issues | missing SUMMARY |
| quick_task | 4-fix-named-directional-normalization | missing SUMMARY |
| todo | Add env config for caching area range | pending |
| todo | Parse non-ASP parking restrictions in future phase | pending |
| todo | Add HA diagnostics endpoint | pending |
| todo | Schedule monthly spatial index rebuild in HA | pending |
| todo | Add Level 4 hit rate observability metrics | pending |

---

## v2.0 Full Borough Coverage (Shipped: 2026-03-30)

**Phases completed:** 7 phases, 12 plans, 27 tasks

**Key accomplishments:**

- Four grep-friendly l4_event= INFO log entries added to retrieve_signs() Level 4 block, enabling HA operators to diagnose mid-span match failures with a single grep command
- TDD RED tests for soda_level propagation: 4 passing unit tests on test-local mirror + 2 failing integration tests on production ASPResult
- Thread soda_level (int 1-4) from SignRetrievalSuccess through ASPResult, coordinator, and sensor extra_state_attributes -- making Wave 0 RED tests GREEN
- 2-hop BFS filter function and zstandard-compressed graph.json.zst output in build_index.py, with 10 tests (9 GREEN, 1 RED for Plan 02)
- StreetGraph.load() reads graph.json.zst via zstandard streaming decompression with plain .json fallback for local dev
- Queens/Manhattan GPS fixtures (25+18 locations), live SODA audit script, and RED TDD tests for TPKE/CRES normalization gaps
- Added TPKE->TURNPIKE and CRES->CRESCENT suffix expansions, rebuilt spatial index, verified coverage with audit script -- remaining gaps confirmed as structural CSCL/SODA boundary mismatches by Phases 16-17
- Geocoded 25 Queens residential addresses via GeoSearch v2 API and extended audit script with CSCL-vs-SODA span diagnostics for Level 3+ failures
- L3 diagnostic audit of 25 geocoded Queens fixtures found 0 new suffix gaps -- all failures are geometric mismatches (CSCL/SODA cross-street disagreement) or SODA data gaps
- 18 Manhattan addresses geocoded via GeoSearch v2 across 4 neighborhoods; L3 diagnostic audit reveals 5.6% Level 1+2 baseline with cross-street boundary mismatches as dominant failure pattern
- Lettered avenue prefix expansion (AVE A -> AVENUE A) improves Manhattan L1+2 from 5.6% to 11.1%; all remaining failures categorized as geometric mismatches, name alias mismatches, or SODA data gaps
- Synced Phase 12 structured Level 4 l4_event= logging to vendored HA signs module, closing OBS-02 gap; corrected REQUIREMENTS.md traceability table

---

## v1.1 Bug Fixes (Shipped: 2026-03-07)

**Phases completed:** 7 phases (5-11), 13 plans
**Timeline:** 5 days (2026-02-27 → 2026-03-03)
**Code:** 7,585 lines Python, 37 files
**Commits:** 50

**Delivered:** Hardened and expanded the v1.0 pipeline — fixed two critical bugs, improved confidence scoring with real street-width data, exposed a clean `resolve_asp()` API, refactored the codebase, rebuilt the spatial index (+44%), and achieved 58.2%/74.1% ASP coverage in Manhattan/Brooklyn via BFS graph propagation.

**Key accomplishments:**

- Fixed stale venv shebangs (BUG-01) and `ScheduleFound.next_window` type mismatch (BUG-02)
- Width-relative confidence algorithm using NYC street width data — fixed PROSPECT PL from confidence=0.0 to 0.61
- `resolve_asp(lat, lon, debug=False)` — single importable function with `@overload` stubs and rich debug output
- Restructured module layout: `pipeline.py`, thin `__init__.py`, build tools in `scripts/`
- Rebuilt spatial index to 26,374 ASP segments (+44%) after fixing 3 bugs in `build_index.py`
- BFS graph propagation for mid-span ASP coverage — Manhattan 29.5%→58.2%, Brooklyn 47.9%→74.1%; 62,455 interior blocks added

**Tech debt accepted:**

- HA coordinator still calls three pipeline stages manually (not via `resolve_asp()`) — divergent invocation paths
- v1.1 requirements tracked ad-hoc (no formal REQ-IDs in REQUIREMENTS.md)
- Manhattan coverage 58.2% (60-80% target), Queens 36.8% — further BFS tuning deferred to v1.2

---

## v1.0 MVP (Shipped: 2026-02-23)

**Phases completed:** 4 phases, 9 plans
**Timeline:** 2 days (2026-02-21 → 2026-02-22)
**Code:** 7,314 lines Python across 41 files, 213 tests passing

**Delivered:** Full GPS-to-next-move-time pipeline running inside Home Assistant, triggered by VW CarNet GPS updates, with results exposed as sensor entities.

**Key accomplishments:**

- GPS-to-street resolution with R-tree spatial index (105K NYC segments), cross-product side resolver, and confidence scoring
- Three-level fallback SODA API client for ASP sign retrieval with pagination, retry, and CSCL-to-SODA name normalization
- Regex-based sign description parser handling 7+ format variations with conservative window merging and timezone-aware next-move computation
- Home Assistant custom component with 3-step config wizard, event-driven coordinator (50m threshold, 5s debounce, 8hr refresh), and rich sensor entities
- Full async pipeline: GPS coordinate → "next time to move is Tuesday at 8:30 AM" in a single call chain
- HACS-ready packaging with 213 tests and zero regressions

**Tech debt accepted:**

- ScheduleFound.next_window type mismatch (can receive None in edge case)
- SODA API app_token not configurable via HA UI
- ROADMAP tracking entries stale for Phases 3-4

---
