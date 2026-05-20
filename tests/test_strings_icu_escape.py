"""Unit tests for Phase 35 ICU escape fix — strings.json / translations/en.json (CALDAV-09)."""

from __future__ import annotations

import json
import re
from pathlib import Path

# Path anchoring via __file__ (pattern from tests/test_sync_vendored.py:30-31).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_STRINGS = _REPO_ROOT / "custom_components" / "asp_parking" / "strings.json"
_EN_JSON = _REPO_ROOT / "custom_components" / "asp_parking" / "translations" / "en.json"

# Raw-placeholder regression regex: match `{word}` ONLY when neither flanking
# character is an ASCII apostrophe (U+0027). Used in Tests 1, 2, 4.
_RAW_PLACEHOLDER_RE = re.compile(r"(?<!')\{[a-z_]+\}(?!')")


def test_caldav_event_title_template_is_icu_escaped() -> None:
    """Tooltip on line 115 must wrap every literal `{name}` in ASCII apostrophes.

    Expected wrapped occurrences: '{street}' x2, '{time}' x1, '{side}' x1
    (4 placeholders total — "Placeholders:" group plus the "Default:" clause).
    """
    data = json.loads(_STRINGS.read_text(encoding="utf-8"))
    value = data["options"]["step"]["caldav"]["data_description"][
        "caldav_event_title_template"
    ]
    # ICU-escaped occurrences (the fix).
    assert value.count("'{street}'") == 2, (
        f"Expected 2 occurrences of '{{street}}', got {value.count(chr(39) + '{street}' + chr(39))} in: {value!r}"
    )
    assert value.count("'{time}'") == 1, (
        f"Expected 1 occurrence of '{{time}}', got {value.count(chr(39) + '{time}' + chr(39))} in: {value!r}"
    )
    assert value.count("'{side}'") == 1, (
        f"Expected 1 occurrence of '{{side}}', got {value.count(chr(39) + '{side}' + chr(39))} in: {value!r}"
    )
    # No raw placeholder (i.e., {name} NOT flanked by apostrophes) must remain.
    assert not re.search(r"(?<!')\{street\}(?!')", value), (
        f"Raw {{street}} placeholder still present in: {value!r}"
    )
    assert not re.search(r"(?<!')\{time\}(?!')", value), (
        f"Raw {{time}} placeholder still present in: {value!r}"
    )
    assert not re.search(r"(?<!')\{side\}(?!')", value), (
        f"Raw {{side}} placeholder still present in: {value!r}"
    )


def test_caldav_invalid_template_is_icu_escaped() -> None:
    """Error string on line 132 must wrap every literal `{name}` in ASCII apostrophes.

    Expected wrapped occurrences: '{street}' x1, '{side}' x1, '{time}' x1
    (3 placeholders total — note '{side}' precedes '{time}' on this line).
    """
    data = json.loads(_STRINGS.read_text(encoding="utf-8"))
    value = data["options"]["error"]["caldav_invalid_template"]
    assert value.count("'{street}'") == 1, (
        f"Expected 1 occurrence of '{{street}}', got {value.count(chr(39) + '{street}' + chr(39))} in: {value!r}"
    )
    assert value.count("'{side}'") == 1, (
        f"Expected 1 occurrence of '{{side}}', got {value.count(chr(39) + '{side}' + chr(39))} in: {value!r}"
    )
    assert value.count("'{time}'") == 1, (
        f"Expected 1 occurrence of '{{time}}', got {value.count(chr(39) + '{time}' + chr(39))} in: {value!r}"
    )
    # No raw placeholders must remain in the error string either.
    assert not re.search(r"(?<!')\{street\}(?!')", value), (
        f"Raw {{street}} placeholder still present in: {value!r}"
    )
    assert not re.search(r"(?<!')\{side\}(?!')", value), (
        f"Raw {{side}} placeholder still present in: {value!r}"
    )
    assert not re.search(r"(?<!')\{time\}(?!')", value), (
        f"Raw {{time}} placeholder still present in: {value!r}"
    )


def test_strings_and_en_json_byte_identical() -> None:
    """Phase 31 discipline: strings.json and translations/en.json must be byte-identical.

    Acts as a regression guard against one-file-only edits (Pitfall 1 in RESEARCH.md).
    Starts GREEN today (files are currently in sync); must remain GREEN after Task 2.
    """
    assert _STRINGS.read_bytes() == _EN_JSON.read_bytes(), (
        "strings.json and translations/en.json have diverged — one-file-only edit?"
    )


def test_no_raw_curly_placeholders() -> None:
    """Belt-and-suspenders regression guard: no raw `{name}` token may survive in either JSON file.

    Scans the full text of each file for `{word}` tokens NOT flanked by ASCII apostrophes.
    Catches missed-line drift not covered by the two key-targeted tests above
    (RESEARCH.md §Validation Architecture).
    """
    for path in (_STRINGS, _EN_JSON):
        text = path.read_text(encoding="utf-8")
        matches = _RAW_PLACEHOLDER_RE.findall(text)
        assert matches == [], f"{path.name}: raw placeholders found: {matches}"
