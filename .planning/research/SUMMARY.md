# Project Research Summary

**Project:** GPS2ASP Resolver — v3.0 Suspension Handling
**Domain:** NYC Alternate Side Parking suspension awareness (holiday calendar + emergency API + HA integration)
**Researched:** 2026-03-31
**Confidence:** HIGH

## Executive Summary

GPS2ASP v3.0 adds suspension awareness on top of a fully operational v2.0 pipeline. The existing system resolves GPS to a cleaning schedule and exposes "next move time" as a Home Assistant sensor — but it is blind to the ~43 annual NYC holiday suspensions and all weather/emergency suspensions. On any of those days, the sensor fires a false "move your car" answer. The fix is a suspension layer that is deliberately post-pipeline: a pure `apply_suspension()` function overlays a `SuspensionStatus` onto the computed `ScheduleResult` without touching the GPS-to-SODA pipeline itself. This separation is the core architectural insight — suspension is an annotation on top of a schedule, not a replacement for one. Critically, the existing `ScheduleFound` and `ASPActiveNow` dataclasses already have a `suspended: bool = False` hook left in place from v2.0 precisely for this milestone.

Two data sources are required and must be strictly layered. The NYC DOT annual ICS calendar covers all pre-announced holiday suspensions (~43 dates/year; no API key, no runtime network call, low risk). The NYC 311 Public API (`api.nyc.gov/public/api/GetCalendar`) covers weather and emergency suspensions announced same-day (requires a free API key, network-dependent, medium risk). A third optional path — reading state from the `ha-nyc311` HACS integration if the user has it installed — eliminates duplicate API polling and is the lowest-friction path for users who already have it. The system must degrade gracefully through this priority chain: ha-nyc311 bridge → direct 311 polling → holiday-calendar-only.

The dominant risk is **false confidence from the NYC 311 API layer**. The `nyc311calendar` Python library (used by ha-nyc311 internally) is alpha-quality and last released December 2022; it must not be taken as a dependency. The raw 311 API must be called directly via the existing `httpx` client. A second structural risk is conflating the four distinct API status values (`IN_EFFECT`, `NOT_IN_EFFECT`, `SUSPENDED`, `NO_INFORMATION`) into a boolean. Specifically, `NOT_IN_EFFECT` (normal Sunday — never had cleaning) must never be conflated with `SUSPENDED` (holiday or emergency — cancelled active cleaning). Suspension state must be a typed enum throughout, never a raw `bool`.

---

## Key Findings

### Recommended Stack

The only new library dependency for v3.0 is `icalendar >= 6.1.0` (pure Python, RFC 5545 compliant, actively maintained, no compiled extensions, no HA conflicts). Everything else uses the existing stack: `httpx` for the direct 311 API call, `dataclasses.replace()` for frozen dataclass mutation, and HA's `async_track_state_change_event` for the ha-nyc311 bridge. The `nyc311calendar` PyPI package must NOT be added — it requires `aiohttp` (conflicting second HTTP client framework in HA's shared Python environment) and self-identifies as alpha with no maintenance since December 2022.

**Core technologies (v3.0 additions only):**
- `icalendar >= 6.1.0` — parse NYC DOT annual ICS file for holiday dates; only new runtime dependency; pure Python, no conflicts with HA packages
- `httpx` (existing) — direct calls to `api.nyc.gov/public/api/GetCalendar`; no wrapper library needed; 311 API is a single JSON endpoint
- `dataclasses.replace()` (stdlib) — mutate frozen `ScheduleFound`/`ASPActiveNow` to set `suspended=True`; existing codebase pattern
- `async_track_state_change_event` (HA helpers, existing) — watch `binary_sensor.nyc311_parking_exception_today` state for ha-nyc311 bridge

**Do NOT add:** `nyc311calendar` (aiohttp conflict, alpha quality), `aiohttp` (second HTTP framework), `ics.py` (less maintained than icalendar), `python-dateutil` (not needed; ICS dates are plain dates with no recurring rules), `recurring-ical-events` (overkill; ASP suspension dates are non-recurring VEVENT entries).

**pyproject.toml change:** Add `"icalendar>=6.1.0"` to `[project]` dependencies and `manifest.json` requirements.

See `.planning/research/STACK.md` for full rationale and alternatives considered.

### Expected Features

NYC drivers expect a suspension-aware sensor to answer two questions precisely: "do I need to move today?" and "do I need to move tomorrow?" False alarms (showing a cleaning window on a holiday) erode trust faster than no feature at all — users will move unnecessarily and stop trusting the sensor.

**Must have (table stakes for v3.0):**
- **SUSP-01: Holiday calendar** — all 43 annual NYC DOT suspension dates; `is_holiday_suspension(date) -> bool`; include holiday name and suspension type (major legal holiday vs. religious/other) in attributes; no API call required at runtime
- **SUSP-02: Weather/emergency polling** — poll NYC 311 API at 60-minute default interval (15 minutes during 8 PM–midnight NYC window); required for snow-day suspensions announced same-day; API key in config flow (optional — system degrades to holiday-only if absent)
- **SUSP-03: Merged authoritative answer** — when suspended, `next_move_time` advances to next non-suspended window; `is_suspended`, `suspension_reason`, `suspension_type` in sensor attributes; binary sensor `is_on` returns `False` during suspensions even if inside an otherwise-active window
- **SUSP-04: ha-nyc311 bridge** — read `binary_sensor.nyc311_parking_exception_today/tomorrow` from ha-nyc311 if installed; auto-detected via `hass.states.get()` (no user config required); fall back to direct 311 polling if absent

**Should have (differentiators):**
- `suspension_type` attribute: `"none"` / `"street_cleaning_only"` / `"all_parking_rules"` — major legal holidays also suspend meters and No Standing restrictions; users need this distinction
- `suspension_reason` attribute: "Rosh Hashanah", "Snow Emergency", etc. — sourced from ICS holiday name or 311 API reason string
- `resolution_reason` attribute: distinguishes `"suspended_holiday"` / `"suspended_emergency"` / `"no_asp_on_block"` / `"no_data_for_block"` / `"active"` — prevents user confusion between three semantically different "no move needed" states

**Defer (v3.x+):**
- NOTIF-01: HA push notification "move your car tomorrow" — requires stable suspension-aware schedule first
- COV-03: Coordinator migration to `resolve_asp()` — existing tech debt; suspension can be wired without it; defer
- HA CalendarEntity for suspension schedule — ha-nyc311 already provides this for users who have it installed

**Anti-features (do not build):**
- Standalone `binary_sensor` entity for suspension — `is_suspended` attribute on the existing sensor is sufficient; avoids an extra entity the user must manage when ha-nyc311 is not installed
- Polling 311 API more than once per 15 minutes — data updates at most hourly; over-polling risks rate throttling without adding value
- Scraping @NYCASP Twitter — official 311 API carries the same data with stability guarantees; Twitter auth is a nightmare in 2025+

See `.planning/research/FEATURES.md` for the full feature landscape and dependency graph.

### Architecture Approach

Suspension is a post-pipeline annotation. The GPS → segment → SODA signs → schedule pipeline (Stages 1-3) runs unchanged. A new Stage 4 (`apply_suspension()`) is a pure function called after `compute_schedule()` returns. This design enables re-application of suspension to a cached `ScheduleResult` when suspension status changes independently — without re-running the expensive SODA query. The coordinator holds suspension state as a separate field from schedule state and entities merge them lazily at sensor read time. This lazy-merge design is the key choice that prevents the race-condition pitfall.

**New `gps2asp` library components:**
1. `suspension/calendar.py` — static `frozenset[date]` of holiday suspension dates; `is_holiday_suspension(date)` and `get_suspension_reason(date)` public API; no network dependency
2. `suspension/models.py` — `SuspensionStatus` frozen dataclass with `is_suspended: bool`, `reason: str | None`, `source: Literal["holiday_calendar", "nyc311_api", "ha_nyc311_bridge", "unknown"]`
3. `suspension/merge.py` — pure `apply_suspension(schedule, status) -> ScheduleResult`; uses `dataclasses.replace()`; merge rules: `ScheduleFound`/`ASPActiveNow` with next window on a suspended date → `suspended=True`; all other variants pass through unchanged
4. `suspension/poller.py` — async `fetch_suspension_status(date, api_key, session) -> SuspensionStatus` via direct `httpx` call to NYC 311 API; fails open on network error (`is_suspended=False`, `source="unknown"`); 401 surfaced as config error

**Modified `gps2asp` library components:**
5. `schedule/models.py` — add `suspension_reason: str | None = None` to `ScheduleFound` and `ASPActiveNow` (the `suspended: bool = False` hook already exists)
6. `pipeline.py` — add optional `suspension_status: SuspensionStatus | None = None` parameter; call `apply_suspension()` as Stage 4
7. `api_models.py` — add `suspension_reason: str | None = None` to `ASPResult`

**Modified HA layer components:**
8. `coordinator.py` — new `suspended`, `suspension_reason`, `suspension_source`, `last_suspension_check` fields on `ASPParkingData`; separate `async_track_time_interval` for suspension polling; eager fetch on `async_start()`; bridge detection at startup; `config_flow.py` gains optional `CONF_NYC311_API_KEY` and `CONF_NYC311_ENTITY`
9. `sensor.py` — new `asp_suspended`, `suspension_reason`, `suspension_source` attributes; "Suspended" state text when `suspended=True`; lazy merge at read time
10. `binary_sensor.py` — `is_on` returns `isinstance(schedule, ASPActiveNow) and not schedule.suspended`
11. `suspension_bridge.py` (new, HA layer only) — reads ha-nyc311 entity state; returns `None` if absent

**Critical constraint:** All `src/gps2asp/suspension/` files must be mirrored to `custom_components/asp_parking/gps2asp/suspension/` (existing vendored-copy sync requirement from v2.0). Do not defer this sync.

**Three new data flow paths added to the coordinator:**
- Path 2: Suspension timer fires → re-apply suspension to cached schedule → notify entities (no GPS re-resolve needed)
- Path 3: Midnight reset → fetch new day's status → conditional full pipeline re-resolve
- Path 4: ha-nyc311 state change event → immediate `apply_suspension()` call (most responsive path)

See `.planning/research/ARCHITECTURE.md` for the full component boundary table, all integration points (A-F), and the ARCHITECTURE.md build order diagram.

### Critical Pitfalls

The five pitfalls most likely to cause silent wrong answers or user-visible failures:

1. **nyc311calendar alpha library breaks silently** — v0.4.1 (December 2022) maps raw API strings to enums in a hardcoded `STATUS_MAP`. If NYC renames `"SUSPENDED"` to `"SUSPENDED - HOLIDAY"`, the mapping silently returns `NO_INFORMATION` (missed suspension) rather than an exception. **Mitigation:** Do not depend on `nyc311calendar`. Call the 311 API directly with `httpx`. Read the library's `services.py` source to extract endpoint URL and response schema without taking a package dependency.

2. **`NOT_IN_EFFECT` (normal Sunday) conflated with `SUSPENDED` (holiday/emergency)** — Both produce "don't move" but for completely different reasons. Conflating them fires suspension notifications on every non-cleaning day. **Mitigation:** Use a typed `SuspensionStatus` model (not `bool`) throughout. The merge layer checks both the block's own schedule for the date and the city-wide suspension independently. Map `NOT_IN_EFFECT` to `is_in_effect=False` but `is_suspended=False`.

3. **Race condition between GPS-triggered schedule update and suspension poll** — A GPS event fires at 06:45, suspension poll fires at 07:00. For 15 minutes, the sensor shows a cleaning window without today's suspension status. **Mitigation:** Compute the merged result lazily in the sensor's `native_value` property, not as a cached merged object in `coordinator.data`. Notify entities immediately when suspension status changes, independent of GPS events. Keep `schedule_result` and `suspension_state` as separate fields in `ASPParkingData`.

4. **Timezone mismatch: HA server in UTC queries wrong date** — The 311 API is date-keyed (`"%Y%m%d"`) with no time component. At 11 PM UTC (7 PM NYC), `datetime.date.today()` on a UTC server returns tomorrow's NYC date. **Mitigation:** Always derive query date from `datetime.now(NYC_TZ).date()`. Never let the poller or any library call `date.today()` implicitly.

5. **Multi-day emergency suspension resumption silently missed** — During a multi-day snow event (e.g., January 2025: 4+ consecutive days), short-circuiting the poll loop because `suspension_state == SUSPENDED` means the resumption of ASP is never detected. Users' cars get ticketed. **Mitigation:** Never skip poll cycles based on current suspension state. The `WEEK_AHEAD` calendar returns all 7 days in a single API call, so checking tomorrow's status costs nothing extra.

See `.planning/research/PITFALLS.md` for the full 12-pitfall catalogue with detection signals, recovery costs, and phase-specific warnings.

---

## Implications for Roadmap

The dependency graph in ARCHITECTURE.md (Phases A-G) maps directly to seven roadmap phases. The ordering is strict: pure library components with no I/O first, network-dependent components second, HA layer last, optional bridge last of all.

### Phase 1: Suspension Package Foundation (SUSP-01)

**Rationale:** Zero external dependencies; unblocks all downstream phases. Holiday calendar alone covers ~43 days/year with no network call — a self-contained, shippable feature. All subsequent suspension work depends on the `SuspensionStatus` model existing here.
**Delivers:** `gps2asp/suspension/` package; `calendar.py` with `is_holiday_suspension(date)` and `get_suspension_reason(date)`; `models.py` with `SuspensionStatus` frozen dataclass and typed `source` literal field; vendored copy synced to `custom_components/asp_parking/gps2asp/suspension/`.
**Addresses:** SUSP-01 (holiday calendar); establishes three-value state model that prevents Pitfall 2.
**Avoids:** Pitfall 10 (year boundary) — return `source="unknown"`, `is_suspended=False` for out-of-range dates; add a build-time assertion that the calendar extends at least 6 months into the future.
**Research flag:** Standard patterns — no phase research needed; all data available from official NYC DOT ICS/PDF.

### Phase 2: Suspension Merge Layer

**Rationale:** Pure function, no I/O, easiest to test in isolation. Must exist before pipeline wiring or coordinator work. Adding `suspension_reason` to `ScheduleFound`/`ASPActiveNow` is a schema change all later phases depend on. Defining all `resolution_reason` states here — before any UI code — prevents post-hoc attribute sprawl.
**Delivers:** `suspension/merge.py` with `apply_suspension(schedule, status) -> ScheduleResult`; `suspension_reason: str | None` field added to `ScheduleFound` and `ASPActiveNow`; all `resolution_reason` state values enumerated and documented.
**Uses:** `SuspensionStatus` model from Phase 1; `dataclasses.replace()` (stdlib).
**Avoids:** Pitfall 2 (NOT_IN_EFFECT vs. SUSPENDED) — merge rules are the canonical definition of this distinction; Pitfall 7 (suspension vs. no-schedule confusion) — `resolution_reason` states designed here with all six values specified before any sensor code is written.
**Research flag:** Standard patterns — pure function over frozen dataclasses; no research needed.

### Phase 3: Pipeline Wiring

**Rationale:** Minimal, additive change to the existing pipeline. One optional parameter on `resolve_asp()`, one call to `apply_suspension()` as Stage 4, one new field on `ASPResult`. Keeps the pipeline interface clean and enables integration testing before any HA work begins.
**Delivers:** `pipeline.py` with optional `suspension_status: SuspensionStatus | None = None` parameter; `api_models.py` `ASPResult.suspension_reason` field; pipeline-level tests with mocked `SuspensionStatus` inputs.
**Implements:** Architecture integration points A and B from ARCHITECTURE.md.
**Avoids:** 311 API call must remain OUT of `resolve_asp()` — the caller (coordinator) owns all network concerns for the suspension data source. Document this boundary explicitly.
**Research flag:** Standard patterns — no research needed.

### Phase 4: Direct 311 API Poller (SUSP-02)

**Rationale:** Network-dependent; isolated from the pipeline so failures cannot cascade. This is where the most defensive code lives. The `nyc311calendar` rejection is implemented here — the thin `httpx` wrapper is written directly against the raw API.
**Delivers:** `suspension/poller.py` with `fetch_suspension_status(date, api_key, session) -> SuspensionStatus`; fail-open on network error; 401 surfaced as a config error (not UNKNOWN); configurable poll interval with 60-minute default and 15-minute floor; vendored copy synced.
**Uses:** `httpx.AsyncClient` (existing); `api.nyc.gov/public/api/GetCalendar`; `SuspensionStatus` model from Phase 1.
**Avoids:** Pitfall 1 (nyc311calendar alpha) — direct `httpx` call eliminates the dependency; Pitfall 5 (NO_INFORMATION = not suspended) — `NO_INFORMATION` maps to `source="unknown"`, `is_suspended=False`; Pitfall 8 (over-polling) — 60-minute default, 15-minute floor, exponential backoff on 429; Pitfall 11 (UTC timezone) — explicit `datetime.now(NYC_TZ).date()` passed in by caller.
**Research flag:** Needs one verification step — before writing the poller, read `nyc311calendar` `services.py` source to confirm exact request headers (`Ocp-Apim-Subscription-Key`), date format (`%m/%d/%Y` in request, `%Y%m%d` in response keys), and the four raw status string values. This is a 10-minute code read, not a research spike.

### Phase 5: HA Coordinator Integration

**Rationale:** The largest single change in v3.0 — wires all library phases into the HA layer. The separate suspension poll timer, eager startup fetch, and lazy-merge decision all live here. Must be complete and stable before sensor/binary_sensor changes.
**Delivers:** `coordinator.py` with `suspended`, `suspension_reason`, `suspension_source`, `last_suspension_check` fields on `ASPParkingData`; separate `async_track_time_interval` for suspension polling (independent of GPS events); eager suspension fetch in `async_start()` before first entity read; `config_flow.py` with optional `CONF_NYC311_API_KEY`.
**Avoids:** Pitfall 3 (race condition) — suspension state is a separate `ASPParkingData` field, not folded into `schedule_result`; lazy merge in sensor property (not coordinator); entities notified immediately when suspension changes; Pitfall 9 (multi-day resumption) — poll loop never short-circuits on current state; Pitfall 12 (HA restart) — eager fetch in `async_start()` before entities report.
**Research flag:** Standard HA patterns — `async_track_time_interval`, `async_start()` sequencing, and `ASPParkingData` extension follow established patterns already in this codebase. No research needed.

### Phase 6: HA Sensor and Binary Sensor Changes

**Rationale:** Terminal UI phase — thin consumer of the suspension data already flowing from Phase 5. Lazy merge implemented here (not in coordinator). All state values and `resolution_reason` codes defined in Phase 2 surface here for the first time in the UI.
**Delivers:** `sensor.py` with `asp_suspended`, `suspension_reason`, `suspension_source`, `resolution_reason` attributes; "Suspended" state text when `suspended=True`; lazy merge at `native_value` read time; `binary_sensor.py` `is_on` returns `isinstance(schedule, ASPActiveNow) and not schedule.suspended`.
**Avoids:** Pitfall 7 (suspension vs. no-schedule confusion) — `resolution_reason` attribute distinguishes all six meaningful states.
**Research flag:** Standard patterns — attribute additions and state logic follow existing sensor patterns in this codebase.

### Phase 7: ha-nyc311 Bridge (SUSP-04, optional)

**Rationale:** Optional optimization — adds no correctness, only eliminates duplicate API polling for users who already have ha-nyc311 installed. Must be implemented only after Phases 1-6 are independently verified working. Can be deferred to v3.1 without any functional loss.
**Delivers:** `suspension_bridge.py` with `read_nyc311_bridge(hass, date) -> SuspensionStatus | None`; bridge detection in `coordinator.async_start()`; `async_track_state_change_event` listener for immediate reaction to ha-nyc311 state changes; optional `CONF_NYC311_ENTITY` in config flow.
**Avoids:** Pitfall 6 (bridge creates hard dependency) — bridge returns `None` when ha-nyc311 absent, falling back to Phase 4 poller transparently; explicit handling for `None`, `"unavailable"`, `"unknown"` sensor states.
**Research flag:** Standard HA patterns — cross-integration state reading via `hass.states.get()` and `async_track_state_change_event` is covered in official HA developer docs. No research spike needed.

### Phase Ordering Rationale

- Phases 1-3 are pure Python with no I/O and can be developed in tight sequence without external blockers; they share no files and can be reviewed independently.
- Phase 4 (network layer) is isolated so that its failure modes and API shape questions do not affect the clean pipeline interface from Phase 3.
- Phase 5 (coordinator) depends on all four prior phases being stable; it is the largest HA change and deserves its own testing cycle.
- Phase 6 is thin and depends only on Phase 5; it should not be merged until Phase 5 is verified end-to-end.
- Phase 7 is fully optional and can be deferred to v3.1 without any user-facing loss of correctness.
- The vendored-copy sync (`custom_components/asp_parking/gps2asp/`) must happen alongside Phases 1-4; do not defer it to a separate phase or it will be skipped.

### Research Flags

Phases needing verification before implementation begins:
- **Phase 4 (311 API Poller):** Read `nyc311calendar/services.py` on GitHub to confirm exact request headers, date format, and the four raw API status strings before writing the poller. This is a 10-minute code read. Estimated confidence after this read: HIGH.

Phases with standard patterns (no research spike needed):
- **Phases 1, 2, 3:** Frozen dataclasses, ICS parsing with `icalendar`, pure function composition — all established patterns with official documentation and existing codebase precedent.
- **Phases 5, 6:** HA coordinator extension, sensor attribute addition, binary sensor state logic — all follow existing patterns already in this codebase (`SpatialIndex.reset()`, `ASPParkingData` field additions, `extra_state_attributes`).
- **Phase 7:** `async_track_state_change_event` bridge — official HA developer docs cover this pattern completely.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Only one new dependency (`icalendar`); rejection of `nyc311calendar` and `aiohttp` is supported by direct PyPI/source inspection. 311 API endpoint and auth scheme confirmed from multiple sources including nyc311calendar source code and NYC API Portal. |
| Features | HIGH | Sourced from official NYC DOT calendar, NYC 311 portal, nyc311calendar library source, ha-nyc311 integration v0.1.5, and live API discovery. Feature list is minimal and grounded in the real suspension domain. |
| Architecture | HIGH | Based on direct code inspection of the existing coordinator, pipeline, schedule models, and binary sensor. The `suspended: bool = False` hook confirmed present on `ScheduleFound` and `ASPActiveNow`. Coordinator tech debt (manual 3-stage call) confirmed and documented as deferred. |
| Pitfalls | HIGH | Each pitfall is sourced from direct code analysis (race condition traced to specific coordinator + sensor code paths), confirmed API behavior (four-value status, timezone absence in nyc311calendar source), or documented NYC ASP patterns (multi-day snow emergency suspensions). Not speculative. |

**Overall confidence:** HIGH

### Gaps to Address

- **311 API response field names:** The endpoint URL (`https://api.nyc.gov/public/api/GetCalendar`), auth header (`Ocp-Apim-Subscription-Key`), and four status strings are confirmed from community sources and nyc311calendar source code. The exact JSON response field names for the date key and service array should be confirmed by reading nyc311calendar `services.py` before Phase 4 implementation. Low friction — 10-minute code read; not a blocking gap.

- **ICS URL exact path:** The URL `https://www.nyc.gov/html/dot/downloads/ics/asp-calendar-YYYY.ics` is inferred from the PDF URL pattern. The ICS availability on the NYC DOT page is confirmed. The exact URL path was not validated by a live download (network restrictions during research). If the URL is incorrect when tested, the hardcoded-dates path works as a fallback with no code change required.

- **NYC 311 API rate limits:** The free "NYC 311 Public Developers" product tier rate limits are not published. The 60-minute default poll interval is a conservative assumption consistent with aspnyc.info's stated hourly polling. The 15-minute floor during the high-alert window should be validated against the actual rate limit before deploying. Low risk given aspnyc.info's confirmed operation without throttling.

- **ha-nyc311 entity name disambiguation:** Entity names like `binary_sensor.nyc311_parking_exception_today` are confirmed from ha-nyc311 GitHub source. Users who have renamed these entities in HA will need to use the `CONF_NYC311_ENTITY` config flow option (Phase 7) to specify the entity manually. Document this case in the integration README.

---

## Sources

### Primary (HIGH confidence)
- NYC DOT ASP Suspension Calendar: `https://www.nyc.gov/html/dot/html/motorist/alternate-side-parking.shtml` — ICS file availability, suspension types, 2026 calendar dates confirmed
- NYC DOT 2026 ASP Calendar PDF: `https://www.nyc.gov/html/dot/downloads/pdf/asp-calendar-2026.pdf` — 43 suspension dates, holiday type classification (legal vs. religious)
- NYC API Portal: `https://api-portal.nyc.gov/` — 311 API free key registration, "NYC 311 Public Developers" product confirmed
- ha-nyc311 GitHub (elahd/ha-nyc311) v0.1.5 — entity naming pattern, binary sensor attributes, integration design, aiohttp/nyc311calendar internal dependency
- nyc311calendar GitHub (elahd/nyc311calendar) v0.4.1 — NYC 311 API endpoint, request/response format, four status strings, alpha warning ("Expect breaking changes"), aiohttp dependency, last commit 2022
- icalendar on PyPI — v6.1.0+, actively maintained, RFC 5545 compliant, pure Python, no compiled extensions
- HA Developer Docs (Listening for Events) — `async_track_state_change_event` is the recommended pattern for cross-integration state reading
- Existing codebase: `coordinator.py`, `pipeline.py`, `schedule/models.py`, `binary_sensor.py`, `sensor.py` — direct code inspection confirming `suspended: bool = False` hooks, coordinator 3-stage manual call, `ASPParkingData` fields

### Secondary (MEDIUM confidence)
- aspnyc.info (unofficial 311 API consumer) — confirms hourly polling cadence, status format, `IN_EFFECT`/`SUSPENDED`/`NOT_IN_EFFECT`/`NO_INFO` values
- NYC Open Data community (DOT-Data-Feeds Issue #1) — `api.cityofnewyork.us/311/v1/municipalservices` older endpoint; documented as emergency fallback only
- @NYCASP official X account — confirms same-day and 1-day-advance suspension announcement timing patterns

### Tertiary (LOW confidence)
- NYC DOT ICS URL pattern — inferred from PDF URL pattern; not validated by live download; hardcoded-dates path is a complete fallback

---
*Research completed: 2026-03-31*
*Ready for roadmap: yes*
