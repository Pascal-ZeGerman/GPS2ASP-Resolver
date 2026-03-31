# Architecture Patterns: Suspension Handling Integration

**Domain:** ASP suspension handling added to existing GPS2ASP pipeline
**Researched:** 2026-03-30
**Milestone:** v3.0 — Suspension Handling

---

## Existing Pipeline (Baseline)

The current pipeline is a strict linear chain with no suspension awareness:

```
GPS (lat/lon)
    └─► Stage 1: resolve_segment()   → ResolutionResult
            └─► Stage 2: retrieve_signs()  → SignRetrievalResult
                    └─► Stage 3: compute_schedule() → ScheduleResult
                                                        (ScheduleFound | ASPActiveNow |
                                                         NoASPSchedule | NoMatchSchedule |
                                                         AllUnparseable)
                            └─► ASPResult (public API output)
                                    └─► ASPParkingCoordinator.data (HA layer)
                                            └─► ASPNextMoveTimeSensor / ASPActiveNowBinarySensor
```

Key facts about the existing architecture:

- `resolve_asp()` in `pipeline.py` wires stages 1-3. It is the single public API entry point.
- `ASPResult` and `ASPDebugResult` in `api_models.py` are the only outputs callers see.
- `ScheduleFound` and `ASPActiveNow` both have a `suspended: bool = False` field already — a v2 hook deliberately left in place for this milestone.
- `find_next_window()` in `next_move.py` does a 7-day lookahead without suspension awareness. It will return a window even on a suspended day.
- The HA coordinator (`coordinator.py`) calls stages 1-3 manually (not `resolve_asp()`) — this is known tech debt noted in PROJECT.md.
- `ASPParkingData` dataclass in the coordinator holds all state exposed to HA entities.
- Entity notification flows through `_async_notify_entities()` → `async_write_ha_state` on each entity.

---

## New Components Required

### 1. Suspension Calendar (static, in `gps2asp` package)

**Location:** `src/gps2asp/suspension/calendar.py`
**What it is:** A hardcoded lookup table of all NYC holiday ASP suspension dates for the current year, plus next year.

NYC DOT publishes an official annual PDF calendar with ~50 suspension dates per year (holidays + religious observances). This data changes once a year (new calendar published in November/December). It does not require an API call.

**Data source:** Hard-coded as a `frozenset[date]` derived from the official NYC DOT calendar (https://www.nyc.gov/html/dot/downloads/pdf/asp-calendar-2026.pdf). Alternatively, shipped as a static data file (JSON or ICS).

**Interface:**
```python
def is_holiday_suspension(date: date) -> bool:
    """Return True if the given date is an official NYC holiday ASP suspension."""

def get_suspension_reason(date: date) -> str | None:
    """Return the holiday name if suspended, None otherwise. e.g. 'Eid Al-Fitr'"""
```

**Why static over ICS-fetch:** The calendar is published once a year. An ICS fetch adds network dependency and parse complexity for data that rarely changes. Hard-coding with an annual update cycle is simpler and more reliable. The ICS format is available for automation, but parsing it adds scope.

---

### 2. Suspension Poller (dynamic, in `gps2asp` package)

**Location:** `src/gps2asp/suspension/poller.py`
**What it is:** An async HTTP client that queries the NYC 311 Public API for today's parking status.

**API:** `GET https://api.nyc.gov/public/api/GetCalendar`
- Requires: API key via `Ocp-Apim-Subscription-Key` header (free registration at api-portal.nyc.gov)
- Returns: JSON with status per service per date
- Parking status values (from `nyc311calendar` library source): `IN_EFFECT`, `SUSPENDED`, `NOT_IN_EFFECT`, `NO_INFO`

**IMPORTANT:** `IN_EFFECT` = ASP is active (cleaning will happen). `SUSPENDED` = holiday/emergency suspension. `NOT_IN_EFFECT` = routine non-enforcement (Sundays). `NO_INFO` = unknown.

For this integration only `SUSPENDED` matters — it means ASP is cancelled city-wide on a date that would otherwise be a cleaning day. The consumer must cross-reference with the block's own schedule to determine actual impact.

**Why poll at all when we have the static calendar:** Emergency/weather suspensions (snow emergencies, mayoral declarations) are NOT in the static calendar. They are announced same-day via the 311 API. The static calendar covers planned holidays; the 311 API covers dynamic suspensions. Both sources are needed.

**Polling cadence:** Once daily refresh is sufficient for holiday suspensions. For weather/emergency suspensions, poll more frequently on days where ASP is otherwise in effect (e.g., every 2-4 hours during business hours). The 311 API data at aspnyc.info is "updated every hour."

**Interface:**
```python
@dataclass(frozen=True)
class SuspensionStatus:
    date: date
    is_suspended: bool        # True for SUSPENDED; False for IN_EFFECT/NOT_IN_EFFECT
    is_in_effect: bool        # True only for IN_EFFECT
    reason: str | None        # "Rosh Hashanah", "Snow Emergency", etc. — from API
    source: Literal["311_api", "cache", "unknown"]

async def fetch_suspension_status(
    date: date,
    api_key: str,
    session: httpx.AsyncClient,
) -> SuspensionStatus:
    """Fetch today's suspension status from NYC 311 API."""
```

**Error handling:** Network failure should NOT block the schedule pipeline. On failure, return a `SuspensionStatus` with `is_suspended=False`, `source="unknown"` — fail open (don't suppress real cleaning days on network failure).

---

### 3. Suspension Merger (pure function, in `gps2asp` package)

**Location:** `src/gps2asp/suspension/merge.py`
**What it is:** A pure function that takes a `ScheduleResult` and `SuspensionStatus` and returns a new `ScheduleResult` with the `suspended` flag set on affected variants.

**Interface:**
```python
def apply_suspension(
    schedule: ScheduleResult,
    suspension: SuspensionStatus,
) -> ScheduleResult:
    """Apply suspension status to a schedule result.

    Returns a new ScheduleResult with suspended=True if the next_window
    or active_window falls on a suspended date.
    """
```

**Merge rules:**
- `ScheduleFound` with `next_window` on a suspended date → return new `ScheduleFound(suspended=True)`
- `ASPActiveNow` on a suspended date → return new `ASPActiveNow(suspended=True)`. This is the critical case: user's car is in an "active" window but ASP is suspended, so they do NOT need to move.
- `NoASPSchedule`, `NoMatchSchedule`, `AllUnparseable` → pass through unchanged (no cleaning day to suspend)
- If `suspension.is_suspended=False` → return schedule unchanged (no mutation needed)

**Why a separate pure function instead of inside `compute_schedule()`:** `compute_schedule()` currently has no external dependencies — it only processes signs. Suspension adds an external data dependency. Keeping the merger separate preserves the pure nature of the schedule stage and allows suspension to be applied outside the pipeline (e.g., in the HA coordinator after a suspension status update without a full re-resolve).

---

### 4. ha-nyc311 Bridge (optional, HA layer only)

**Location:** `custom_components/asp_parking/suspension_bridge.py`
**What it is:** Code that reads suspension state from the ha-nyc311 integration's entities instead of calling the 311 API directly. Used when ha-nyc311 is installed alongside asp_parking.

**ha-nyc311 entities (confirmed from source):**
- `binary_sensor.nyc311_parking_exception_today` — True when parking is suspended today
- `binary_sensor.nyc311_parking_exception_tomorrow` — True for tomorrow
- `binary_sensor.nyc311_parking_exception_in_N_days` — for N=2 through 6
- Attributes: `service_name`, `closure_type` ("Exception" or "Routine"), `date`, `reason`

**Bridge interface:**
```python
async def read_nyc311_bridge(
    hass: HomeAssistant,
    date: date,
) -> SuspensionStatus | None:
    """Read suspension status from ha-nyc311 entities if available.

    Returns None if ha-nyc311 is not installed or entity not found.
    Falls back to direct 311 API polling when None is returned.
    """
```

**Why optional:** The bridge requires ha-nyc311 to be installed. Not all users will have it. The integration must work standalone via direct 311 API polling. The bridge is an optimization — avoids a duplicate API call when ha-nyc311 is already polling.

**Bridge detection:** Check `hass.states.get("binary_sensor.nyc311_parking_exception_today")` — if `None`, ha-nyc311 is absent, fall back to direct polling. No config required from the user for detection.

---

## Integration Points in the Existing Pipeline

### Point A: `pipeline.py` — resolve_asp()

**Change type:** New parameter + new stage

`resolve_asp()` grows a new optional parameter `suspension_status: SuspensionStatus | None = None`. When provided, `apply_suspension()` is called after `compute_schedule()` before returning.

```python
# After Stage 3 (existing)
schedule = compute_schedule(sign_result)

# New Stage 4 (suspension merge)
if suspension_status is not None:
    schedule = apply_suspension(schedule, suspension_status)
```

This keeps suspension optional — callers that don't provide `suspension_status` get the existing behavior unchanged. The HA coordinator, which passes the suspension status in, handles the suspension lookup.

**Do NOT call the 311 API inside `resolve_asp()`** — that would make every pipeline run dependent on network availability of a second API. The caller (coordinator) owns that concern.

---

### Point B: `api_models.py` — ASPResult

**Change type:** New field

`ASPResult` gets a `suspension_reason: str | None = None` field. When the schedule's `suspended=True`, this propagates the reason to the HA sensor attributes.

```python
@dataclass(frozen=True)
class ASPResult:
    schedule: ScheduleResult | None
    resolution_failed: bool
    resolution_error: str | None
    soda_level: int = 0
    suspension_reason: str | None = None   # NEW: populated when suspended=True
```

---

### Point C: `schedule/models.py` — ScheduleFound and ASPActiveNow

**Change type:** Already has the hook — just needs `apply_suspension()` to set it.

The `suspended: bool = False` field already exists on both `ScheduleFound` and `ASPActiveNow`. Since these are frozen dataclasses, `apply_suspension()` returns a `dataclasses.replace(schedule, suspended=True)` copy. No model changes needed for the flag.

**New field needed:** `suspension_reason: str | None = None` should be added to `ScheduleFound` and `ASPActiveNow` to carry the reason alongside the flag. This allows the HA sensor to show "Suspended: Eid Al-Fitr" in attributes.

---

### Point D: `coordinator.py` — ASPParkingCoordinator

**Change type:** New suspension polling, new data field, modified pipeline call

This is the largest change. The coordinator becomes responsible for:

1. **Suspension state management:** Holds a `SuspensionStatus` that is refreshed on its own schedule, independent of GPS events.
2. **Bridge detection:** On `async_start()`, detect ha-nyc311 presence and configure the suspension source.
3. **Suspension-aware pipeline:** Pass `suspension_status` to each pipeline run.
4. **Re-evaluation trigger:** When suspension status changes, re-apply suspension to the current `schedule_result` without running the full GPS pipeline.

New fields on `ASPParkingData`:

```python
@dataclass
class ASPParkingData:
    # ... existing fields ...
    suspended: bool = False                  # NEW: is ASP suspended today?
    suspension_reason: str | None = None     # NEW: "Rosh Hashanah", "Snow Emergency", etc.
    suspension_source: str = "unknown"       # NEW: "311_api", "ha_nyc311_bridge", "holiday_calendar", "none"
    last_suspension_check: datetime | None = None  # NEW: when suspension was last checked
```

**Suspension refresh schedule:** Separate `async_track_time_interval` callback that runs:
- Once at startup
- Every 4 hours during daytime (6am-10pm NYC time) when ASP is currently in effect
- Once at midnight to pick up the new day's status

This is separate from the GPS-driven pipeline refresh. The suspension poller runs even when the car hasn't moved.

**Re-evaluation on suspension change:** When the suspension poller fires and the status changes (was `suspended=False`, now `True`, or vice versa), the coordinator must re-apply suspension to the current `schedule_result` and notify entities — without re-running the SODA pipeline. This is the key architectural advantage of keeping `apply_suspension()` as a pure function that can be called in isolation.

---

### Point E: `sensor.py` — ASPNextMoveTimeSensor

**Change type:** New state text and new attributes

When `schedule.suspended == True`, the sensor state should communicate this to the user clearly:
- If `ScheduleFound` with `suspended=True`: state changes from "Mon 8:00 AM" to "Suspended" (or "No restrictions")
- If `ASPActiveNow` with `suspended=True`: `is_on` on the binary sensor becomes `False` (user does NOT need to move)

New attributes when suspended:
```python
attrs["asp_suspended"] = schedule.suspended          # bool
attrs["suspension_reason"] = schedule.suspension_reason  # str | None
attrs["suspension_source"] = data.suspension_source  # "311_api" | "ha_nyc311_bridge" | etc.
```

**Binary sensor (`binary_sensor.py`):** `ASPActiveNowBinarySensor.is_on` currently returns `isinstance(schedule, ASPActiveNow)`. This must change to `isinstance(schedule, ASPActiveNow) and not schedule.suspended`. An active window during a suspension should NOT trigger the binary sensor.

---

### Point F: `config_flow.py` — Configuration

**Change type:** New optional fields

New optional configuration fields:
- `CONF_NYC311_API_KEY` — optional; skips 311 API polling if absent (holiday calendar only)
- `CONF_SUSPENSION_POLL_INTERVAL` — hours between suspension checks (default: 4)
- `CONF_USE_HA_NYC311_BRIDGE` — bool, auto-detected but user-overridable; true = use ha-nyc311 bridge

The 311 API key is optional because:
1. Holiday suspensions from the static calendar work without it.
2. Some users may not want to register for an API key.
3. The ha-nyc311 bridge path does not need the API key.

---

## Data Flow Summary

### Path 1: GPS movement triggers pipeline (existing path, extended)

```
GPS update → movement > 50m → debounce 5s
    → fetch_suspension_status(today)        ← NEW (or read from ha-nyc311 bridge)
    → resolve_segment(lat, lon)
    → retrieve_signs(...)
    → compute_schedule(sign_result)
    → apply_suspension(schedule, status)    ← NEW
    → ASPParkingData updated
    → entities notified
```

### Path 2: Suspension status changes (new path, no GPS re-resolve)

```
suspension_poll_timer fires
    → fetch_suspension_status(today)
    → if status changed from last check:
        → apply_suspension(coordinator.data.schedule_result, new_status)
        → update coordinator.data.schedule_result
        → update coordinator.data.suspended + suspension_reason
        → entities notified
    → else: no-op
```

### Path 3: Daily midnight reset (new path)

```
midnight timer fires
    → fetch_suspension_status(tomorrow = new today)
    → update coordinator.data with new status
    → if next_window is now unsuspended (yesterday had suspension, today doesn't):
        → re-resolve full pipeline with current GPS
```

### Path 4: ha-nyc311 bridge state change (new path, HA-only)

```
ha-nyc311 entity state change event
    → read binary_sensor.nyc311_parking_exception_today state
    → if changed from last known:
        → apply suspension (same as Path 2)
```

This is the most responsive path — ha-nyc311 fires an HA state change event immediately when the 311 API returns a new suspension. The 311 API update cadence from aspnyc.info is "updated every hour."

---

## Build Order (Component Dependencies)

```
Phase A: Static holiday calendar
    src/gps2asp/suspension/__init__.py
    src/gps2asp/suspension/calendar.py
    → No external dependencies. Self-contained. Tests are simple date lookups.
    → Dependency: none

Phase B: SuspensionStatus model + apply_suspension() merger
    src/gps2asp/suspension/models.py    (SuspensionStatus dataclass)
    src/gps2asp/suspension/merge.py     (apply_suspension pure function)
    schedule/models.py                  (add suspension_reason field to ScheduleFound + ASPActiveNow)
    → Dependency: Phase A (SuspensionStatus model)
    → Tests: pure function, no I/O needed

Phase C: pipeline.py + api_models.py wiring
    pipeline.py                         (add suspension_status param, call apply_suspension)
    api_models.py                       (add suspension_reason to ASPResult)
    → Dependency: Phase B (apply_suspension exists)
    → Tests: resolve_asp() with mock SuspensionStatus

Phase D: Direct 311 API poller
    src/gps2asp/suspension/poller.py    (async httpx client for NYC 311 API)
    → Dependency: Phase B (SuspensionStatus model)
    → External dependency: nyc311calendar OR direct httpx call to api.nyc.gov
    → Tests: mock httpx responses; live integration test behind skip flag

Phase E: HA coordinator suspension integration
    coordinator.py                      (suspension polling, new ASPParkingData fields)
    config_flow.py                      (NYC311_API_KEY, poll interval options)
    → Dependency: Phase C (pipeline.py change), Phase D (poller)

Phase F: HA sensor/binary_sensor changes
    sensor.py                           (suspended state text, new attributes)
    binary_sensor.py                    (suspended check in is_on)
    → Dependency: Phase E (coordinator exposes suspended data)

Phase G: ha-nyc311 bridge (optional, separate phase)
    suspension_bridge.py                (read ha-nyc311 entities)
    coordinator.py                      (bridge detection + state change listener)
    → Dependency: Phase E (coordinator suspension polling exists as fallback)
    → Can be deferred if no ha-nyc311 is installed in the user's HA
```

---

## Component Boundary Summary

| Component | Layer | New or Modified | Dependency |
|-----------|-------|----------------|------------|
| `suspension/calendar.py` | `gps2asp` lib | New | None |
| `suspension/models.py` | `gps2asp` lib | New | None |
| `suspension/merge.py` | `gps2asp` lib | New | models |
| `suspension/poller.py` | `gps2asp` lib | New | models, httpx |
| `schedule/models.py` | `gps2asp` lib | Modified (add `suspension_reason`) | None |
| `pipeline.py` | `gps2asp` lib | Modified (add stage 4) | merge |
| `api_models.py` | `gps2asp` lib | Modified (add `suspension_reason`) | models |
| `coordinator.py` | HA layer | Modified (suspension polling) | poller, bridge |
| `sensor.py` | HA layer | Modified (new state/attrs) | coordinator |
| `binary_sensor.py` | HA layer | Modified (suspended check) | coordinator |
| `config_flow.py` | HA layer | Modified (new options) | const |
| `suspension_bridge.py` | HA layer | New | hass states |

---

## Key Architectural Decisions

**Suspension is a post-pipeline annotation, not a pipeline input.** The GPS-to-signs pipeline is unchanged. Suspension is applied after `compute_schedule()` returns. This preserves the existing pipeline's testability and keeps the SODA dependency cleanly separate from the 311 dependency.

**Fail open on suspension API failure.** If the 311 API is unreachable, treat suspension as unknown/False. Never suppress a legitimate cleaning window because the suspension check failed — a missed cleaning notice is worse than a false alarm.

**Two suspension data sources are strictly layered.** Static calendar covers holidays (no API key needed, always available). 311 API covers emergency/weather suspensions (API key needed, network-dependent). When both are available, the 311 API is authoritative (it subsumes holidays too). When only the static calendar is available, holiday suspensions still work.

**The merger is a pure function, not a pipeline stage.** `apply_suspension()` takes a `ScheduleResult` and returns a new `ScheduleResult`. This enables re-application when suspension status changes without re-running the expensive SODA query and parse stages.

**ha-nyc311 bridge is an optimization, not a requirement.** The integration is fully functional without ha-nyc311. The bridge eliminates a duplicate API call for users who already have ha-nyc311 installed. It is detected automatically from HA state registry, requiring no user configuration.

**Vendored copy (`custom_components/asp_parking/gps2asp/`) must be kept in sync.** All changes to `src/gps2asp/suspension/` must be mirrored to `custom_components/asp_parking/gps2asp/suspension/`. This vendored sync is an existing constraint (established in v2.0).

---

## Sources

- Existing codebase: `src/gps2asp/pipeline.py`, `api_models.py`, `schedule/models.py`, `schedule/next_move.py`, `coordinator.py`, `sensor.py`, `binary_sensor.py`
- nyc311calendar library source: https://github.com/elahd/nyc311calendar (`services.py` — parking status enum values `IN_EFFECT`, `SUSPENDED`, `NOT_IN_EFFECT`, `NO_INFO`)
- ha-nyc311 integration: https://github.com/elahd/ha-nyc311 (entity ID patterns, binary sensor attributes, `binary_sensor.nyc311_parking_exception_today`)
- NYC 311 Public API: `https://api.nyc.gov/public/api/GetCalendar` — requires free registration at https://api-portal.nyc.gov/
- NYC DOT ASP Suspension Calendar: https://www.nyc.gov/html/dot/html/motorist/alternate-side-parking.shtml (~50 suspension dates/year, available as ICS and PDF)
- aspnyc.info (unofficial reference consumer of 311 API): https://www.aspnyc.info/ — confirms hourly 311 API polling cadence and status format
