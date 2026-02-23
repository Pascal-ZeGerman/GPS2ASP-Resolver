---
phase: 04-home-assistant-integration
plan: 02
subsystem: ha-integration
tags: [homeassistant, config-flow, sensor, binary-sensor, entity, device-info]

# Dependency graph
requires:
  - phase: 04-home-assistant-integration
    plan: 01
    provides: "ASPParkingCoordinator, ASPParkingData, const.py, strings.json, services.yaml"
  - phase: 03-schedule-computation
    provides: "ScheduleResult union (ScheduleFound, ASPActiveNow, NoASPSchedule, NoMatchSchedule, AllUnparseable)"
provides:
  - "ASPParkingConfigFlow: 3-step config wizard (VW stub -> vehicle EntitySelector -> settings)"
  - "ASPParkingOptionsFlow: reconfigure thresholds without removing integration"
  - "ASPNextMoveTimeSensor: maps all ScheduleResult variants + special states to sensor values"
  - "ASPActiveNowBinarySensor: ON only during active ASP cleaning window"
  - "async_setup_entry / async_unload_entry: integration entry point with service registration"
affects: [04-03]

# Tech tracking
tech-stack:
  added: [homeassistant.helpers.selector.EntitySelector, voluptuous, homeassistant.components.sensor.SensorEntity, homeassistant.components.binary_sensor.BinarySensorEntity]
  patterns: [multi-step config flow, EntitySelector for entity dropdown, runtime_data for coordinator storage, options update listener for reload]

key-files:
  created:
    - custom_components/asp_parking/config_flow.py
    - custom_components/asp_parking/sensor.py
    - custom_components/asp_parking/binary_sensor.py
  modified:
    - custom_components/asp_parking/__init__.py

key-decisions:
  - "No device_class on sensor -- text states like 'No restrictions' break timestamp device class"
  - "mdi:car-clock icon for sensor, mdi:broom for binary sensor"
  - "Device tracker in entry.data (immutable), thresholds in entry.options (reconfigurable)"
  - "Sensor retains last known attributes when special_state is set (per user decision)"
  - "AllUnparseable and NoMatchSchedule treated as 'No restrictions' fallback"

patterns-established:
  - "Config flow: multi-step with state carried via instance vars"
  - "Entity setup: async_setup_entry reads coordinator from entry.runtime_data"
  - "Shared DeviceInfo groups entities under 'ASP Parking Monitor' device"
  - "Options reload: entry.async_on_unload(entry.add_update_listener(...))"

requirements-completed: [HA-02, HA-03]

# Metrics
duration: 2min
completed: 2026-02-22
---

# Phase 4 Plan 2: Config Flow, Sensors, and Entry Point Summary

**3-step config wizard, ASPNextMoveTimeSensor mapping all schedule variants to states, ASPActiveNowBinarySensor, and full integration entry point with service registration**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-23T01:17:31Z
- **Completed:** 2026-02-23T01:19:42Z
- **Tasks:** 2
- **Files created:** 3, modified: 1

## Accomplishments
- Config flow with 3-step wizard: VW CarNet stub, EntitySelector vehicle dropdown, threshold settings
- Options flow for reconfiguring movement threshold, refresh interval, and stale timeout
- Sensor mapping all 5 ScheduleResult variants plus special states to user-friendly values
- Rich sensor attributes across 5 groups (schedule, location, window, metadata, error)
- Binary sensor ON only during active ASP cleaning windows
- Integration entry point wiring coordinator, platforms, service, and options listener

## Task Commits

Each task was committed atomically:

1. **Task 1: Create config flow and options flow** - `44059a2` (feat)
2. **Task 2: Create sensor entity, binary sensor entity, and integration entry point** - `d4dd1f8` (feat)

## Files Created/Modified
- `custom_components/asp_parking/config_flow.py` - ASPParkingConfigFlow (3-step wizard) and ASPParkingOptionsFlow
- `custom_components/asp_parking/sensor.py` - ASPNextMoveTimeSensor with rich state attributes
- `custom_components/asp_parking/binary_sensor.py` - ASPActiveNowBinarySensor (minimal, ON during active window)
- `custom_components/asp_parking/__init__.py` - Full entry point replacing placeholder (coordinator, platforms, service, options listener)

## Decisions Made
- No device_class set on sensor because text states ("No restrictions", "Outside coverage area") break the HA timestamp device class
- mdi:car-clock for the sensor icon, mdi:broom for the binary sensor (street cleaning metaphor)
- Device tracker entity stored in entry.data (immutable after setup), thresholds in entry.options (reconfigurable)
- AllUnparseable and NoMatchSchedule both return "No restrictions" as the safest fallback
- Sensor retains last known schedule/location attributes when special_state is set (preserving context)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- All HA entity and config infrastructure complete for Plan 03 (tests)
- Integration fully wired: coordinator -> entities -> service -> options
- resolve_now service registered for manual pipeline trigger
- Both entities grouped under "ASP Parking Monitor" device

## Self-Check: PASSED

All 4 created/modified files verified on disk. Both task commits (44059a2, d4dd1f8) verified in git log.

---
*Phase: 04-home-assistant-integration*
*Completed: 2026-02-22*
