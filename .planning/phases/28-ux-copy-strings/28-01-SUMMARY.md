---
phase: 28-ux-copy-strings
plan: 01
subsystem: home-assistant
tags: [home-assistant, i18n, strings.json, translations, hacs]

# Dependency graph
requires:
  - phase: pre-existing
    provides: HA integration scaffold, config_flow steps, sensor entities
provides:
  - strings.json byte-equivalent to translations/en.json
  - Dead config.step.vehicle removed
  - VW CarNet placeholder copy purged
  - All 12 entity.sensor translation keys covered
  - Generic notify_service description (no personal example)
  - config.error and options.error blocks added (4 keys each)
  - api_keys config step added with NYC 311 wording
affects:
  - any future HA UI copy work
  - HACS validator runs (English template + en.json now consistent)
  - downstream plans editing config_flow/options_flow steps

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "translations/en.json is the source of truth; strings.json is rewritten to match it byte-for-byte"
    - "Unit suffixes (meters, hours, minutes) live in data_description, not in data labels"
    - "config.step keys are kept in 1:1 sync with config_flow.py step_id values"
    - "entity.sensor keys are kept in 1:1 sync with sensor.py _attr_translation_key values"

key-files:
  created: []
  modified:
    - "custom_components/asp_parking/translations/en.json"
    - "custom_components/asp_parking/strings.json"

key-decisions:
  - "D-01: translations/en.json is authoritative; strings.json mirrors it byte-for-byte"
  - "D-02: Drop dead config.step.vehicle (no matching step_id in config_flow.py)"
  - "D-03: user step uses generic 'Select Vehicle' wording with device_tracker label"
  - "D-04: api_keys step added to config section (NYC 311 optional)"
  - "D-05: settings step gains data_description for all three fields"
  - "D-06: Both config.error and options.error blocks present with the 4 validation keys"
  - "D-07: options.step.init gains description matching settings step"
  - "D-08: Removed personal 'notify.mobile_app_yourphone' from notify_service description in both files"
  - "D-09: All 12 sensor translation keys present in entity.sensor"

patterns-established:
  - "strings.json/en.json byte-equivalence — verifiable via cmp -s"
  - "Labels carry no unit suffixes — units live exclusively in data_description"

requirements-completed:
  - UX-01
  - UX-02
  - UX-03
  - UX-04

# Metrics
duration: 3min
completed: 2026-05-02
---

# Phase 28 Plan 01: UX Copy & Strings Summary

**Synced strings.json to translations/en.json byte-for-byte and stripped the personal `notify.mobile_app_yourphone` example, fixing dead vehicle step, VW-era copy, missing api_keys step, missing error blocks, and 7 missing sensor translation keys.**

## Performance

- **Duration:** ~3 min (execution time; plan was tightly scoped to two static-JSON edits)
- **Started:** 2026-05-02T16:14:09Z
- **Completed:** 2026-05-02T16:17:27Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- `cmp -s custom_components/asp_parking/strings.json custom_components/asp_parking/translations/en.json` reports MATCH (byte-equivalent).
- All four UX requirements (UX-01..UX-04) verified by the phase-level verification block.
- Dead `config.step.vehicle` key (silently dropping its title) removed; live step_id set is exactly `{user, settings, api_keys}` for config and `{init, debug, parking_area}` for options.
- VW CarNet placeholder copy purged from both files (`grep -c "VW CarNet"` is 0).
- Personal `notify.mobile_app_yourphone` example removed from both files (`grep -c "yourphone"` is 0).
- All 12 sensor translation keys now present in `entity.sensor` (added 7: `car_name`, `vin`, `latitude`, `longitude`, `resolved_street`, `resolution_status`, `debug_mode`).
- `config.error` and `options.error` blocks added with the 4 validation keys each.
- 301 unit tests still pass (one pre-existing unrelated failure in `tests/test_suspension.py::test_is_suspended_holiday` — see Deferred Issues).

## Task Commits

Each task was committed atomically:

1. **Task 1: Apply D-08 generic copy fix to translations/en.json** — `425e496` (fix)
2. **Task 2: Rewrite strings.json to be byte-equivalent to translations/en.json** — `92247bc` (fix)

## Files Created/Modified

- `custom_components/asp_parking/translations/en.json` — replaced one line: `notify_service` data_description, dropping the `(e.g. notify.mobile_app_yourphone)` substring.
- `custom_components/asp_parking/strings.json` — rewritten to be byte-identical to the post-Task-1 `translations/en.json`. Net change: +65 / -18 lines.

## Decisions Made

None beyond what is captured in `28-CONTEXT.md` (D-01..D-10). The plan executed exactly as written.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The worktree `.venv/bin/pytest` shebang points at a typo'd path (`GSP2ASP-Resolver` instead of `GPS2ASP-Resolver`). Worked around by invoking `.venv/bin/python -m pytest`. Pre-existing environmental issue; not in scope for this plan.

## Deferred Issues

See `.planning/phases/28-ux-copy-strings/deferred-items.md`.

- `tests/test_suspension.py::test_is_suspended_holiday` fails on the plan base before any of this plan's edits (verified via `git stash`). Failure is in `gps2asp.suspension` (HolidayCalendar early-return) — completely unrelated to strings/translation JSON. Per executor scope-boundary rule, NOT fixed in this plan. Suggested follow-up: open a small bug-fix plan or repair issue. All other 301 tests pass.

## User Setup Required

None — pure static JSON edits; no environment, no migrations, no secrets.

## Next Phase Readiness

- HACS validator should now report no missing-translation warnings for strings.json.
- HA UI rendering of config/options flow titles, descriptions, field labels, and entity names will use the corrected text after the integration reloads.
- Future phases that add new config_flow steps or sensor translation keys must update both `strings.json` and `translations/en.json` together (byte-equivalence is now an invariant; a future CI check could enforce this with `cmp -s`).
- Pre-existing `test_is_suspended_holiday` failure should be tracked as a separate small bug-fix plan.

## Self-Check: PASSED

- `custom_components/asp_parking/translations/en.json` exists and contains the D-08 generic copy.
- `custom_components/asp_parking/strings.json` exists and is byte-equivalent to translations/en.json.
- Commit `425e496` exists in `git log` (Task 1).
- Commit `92247bc` exists in `git log` (Task 2).
- Phase verification block from PLAN.md: all four UX assertions pass.

---
*Phase: 28-ux-copy-strings*
*Completed: 2026-05-02*
