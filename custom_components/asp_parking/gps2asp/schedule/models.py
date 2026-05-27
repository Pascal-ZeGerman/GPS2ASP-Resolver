"""Data models for ASP schedule parsing and next-move computation.

All models are frozen dataclasses following project conventions.
ASPDay enum values match datetime.weekday() convention (Monday=0).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import IntEnum
from typing import Literal


class ASPDay(IntEnum):
    """Day of week for ASP schedules.

    Values match datetime.weekday() convention: Monday=0 through Sunday=6.
    Use .name for display ("MONDAY") and .value for computation (0).
    """

    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


@dataclass(frozen=True)
class TimeWindow:
    """A single time range on a single day, as parsed from one sign.

    Represents the raw parser output before merging across multiple signs.

    Attributes:
        day: Day of the week this window applies to.
        start_time: Start of the cleaning window.
        end_time: End of the cleaning window.
        source_sign: The raw sign_description text this was parsed from.
    """

    day: ASPDay
    start_time: time
    end_time: time
    source_sign: str


@dataclass(frozen=True)
class CleaningWindow:
    """A resolved upcoming cleaning window with concrete datetimes.

    Used in result types to convey both the weekly pattern (day + times)
    and the specific upcoming occurrence (start/end datetimes).

    Attributes:
        day: Day of the week.
        start_time: Weekly recurring start time.
        end_time: Weekly recurring end time.
        start_datetime: Concrete NYC-local start datetime of the next occurrence.
        end_datetime: Concrete NYC-local end datetime of the next occurrence.
        source_signs: Sign description texts that produced this window
            (may be merged from multiple signs).
    """

    day: ASPDay
    start_time: time
    end_time: time
    start_datetime: datetime
    end_datetime: datetime
    source_signs: list[str]


@dataclass(frozen=True)
class WeeklySchedule:
    """Full parsed weekly schedule for a block.

    Contains all cleaning windows sorted by day then start_time.

    Attributes:
        windows: All time windows in the schedule, sorted by
            (day, start_time).
    """

    windows: tuple[TimeWindow, ...]

    def windows_for_day(self, day: ASPDay) -> list[TimeWindow]:
        """Return all time windows for a specific day.

        Args:
            day: The day to filter on.

        Returns:
            List of TimeWindow objects for that day, preserving sort order.
        """
        return [w for w in self.windows if w.day == day]


@dataclass(frozen=True)
class ParseFailure:
    """Record of a sign description that failed to parse.

    Attributes:
        raw: The original sign_description text.
        reason: Why parsing failed (e.g., "no time window found",
            "unrecognized prefix").
    """

    raw: str
    reason: str


# ---------------------------------------------------------------------------
# ScheduleResult discriminated union (5 variants)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScheduleFound:
    """ASP schedule successfully parsed and next move window computed.

    Attributes:
        status: Discriminator literal "schedule_found".
        next_window: The next upcoming ASP cleaning window, or None if no
            upcoming window found within the 8-calendar-day lookahead
            (today + 7 future days). See find_next_window. (BUG-T-001.)
        weekly_schedule: Full parsed weekly schedule (all days/windows).
        on_street: Street name in CSCL format.
        from_street: Cross street at one end.
        to_street: Cross street at the other end.
        side_of_street: Compass direction side (N, S, E, W).
        source_signs: Original sign description texts.
        summary: Human-readable schedule summary.
        parse_failures: Signs that failed to parse (raw + reason).
        suspended: v3 suspension layer flag. Set to True when ASP is suspended.
        suspension_reason: Human-readable reason for suspension (e.g. "MLK Day").
            None when not suspended.
        resolution_reason: Machine-readable suspension classification. One of:
            'suspended_holiday' (holiday suspension),
            'suspended_emergency' (emergency/weather suspension),
            'suspended_unknown' (suspension source not recognised).
            None when not suspended / not yet annotated by apply_suspension().
    """

    status: Literal["schedule_found"]
    next_window: CleaningWindow | None
    weekly_schedule: WeeklySchedule
    on_street: str
    from_street: str
    to_street: str
    side_of_street: str
    source_signs: list[str]
    summary: str
    parse_failures: list[ParseFailure]
    # v3 suspension merge fields
    suspended: bool = False
    suspension_reason: str | None = None
    resolution_reason: (
        Literal[
            "suspended_holiday",
            "suspended_emergency",
            "suspended_unknown",
        ]
        | None
    ) = None


@dataclass(frozen=True)
class ASPActiveNow:
    """Car is currently parked during an active ASP cleaning window.

    Attributes:
        status: Discriminator literal "asp_active_now".
        active_window: The currently active cleaning window.
        on_street: Street name in CSCL format.
        from_street: Cross street at one end.
        to_street: Cross street at the other end.
        side_of_street: Compass direction side (N, S, E, W).
        source_signs: Original sign description texts.
        summary: Human-readable schedule summary.
        suspended: v3 suspension layer flag. Set to True when ASP is suspended.
        suspension_reason: Human-readable reason for suspension (e.g. "MLK Day").
            None when not suspended.
        resolution_reason: Machine-readable suspension classification. One of:
            'suspended_holiday' (holiday suspension),
            'suspended_emergency' (emergency/weather suspension),
            'suspended_unknown' (suspension source not recognised).
            None when not suspended / not yet annotated by apply_suspension().
    """

    status: Literal["asp_active_now"]
    active_window: CleaningWindow
    on_street: str
    from_street: str
    to_street: str
    side_of_street: str
    source_signs: list[str]
    summary: str
    # v3 suspension merge fields
    suspended: bool = False
    suspension_reason: str | None = None
    resolution_reason: (
        Literal[
            "suspended_holiday",
            "suspended_emergency",
            "suspended_unknown",
        ]
        | None
    ) = None


@dataclass(frozen=True)
class NoASPSchedule:
    """Phase 2 returned NoASPSigns -- no ASP on this block.

    Attributes:
        status: Discriminator literal "no_asp".
    """

    status: Literal["no_asp"] = "no_asp"


@dataclass(frozen=True)
class NoMatchSchedule:
    """Phase 2 returned NoMatchFound -- street not in SODA.

    Attributes:
        status: Discriminator literal "no_match".
    """

    status: Literal["no_match"] = "no_match"


@dataclass(frozen=True)
class AllUnparseable:
    """All signs on the block failed to parse.

    Attributes:
        status: Discriminator literal "all_unparseable".
        parse_failures: List of parse failures with raw text and reasons.
    """

    status: Literal["all_unparseable"]
    parse_failures: list[ParseFailure]


# Type alias for the full discriminated union.
ScheduleResult = (
    ScheduleFound | ASPActiveNow | NoASPSchedule | NoMatchSchedule | AllUnparseable
)
