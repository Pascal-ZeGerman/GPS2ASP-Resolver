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
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .models import ASPDay, CleaningWindow, WeeklySchedule

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

    Two-layer suspension contract (BUG-T-003 / RESEARCH.md Open Question 2):
    this function intentionally does NOT consult ``suspended_dates``.
    Suspension annotation is applied as a post-processing merge by
    :func:`gps2asp.suspension.merge.apply_suspension`, which flips
    ``suspended=True`` and sets ``resolution_reason`` on the resulting
    schedule. Keeping the suspension authority in the merge layer preserves
    separation of concerns and lets the same window object be reused across
    holiday / non-holiday contexts.

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

    # BUG-T-011: datetime.weekday() always returns 0-6 (Mon-Sun) and ASPDay
    # spans 0-6 — ASPDay(weekday) cannot raise ValueError under any input.
    today_day = ASPDay(now.weekday())

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
    suspended_dates: frozenset[date] | None = None,
) -> CleaningWindow | None:
    """Find the next upcoming ASP cleaning window.

    Looks ahead up to 8 calendar days (today + 7) to find the next
    window whose start time is strictly in the future.

    Args:
        schedule: The weekly ASP schedule to search.
        now: Current time (defaults to now in NYC timezone).
            If naive, NYC timezone is attached.
        suspended_dates: Set of calendar dates on which ASP is suspended
            (holidays). Candidate dates in this set are skipped.

    Returns:
        CleaningWindow for the next upcoming window, or None if no
        window found within the 8-calendar-day lookahead.
    """
    if now is None:
        now = datetime.now(NYC_TZ)
    else:
        now = _ensure_aware(now)

    # BUG-T-002: track whether the schedule had any candidate windows so we
    # can emit a cause-specific warning when no match is found.
    had_any_windows = False
    had_any_unsuspended_candidate = False

    for day_offset in range(8):
        candidate_date = now.date() + timedelta(days=day_offset)
        is_suspended = bool(suspended_dates and candidate_date in suspended_dates)

        # BUG-T-011: datetime.weekday() always returns 0-6 — ASPDay never
        # raises ValueError. The previous try/except was unreachable.
        asp_day = ASPDay(candidate_date.weekday())

        day_windows = schedule.windows_for_day(asp_day)
        if day_windows:
            had_any_windows = True
            if not is_suspended:
                had_any_unsuspended_candidate = True

        if is_suspended:
            continue

        for window in day_windows:
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

    # BUG-T-002: emit a cause-specific warning so operators can distinguish
    # an empty schedule from one whose every candidate date is suspended.
    if not had_any_windows:
        logger.warning(
            "find_next_window: no windows in schedule; cannot find next move"
        )
    elif not had_any_unsuspended_candidate:
        logger.warning(
            "find_next_window: all candidate windows in 8-day lookahead "
            "fell on suspended dates"
        )
    else:
        logger.warning("No next window found within 8-calendar-day lookahead")
    return None
