---
phase: 23-ha-nyc311-bridge
plan: 01
subsystem: coordinator, suspension
tags: [bridge, ha-nyc311, suspension, coordinator, binary-sensor]
dependency_graph:
  requires:
    - 22-02 (coordinator suspension wiring, NYC311Client, config flow)
    - 21-01 (NYC311Client poller)
    - 19-01 (HolidayCalendar, SuspensionInfo)
  provides:
    - ha-nyc311 bridge detection at coordinator startup
    - immediate state-change propagation via subscription
    - suspension poll short-circuit when bridge healthy
  affects:
    - coordinator.py (bridge detection, subscription, poll-skip)
    - const.py (CONF_NYC311_ENTITY, DEFAULT_NYC311_BRIDGE_ENTITY)
    - suspension __init__.py in both src/ and custom_components/ (ha_nyc311 Literal)
tech_stack:
  added: []
  patterns:
    - async_track_state_change_event for ha-nyc311 entity subscription (same pattern as GPS tracker)
    - _listeners list for unsub callable management
    - fail-open on unavailable/unknown bridge state (source='none')
key_files:
  created: []
  modified:
    - custom_components/asp_parking/const.py
    - custom_components/asp_parking/coordinator.py
    - custom_components/asp_parking/gps2asp/suspension/__init__.py
    - src/gps2asp/suspension/__init__.py
decisions:
  - Bridge detection at startup only (no dynamic re-detection mid-session)
  - Bridge entity chosen via auto-detect (DEFAULT_NYC311_BRIDGE_ENTITY) or user override (CONF_NYC311_ENTITY)
  - Bridge fails open on unavailable/unknown state (source='none', is_suspended=False)
  - Poll timer kept registered; short-circuits to bridge state when healthy
metrics:
  duration_minutes: 12
  completed_date: "2026-04-05"
  tasks_completed: 2
  files_modified: 4
---

# Phase 23 Plan 01: ha-nyc311 Bridge - Constants, Literals, and Coordinator Wiring Summary

**One-liner:** ha-nyc311 bridge wired into coordinator via async_track_state_change_event with fail-open fallback and poll-skip short-circuit.

## What Was Built

Task 1 added three constants to `const.py` (`CONF_NYC311_ENTITY`, `DEFAULT_NYC311_ENTITY`, `DEFAULT_NYC311_BRIDGE_ENTITY`) and updated `SuspensionInfo.source` Literal in both `src/` and `custom_components/` copies to include `'ha_nyc311'`.

Task 2 wired the full bridge into `coordinator.py`:
- `_nyc311_bridge_entity: str | None` instance variable
- Bridge detection in `async_start()`: auto-detects `binary_sensor.nyc311_parking_exception_today` or uses user-specified entity from `CONF_NYC311_ENTITY` options
- `async_track_state_change_event` subscription on bridge entity, unsub stored in `_listeners`
- `_bridge_state_to_info()` static method: maps `on` → suspended with reason attribute, `off` → not suspended, `unavailable`/`unknown` → fail-open with warning log
- `_async_on_nyc311_state_change()` callback: immediately converts state and calls `_async_notify_entities()`
- `_async_update_suspension()` short-circuit: when bridge entity state is `on` or `off`, skips holiday calendar and 311 API
- `_async_initial_311_fetch()` guard: returns early if bridge is active

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | 39be707 | feat(23-01): add NYC311 bridge constants and ha_nyc311 source Literal |
| 2 | 18c1522 | feat(23-01): wire ha-nyc311 bridge detection, subscription, and poll-skip into coordinator |

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None - all bridge logic is fully wired. Data flows from ha-nyc311 entity state through `_bridge_state_to_info` to `SuspensionInfo` to entities.

## Threat Flags

No new network endpoints, auth paths, or file access patterns introduced. CONF_NYC311_ENTITY user input is passed through `hass.states.get()` which returns None for invalid entity IDs (fail-open per T-23-02 mitigation). T-23-03 fallback (bridge stuck unavailable falls through to 311 API + holiday calendar) is implemented in `_async_update_suspension`.

## Self-Check: PASSED

- custom_components/asp_parking/const.py — contains CONF_NYC311_ENTITY, DEFAULT_NYC311_BRIDGE_ENTITY
- custom_components/asp_parking/coordinator.py — contains _nyc311_bridge_entity, _bridge_state_to_info, _async_on_nyc311_state_change, bridge short-circuit in _async_update_suspension
- custom_components/asp_parking/gps2asp/suspension/__init__.py — contains ha_nyc311 in Literal
- src/gps2asp/suspension/__init__.py — contains ha_nyc311 in Literal
- Commits 39be707 and 18c1522 exist in git log
- 262 tests pass (1 pre-existing spatial index failure unrelated to this plan)
