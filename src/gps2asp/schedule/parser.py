"""Regex-based ASP sign description parser.

Parses raw sign description text from SODA API into structured TimeWindow
objects. Handles all observed format variations from the NYC sign catalog
(447 unique patterns, 194,504 records).

Public API:
    parse_sign(sign_description) -> list[TimeWindow] | None
"""

from __future__ import annotations

import logging
import re
from datetime import time

from gps2asp.schedule.models import ASPDay, TimeWindow

logger = logging.getLogger("gps2asp.schedule.parser")

# ---------------------------------------------------------------------------
# Day name lookup
# ---------------------------------------------------------------------------

_DAY_NAMES: dict[str, ASPDay] = {
    "MONDAY": ASPDay.MONDAY,
    "TUESDAY": ASPDay.TUESDAY,
    "WEDNESDAY": ASPDay.WEDNESDAY,
    "THURSDAY": ASPDay.THURSDAY,
    "FRIDAY": ASPDay.FRIDAY,
    "SATURDAY": ASPDay.SATURDAY,
    "SUNDAY": ASPDay.SUNDAY,
}

# Ordered list for range expansion (Monday through Sunday).
_DAY_ORDER: list[ASPDay] = [
    ASPDay.MONDAY,
    ASPDay.TUESDAY,
    ASPDay.WEDNESDAY,
    ASPDay.THURSDAY,
    ASPDay.FRIDAY,
    ASPDay.SATURDAY,
    ASPDay.SUNDAY,
]

# ---------------------------------------------------------------------------
# Compiled regex patterns
# ---------------------------------------------------------------------------

# Prefix: optional NIGHT REGULATION + mandatory NO PARKING (SANITATION BROOM
# SYMBOL) + optional MOON & STARS.
_PREFIX_RE = re.compile(
    r"^(?:NIGHT\s+REGULATION\s*\(MOON\s*&\s*STAR(?:S)?\s*SYMBOLS?\)\s*)?"
    r"NO\s+PARKING\s*\(SANITATION\s+BROOM\s+SYMBOL\)\s*"
    r"(?:MOON\s*&\s*STARS?\s*\(SYMBOLS?\)\s*)?",
    re.IGNORECASE,
)

# Suffix: arrows (<->, -->) and optional SUPERSEDES clause.
_SUFFIX_RE = re.compile(
    r"\s*(?:<-+>|--+>)\s*(?:\(SUPERSEDES\s+[^)]+\))?\s*$",  # lgtm[py/bad-tag-filter]
    re.IGNORECASE,
)

# Time window pattern: START-END where each token is a time or NOON/MIDNIGHT.
_TIME_RE = re.compile(
    r"(MIDNIGHT|NOON|\d{1,2}(?::\d{2})?(?:AM|PM))"
    r"\s*-\s*"
    r"(MIDNIGHT|NOON|\d{1,2}(?::\d{2})?(?:AM|PM))",
    re.IGNORECASE,
)

# Day range with dash: MONDAY-FRIDAY.
_DAY_RANGE_RE = re.compile(
    r"(\w+DAY)\s*-\s*(\w+DAY)",
    re.IGNORECASE,
)

# EXCEPT clause: EXCEPT SUNDAY.
_EXCEPT_RE = re.compile(
    r"EXCEPT\s+(\w+DAY)",
    re.IGNORECASE,
)

# Individual day name (whole word match).
_SINGLE_DAY_RE = re.compile(
    r"\b(" + "|".join(_DAY_NAMES.keys()) + r")\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def parse_time_token(token: str) -> time:
    """Parse a time token into a datetime.time object.

    Handles standard AM/PM times, NOON, and MIDNIGHT. Case-insensitive.

    Args:
        token: Time string like "8:30AM", "1PM", "NOON", "MIDNIGHT".

    Returns:
        Parsed datetime.time value.

    Raises:
        ValueError: If the token cannot be parsed.
    """
    token = token.strip().upper()

    if token == "NOON":
        return time(12, 0)
    if token == "MIDNIGHT":
        return time(0, 0)

    match = re.match(r"^(\d{1,2})(?::(\d{2}))?(AM|PM)$", token)
    if not match:
        raise ValueError(f"Cannot parse time token: {token!r}")

    hour = int(match.group(1))
    minute = int(match.group(2) or "0")
    period = match.group(3)

    # Handle 12-hour boundary: 12AM = midnight (0:00), 12PM = noon (12:00).
    if period == "AM" and hour == 12:
        hour = 0
    elif period == "PM" and hour != 12:
        hour += 12

    return time(hour, minute)


def extract_days(text: str) -> list[ASPDay]:
    """Extract days of week from sign description text.

    Parsing order (per research pitfall #5):
    1. EXCEPT clause: "EXCEPT SUNDAY" -> all 7 days minus excepted day
    2. Dash range: "MONDAY-FRIDAY" -> expanded range
    3. Individual day names: "TUESDAY FRIDAY" -> those specific days

    Args:
        text: Day portion of a sign description (times already removed).

    Returns:
        Sorted list of ASPDay values. Empty list if no days found.
    """
    upper_text = text.upper()

    # 1. Check for EXCEPT clause first.
    except_match = _EXCEPT_RE.search(upper_text)
    if except_match:
        excepted_name = except_match.group(1).upper()
        excepted_day = _DAY_NAMES.get(excepted_name)
        if excepted_day is not None:
            return sorted(
                [d for d in _DAY_ORDER if d != excepted_day],
                key=lambda d: d.value,
            )

    # 2. Check for dash range: MONDAY-FRIDAY.
    range_match = _DAY_RANGE_RE.search(upper_text)
    if range_match:
        start_name = range_match.group(1).upper()
        end_name = range_match.group(2).upper()
        start_day = _DAY_NAMES.get(start_name)
        end_day = _DAY_NAMES.get(end_name)
        if start_day is not None and end_day is not None:
            return sorted(
                [d for d in _DAY_ORDER if start_day <= d <= end_day],
                key=lambda d: d.value,
            )

    # 3. Find all individual day names.
    found: list[ASPDay] = []
    for match in _SINGLE_DAY_RE.finditer(upper_text):
        day = _DAY_NAMES.get(match.group(1).upper())
        if day is not None and day not in found:
            found.append(day)

    return sorted(found, key=lambda d: d.value)


def parse_sign(sign_description: str) -> list[TimeWindow] | None:
    """Parse a raw sign description into a list of TimeWindow objects.

    Returns None if the sign cannot be parsed (unrecognized prefix,
    missing time window, missing days, garbled tokens). Partial parses
    are treated as failures -- either the full sign parses cleanly or
    it is rejected entirely.

    Args:
        sign_description: Raw sign_description text from SODA API.

    Returns:
        List of TimeWindow objects (one per day) on success, or None
        on failure.
    """
    original = sign_description

    # Step 1: Strip prefix (NIGHT REGULATION + NO PARKING + MOON & STARS).
    prefix_match = _PREFIX_RE.match(sign_description)
    if not prefix_match:
        logger.warning("Unrecognized prefix, rejecting sign: %r", original)
        return None

    text = sign_description[prefix_match.end() :]

    # Step 2: Strip suffix (arrows + SUPERSEDES).
    text = _SUFFIX_RE.sub("", text)

    # Step 3: Extract time window.
    time_match = _TIME_RE.search(text)
    if not time_match:
        logger.warning("No time window found in sign: %r", original)
        return None

    # Step 4: Parse time tokens.
    try:
        start_time = parse_time_token(time_match.group(1))
        end_time = parse_time_token(time_match.group(2))
    except ValueError as exc:
        logger.warning("Failed to parse time tokens in sign %r: %s", original, exc)
        return None

    # Step 5: Validate same-day window (end > start).
    # BUG-T-004 / RESEARCH.md Pitfall 3: admit cross-midnight windows
    # (e.g. "11PM-MIDNIGHT", "10:30PM-MIDNIGHT") by truncating the end at
    # 23:59:59 on the same day. This keeps the TimeWindow within one calendar
    # day so downstream callers (merge, summary, find_active_window,
    # find_next_window) stay unchanged. MIDNIGHT-MIDNIGHT (zero-length) and
    # any other non-midnight reversal (e.g. "9AM-8AM") are still rejected.
    end_is_midnight = end_time == time(0, 0)
    if end_is_midnight and start_time > time(0, 0):
        end_time = time(23, 59, 59)
    elif end_time <= start_time:
        logger.warning(
            "Invalid time window (end <= start) in sign: %r (start=%s, end=%s)",
            original,
            start_time,
            end_time,
        )
        return None

    # Step 6: Remove time match from text, extract days from remainder.
    day_text = text[: time_match.start()] + text[time_match.end() :]
    days = extract_days(day_text)

    if not days:
        # Check if there's an EXCEPT clause in the full remaining text
        # (extract_days already handles this, but double-check).
        logger.warning("No days found in sign: %r", original)
        return None

    # Step 7: Build TimeWindow objects.
    windows = [
        TimeWindow(
            day=day,
            start_time=start_time,
            end_time=end_time,
            source_sign=original,
        )
        for day in days
    ]

    logger.debug(
        "Parsed sign %r -> %d windows: %s",
        original,
        len(windows),
        [(w.day.name, str(w.start_time), str(w.end_time)) for w in windows],
    )

    return windows
