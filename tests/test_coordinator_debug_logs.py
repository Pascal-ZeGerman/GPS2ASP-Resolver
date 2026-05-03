"""Unit tests for coordinator changes in Phase 29-01 (D-02, D-03, D-10, D-11, D-13).

Verifies the coordinator contract:
  - ASPParkingCoordinator exposes a public async_update_listeners() method
    that aliases _async_notify_entities (D-03 / PATTERNS.md note 2).
  - In async_start, _debug_enabled is unconditionally False regardless of
    entry.options[CONF_DEBUG_ENABLED] (D-02).
  - The two error handlers in the main resolve loop log at WARNING level
    with the actionable user-facing messages (D-10, D-11, D-13).
  - The pre-seeder OutsideNYCError WARNING (~line 711) is left unchanged (D-12).
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest


COORD_PATH = (
    Path(__file__).parent.parent
    / "custom_components"
    / "asp_parking"
    / "coordinator.py"
)


def _coord_source() -> str:
    return COORD_PATH.read_text(encoding="utf-8")


def test_async_update_listeners_method_exists():
    """D-03: coordinator must expose a public async_update_listeners() method.

    The switch platform (Phase 29 / DBG-01) calls
    coordinator.async_update_listeners() after mutating _debug_enabled.
    """
    from custom_components.asp_parking.coordinator import ASPParkingCoordinator

    assert hasattr(ASPParkingCoordinator, "async_update_listeners"), (
        "ASPParkingCoordinator must define async_update_listeners() — "
        "the switch platform calls it after mutating _debug_enabled (D-03)."
    )
    method = ASPParkingCoordinator.async_update_listeners
    assert callable(method)


def test_async_update_listeners_invokes_notify_entities():
    """The public alias must invoke the private _async_notify_entities()."""
    from custom_components.asp_parking.coordinator import ASPParkingCoordinator

    # Inspect source of the public method to confirm it delegates.
    src = inspect.getsource(ASPParkingCoordinator.async_update_listeners)
    assert "_async_notify_entities" in src, (
        "async_update_listeners must call _async_notify_entities() to "
        "preserve the existing entity callback contract."
    )


def test_async_update_listeners_dispatches_to_callbacks():
    """Calling the alias on a real instance must invoke registered callbacks."""
    from custom_components.asp_parking.coordinator import ASPParkingCoordinator

    # Build a minimal fake instance — bypass __init__ to avoid HA dependency.
    coord = ASPParkingCoordinator.__new__(ASPParkingCoordinator)
    calls: list[int] = []

    def cb1():
        calls.append(1)

    def cb2():
        calls.append(2)

    coord._entity_update_callbacks = [cb1, cb2]
    coord.async_update_listeners()
    assert calls == [1, 2]


def test_async_start_initializes_debug_enabled_false_unconditionally():
    """D-02: _debug_enabled must be set to False in async_start regardless of options.

    Verified by source inspection — the legacy
    `self.entry.options.get(CONF_DEBUG_ENABLED, ...)` read MUST be gone, and
    a literal `self._debug_enabled = False` must appear inside async_start.
    """
    src = _coord_source()

    # Legacy read must be gone.
    assert "options.get(\n            CONF_DEBUG_ENABLED" not in src, (
        "async_start must no longer read CONF_DEBUG_ENABLED from entry.options (D-02)."
    )
    # The pattern with surrounding whitespace tolerance:
    assert not re.search(
        r"self\._debug_enabled\s*=\s*self\.entry\.options\.get\(\s*CONF_DEBUG_ENABLED",
        src,
    ), "async_start still contains the legacy CONF_DEBUG_ENABLED read (D-02)."

    # Two unconditional assignments must exist:
    # one in __init__ (annotated `self._debug_enabled: bool = False`),
    # one in async_start (`self._debug_enabled = False`) per D-02.
    occurrences = re.findall(
        r"self\._debug_enabled(?:\s*:\s*bool)?\s*=\s*False\b",
        src,
    )
    assert len(occurrences) == 2, (
        f"Expected exactly 2 unconditional `self._debug_enabled = False` "
        f"assignments (__init__ + async_start per D-02); found {len(occurrences)}."
    )


def test_const_imports_drop_debug_enabled_names():
    """After D-02, CONF_DEBUG_ENABLED and DEFAULT_DEBUG_ENABLED are unused in coordinator."""
    src = _coord_source()
    assert "CONF_DEBUG_ENABLED" not in src, (
        "CONF_DEBUG_ENABLED must be removed from coordinator.py (no longer referenced after D-02)."
    )
    assert "DEFAULT_DEBUG_ENABLED" not in src, (
        "DEFAULT_DEBUG_ENABLED must be removed from coordinator.py (no longer referenced after D-02)."
    )


def _join_string_continuations(src: str) -> str:
    """Concatenate adjacent string literals split across lines.

    Python source like::

        "first part"
        " -- second part"

    becomes the single runtime string ``"first part -- second part"`` after
    Python's literal-concatenation rule. This helper splices such pairs in
    raw source so substring matching can find the runtime concatenation.
    """
    # Replace `"...\n   "` with empty string (closing quote, optional comma,
    # whitespace including newline, opening quote of next adjacent literal).
    return re.sub(r'"\s*\n\s*"', "", src)


def test_outside_nyc_main_loop_logs_warning_with_actionable_message():
    """D-10, D-13: OutsideNYCError in main resolve loop emits WARNING with actionable text.

    The format string may be written in source as adjacent string literals
    split across lines for readability — at runtime they concatenate. The
    test normalizes whitespace before substring matching so either layout
    is acceptable, but the *concatenated* phrase must be present.
    """
    src_joined = _join_string_continuations(_coord_source())
    expected = (
        "GPS coordinates (%.4f, %.4f) are outside NYC coverage area"
        " -- check that your device tracker is reporting a valid NYC location"
    )
    assert expected in src_joined, (
        "Main-loop OutsideNYCError WARNING is missing or differs from spec "
        "(D-10, D-13)."
    )
    # And the legacy info-level line must be gone:
    src = _coord_source()
    assert "logger.info(\"GPS outside NYC coverage area" not in src, (
        "Legacy `logger.info(\"GPS outside NYC coverage area ...\")` must be replaced "
        "with logger.warning(...) per D-10."
    )
    # The new line must be a logger.warning call (search the immediate window).
    assert re.search(
        r"logger\.warning\(\s*\n?\s*\"GPS coordinates \(%\.4f, %\.4f\) are outside NYC coverage area\"",
        src,
    ), "OutsideNYCError handler must use logger.warning(...) for the actionable message."


def test_no_segment_handler_logs_warning_with_actionable_message():
    """D-11, D-13: NoSegmentFoundError/AmbiguousResolutionError emit WARNING with actionable text."""
    src_joined = _join_string_continuations(_coord_source())
    expected = (
        "No street segment found at (%.4f, %.4f)"
        " -- check that your device tracker is reporting accurate"
        " coordinates within a mapped NYC street: %s"
    )
    assert expected in src_joined, (
        "Main-loop NoSegmentFoundError/AmbiguousResolutionError WARNING is "
        "missing or differs from spec (D-11, D-13)."
    )
    src = _coord_source()
    assert "logger.info(\"No street match at" not in src, (
        "Legacy `logger.info(\"No street match ...\")` must be replaced with "
        "logger.warning(...) per D-11."
    )
    assert re.search(
        r"logger\.warning\(\s*\n?\s*\"No street segment found at \(%\.4f, %\.4f\)\"",
        src,
    ), "NoSegment/Ambiguous handler must use logger.warning(...) for the actionable message."


def test_preseeder_outside_nyc_warning_unchanged():
    """D-12: pre-seeder's OutsideNYCError WARNING (~line 711) must be left intact."""
    src = _coord_source()
    # Look for the distinctive pre-seeder phrase introduced in Phase 26.
    assert "Phase 26: parking area" in src, (
        "Pre-seeder OutsideNYCError WARNING (Phase 26) appears to have been "
        "removed; D-12 requires it remain unchanged."
    )
    assert "is outside NYC; " in src, (
        "Pre-seeder OutsideNYCError WARNING text was modified — D-12 says leave unchanged."
    )
