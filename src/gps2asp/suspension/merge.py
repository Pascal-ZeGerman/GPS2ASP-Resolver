"""Suspension merge layer: apply_suspension() pure function.

Annotates ScheduleFound or ASPActiveNow with suspension metadata when
ASP is suspended. Non-schedule results (NoASPSchedule, NoMatchSchedule,
AllUnparseable) pass through unchanged.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Literal

from ..schedule.models import ASPActiveNow, ScheduleFound, ScheduleResult
from . import SuspensionInfo

logger = logging.getLogger(__name__)


def apply_suspension(
    schedule: ScheduleResult,
    info: SuspensionInfo,
) -> ScheduleResult:
    """Apply suspension annotation to a schedule result.

    If info.is_suspended is False, returns schedule unchanged.
    If schedule is not ScheduleFound or ASPActiveNow, returns unchanged.
    Otherwise returns a new frozen instance with suspended=True,
    suspension_reason set to info.reason, and resolution_reason derived
    from info.source ('holiday' -> 'suspended_holiday', 'emergency' ->
    'suspended_emergency', unknown -> 'suspended_unknown').

    Args:
        schedule: Pipeline output from compute_schedule().
        info: Suspension check result from HolidayCalendar or 311 poller.

    Returns:
        Annotated ScheduleResult (same type, different field values).
    """
    if not info.is_suspended:
        return schedule

    if not isinstance(schedule, (ScheduleFound, ASPActiveNow)):
        return schedule

    resolution_reason: Literal[
        "suspended_holiday", "suspended_emergency", "suspended_unknown"
    ]
    if info.source == "holiday":
        resolution_reason = "suspended_holiday"
    elif info.source in ("emergency", "ha_nyc311"):
        resolution_reason = "suspended_emergency"
    else:
        # BUG-T-006: elevate unknown-source log to ERROR so HA diagnostics
        # surface future-introduced sources (e.g. "weather", "construction").
        # Use "suspended_unknown" so the sensor label itself signals that
        # something unexpected occurred rather than silently mis-classifying.
        logger.error(
            "apply_suspension: unknown source %r — using 'suspended_unknown'",
            info.source,
        )
        resolution_reason = "suspended_unknown"

    return dataclasses.replace(
        schedule,
        suspended=True,
        suspension_reason=info.reason,
        resolution_reason=resolution_reason,
    )


__all__ = ["apply_suspension"]
