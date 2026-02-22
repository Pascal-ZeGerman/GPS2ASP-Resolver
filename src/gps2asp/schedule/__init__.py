"""Parse ASP sign descriptions into structured schedules and compute next move time.

This module is standalone -- no Home Assistant dependency.

Public API:
    - parse_sign(): Parse a single sign description into TimeWindow objects
    - ASPDay: Day-of-week enum (Monday=0 through Sunday=6)
    - ScheduleResult union types: ScheduleFound, ASPActiveNow, NoASPSchedule,
      NoMatchSchedule, AllUnparseable
    - Supporting models: TimeWindow, CleaningWindow, WeeklySchedule, ParseFailure
"""

from __future__ import annotations

from gps2asp.schedule.models import (
    AllUnparseable,
    ASPActiveNow,
    ASPDay,
    CleaningWindow,
    NoASPSchedule,
    NoMatchSchedule,
    ParseFailure,
    ScheduleFound,
    ScheduleResult,
    TimeWindow,
    WeeklySchedule,
)

# TODO: Plan 02 -- compute_schedule() public API (merge + next_move)

__all__ = [
    "ASPDay",
    "TimeWindow",
    "CleaningWindow",
    "WeeklySchedule",
    "ParseFailure",
    "ScheduleFound",
    "ASPActiveNow",
    "NoASPSchedule",
    "NoMatchSchedule",
    "AllUnparseable",
    "ScheduleResult",
]
