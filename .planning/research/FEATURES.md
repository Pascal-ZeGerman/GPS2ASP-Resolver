# Feature Landscape: ASP Suspension Handling

**Domain:** NYC Alternate Side Parking suspension awareness — holiday calendar, weather/emergency polling, schedule merge, HA integration
**Milestone:** v3.0 Suspension Handling
**Researched:** 2026-03-30
**Confidence:** HIGH (sourced from official NYC DOT, NYC 311 portal, ha-nyc311 integration, nyc311calendar library, live API discovery)

---

## Context: What Is Already Built

This is a subsequent milestone for a fully operational system. The existing pipeline resolves GPS to schedule and exposes "next time to move" as an HA sensor. Suspension handling is additive — it layers a new signal (is ASP suspended today?) on top of the existing schedule signal (when is the next cleaning window?).

**Existing pipeline (v2.0 operational):**
- `resolve_asp(lat, lon)` → `ASPResult` — full GPS-to-schedule pipeline, public API
- `CleaningSchedule` + `next_cleaning_window()` — schedule data model and next-window computation
- `ASPNextMoveTimeSensor` — HA sensor exposing datetime value + schedule attributes
- `soda_level` attribute (1-4) — observability for which fallback level resolved the data
- Structured `l4_event=` logging — grep-friendly failure diagnosis

**What is missing for v3.0:**
- No awareness of whether ASP is currently suspended
- Sensor shows a "next move" datetime even on days when the user does not need to move at all
- No distinction between "move required tomorrow" vs "suspended tomorrow — you're fine"

---

## Suspension Domain: How It Actually Works

### Two Distinct Suspension Types

NYC operates two fundamentally different types of ASP suspension:

**Type 1: Holiday Suspensions (Pre-scheduled)**
- Announced annually by NYC DOT, published as a PDF calendar and ICS file at the start of each year
- The 2026 calendar has 43 suspension dates across legal and religious holidays
- Importable into Google Calendar / Outlook via ICS at `https://www.nyc.gov/html/dot/html/motorist/disclaimer.shtml`
- Two sub-tiers within holiday suspensions:
  - **Major legal holidays** (e.g., Christmas, Thanksgiving, New Year's Day, Labor Day): All parking rules suspended, including No Standing/No Stopping restrictions. Meters also suspended.
  - **Religious/other holidays** (e.g., Rosh Hashanah, Yom Kippur, Diwali, Lunar New Year, Eid): Street cleaning rules only suspended. All other parking restrictions remain in effect.
- Example 2026 dates: Three Kings Day (Jan 6), MLK Day (Jan 19), Lincoln's Birthday (Feb 12), Presidents Day (Feb 16), Lunar New Year (Feb 17), Ash Wednesday (Feb 18), Good Friday (Apr 3), Passover (Apr 8-9), Labor Day (Sep 7), Rosh Hashanah (Sep 12-13), Yom Kippur (Sep 22), Diwali (Oct 20), Thanksgiving (Nov 26), Christmas (Dec 25), and ~30 more.

**Type 2: Weather/Emergency Suspensions (Dynamic)**
- Announced with minimal advance notice — typically same-day or one day ahead
- Decision made late in the day because weather patterns change fast (NYC DOT's own words)
- Triggered by snow storms, nor'easters, declared emergencies
- Can last multiple consecutive days (e.g., "suspended through Sunday to facilitate snow operations")
- Source of truth: NYC 311 API (real-time), @NYCASP on Twitter/X (simultaneous announcements)
- No way to predict; must poll for updates

### What a Suspension Means for Users

During any suspension (holiday or weather): the user does NOT need to move their legally parked car to comply with street cleaning windows. The suspension does not cancel tickets for other violations (hydrant, expired meter on non-legal-holiday, etc.).

The primary user value of suspension awareness: avoid unnecessary moves. Moving a car when ASP is suspended wastes time and loses a parking spot. NYC drivers who check status frequently make this trade-off wrong.

---

## Table Stakes

Features users expect from a suspension-aware parking sensor. Missing any of these makes the feature feel incomplete or worse than checking manually.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Holiday suspension calendar embedded | All 43 annual holidays are known in advance; a sensor that ignores them gives wrong "move required" answers on ~43 days per year | LOW | Hard-coded or parsed-from-ICS annually; no API call required. NYC DOT publishes the full year calendar in January. The 2026 ICS is available for download and can be parsed with Python's `icalendar` library. |
| Weather/emergency suspension polling | The most common suspension scenario (snow); without it the sensor is wrong during every storm | MEDIUM | Requires polling the NYC 311 Calendar API (`api-portal.nyc.gov/nyc-311-public-api`). API key required (free registration). Returns today/tomorrow/next-7-days suspension status per service type (Parking, Schools, Sanitation). |
| Merged authoritative answer on the sensor | The sensor's core value is "do I need to move?" — if suspension is separate from schedule, users must mentally combine two signals | MEDIUM | When suspended, the sensor state should reflect that the next cleaning window does not require action. The datetime value should either be suppressed (None) or the attribute should carry `is_suspended: True`. |
| Today/tomorrow suspension visibility | Users plan ahead — "will I need to move tomorrow?" is as important as "today?" | LOW | The 311 Calendar API returns week-ahead status. Holiday calendar trivially supports N-day lookahead. Both signals should expose at minimum today + tomorrow. |

---

## Differentiators

Features that go beyond the baseline and make this sensor meaningfully better than checking the @NYCASP Twitter account manually.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Bridge with ha-nyc311 integration | ha-nyc311 (HACS, elahd) already exposes `binary_sensor.nyc311_parking_today` and related entities — reading their state avoids GPS2ASP needing its own 311 API key or polling loop | LOW-MEDIUM | ha-nyc311 uses the same NYC 311 Calendar API. If the user has it installed, GPS2ASP can read `binary_sensor.nyc311_parking_today` via `hass.states.get()`. Eliminates duplicate API calls and key management. Requires fallback path when ha-nyc311 is not installed. |
| Suspension reason in attributes | Knowing WHY ASP is suspended (holiday name vs "snow emergency") helps users decide if they actually need to follow other rules (meters, No Standing) | LOW | The 311 Calendar API returns a reason string (e.g., "New Year's Day", "Snow Emergency"). Holiday calendar entries carry the holiday name. Expose as `suspension_reason: str` attribute on the sensor. |
| Suspension type differentiation | Major legal holidays suspend more than just cleaning rules; the sensor should reflect this distinction | LOW | Add a `suspension_type` attribute: `"none"` / `"street_cleaning_only"` / `"all_parking_rules"`. Major legal holidays map to `all_parking_rules`; religious/other holidays map to `street_cleaning_only`. Weather/emergency maps to `street_cleaning_only`. |
| HA calendar entity for suspension schedule | Users can visualize upcoming suspensions in the HA calendar dashboard alongside other home events | MEDIUM | ha-nyc311 already creates a calendar entity. If bridging with ha-nyc311, GPS2ASP does not need to recreate this. If implementing standalone, the HA `CalendarEntity` interface is standard. |

---

## Anti-Features

Features that seem helpful but should not be built for v3.0.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Real-time suspension push notifications | Users want "tell me when ASP is suspended" — but HA already has robust notification and automation support | Expose a clean `is_suspended` binary sensor attribute or entity. Let users build their own automations using HA's native notification actions (NOTIF-01/02 is already planned for a later milestone). |
| Predicting weather suspensions in advance | No public data supports this — the city itself can't predict storm suspensions more than 12-24 hours ahead | Poll the official 311 API on schedule. Any prediction logic is false confidence. |
| Scraping @NYCASP Twitter/X | Unofficial, fragile, rate-limited, authentication nightmare in 2025+ | Use the official NYC 311 Calendar API. It receives the same suspension announcements and is stable. |
| Building a custom holiday table from scratch | Maintaining a hand-curated list is error-prone; holidays change (new observances added) | Parse the official NYC DOT ICS file annually. Alternatively, the 311 Calendar API includes holiday suspensions in its response, making the ICS parsing redundant if using the API. |
| Integrating OpenCurb API | Only covers Midtown Manhattan; explicitly out of scope per PROJECT.md | N/A — already rejected in v1.0 decisions |
| Polling 311 API more than once per hour | Weather suspensions are announced as discrete events, not continuously updated; over-polling wastes API quota and adds no value | Poll every 30-60 minutes during the 4-8am window when suspensions are typically announced; hourly otherwise. |
| Separate suspension binary_sensor entity (standalone) | Adds an entity the user must manage if ha-nyc311 is NOT installed — but ha-nyc311 already does this correctly | If ha-nyc311 is present, read its entities. If absent, expose `is_suspended` only as an attribute on the existing `ASPNextMoveTimeSensor`. A new standalone binary_sensor entity is unnecessary complexity unless user explicitly requests it. |

---

## Feature Dependencies

```
[Holiday calendar (SUSP-01)]
    └──independent of──> [Weather polling (SUSP-02)]
    └──both required for──> [Merge with schedule (SUSP-03)]
                                └──drives──> [HA sensor state change]
                                └──feeds──> [Bridge with ha-nyc311 (SUSP-04)]

[SUSP-04: Bridge with ha-nyc311]
    └──reads from──> [binary_sensor.nyc311_parking_today (ha-nyc311)]
                         └──requires──> [ha-nyc311 installed + configured]
    └──fallback to──> [SUSP-02 standalone 311 polling if ha-nyc311 absent]

[SUSP-02: Weather polling]
    └──requires──> [NYC API Portal API key (free, user-provided in config_flow)]
    └──optional──> [if SUSP-04 bridge is active, polling may be skipped]

[SUSP-03: Merge suspension with schedule]
    └──depends on──> [SUSP-01 holiday calendar: is_holiday_suspension(date) -> bool]
    └──depends on──> [SUSP-02 OR SUSP-04: is_weather_suspended_today() -> bool]
    └──modifies──> [CleaningSchedule.next_cleaning_window() output interpretation]
    └──exposes via──> [ASPNextMoveTimeSensor extra_state_attributes]
```

### Dependency Notes

- **Holiday calendar is standalone:** A Python dict or frozen dataclass mapping dates to holiday names can be computed from the ICS file at build time and shipped as data. No runtime API call required. This is the simplest piece and should ship first.

- **Weather polling requires API key:** The NYC 311 Calendar API (`api-portal.nyc.gov`) requires a free API key. The key must be exposed in the HA config_flow UI for user entry. The nyc311calendar library (PyPI: `nyc311calendar`, GitHub: `elahd/nyc311calendar`) wraps this API and is already used by ha-nyc311. GPS2ASP could use it directly or read ha-nyc311's entities to avoid duplicate key management.

- **SUSP-04 bridge is the lowest-friction path:** If the user has ha-nyc311 installed, GPS2ASP can read `binary_sensor.nyc311_parking_today` and `binary_sensor.nyc311_parking_tomorrow` without needing its own API key or polling logic. This is the recommended primary path. Standalone 311 polling (SUSP-02) is the fallback for users without ha-nyc311.

- **Merge does not require schedule recomputation:** Suspension is a post-processing step applied to the existing `ASPResult`. When suspended, the effective "next move time" is the next non-suspended cleaning window. The existing `next_cleaning_window()` logic doesn't change — the suspension layer filters its output.

- **COV-03 (coordinator migration) remains deferred:** Suspension state can be injected into `ASPParkingData` the same way `soda_level` was — as an additional field, populated in `_async_resolve_pipeline()` — without migrating the coordinator to use `resolve_asp()`.

---

## What Users Expect From a Suspension-Aware Sensor

Based on user behavior research and the NYC parking experience:

1. **"Do I need to move today?"** — The primary daily question. Sensor state should answer this directly. If suspended, the answer is "no" — the datetime should reflect the next non-suspended window.

2. **"Do I need to move tomorrow?"** — Users check the night before and in the morning. Tomorrow's suspension status is as important as today's.

3. **"Why is it suspended?"** — Secondary, but users want to know if it's a snow emergency vs a holiday. Helps them decide about meters and No Standing restrictions.

4. **No false alarms.** — Showing a "move at 11am" notification on Rosh Hashanah is worse than showing nothing. Precision matters more than recall here.

5. **No unnecessary moves on suspended days.** — The core anti-pattern this feature eliminates. NYC drivers who don't check status lose parking spots by moving when they don't have to.

6. **Automation-friendly attributes.** — Users want to build HA automations: "notify me the night before if ASP is in effect tomorrow." The sensor should expose structured attributes (`is_suspended`, `suspension_reason`, `next_non_suspended_window`) that automation templates can consume.

---

## MVP Definition for v3.0

### Launch With (v3.0)

- [ ] **SUSP-01: Holiday calendar** — Parse or hard-code 2026 NYC DOT ICS data; `is_holiday_suspended(date) -> bool`; include holiday name + type (legal/religious) for the `suspension_reason` attribute
- [ ] **SUSP-02: Weather/emergency polling** — Poll NYC 311 Calendar API (or read ha-nyc311 entities if present) for today/tomorrow suspension status; 30-60 min polling during morning window
- [ ] **SUSP-03: Merge with schedule** — Post-process `ASPResult`: when suspended, set `next_move_time` to the next non-suspended window (or `None` if no non-suspended windows in the lookahead); add `is_suspended: bool`, `suspension_reason: str | None`, `suspension_type: str` to `extra_state_attributes`
- [ ] **SUSP-04: Bridge with ha-nyc311** — Read `binary_sensor.nyc311_parking_today` / `_tomorrow` from ha-nyc311 if installed; fall back to direct 311 polling if not

### Add After Validation (v3.x)

- [ ] **NOTIF-01: HA actionable notification** — "Move your car by 11am tomorrow (ASP in effect)" push notification with configurable lead time; requires stable suspension-aware schedule first
- [ ] **NOTIF-02: Automation-ready structured output** — Expose structured attributes sufficient for user-authored HA automations
- [ ] **COV-03: Coordinator migration to `resolve_asp()`** — Tech debt from v2.0; suspension logic is a cleaner fit after this migration

### Out of Scope for v3.0

- Multi-year holiday calendar automation — annual ICS re-import is acceptable; auto-fetching next year's calendar is not worth the complexity
- Suspension prediction beyond official announcements — no data supports it
- Standalone binary_sensor entity for suspension — `is_suspended` attribute on existing sensor is sufficient
- Emergency parking rule changes other than ASP suspension (e.g., snow emergency routes) — separate domain

---

## Complexity Assessment by Feature

| Feature | Implementation Complexity | Integration Complexity | Risk |
|---------|--------------------------|----------------------|------|
| SUSP-01: Holiday calendar | LOW — parse ICS or hard-code dict; ~50-100 lines | LOW — standalone function, no external calls | LOW — data is stable, annual update only |
| SUSP-02: 311 API polling | MEDIUM — async httpx call, API key in config_flow, response parsing, error handling | MEDIUM — new async update loop in coordinator | MEDIUM — API key registration barrier for users; API reliability |
| SUSP-03: Merge with schedule | MEDIUM — post-process ASPResult; handle edge cases (all windows suspended, suspension spanning midnight) | LOW — modifies existing sensor attribute output | LOW — logic is deterministic given suspension status |
| SUSP-04: ha-nyc311 bridge | LOW-MEDIUM — `hass.states.get()` to read entity state; state parsing | LOW — reads HA state, no external calls | LOW — graceful if ha-nyc311 absent; entity names are stable |

---

## Sources

- [NYC DOT Alternate Side Parking Suspensions](https://www.nyc.gov/html/dot/html/motorist/alternate-side-parking.shtml) — Official suspension types, holiday list, announcement timing (HIGH confidence)
- [NYC 311 Portal: ASP Article](https://portal.311.nyc.gov/article/?kanumber=KA-01011) — How suspensions are communicated, official channels (HIGH confidence)
- [NYC DOT 2026 ASP Calendar PDF](https://www.nyc.gov/html/dot/downloads/pdf/asp-calendar-2026.pdf) — 43 suspension dates for 2026 (HIGH confidence)
- [NYC DOT Calendar File Download](https://www.nyc.gov/html/dot/html/motorist/disclaimer.shtml) — ICS file for programmatic access (HIGH confidence)
- [ha-nyc311 GitHub (elahd)](https://github.com/elahd/ha-nyc311) — HA integration design, entity structure, binary_sensor names, API key requirements (HIGH confidence)
- [nyc311calendar PyPI](https://pypi.org/project/nyc311calendar/) — Python library wrapping NYC 311 Calendar API; `CalendarDayEntry`, `ServiceType.PARKING`, `StandardizedStatusTypes` (MEDIUM confidence — PyPI page did not render, inferred from ha-nyc311 README and packagegalaxy.com datasheet)
- [DOT-Data-Feeds Issue #1](https://github.com/CityOfNewYork/DOT-Data-Feeds/issues/1) — `api.cityofnewyork.us/311/v1/municipalservices` endpoint structure; `status: "IN EFFECT"` vs suspended format (MEDIUM confidence — issue thread, not official docs)
- [aspnyc.info](https://www.aspnyc.info/) — Confirms hourly polling of 311 API for real-time status including weather emergencies (MEDIUM confidence — third-party site)
- [@NYCASP on X](https://x.com/NYCASP/status/2026020592281964713) — Weather suspension timing examples: same-day and 1-day advance notice (HIGH confidence — official city account)
- [NYC API Portal](https://api-portal.nyc.gov/) — Free API key requirement for 311 Calendar API (HIGH confidence)

---
*Feature research for: GPS2ASP Resolver v3.0 — ASP Suspension Handling*
*Researched: 2026-03-30*
