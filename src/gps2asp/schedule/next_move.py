"""Timezone-aware next-occurrence computation for ASP cleaning windows.

All datetime operations use America/New_York timezone. Computes both
the next upcoming ASP window and whether the current time falls inside
an active window.

Public API:
    find_active_window(schedule, now) -> CleaningWindow | None
    find_next_window(schedule, now) -> CleaningWindow | None
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from gps2asp.schedule.models import ASPDay, CleaningWindow, WeeklySchedule

logger = logging.getLogger("gps2asp.schedule.next_move")

NYC_TZ = ZoneInfo("America/New_York")


def _ensure_aware(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (America/New_York).

    Args:
        dt: A datetime that may or may not have tzinfo.

    Returns:
        Timezone-aware datetime in NYC timezone.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=NYC_TZ)
    return dt


def find_active_window(
    schedule: WeeklySchedule,
    now: datetime | None = None,
) -> CleaningWindow | None:
    """Check if the current time falls inside an active ASP window.

    Args:
        schedule: The weekly ASP schedule to check against.
        now: Current time (defaults to now in NYC timezone).
            If naive, NYC timezone is attached.

    Returns:
        CleaningWindow for the active window if currently inside one,
        or None if not inside any window.
    """
    if now is None:
        now = datetime.now(NYC_TZ)
    else:
        now = _ensure_aware(now)

    today_weekday = now.weekday()
    try:
        today_day = ASPDay(today_weekday)
    except ValueError:
        return None

    current_time = now.time()

    for window in schedule.windows_for_day(today_day):
        # Start is inclusive, end is exclusive.
        if window.start_time <= current_time < window.end_time:
            start_dt = datetime.combine(now.date(), window.start_time, tzinfo=NYC_TZ)
            end_dt = datetime.combine(now.date(), window.end_time, tzinfo=NYC_TZ)
            return CleaningWindow(
                day=today_day,
                start_time=window.start_time,
                end_time=window.end_time,
                start_datetime=start_dt,
                end_datetime=end_dt,
                source_signs=[window.source_sign],
            )

    return None


def find_next_window(
    schedule: WeeklySchedule,
    now: datetime | None = None,
) -> CleaningWindow | None:
    """Find the next upcoming ASP cleaning window.

    Looks ahead up to 8 calendar days (today + 7) to find the next
    window whose start time is strictly in the future.

    Args:
        schedule: The weekly ASP schedule to search.
        now: Current time (defaults to now in NYC timezone).
            If naive, NYC timezone is attached.

    Returns:
        CleaningWindow for the next upcoming window, or None if no
        window found within the 8-calendar-day lookahead.
    """
    if now is None:
        now = datetime.now(NYC_TZ)
    else:
        now = _ensure_aware(now)

    for day_offset in range(8):
        candidate_date = now.date() + timedelta(days=day_offset)
        weekday = candidate_date.weekday()

        try:
            asp_day = ASPDay(weekday)
        except ValueError:
            continue

        for window in schedule.windows_for_day(asp_day):
            window_start = datetime.combine(
                candidate_date, window.start_time, tzinfo=NYC_TZ
            )
            if window_start > now:
                window_end = datetime.combine(
                    candidate_date, window.end_time, tzinfo=NYC_TZ
                )
                logger.debug(
                    "Next window: %s %s-%s on %s",
                    asp_day.name,
                    window.start_time,
                    window.end_time,
                    candidate_date,
                )
                return CleaningWindow(
                    day=asp_day,
                    start_time=window.start_time,
                    end_time=window.end_time,
                    start_datetime=window_start,
                    end_datetime=window_end,
                    source_signs=[window.source_sign],
                )

    logger.warning("No next window found within 8-calendar-day lookahead")
    return None
