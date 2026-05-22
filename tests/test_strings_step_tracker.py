"""Regression tests for Phase 37 — Step N of 3: prefix on config-flow step titles (CONFIG-01).

Guards that all three config-flow step titles carry the correct "Step N of 3:" prefix,
that strings.json and translations/en.json remain byte-identical (Phase 31 discipline),
and that the options-flow step titles are NOT prefixed (D-03 scope boundary).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_INTEGRATION_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "asp_parking"
_STRINGS_PATH = _INTEGRATION_DIR / "strings.json"
_EN_PATH = _INTEGRATION_DIR / "translations" / "en.json"


def test_config_step_titles_exact() -> None:
    """All 3 config-flow step titles must equal their exact Step N of 3: ... strings."""
    data = json.loads(_STRINGS_PATH.read_text(encoding="utf-8"))
    steps = data["config"]["step"]
    assert steps["user"]["title"] == "Step 1 of 3: Select Vehicle", (
        f"config.step.user.title expected 'Step 1 of 3: Select Vehicle', got {steps['user']['title']!r}"
    )
    assert steps["settings"]["title"] == "Step 2 of 3: Settings", (
        f"config.step.settings.title expected 'Step 2 of 3: Settings', got {steps['settings']['title']!r}"
    )
    assert steps["api_keys"]["title"] == "Step 3 of 3: API Keys", (
        f"config.step.api_keys.title expected 'Step 3 of 3: API Keys', got {steps['api_keys']['title']!r}"
    )


@pytest.mark.parametrize(
    "step_key,expected_prefix",
    [
        ("user", "Step 1 of 3:"),
        ("settings", "Step 2 of 3:"),
        ("api_keys", "Step 3 of 3:"),
    ],
)
def test_config_step_title_has_prefix(step_key: str, expected_prefix: str) -> None:
    """Each config-flow step title must start with the corresponding Step N of 3: prefix."""
    data = json.loads(_STRINGS_PATH.read_text(encoding="utf-8"))
    title = data["config"]["step"][step_key]["title"]
    assert title.startswith(expected_prefix), (
        f"Phase 37 regression: config.step.{step_key}.title must start with "
        f"{expected_prefix!r}. Got: {title!r}"
    )


def test_strings_and_en_json_byte_identical() -> None:
    """Phase 31 CI guard: strings.json and translations/en.json must be byte-identical."""
    strings_bytes = _STRINGS_PATH.read_bytes()
    en_bytes = _EN_PATH.read_bytes()
    assert strings_bytes == en_bytes, (
        "Phase 31 sync-guard regression: strings.json and translations/en.json "
        "must remain byte-identical. Re-run any tooling that keeps them in sync."
    )


def test_options_step_titles_not_prefixed() -> None:
    """No options-flow step title may start with 'Step' — options flow is out of scope."""
    data = json.loads(_STRINGS_PATH.read_text(encoding="utf-8"))
    options_steps = data["options"]["step"]
    for step_key, step_val in options_steps.items():
        title = step_val.get("title", "")
        assert not title.startswith("Step"), (
            f"Phase 37 boundary violation: options.step.{step_key}.title starts "
            f"with 'Step'. Options-flow titles are out of scope. Got: {title!r}"
        )
