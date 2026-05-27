"""Regression tests for Phase 35 — ICU-escape curly placeholders in i18n strings.

Background:
    Home Assistant's frontend uses FormatJS (intl-messageformat) to render
    strings from `strings.json` / `translations/en.json`. Any `{name}` token
    inside a human-readable string is interpreted as a FormatJS argument
    slot. If no corresponding argument is passed at render time, FormatJS
    raises a ``MISSING_VALUE`` error and the entire string fails to render —
    leaving the user with an empty tooltip or blank error message.

    For description / error messages that mention placeholder names purely
    as documentation (not as render-time arguments), the curly braces must
    be ICU-escaped. The preferred form isolates each brace in its own
    single-quoted escape so the identifier is not inside quotes:
    ``'{'street'}'`` (ICU: ``'{'`` = literal ``{``, ``street`` = literal
    text, ``'}'`` = literal ``}``). This form is accepted by hassfest which
    rejects the older ``'{street}'`` pattern (identifier inside quotes).

These tests guard against regression of the Phase 35 headline fix.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_INTEGRATION_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "asp_parking"
_STRINGS_PATH = _INTEGRATION_DIR / "strings.json"
_EN_PATH = _INTEGRATION_DIR / "translations" / "en.json"


def _load_strings() -> dict:
    return json.loads(_STRINGS_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("strings_path", [_STRINGS_PATH, _EN_PATH])
def test_caldav_event_title_template_is_icu_escaped(strings_path: Path) -> None:
    """The caldav_event_title_template description must use '{'street'}' (ICU-escaped).

    The brace-escape form ``'{'name'}'`` is used instead of ``'{name}'`` because
    hassfest rejects identifiers inside single-quoted ICU escape sequences.
    """
    data = json.loads(strings_path.read_text(encoding="utf-8"))
    description = data["options"]["step"]["caldav"]["data_description"][
        "caldav_event_title_template"
    ]
    assert "'{'street'}'" in description, (
        "Phase 35 regression: caldav_event_title_template description must "
        "contain ICU-escaped '{'street'}' to prevent FormatJS MISSING_VALUE errors. "
        f"Got: {description!r}"
    )
    # The description references three placeholder names — all must be escaped.
    assert "'{'time'}'" in description
    assert "'{'side'}'" in description


def test_caldav_invalid_template_is_icu_escaped() -> None:
    """The caldav_invalid_template error must use '{'street'}', '{'side'}', '{'time'}'."""
    data = _load_strings()
    error = data["options"]["error"]["caldav_invalid_template"]
    assert "'{'street'}'" in error, (
        "Phase 35 regression: caldav_invalid_template must contain ICU-escaped "
        "'{'street'}' to prevent FormatJS MISSING_VALUE errors. "
        f"Got: {error!r}"
    )
    assert "'{'side'}'" in error
    assert "'{'time'}'" in error


def test_strings_and_en_json_byte_identical() -> None:
    """Phase 31 CI guard: strings.json and translations/en.json must be byte-identical."""
    strings_bytes = _STRINGS_PATH.read_bytes()
    en_bytes = _EN_PATH.read_bytes()
    assert strings_bytes == en_bytes, (
        "Phase 31 sync-guard regression: strings.json and translations/en.json "
        "must remain byte-identical. Re-run any tooling that keeps them in sync."
    )


@pytest.mark.parametrize("strings_path", [_STRINGS_PATH, _EN_PATH])
@pytest.mark.parametrize(
    "key_path",
    [
        ("options", "step", "caldav", "data_description", "caldav_event_title_template"),
        ("options", "error", "caldav_invalid_template"),
    ],
)
def test_no_raw_curly_placeholders(key_path: tuple, strings_path: Path) -> None:
    """No unescaped {street}/{time}/{side} placeholders may appear in caldav strings.

    After ICU-escaping, any occurrence of {street}, {time}, or {side} in
    these strings must be wrapped in single quotes — i.e. ``'{street}'``,
    never bare ``{street}``.
    """
    data = json.loads(strings_path.read_text(encoding="utf-8"))
    value = data
    for part in key_path:
        value = value[part]
    assert isinstance(value, str), f"Expected string at {key_path}, got {type(value)}"

    # For each placeholder name, find all occurrences and verify each is
    # preceded by a single quote and followed by a single quote.
    for name in ("street", "time", "side"):
        # Find every '{name}' span — both escaped and bare.
        for match in re.finditer(r"\{" + re.escape(name) + r"\}", value):
            start, end = match.span()
            prev_char = value[start - 1] if start > 0 else ""
            next_char = value[end] if end < len(value) else ""
            assert prev_char == "'" and next_char == "'", (
                f"Phase 35 regression: unescaped placeholder {match.group()!r} found "
                f"in {'.'.join(key_path)}. All curly placeholders in i18n description / "
                f"error strings must be ICU-escaped as '{name}'. "
                f"Context: ...{value[max(0, start - 10):min(len(value), end + 10)]}..."
            )
