"""Parse ASP sign descriptions into structured schedules and compute next move time.

This module is standalone -- no Home Assistant dependency.

Public API:
    - compute_schedule(): Main entry point -- accepts SignRetrievalResult, returns ScheduleResult
    - parse_sign(): Parse a single sign description into TimeWindow objects
    - merge_windows(): Merge overlapping windows from multiple signs
    - find_next_window(): Find the next upcoming ASP cleaning window
    - find_active_window(): Check if currently inside an ASP window
    - format_summary(): Generate human-readable schedule summary
    - ASPDay: Day-of-week enum (Monday=0 through Sunday=6)
    - ScheduleResult union types: ScheduleFound, ASPActiveNow, NoASPSchedule,
      NoMatchSchedule, AllUnparseable
    - Supporting models: TimeWindow, CleaningWindow, WeeklySchedule, ParseFailure
"""

from __future__ import annotations

import logging
from datetime import datetime

from gps2asp.schedule.merge import merge_windows
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
from gps2asp.schedule.next_move import find_active_window, find_next_window
from gps2asp.schedule.parser import parse_sign
from gps2asp.schedule.summary import format_summary
from gps2asp.signs.models import (
    NoASPSigns,
    NoMatchFound,
    SignRetrievalResult,
    SignRetrievalSuccess,
)

logger = logging.getLogger("gps2asp.schedule")

__all__ = [
    "compute_schedule",
    "parse_sign",
    "merge_windows",
    "find_next_window",
    "find_active_window",
    "format_summary",
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


def compute_schedule(
    sign_result: SignRetrievalResult,
    now: datetime | None = None,
) -> ScheduleResult:
    """Compute ASP schedule from sign retrieval results.

    Main entry point for the schedule computation pipeline. Accepts the
    full Phase 2 discriminated union and returns the appropriate
    ScheduleResult variant.

    Args:
        sign_result: Result from Phase 2 sign retrieval (SignRetrievalSuccess,
            NoASPSigns, or NoMatchFound).
        now: Current time for next-window computation. Defaults to now in
            America/New_York timezone. Use explicit value for testing.

    Returns:
        ScheduleResult variant:
        - NoASPSchedule if input is NoASPSigns
        - NoMatchSchedule if input is NoMatchFound
        - AllUnparseable if all signs fail to parse
        - ASPActiveNow if currently inside an ASP window
        - ScheduleFound with next_window for normal case
    """
    # Route non-success variants directly.
    if isinstance(sign_result, NoASPSigns):
        logger.info("No ASP signs on this block")
        return NoASPSchedule(status="no_asp")

    if isinstance(sign_result, NoMatchFound):
        logger.info("No matching street found in SODA")
        return NoMatchSchedule(status="no_match")

    # SignRetrievalSuccess: parse each sign.
    # Use explicit TypeError rather than assert (assert can be stripped by -O).
    if not isinstance(sign_result, SignRetrievalSuccess):
        raise TypeError(
            f"Expected SignRetrievalSuccess, got {type(sign_result).__name__}"
        )

    all_windows: list[TimeWindow] = []
    parse_failures: list[ParseFailure] = []

    for sign in sign_result.signs:
        result = parse_sign(sign.sign_description)
        if result is None:
            failure = ParseFailure(
                raw=sign.sign_description,
                reason="Failed to parse sign description",
            )
            parse_failures.append(failure)
            logger.warning(
                "Parse failure for sign: %r", sign.sign_description
            )
        else:
            all_windows.extend(result)

    # All signs failed to parse.
    if not all_windows:
        logger.info(
            "All %d signs failed to parse", len(sign_result.signs)
        )
        return AllUnparseable(
            status="all_unparseable",
            parse_failures=parse_failures,
        )

    # Merge windows from all successfully parsed signs.
    merged_schedule = merge_windows(all_windows)

    # Generate human-readable summary.
    summary = format_summary(merged_schedule)

    # Street info passthrough.
    on_street = sign_result.on_street
    from_street = sign_result.from_street
    to_street = sign_result.to_street
    side_of_street = sign_result.side_of_street
    source_signs = [s.sign_description for s in sign_result.signs]

    # Check for active window first.
    active = find_active_window(merged_schedule, now)
    if active is not None:
        logger.info("ASP is active NOW on %s", on_street)
        return ASPActiveNow(
            status="asp_active_now",
            active_window=active,
            on_street=on_street,
            from_street=from_street,
            to_street=to_street,
            side_of_street=side_of_street,
            source_signs=source_signs,
            summary=summary,
        )

    # Find next upcoming window.
    next_win = find_next_window(merged_schedule, now)

    logger.info(
        "Schedule found on %s: next window %s",
        on_street,
        next_win.day.name if next_win else "None",
    )

    return ScheduleFound(
        status="schedule_found",
        next_window=next_win,  # CleaningWindow | None — find_next_window returns None only when WeeklySchedule has no windows
        weekly_schedule=merged_schedule,
        on_street=on_street,
        from_street=from_street,
        to_street=to_street,
        side_of_street=side_of_street,
        source_signs=source_signs,
        summary=summary,
        parse_failures=parse_failures,
    )
