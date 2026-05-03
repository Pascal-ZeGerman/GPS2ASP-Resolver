---
phase: 30-add-richer-debug-sensor-pipeline-attributes
plan: 03
subsystem: coordinator
tags: [python, homeassistant, coordinator, dataclass, tdd, borough-mapping]

# Dependency graph
requires:
  - phase: 30-add-richer-debug-sensor-pipeline-attributes
    plan: 01
    provides: ResolutionResult.borocode / .perpendicular_distance_ft / .street_width_ft / .segment_id (consumed by ASPParkingData success branch)
  - phase: 30-add-richer-debug-sensor-pipeline-attributes
    plan: 02
    provides: ASPDebugResult top-level diagnostic fields (parallel API surface; not consumed by this plan but ensures the pipeline + coordinator both expose the same data shape)
provides:
  - "_BOROUGH_NAMES module-level constant in coordinator.py — maps CSCL borocode str ('1'..'5') to human-readable borough name"
  - "ASPParkingData.borough (str | None) — human-readable borough name; None if not resolved or unmapped"
  - "ASPParkingData.distance_ft (float | None) — perpendicular GPS-to-centerline distance"
  - "ASPParkingData.street_width_ft (float | None) — post-fallback effective width"
  - "ASPParkingData.segment_id (int | None) — CSCL physical segment ID"
  - "Coordinator success branch unconditionally populates all 4 fields from ResolutionResult (D-09)"
  - "Both error branches (OutsideNYCError, NoSegmentFoundError/AmbiguousResolutionError) reset all 4 fields to None"
affects:
  - 30-04 (sensor extra_state_attributes — will read coordinator.data.borough/.distance_ft/.street_width_ft/.segment_id)

# Tech tracking
tech-stack:
  added: []  # No new deps; uses existing pytest + dataclasses
  patterns:
    - "Module-level UPPER_SNAKE_CASE dict for static name mapping (parallels _METRES_TO_FEET pattern)"
    - "Optional-field extension on mutable @dataclass with None defaults (parallels existing soda_level=0/confidence_score=None pattern)"
    - "Coordinator error-branch reset block — pattern: append `self.data.<new_field> = None` after the existing `self.data.soda_level = 0` reset, so all derived state clears together"
    - "TDD RED → GREEN cycle as two atomic commits with shared test module"

key-files:
  created:
    - tests/test_coordinator_borough_fields.py
  modified:
    - custom_components/asp_parking/coordinator.py

key-decisions:
  - "D-09 (closed): Fields populated unconditionally on the success path (not gated on debug=True); existing resolve() call site unchanged"
  - "D-10 (closed): ASPParkingData gets 4 new optional fields with None defaults (additive change, all existing call sites keep working)"
  - "D-11 (closed): Coordinator owns the borocode→human-readable borough name translation; success branch maps via _BOROUGH_NAMES.get(...) with None-safe `or ''` coalesce"
  - "D-12 (closed): _BOROUGH_NAMES module-level constant uses str keys ('1'..'5') matching CSCL borocode type"

patterns-established:
  - "Borocode→borough name lookup: `_BOROUGH_NAMES.get(resolution.borocode or '')` returns None for both `borocode=None` and `borocode=''`, sidestepping the dict.get(None, ...) edge case while still returning None on unmapped non-empty inputs"
  - "Coordinator generic-Exception branch (line ~714) intentionally does NOT reset diagnostic fields (matches the existing `soda_level` pattern: last-known-state fallback for unexpected errors); Phase 30 follows the same convention"

requirements-completed: [DIAG-04]

# Metrics
duration: ~12min
completed: 2026-05-03
---

# Phase 30 Plan 03: Coordinator borough mapping and diagnostic field threading Summary

**ASPParkingData exposes four new diagnostic fields (borough, distance_ft, street_width_ft, segment_id) populated unconditionally from ResolutionResult on success and reset to None on resolution-failure branches; new _BOROUGH_NAMES constant translates CSCL borocode str to human-readable borough name.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-05-03T15:42:00Z (approx — execution start)
- **Completed:** 2026-05-03T15:54:00Z (approx — final commit)
- **Tasks:** 2 (RED + GREEN)
- **Files modified:** 1 (coordinator.py)
- **Files created:** 1 (test_coordinator_borough_fields.py)

## Accomplishments

- New module-level constant `_BOROUGH_NAMES: dict[str, str]` in `coordinator.py`, sitting next to `_METRES_TO_FEET`, mapping the 5 CSCL borocodes (str keys `"1"`..`"5"`) to human-readable borough names (D-12).
- `ASPParkingData` extended from 14 to 18 fields — four new optional diagnostic fields (`borough`, `distance_ft`, `street_width_ft`, `segment_id`) all default `None` so every existing constructor call site (e.g., `ASPParkingData()` in `__init__`) keeps working unchanged (D-10).
- `_async_resolve_pipeline()` success branch now populates all 4 fields immediately after the existing `self.data.confidence_score = resolution.confidence` line. Borough lookup uses `_BOROUGH_NAMES.get(resolution.borocode or "")` which returns `None` for both `borocode=None` and unmapped values — no exception, no leakage (D-09, D-11).
- `OutsideNYCError` handler and the combined `NoSegmentFoundError`/`AmbiguousResolutionError` handler both reset all 4 new fields to `None` immediately after the existing `self.data.soda_level = 0` reset, preventing stale data from a prior resolution leaking into a sensor read after a GPS jump.
- Generic `Exception` handler intentionally untouched: the existing pattern leaves `soda_level` alone for unknown errors (last-known-state fallback), so the new fields follow the same convention.
- 8 new unit tests covering: (1) constant existence + key/value type, (2) dataclass field declarations + None defaults, (3-4) success-path borocode→name mapping for Brooklyn and Manhattan, (5) unmapped borocode (`"99"`) yields `borough=None` while keeping the other 3 populated, (6) `borocode=None` coalesces safely without TypeError, (7) `OutsideNYCError` reset, (8) `NoSegmentFoundError` reset.
- Foundation in place for Plan 30-04 (sensor `extra_state_attributes`) which can now read `coordinator.data.borough` / `.distance_ft` / `.street_width_ft` / `.segment_id` directly from the coordinator without nested unwrapping.

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): failing tests for coordinator borough mapping and field population** — `3a51eb3` (test)
2. **Task 2 (GREEN): add _BOROUGH_NAMES and thread diagnostic fields through ASPParkingData** — `ce32de4` (feat)

_Note: This is a TDD plan; the test commit precedes the implementation commit. No REFACTOR commit was needed — the GREEN edits are pure additive extensions._

## Files Created/Modified

- `tests/test_coordinator_borough_fields.py` — **created** (~410 lines) — 8 tests covering constant existence, dataclass field shape, success-branch borocode→name mapping (Brooklyn + Manhattan + unmapped + None edge cases), and error-branch field resets for both `OutsideNYCError` and `NoSegmentFoundError`.
- `custom_components/asp_parking/coordinator.py` — **modified** — added `_BOROUGH_NAMES` constant (8 lines) right after `_METRES_TO_FEET`; extended `ASPParkingData` docstring + body with 4 new fields (8 lines); added 1 success-branch population block (5 lines incl. comment); added 2 error-branch reset blocks (5 lines each incl. comment).

## ASPParkingData Signature Change

| Item | Before | After |
|------|--------|-------|
| Field count | 14 | 18 (+4) |
| `borough: str \| None` | absent | added (default `None`) |
| `distance_ft: float \| None` | absent | added (default `None`) |
| `street_width_ft: float \| None` | absent | added (default `None`) |
| `segment_id: int \| None` | absent | added (default `None`) |

_Note: the plan frontmatter said "15 → 19 fields" — actual original count was 14, not 15 (verified via `dataclasses.fields(ASPParkingData)`). The additive count of +4 is exact._

## Coordinator Branch Edits

| Branch | Edit |
|--------|------|
| Success branch (after line `self.data.confidence_score = resolution.confidence`) | +5 lines (1 comment + 4 assignments). Reads from `resolution.borocode/.perpendicular_distance_ft/.street_width_ft/.segment_id`. Borough uses `_BOROUGH_NAMES.get(resolution.borocode or "")` for None-safe lookup. |
| `except OutsideNYCError` (after `self.data.soda_level = 0`) | +5 lines (1 comment + 4 None resets). |
| `except (NoSegmentFoundError, AmbiguousResolutionError)` (after `self.data.soda_level = 0`) | +5 lines (1 comment + 4 None resets). |
| `except Exception` (line ~714) | **No change** — generic handler does not reset `soda_level` either; preserves last-known-state fallback. |

## resolve() Call Site Unchanged (D-09)

`coordinator.py` line 578 still reads `resolution = await resolve(lat, lon)` — the bare resolver call. Per D-09, the new fields flow through the `ResolutionResult` directly (Plan 30-01 added the 4 fields to that dataclass). No pipeline call signature change; no `resolve_asp(debug=True)` swap.

## Test Count Delta

- New module: `tests/test_coordinator_borough_fields.py` — 8 tests
- Net delta: **+8 tests** (no existing tests modified or deleted)
- Pre-RED state: 8 of 8 fail at collection (ImportError on `_BOROUGH_NAMES` — comprehensively confirms RED gate before any implementation)
- Post-GREEN state: 8 of 8 pass; full fast suite (`-m "not integration and not ha_integration"`) reports `351 passed, 1 failed, 102 deselected` — the single failure is the pre-existing `test_suspension::test_is_suspended_holiday` already deferred since Plan 30-01

## Decisions Made

Followed plan as specified — all decisions D-09, D-10, D-11, D-12 implemented exactly as defined in the plan frontmatter. No new decisions required.

## Deviations from Plan

None — plan executed exactly as written. Edit instructions in the plan's `<action>` blocks (Edit 1 through Edit 6) were applied verbatim to the worktree. The "Edit 6" instruction was a no-op verification step ("confirm no `self.data.soda_level = 0` reset exists in the generic Exception block") which was confirmed and respected (no edit applied).

The only minor delta from the plan is documentation: the plan's verification section claimed `dataclasses.fields(ASPParkingData)` would return 19 entries (15 + 4); the actual count is 18 (14 + 4). Verified via runtime inspection — the original dataclass had 14 fields, not 15. This is a typo in the plan, not a deviation in implementation; the +4 additive change is exact.

## Issues Encountered

- **Initial file misplacement (operational, not code)** — During execution, the first attempt to create `tests/test_coordinator_borough_fields.py` was made via an absolute path that resolved to the project root (`/home/pascal/.../GPS2ASP-Resolver/tests/`) instead of the worktree (`/home/pascal/.../GPS2ASP-Resolver/.claude/worktrees/agent-a0354568/tests/`). Caught by inspecting `git status` in both locations after the initial Write. Resolved by removing the misplaced file from the project root with `git reset -- <file>` + `rm -f <file>` (no commits at the project root were made), then re-creating in the worktree with the correct absolute path. Zero impact on the worktree's commit history.

- **Pre-existing failure in `tests/test_suspension.py::test_is_suspended_holiday`** — same failure that Plans 30-01 and 30-02 already logged to `deferred-items.md`. Confirmed not caused by Plan 30-03: this plan only touches `coordinator.py` and adds `tests/test_coordinator_borough_fields.py`; `HolidayCalendar` lives in `gps2asp/suspension/` with no plausible coupling. Already tracked.

## User Setup Required

None — all changes are internal-coordinator / dataclass-shape changes that flow through automatically once Plan 30-04 wires the downstream sensor `extra_state_attributes` consumers.

## Next Phase Readiness

- **Plan 30-04** can now read `coordinator.data.borough` (already a human-readable string), `coordinator.data.distance_ft`, `coordinator.data.street_width_ft`, and `coordinator.data.segment_id` directly off the coordinator's data bag — no per-sensor borocode translation needed (D-11 fulfilled at the coordinator layer per the design).
- The vendored mirror policy does NOT apply to this plan — `coordinator.py` is the integration code, not a vendored library copy. No `src/` parity to maintain.
- Fast test suite is green for the 8 new tests + zero new regressions in the 343 other tests; only the pre-existing `test_suspension::test_is_suspended_holiday` failure remains (already deferred since Plan 30-01).
- TDD gate compliance: RED commit `3a51eb3` precedes GREEN commit `ce32de4`; no REFACTOR commit needed.

## TDD Gate Compliance

- **RED gate:** `3a51eb3` (`test(30-03): add failing tests for coordinator borough mapping and field population`) — confirmed failing at collection with `ImportError: cannot import name '_BOROUGH_NAMES'`. Comprehensive: a single import-time failure blocks all 8 tests, satisfying "MUST fail" before implementation.
- **GREEN gate:** `ce32de4` (`feat(30-03): add _BOROUGH_NAMES and thread diagnostic fields through ASPParkingData`) — all 8 new tests pass; full fast suite green except the pre-existing deferred suspension failure.
- **REFACTOR gate:** Not exercised — the GREEN edits are pure additive extensions (one new constant, four new fields, one new success-branch block, two new error-branch blocks); no follow-up cleanup needed.

## Self-Check: PASSED

- `tests/test_coordinator_borough_fields.py` exists ✓ (FOUND)
- `custom_components/asp_parking/coordinator.py` modified ✓ (FOUND in `git diff` HEAD~1..HEAD)
- Commit `3a51eb3` (RED) exists in git log ✓ (FOUND)
- Commit `ce32de4` (GREEN) exists in git log ✓ (FOUND)
- All 8 new tests pass ✓ (`8 passed in 0.60s`)
- Fast suite shows zero new regressions ✓ (351 passed; only pre-existing deferred test_suspension failure remains)
- `_BOROUGH_NAMES` exists with 5 entries ✓ (verified via runtime `len(_BOROUGH_NAMES) == 5`)
- ASPParkingData has 4 new fields with None defaults ✓ (verified via `dataclasses.fields(ASPParkingData)` returning 18 entries total)
- Success branch populates all 4 fields ✓ (4 grep matches in `coordinator.py`)
- Both error branches reset all 4 fields ✓ (2 occurrences of `self.data.borough = None` in `coordinator.py`, one per branch)
- `resolve()` call site unchanged ✓ (D-09 honored — line 578 still reads `resolution = await resolve(lat, lon)`)
- No deletions in either commit ✓ (verified via `git diff --diff-filter=D --name-only HEAD~2 HEAD` returning empty)

---
*Phase: 30-add-richer-debug-sensor-pipeline-attributes*
*Completed: 2026-05-03*
