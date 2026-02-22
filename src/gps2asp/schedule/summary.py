"""Human-readable schedule summary generation.

Generates compact text like "TUE & FRI 11:30 AM - 1:00 PM" from a
WeeklySchedule for display in Home Assistant UI and notifications.

Public API:
    format_summary(schedule) -> str
"""

from __future__ import annotations

import logging
from datetime import time

from gps2asp.schedule.models import ASPDay, WeeklySchedule

logger = logging.getLogger("gps2asp.schedule.summary")

# Abbreviated day names for summary output.
_DAY_ABBR: dict[ASPDay, str] = {
    ASPDay.MONDAY: "MON",
    ASPDay.TUESDAY: "TUE",
    ASPDay.WEDNESDAY: "WED",
    ASPDay.THURSDAY: "THU",
    ASPDay.FRIDAY: "FRI",
    ASPDay.SATURDAY: "SAT",
    ASPDay.SUNDAY: "SUN",
}

# Ordered for consecutive-day detection.
_ORDERED_DAYS: list[ASPDay] = [
    ASPDay.MONDAY,
    ASPDay.TUESDAY,
    ASPDay.WEDNESDAY,
    ASPDay.THURSDAY,
    ASPDay.FRIDAY,
    ASPDay.SATURDAY,
    ASPDay.SUNDAY,
]


def _format_time(t: time) -> str:
    """Format a time value for display.

    Uses 12-hour format. Omits minutes if :00 (e.g., "8 AM" not "8:00 AM").

    Args:
        t: Time value to format.

    Returns:
        Formatted time string like "8:30 AM", "1 PM", "12 PM".
    """
    hour = t.hour
    minute = t.minute
    period = "AM" if hour < 12 else "PM"

    # Convert to 12-hour.
    display_hour = hour % 12
    if display_hour == 0:
        display_hour = 12

    if minute == 0:
        return f"{display_hour} {period}"
    return f"{display_hour}:{minute:02d} {period}"


def _format_time_range(start: time, end: time) -> str:
    """Format a time range, simplifying same-meridiem display.

    If both times share the same meridiem (both AM or both PM), the
    meridiem is omitted from the start time: "8:30 - 10:00 AM".

    Args:
        start: Start time of the range.
        end: End time of the range.

    Returns:
        Formatted time range string.
    """
    start_period = "AM" if start.hour < 12 else "PM"
    end_period = "AM" if end.hour < 12 else "PM"

    if start_period == end_period:
        # Same meridiem: omit on start.
        start_hour = start.hour % 12
        if start_hour == 0:
            start_hour = 12
        if start.minute == 0:
            start_str = str(start_hour)
        else:
            start_str = f"{start_hour}:{start.minute:02d}"
        end_str = _format_time(end)
        return f"{start_str} - {end_str}"
    else:
        return f"{_format_time(start)} - {_format_time(end)}"


def _format_days(days: list[ASPDay]) -> str:
    """Format a list of days as a compact string.

    - Single day: "TUE"
    - Two days: "TUE & FRI"
    - Three or more consecutive: "MON-FRI"
    - Non-consecutive multiple: "MON, WED & FRI"

    Args:
        days: Sorted list of ASPDay values.

    Returns:
        Formatted day string.
    """
    if not days:
        return ""

    if len(days) == 1:
        return _DAY_ABBR[days[0]]

    if len(days) == 2:
        return f"{_DAY_ABBR[days[0]]} & {_DAY_ABBR[days[1]]}"

    # Check if days are consecutive (3+ days).
    indices = [_ORDERED_DAYS.index(d) for d in days]
    is_consecutive = all(
        indices[i + 1] == indices[i] + 1 for i in range(len(indices) - 1)
    )

    if is_consecutive and len(days) >= 3:
        return f"{_DAY_ABBR[days[0]]}-{_DAY_ABBR[days[-1]]}"

    # Non-consecutive: join with commas, last with &.
    parts = [_DAY_ABBR[d] for d in days]
    return ", ".join(parts[:-1]) + " & " + parts[-1]


def format_summary(schedule: WeeklySchedule) -> str:
    """Generate a human-readable schedule summary.

    Groups windows with identical time ranges, formats days compactly,
    and joins multiple time patterns with " / " separator.

    Args:
        schedule: The weekly ASP schedule.

    Returns:
        Summary string like "TUE & FRI 11:30 AM - 1:00 PM" or
        "No schedule" if empty.
    """
    if not schedule.windows:
        return "No schedule"

    # Group windows by (start_time, end_time).
    time_groups: dict[tuple[time, time], list[ASPDay]] = {}
    for window in schedule.windows:
        key = (window.start_time, window.end_time)
        if key not in time_groups:
            time_groups[key] = []
        if window.day not in time_groups[key]:
            time_groups[key].append(window.day)

    # Sort groups by start_time for consistent output.
    sorted_groups = sorted(time_groups.items(), key=lambda g: g[0])

    parts: list[str] = []
    for (start, end), days in sorted_groups:
        sorted_days = sorted(days, key=lambda d: d.value)
        day_str = _format_days(sorted_days)
        time_str = _format_time_range(start, end)
        parts.append(f"{day_str} {time_str}")

    result = " / ".join(parts)
    logger.debug("Generated summary: %s", result)
    return result
