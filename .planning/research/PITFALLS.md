# Domain Pitfalls: Suspension Handling

**Domain:** Adding ASP suspension handling to an existing GPS-to-schedule system (v3.0 milestone)
**Researched:** 2026-03-30
**Confidence:** HIGH — based on direct code inspection of the live coordinator, schedule models, and HA integration; nyc311calendar source analysis; research into NYC 311 API behavior; and analysis of the two distinct suspension data paths (holiday calendar vs. emergency API).

---

## Critical Pitfalls

### Pitfall 1: nyc311calendar is Alpha — API can break with no warning

**What goes wrong:**
`nyc311calendar` v0.4.1 (last released December 2022) self-identifies as alpha software. The README explicitly states "This is an alpha release. Expect breaking changes." The library wraps the NYC `https://api.nyc.gov/public/api/GetCalendar` endpoint, which is an Azure API Management gateway. If the upstream NYC API changes its response format, status strings, or authentication scheme, the library's `STATUS_MAP` hardcoded mappings silently produce wrong results — not an exception, a wrong answer.

The raw API status strings are things like `"IN EFFECT"`, `"NOT IN EFFECT"`, `"SUSPENDED"`, `"NO INFORMATION"`. These are mapped by `services.py` hardcoded dictionaries. A NYC API update that renames `"SUSPENDED"` to `"SUSPENDED - HOLIDAY"` would cause that day to fall into the `"NO INFORMATION"` bucket instead of `StandardizedStatusType.SUSPENDED`, meaning a holiday suspension is silently missed.

**Why it happens:**
The library is maintained by a single developer with no SLA commitment to the nyc.gov API. The last commit was 2022. NYC's public API has no published stability guarantee for response string values. The library's mapping approach requires manual updates any time the upstream strings change.

**Consequences:**
- A holiday suspension is missed: sensor shows "move your car" on a day when ASP is suspended. User moves unnecessarily, or worse, stays put on a day that is NOT suspended because they trusted a stale "suspended" state.
- A normal active day returns `"NO INFORMATION"` from the API (common for far-future dates): library produces a state that looks like a valid suspension, causing a false "suspended today" result.

**Prevention:**
1. Treat `nyc311calendar` as a best-effort layer, not ground truth. The holiday suspension calendar (known dates) should be implemented independently as a hardcoded data set derived from the official NYC DOT PDF calendar (published annually at `nyc.gov/html/dot/downloads/pdf/asp-calendar-YYYY.pdf`). This removes dependency on the API for the common case.
2. For the API-driven emergency path, treat `StandardizedStatusType.NO_INFORMATION` as "unknown, do not suppress schedule" rather than "not suspended." Log it prominently.
3. Add a version-pinned dependency on `nyc311calendar` and a test that asserts the status constants have expected string values — a canary that fires if the library's internals change.
4. Document the alpha risk explicitly in the integration README so users understand the "use at your own risk" proviso.

**Detection:**
- Suspension sensor shows "suspended" on a day when street cleaning is visibly happening
- `"NO INFORMATION"` appears in logs for today's date (valid for future dates, suspicious for today)
- Any exception from `nyc311calendar` during `get_calendar()` propagates as an unhandled error

**Phase to address:** Holiday calendar phase (SUSP-01) should be independent of nyc311calendar. Emergency polling phase (SUSP-02) should isolate all nyc311calendar calls behind a defensive wrapper that catches all exceptions and returns a typed "unknown" result.

---

### Pitfall 2: "NOT IN EFFECT" ≠ "SUSPENDED" — two distinct API states conflated as one

**What goes wrong:**
The NYC 311 API returns four distinct parking status strings. Two of them look like "not suspended" to a naïve implementer but have different meanings:

| Raw API string | nyc311calendar type | Semantic meaning |
|---|---|---|
| `"IN EFFECT"` | `NORMAL_ACTIVE` | ASP is active today — car must move |
| `"NOT IN EFFECT"` | `NORMAL_SUSPENDED` | Regular non-cleaning day (Sunday, or a day without a cleaning schedule) |
| `"SUSPENDED"` | `SUSPENDED` | Holiday or emergency suspension of an otherwise active day |
| `"NO INFORMATION"` | `NO_INFORMATION` | API has no data for this date |

The critical confusion: `"NOT IN EFFECT"` is not a suspension. It is a normal state for days that never had ASP. If you merge `NORMAL_SUSPENDED` and `SUSPENDED` into a single "is_suspended" boolean, you lose the ability to distinguish "today has no ASP because it's Sunday" from "today has no ASP because of a holiday suspension."

This matters for the merge layer (SUSP-03): if the block's schedule has no cleaning on Sundays and today is a holiday-suspended Monday, both "no Sunday cleaning" and "Monday holiday suspension" would produce a suppressed next-window result. The sensor attribute needs to correctly report the reason.

**Why it happens:**
Both states result in "don't move your car" — the distinction feels academic. But for user-facing messaging ("No ASP today — Holiday" vs "No ASP today — Not a cleaning day") and for notification logic (should the user be notified of a holiday suspension even if they have no cleaning that day anyway?), the distinction matters.

**Consequences:**
- User sees "ASP suspended" on a Sunday that was never a cleaning day. Confusing and misleading.
- Automation triggers "suspension detected" notification on normal non-cleaning days.

**Prevention:**
Represent suspension state as an enum with at least three values: `ACTIVE`, `SUSPENDED_HOLIDAY`, `NOT_A_CLEANING_DAY`. Do not collapse `NORMAL_SUSPENDED` and `SUSPENDED` into a single boolean. The merge layer must check both the block's schedule for today and the suspension state independently.

**Detection:**
- Suspension sensor is ON on Sundays or other non-cleaning days for that block
- Automation that fires "suspension detected" fires multiple times per week on normal non-cleaning days

**Phase to address:** SUSP-03 (merge layer). Must be designed with three-value state, not boolean, from the start.

---

### Pitfall 3: Race condition between GPS-triggered schedule update and suspension poll

**What goes wrong:**
The existing coordinator is event-driven: a GPS state change triggers `_async_resolve_pipeline()`, which updates `ASPParkingData.schedule_result`. Suspension status is polled separately on a different timer. Between the GPS-triggered update and the suspension poll completing, `coordinator.data` contains a new schedule but stale suspension state.

If the schedule update runs at 06:45 and the suspension poll runs at 07:00, there is a 15-minute window where the sensor shows the next cleaning window without reflecting today's suspension. If the user happens to check HA in that window on a holiday morning, they see "move your car at 8:00 AM" when in fact ASP is suspended.

The inverse is also possible: a suspension becomes active (emergency declared at 23:55) but the next schedule refresh hasn't run. The schedule still shows tomorrow's window as active.

**Why it happens:**
Two independent data sources with different trigger mechanisms (event-driven GPS vs. time-driven suspension poll) are read and merged only when both are in `coordinator.data`. There is no synchronization point ensuring both are fresh before the merged result is computed.

**Consequences:**
- Transient sensor state that incorrectly shows a cleaning window during a suspension, or vice versa.
- HA automations triggered on stale merged state.

**Prevention:**
1. Re-compute the merged result (`schedule + suspension`) lazily at read time (in the sensor's `native_value` property) rather than eagerly caching a merged object in `coordinator.data`. This way, both `schedule_result` and `suspension_state` are always read from their current values at the moment the sensor is evaluated.
2. When the suspension state changes, call `_async_notify_entities()` immediately — do not wait for the next GPS update.
3. Keep suspension state as a separate field in `ASPParkingData` rather than folding it into `schedule_result`, so the two can be updated independently without invalidating each other.

**Detection:**
- Sensor shows a cleaning window for ~10-15 minutes at the start of a holiday before showing "suspended"
- HA logbook shows `next_move_time` changing from a valid datetime to unavailable without a GPS event

**Phase to address:** SUSP-03. Lazy merge in the sensor property is the safest design. Phase plan should explicitly address the synchronization model.

---

### Pitfall 4: Timezone edge case — suspension announced at 11:55 PM for "today"

**What goes wrong:**
The NYC 311 API returns suspension status keyed by date in `"%Y%m%d"` format with no time component. When `nyc311calendar` queries `WEEK_AHEAD`, it returns yesterday through 6 days ahead. The API has no notion of "this afternoon" vs "tonight" — a suspension that covers December 29 covers midnight-to-midnight in NYC time.

The edge case: it is 11:55 PM on December 28 (America/New_York). NYC announces an emergency ASP suspension for December 29, effective midnight. The 311 API updates its response for December 29. The suspension poll happens at midnight December 29 (i.e., just after the boundary). The query returns `"SUSPENDED"` for December 29.

But the `find_next_window()` call in `next_move.py` computed its result for December 29 at the previous schedule refresh, which ran at 11:00 PM before the suspension was announced. The cached schedule result still shows a cleaning window at 8:30 AM on December 29. The merged result won't update until either the next GPS update (car hasn't moved) or the periodic refresh (configured for every N hours).

**Why it happens:**
`find_next_window()` is called at pipeline execution time and returns an absolute datetime, not a live computation. The schedule result is cached in `ASPParkingData.schedule_result`. Unless the periodic refresh fires or GPS moves, the stale schedule result persists indefinitely.

**Consequences:**
- At 6 AM on a holiday, user gets a notification "move your car at 8:30 AM" when ASP is actually suspended.
- User moves the car unnecessarily or — more concerning — ignores the notification assuming it's working correctly.

**Prevention:**
1. Re-evaluate `find_next_window()` lazily in the sensor property using `datetime.now(NYC_TZ)` rather than relying on a cached `start_datetime` from a previous pipeline run. The schedule (which days/times) rarely changes; only the "next occurrence" needs to be recomputed at read time.
2. Set the suspension poll interval to at most 1 hour during known evening hours (8 PM–midnight NYC) when emergency suspensions are most commonly announced. Hourly polling during that window is low cost and catches overnight announcements.
3. When the suspension state changes from "unknown/not suspended" to "suspended," immediately re-notify entities regardless of GPS or timer state.

**Detection:**
- Sensor shows a cleaning window after 11 PM on an evening when a suspension is later announced
- `coordinator.data.last_resolved` timestamp is several hours old when the suspension was just posted

**Phase to address:** SUSP-02 (emergency polling) and SUSP-03 (merge layer). The periodic refresh interval and the suspension poll interval need to be coordinated.

---

### Pitfall 5: Suspension polling treats "no data" and "not suspended" as equivalent

**What goes wrong:**
The nyc311calendar API returns `"NO INFORMATION"` for dates far in the future (beyond a few days) or when the NYC API is temporarily down. This maps to `StandardizedStatusType.NO_INFORMATION`. If the suspension check interprets this as `is_suspended=False`, a temporary API outage causes the sensor to confidently show upcoming cleaning windows even when it cannot actually confirm suspension status.

For holiday suspensions, this is especially dangerous: on December 24 at 11 PM, if the API returns `"NO INFORMATION"` for December 25 (Christmas) due to a transient outage, the sensor shows "move your car at 8:30 AM on December 25" when ASP is suspended.

**Why it happens:**
Three-value API outputs get mapped to a boolean (`is_suspended: bool`). `NO_INFORMATION` → `False` is the obvious default but semantically wrong.

**Consequences:**
- User receives move notification on a holiday due to transient API outage.
- Worse: if combined with Pitfall 1 (alpha library silently returns wrong type), the outage path is never tested.

**Prevention:**
Represent suspension state as a three-value type: `SuspensionState.ACTIVE | SUSPENDED | UNKNOWN`. Treat `UNKNOWN` as "do not suppress cleaning window" (conservative — user still moves, which is safer than missing a cleaning) but surface the `UNKNOWN` state in the sensor attributes so the user knows the data source was unavailable. Never conflate `UNKNOWN` and `ACTIVE`.

For known holiday dates from the hardcoded calendar (SUSP-01), the hardcoded calendar should override the API. On Christmas, the hardcoded calendar says "suspended" regardless of what the API returns.

**Detection:**
- API outage test: mock `nyc311calendar` to raise `aiohttp.ClientError`; assert `suspension_state` becomes `UNKNOWN`, not `ACTIVE`
- Suspension sensor shows `is_on=False` (not suspended) when API is down, with no indication of uncertainty

**Phase to address:** SUSP-02. The defensive wrapper around nyc311calendar must return a typed `SuspensionState` enum, never a raw boolean.

---

## Moderate Pitfalls

### Pitfall 6: ha-nyc311 bridge creates a second source of truth

**What goes wrong:**
The v3.0 milestone includes bridging with the `ha-nyc311` integration (SUSP-04). `ha-nyc311` exposes its own suspension binary sensors via the `nyc311calendar` library. If this bridge is implemented as "read ha-nyc311 sensor state from `hass.states.get()`," the `asp_parking` integration now depends on another integration being installed, configured, and healthy.

If `ha-nyc311` is not installed, or its API key expires, or it restarts while `asp_parking` is running, `hass.states.get()` returns `None` or `"unavailable"`. If this is not handled defensively, `asp_parking` silently falls back to treating "suspended" as `False`.

There are also two distinct sources computing suspension for the same date: the internal nyc311calendar call in `asp_parking` and the `ha-nyc311` sensor state. If they disagree (due to polling timing differences), the user sees inconsistent sensor states.

**Prevention:**
Design SUSP-04 as an optional bridge, not a dependency. `asp_parking` should have its own suspension logic (SUSP-01 + SUSP-02) that works without `ha-nyc311`. SUSP-04 should be an optional "use ha-nyc311 if present" layer that feeds INTO the `asp_parking` suspension state as one of several inputs, with the hardcoded calendar taking precedence.

Use `hass.states.get()` only as a supplementary signal, with explicit handling for `None`, `"unavailable"`, and `"unknown"` states.

**Detection:**
- `asp_parking` suspension sensor shows different state than `ha-nyc311` sensors for the same day
- `asp_parking` suspension sensor shows `is_on=False` immediately after `ha-nyc311` config entry is reloaded

**Phase to address:** SUSP-04 must be scoped as an optional enhancement only after SUSP-01 and SUSP-02 are independently functional.

---

### Pitfall 7: User confusion — "suspended" vs. "no schedule on this block"

**What goes wrong:**
The existing system already has a meaningful semantic gap between `NoMatchFound` (SODA has no data for this block, we don't know if there's ASP) and `NoASPSigns` (SODA confirmed no broom signs, this block has no ASP). Adding suspension on top creates a third state: "there is ASP on this block, but it's suspended today."

If all three states produce the same `is_on=False` for the binary sensor and `native_value=None` for the schedule sensor, the user cannot distinguish:
1. "Car is on a block with no ASP schedule" → nothing to do, ever
2. "Block has ASP but SODA data is unavailable" → unknown, might need to move
3. "Block has ASP, it would be active today, but it's suspended" → confirmed no need to move today

States 1 and 3 both result in "no move needed" but for completely different reasons. State 2 is the dangerous unknown.

**Prevention:**
Add a `resolution_reason` attribute to the sensor that distinguishes these states explicitly:
- `"no_asp_on_block"` — `NoASPSigns` result
- `"no_data_for_block"` — `NoMatchFound` result
- `"suspended_holiday"` — schedule active but today is a holiday suspension
- `"suspended_emergency"` — schedule active but emergency suspension declared
- `"active"` — schedule found, no suspension
- `"outside_coverage"` or `"no_street_match"` — existing special states

Users and automations can key off this attribute to handle each case distinctly.

**Detection:**
- User asks "is ASP suspended today?" and cannot tell from the sensor whether it's a suspension or just no schedule
- Automation logic uses only `binary_sensor.active_now` and misses suspension state entirely

**Phase to address:** SUSP-03. The merge layer is the right place to emit this reason code. Plan must define all states before implementation.

---

### Pitfall 8: Polling interval too aggressive causes NYC API throttling or key revocation

**What goes wrong:**
The NYC 311 API (`api.nyc.gov/public/api/GetCalendar`) is an Azure API Management endpoint that requires a developer API key. The terms for the "NYC 311 Public Developers" product include rate limits that are not published. Polling every minute for suspension status would likely trigger throttling. More importantly: the data updates at most once or twice per day — there is no benefit to polling more than once per hour.

If the polling interval is set too low (e.g., "check suspension every 5 minutes"), the integration may exhaust the free rate limit, receive HTTP 429 errors, and then fail open (treating the error as "not suspended").

**Prevention:**
Default suspension poll interval to 60 minutes. Increase to 15 minutes only during a configurable "high alert window" (e.g., 8 PM–midnight NYC time, when emergency suspensions are most commonly announced). Never poll more than once per 15 minutes. Expose the poll interval as a config option with a minimum floor.

Treat HTTP 429 as a `UNKNOWN` suspension state, not `ACTIVE`. Back off exponentially on repeated 429s.

**Detection:**
- HA logs show HTTP 429 responses from `api.nyc.gov` repeatedly
- nyc311calendar throws `aiohttp.ClientResponseError` with status 429

**Phase to address:** SUSP-02. Poll interval must be configurable from day one; hardcoded 60-minute default.

---

### Pitfall 9: Multi-day emergency suspensions not re-checked during extended suspension

**What goes wrong:**
During major snow events, NYC can suspend ASP for 4-7 consecutive days (e.g., January 2025: 4 consecutive days). When the suspension ends, the API changes from `"SUSPENDED"` to `"IN EFFECT"`. If the suspension poll logic caches "suspended" and skips polling while `suspension_state == SUSPENDED`, the resumption of ASP is missed.

Users see "suspended" for two days after ASP resumes. Cars that needed to move for street cleaning are ticketed.

**Why it happens:**
A naïve optimization: "if already suspended, don't bother polling for updates." This is wrong because the suspension end date is not known in advance — the city announces it day by day.

**Prevention:**
Never skip a poll cycle because the current state is already "suspended." Always poll on the configured interval regardless of current state. The `WEEK_AHEAD` calendar type already returns the full next-7-day picture in a single API call, so checking tomorrow's status costs nothing extra.

**Detection:**
- `suspension_state` remains `SUSPENDED` for more than the expected suspension period
- HA logbook shows no suspension state change after a known suspension end date

**Phase to address:** SUSP-02. Document this explicitly in the polling loop: "always poll; never short-circuit on current state."

---

## Minor Pitfalls

### Pitfall 10: Holiday calendar year boundary — January 1 before new calendar is loaded

**What goes wrong:**
The NYC DOT ASP holiday calendar is published as a PDF and ICal file (e.g., `asp-calendar-2026.pdf`) typically in late November or early December for the following year. If the hardcoded holiday calendar is bundled into the integration code, a January 1 query for January 2027 dates returns "unknown" because the 2027 calendar hasn't been added yet.

**Prevention:**
For known future dates beyond the loaded calendar's range, return `UNKNOWN` (not `ACTIVE`). Set up a monitoring alert (or rely on GitHub issue) to update the calendar each November. Consider fetching the ICS URL from NYC.gov at startup and caching it — this eliminates the need for manual code updates.

**Phase to address:** SUSP-01. Decision point: hardcode calendar dates in code, or fetch the ICS from a URL. ICS fetch is more maintainable but adds a network dependency at HA startup.

---

### Pitfall 11: nyc311calendar has no explicit timezone handling

**What goes wrong:**
`nyc311calendar`'s `services.py` has no `import` for timezone libraries and no explicit timezone logic. Dates are handled as naive date objects. The `GetCalendar` API returns dates as `"%Y%m%d"` strings. The library's `date_mod()` utility does date arithmetic without timezone context.

If HA is running on a server in UTC, and `datetime.date.today()` is called inside `nyc311calendar` without timezone context, the result is UTC date — which lags NYC time by 4-5 hours. At 11 PM UTC (7 PM NYC), `date.today()` returns tomorrow's NYC date. The suspension query fetches tomorrow's status instead of today's.

**Prevention:**
Always pass an explicit NYC-timezone `date` when constructing the calendar query. Do not let `nyc311calendar` call `date.today()` implicitly. Before calling `get_calendar()`, convert `datetime.now(NYC_TZ).date()` to `date` explicitly and verify the library uses it.

If the library cannot accept an explicit date (not exposed in its API), derive the date externally and compare it against the response data's date keys to verify they match.

**Detection:**
- Suspension sensor shows tomorrow's status instead of today's after 7 PM on a HA server running UTC
- Holiday suspension appears one day early or one day late in the sensor

**Phase to address:** SUSP-02. Test with a HA instance running in UTC timezone.

---

### Pitfall 12: Suspension state not preserved on HA restart

**What goes wrong:**
`ASPParkingData` is an in-memory dataclass with no persistence. On HA restart, all coordinator state is cleared. The suspension poll won't run until the next configured interval fires (up to 60 minutes after startup). During that window, the sensor has `suspension_state=UNKNOWN`.

On a holiday morning, a user restarts HA, the sensor immediately shows "next move: 8:30 AM" while the suspension poll hasn't fired yet, potentially triggering a notification.

**Prevention:**
Either (a) trigger the suspension poll immediately on `async_start()` — before the first entity read — or (b) default the initial suspension state to `UNKNOWN` and suppress notifications when `suspension_state=UNKNOWN`. Option (a) is preferable: fetch suspension status eagerly at startup, before the coordinator reports any schedule data.

**Detection:**
- On HA restart during a holiday, sensor briefly shows a cleaning window before switching to "suspended"
- HA automations fire spuriously after restart on holiday mornings

**Phase to address:** SUSP-02. Initial fetch must be part of `async_start()` sequence, not deferred to the first poll interval.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|---|---|---|
| SUSP-01: Holiday calendar | Year boundary → UNKNOWN for next year's dates | Fetch ICS from nyc.gov or ship new calendar file annually; return UNKNOWN not ACTIVE for out-of-range dates |
| SUSP-01: Holiday calendar | Holiday calendar shipped as hardcoded list falls out of sync | Add a build-time assertion that the calendar extends at least 6 months into the future |
| SUSP-02: Emergency polling | nyc311calendar alpha breakage → silent wrong answer | All nyc311calendar calls wrapped in defensive try/except returning typed `SuspensionState.UNKNOWN` |
| SUSP-02: Emergency polling | API rate throttling from aggressive polling | 60-minute default interval; configurable floor of 15 minutes; back off on 429 |
| SUSP-02: Emergency polling | Timezone mismatch — UTC HA server queries wrong date | Always derive query date from `datetime.now(NYC_TZ).date()` |
| SUSP-02: Emergency polling | Multi-day suspension resumption missed | Never skip poll cycles when state is already SUSPENDED |
| SUSP-03: Merge layer | Race condition between GPS schedule update and suspension poll | Lazy merge in sensor property; notify entities immediately on suspension change |
| SUSP-03: Merge layer | "NOT IN EFFECT" conflated with "SUSPENDED" | Three-value state enum; NORMAL_SUSPENDED ≠ SUSPENDED |
| SUSP-03: Merge layer | "suspended" vs "no schedule" indistinguishable to user | `resolution_reason` attribute distinguishes all states |
| SUSP-04: ha-nyc311 bridge | Bridge creates hard dependency on third-party integration | Optional bridge only; asp_parking must function with SUSP-01+02 alone |
| SUSP-04: ha-nyc311 bridge | ha-nyc311 state = `None`/`"unavailable"` propagates as not-suspended | Explicit handling for all non-boolean sensor states |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|---|---|---|
| nyc311calendar | Call `get_calendar()` and inspect `calendar[CalendarType.WEEK_AHEAD]` without checking for `KeyError` | The `WEEK_AHEAD` key may be absent if the API returns an unexpected structure; always use `.get()` with a default |
| nyc311calendar | Use `ServiceType.PARKING` status without checking for `NO_INFORMATION` | Three-value status: `ACTIVE`, `SUSPENDED`, `UNKNOWN`; treat `NO_INFORMATION` as `UNKNOWN` |
| nyc311calendar | Assume the library handles nyc.gov API auth transparently | An expired or missing API key raises `aiohttp.ClientResponseError(401)`; must be caught and surfaced as a config error, not silently treated as UNKNOWN |
| NYC 311 API date format | Pass dates as `datetime` objects to the library's internal logic | The API uses `"%m/%d/%Y"` for requests and `"%Y%m%d"` in responses; verify date key alignment explicitly |
| HA coordinator (existing) | Add suspension state directly to `schedule_result` (which is a pipeline output type) | Suspension state is orthogonal to schedule resolution; keep it as a separate `ASPParkingData` field |
| HA sensor properties | Compute merged "is suspended today" inside `_async_resolve_pipeline` and cache the result | Compute at read time in the sensor property; stale cached merged state is the root of the race condition pitfall |

---

## "Looks Done But Isn't" Checklist

- [ ] **nyc311calendar wrapper:** `get_calendar()` raises any exception → `suspension_state=UNKNOWN`, not `ACTIVE`. Test with mock that raises `aiohttp.ClientError`.
- [ ] **Holiday calendar:** December 31 query returns `UNKNOWN` for January 1 of a year with no loaded calendar. Test year boundary explicitly.
- [ ] **Status distinction:** `NORMAL_SUSPENDED` (Sunday/no-cleaning-day) does NOT set `suspension_state=SUSPENDED`. Verify on a known Sunday.
- [ ] **Race condition:** GPS pipeline update fires at 06:45; suspension poll fires at 07:00; sensor shows correct state in the window between. Integration test with mocked timings.
- [ ] **Multi-day resumption:** Mock `nyc311calendar` returning `SUSPENDED` for 3 days then `ACTIVE`; verify `suspension_state` transitions to `ACTIVE` on day 4 without manual intervention.
- [ ] **HA restart on holiday:** Restart coordinator on a mocked holiday morning; verify no cleaning-window notification fires before suspension state is fetched.
- [ ] **Timezone:** HA server in UTC timezone; verify `suspension_state` reflects NYC date (not UTC date) at 11 PM UTC (7 PM NYC).
- [ ] **ha-nyc311 not installed:** SUSP-04 bridge disabled gracefully; SUSP-01+02 work without it.

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---|---|---|
| nyc311calendar API change breaks status mapping | MEDIUM | Pin library version; add canary test on status constant values; update STATUS_MAP if upstream API changes |
| Wrong suspension state due to UTC/NYC timezone mismatch | LOW | Pass explicit `datetime.now(NYC_TZ).date()` into all calendar queries; restart coordinator |
| Multi-day suspension resumption missed | LOW | Force poll immediately; poll interval was short-circuiting on current state; fix poll loop |
| ha-nyc311 bridge creates hard dependency, breaks on ha-nyc311 outage | LOW | Degrade gracefully to SUSP-01+02 internal sources; bridge is optional |
| Race condition produces stale merged state for 15 minutes | LOW | Move merge to sensor property (lazy); no coordinator change required |
| Holiday calendar out of date for new year | LOW | Update calendar file; redeploy integration; HA Core update or HACS update path |

---

## Sources

- Direct code inspection: `custom_components/asp_parking/coordinator.py` — `ASPParkingData`, `_async_resolve_pipeline`, `async_track_time_interval` pattern; `src/gps2asp/schedule/next_move.py` — `find_next_window` caching behavior; `custom_components/asp_parking/binary_sensor.py` — `is_on` from `schedule_result` type check
- `nyc311calendar` v0.4.1 (December 2022): self-identified alpha; `services.py` STATUS_MAP shows four raw strings (`"IN EFFECT"`, `"NOT IN EFFECT"`, `"SUSPENDED"`, `"NO INFORMATION"`); no explicit timezone handling in source; README: "Expect breaking changes"
- `ha-nyc311` v0.1.5 (February 2023): requires NYC API Portal developer account; depends on `nyc311calendar`; exposes binary sensors and calendar entities for parking, schools, and trash
- NYC 311 API behavior: returns date-keyed status without time component; status updates at most once or twice per day; `WEEK_AHEAD` returns yesterday through 6 days ahead; `NO INFORMATION` returned for far-future dates and during transient outages
- NYC ASP suspension patterns: holiday suspensions published months in advance as DOT PDF (`asp-calendar-YYYY.pdf`) and ICS; emergency weather suspensions announced day-of or evening-before via NYC Emergency Management NotifyNYC; multi-day consecutive suspensions occur (January 2025: 4+ consecutive days); suspensions cover midnight-to-midnight NYC time
- aspnyc.info: confirms hourly polling of NYC 311 API is the standard pattern for suspension status sites
- STATE.md blocker: "nyc311calendar is alpha — relevant for v2 suspension handling"
- PROJECT.md SUSP-01 through SUSP-04 requirements; existing `ASPParkingData` fields and coordinator architecture

---
*Pitfalls research for: GPS2ASP Resolver v3.0 — Suspension Handling*
*Researched: 2026-03-30*
