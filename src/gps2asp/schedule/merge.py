"""Window merging for multi-sign ASP blocks.

Combines overlapping or adjacent time windows from multiple signs into
a single merged WeeklySchedule. Uses conservative merging: earliest start,
latest end (safer for avoiding tickets per user decision).

Public API:
    merge_windows(windows) -> WeeklySchedule
"""

from __future__ import annotations

import logging
from itertools import groupby

from gps2asp.schedule.models import ASPDay, TimeWindow, WeeklySchedule

logger = logging.getLogger("gps2asp.schedule.merge")


def merge_windows(windows: list[TimeWindow]) -> WeeklySchedule:
    """Merge overlapping/adjacent time windows into a WeeklySchedule.

    Groups windows by day, then merges any overlapping or adjacent windows
    within each day using conservative logic (earliest start, latest end).
    Source sign lists are concatenated for merged windows.

    Note on provenance representations:
        TimeWindow.source_sign: semicolon-joined string of contributing sign
            descriptions for this merged window (e.g. "SIGN A; SIGN B").
        ScheduleFound.source_signs: the raw pre-merge list of all sign
            descriptions on the block.
        These two are different representations of provenance and are not
        expected to be identical.

    Args:
        windows: Flat list of TimeWindow objects from all parsed signs.

    Returns:
        WeeklySchedule with merged, non-overlapping windows sorted by
        (day, start_time).
    """
    if not windows:
        return WeeklySchedule(windows=())

    # Group by day, sort within each day by start_time.
    sorted_windows = sorted(windows, key=lambda w: (w.day.value, w.start_time))
    merged: list[TimeWindow] = []

    for _day, day_group in groupby(sorted_windows, key=lambda w: w.day):
        day_windows = list(day_group)
        # Start with the first window in this day.
        current_start = day_windows[0].start_time
        current_end = day_windows[0].end_time
        current_sources: list[str] = [day_windows[0].source_sign]
        current_day = day_windows[0].day

        for w in day_windows[1:]:
            if w.start_time <= current_end:
                # Overlapping or adjacent: extend conservatively.
                if w.end_time > current_end:
                    current_end = w.end_time
                if w.source_sign not in current_sources:
                    current_sources.append(w.source_sign)
                logger.debug(
                    "Merged overlapping window on %s: extended to %s-%s",
                    current_day.name,
                    current_start,
                    current_end,
                )
            else:
                # No overlap: emit current, start new.
                merged.append(
                    TimeWindow(
                        day=current_day,
                        start_time=current_start,
                        end_time=current_end,
                        source_sign="; ".join(current_sources),
                    )
                )
                current_start = w.start_time
                current_end = w.end_time
                current_sources = [w.source_sign]

        # Emit the last window for this day.
        merged.append(
            TimeWindow(
                day=current_day,
                start_time=current_start,
                end_time=current_end,
                source_sign="; ".join(current_sources),
            )
        )

    result = WeeklySchedule(windows=tuple(merged))
    logger.debug(
        "Merged %d input windows into %d output windows",
        len(windows),
        len(merged),
    )
    return result
