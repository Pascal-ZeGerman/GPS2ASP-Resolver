"""Options flow tests for Phase 34 CalDAV step (CALDAV-01, CALDAV-02, D-02).

Verifies the two new options-flow steps Plan 03 must add to
ASPParkingOptionsFlow:
  - async_step_caldav — auth probe via caldav_sync.validate_connection
    + chain to caldav_calendar on success (CALDAV-01).
  - async_step_caldav_calendar — calendar dropdown sourced from
    caldav_sync.list_calendars (CALDAV-02).

Locked invariants (each asserted by name in the tests below):
  - Empty CONF_CALDAV_URL = complete no-op; entry.options contains no
    CALDAV_* keys (D-02).
  - Any auth probe failure (CalDAVAuthError or generic OSError) shows
    error key 'caldav_auth_failed' (D-03 — treat all probe failures the same).
  - Failed probe MUST NOT persist bad credentials to entry.options
    (T-34-02 mitigation — security regression guard).
  - validate_connection is called with the user's just-submitted values.
  - Default title template 'ASP: {street}' (DEFAULT_CALDAV_EVENT_TITLE_TEMPLATE)
    is used when the user submits a blank string (D-04).
  - Selected calendar URL is persisted to entry.options[CONF_CALDAV_CALENDAR].
  - Custom safety window (CONF_CALDAV_SAFETY_WINDOW=30) round-trips.

RED state proof: ASPParkingOptionsFlow has no async_step_caldav method
and const.py has no CONF_CALDAV_* keys yet (Plan 03). The flow currently
ends with CREATE_ENTRY after parking_area; the tests assert
step_id == 'caldav' which will fail until Plan 03 lands.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from homeassistant.data_entry_flow import FlowResultType

from custom_components.asp_parking.const import (
    CONF_DEVICE_TRACKER,
    CONF_MOVEMENT_THRESHOLD,
    CONF_REFRESH_INTERVAL,
    CONF_STALE_TIMEOUT,
    DOMAIN,
)

# Phase 34 const names — Plan 03 will add them to const.py. Until then,
# use the literal strings locked by the plan's <interfaces> block so
# collection succeeds before Plan 03 lands.
CONF_CALDAV_URL = "caldav_url"
CONF_CALDAV_USERNAME = "caldav_username"
CONF_CALDAV_PASSWORD = "caldav_password"
CONF_CALDAV_CALENDAR = "caldav_calendar"
CONF_CALDAV_SAFETY_WINDOW = "caldav_safety_window"
CONF_CALDAV_EVENT_TITLE_TEMPLATE = "caldav_event_title_template"
DEFAULT_CALDAV_EVENT_TITLE_TEMPLATE = "ASP: {street}"


pytestmark = pytest.mark.ha_integration


# Valid input for the init step (must satisfy _validate_settings).
_INIT_INPUT: dict = {
    CONF_MOVEMENT_THRESHOLD: 50,
    CONF_REFRESH_INTERVAL: 8,
    CONF_STALE_TIMEOUT: 8,
}


def _make_entry(hass, options: dict | None = None):
    """Create + add a MockConfigEntry for the asp_parking integration."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={CONF_DEVICE_TRACKER: "device_tracker.car"},
        options=options or {},
        title="ASP Parking Monitor",
    )
    entry.add_to_hass(hass)
    return entry


async def _reach_caldav_step(hass, entry):
    """Walk the options flow init → parking_area → caldav.

    Returns the result dict for the caldav step. Until Plan 03 lands,
    this will likely return a CREATE_ENTRY (the current chain ends at
    parking_area), and the caller's `step_id == 'caldav'` assertion will
    fail — that's the RED signal.
    """
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _INIT_INPUT
    )
    # Submit empty parking_area form to advance to the caldav step (Plan 03 chain)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    return result


# ---------------------------------------------------------------------------
# D-02 — empty CONF_CALDAV_URL is a complete no-op
# ---------------------------------------------------------------------------


async def test_caldav_step_empty_url_creates_entry_no_op(
    hass, enable_custom_integrations
):
    """D-02: empty URL submission = complete no-op; NO CalDAV keys in entry.options."""
    entry = _make_entry(hass)

    result = await _reach_caldav_step(hass, entry)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "caldav"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_CALDAV_URL: ""}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY

    # D-02: no CalDAV options persisted at all
    assert CONF_CALDAV_URL not in result["data"]
    assert CONF_CALDAV_USERNAME not in result["data"]
    assert CONF_CALDAV_PASSWORD not in result["data"]
    assert CONF_CALDAV_CALENDAR not in result["data"]


# ---------------------------------------------------------------------------
# CALDAV-01 / D-03 — probe failure shows caldav_auth_failed (without persisting)
# ---------------------------------------------------------------------------


async def test_caldav_step_invalid_credentials_shows_error(
    hass, enable_custom_integrations
):
    """CALDAV-01 / D-03: CalDAVAuthError → error 'caldav_auth_failed'.

    T-34-02 mitigation: entry.options MUST NOT be mutated by a failed probe
    (no leaking of bad creds into persistent storage).
    """
    from custom_components.asp_parking.caldav_sync import CalDAVAuthError

    entry = _make_entry(hass)
    options_before = dict(entry.options)

    result = await _reach_caldav_step(hass, entry)
    assert result["step_id"] == "caldav"

    with patch(
        "custom_components.asp_parking.config_flow.caldav_sync.validate_connection",
        new_callable=AsyncMock,
        side_effect=CalDAVAuthError("bad creds"),
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_CALDAV_URL: "https://example.com/dav/",
                CONF_CALDAV_USERNAME: "u",
                CONF_CALDAV_PASSWORD: "p",
            },
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "caldav"
    assert result["errors"] == {"base": "caldav_auth_failed"}
    # T-34-02: failed probe must NOT mutate entry.options
    assert dict(entry.options) == options_before, (
        "Failed auth probe must not persist credentials (security regression T-34-02)"
    )


async def test_caldav_step_network_error_shows_same_error(
    hass, enable_custom_integrations
):
    """CALDAV-01 / D-03: ANY probe failure → same 'caldav_auth_failed' error key.

    D-03 says treat all probe failures (auth + network + DNS + TLS) the same
    to avoid leaking server-internal details to the UI.
    """
    entry = _make_entry(hass)
    options_before = dict(entry.options)

    result = await _reach_caldav_step(hass, entry)
    assert result["step_id"] == "caldav"

    with patch(
        "custom_components.asp_parking.config_flow.caldav_sync.validate_connection",
        new_callable=AsyncMock,
        side_effect=OSError("DNS failure"),
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_CALDAV_URL: "https://example.com/dav/",
                CONF_CALDAV_USERNAME: "u",
                CONF_CALDAV_PASSWORD: "p",
            },
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "caldav"
    assert result["errors"] == {"base": "caldav_auth_failed"}
    assert dict(entry.options) == options_before


# ---------------------------------------------------------------------------
# CALDAV-01 → CALDAV-02 — success chains to calendar dropdown
# ---------------------------------------------------------------------------


async def test_caldav_step_success_chains_to_calendar_step(
    hass, enable_custom_integrations
):
    """CALDAV-01 → CALDAV-02: successful probe chains to caldav_calendar with a
    populated dropdown."""
    entry = _make_entry(hass)

    result = await _reach_caldav_step(hass, entry)
    assert result["step_id"] == "caldav"

    with (
        patch(
            "custom_components.asp_parking.config_flow.caldav_sync.validate_connection",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.asp_parking.config_flow.caldav_sync.list_calendars",
            new_callable=AsyncMock,
            return_value=[
                ("https://srv/cal/work/", "Work"),
                ("https://srv/cal/personal/", "Personal"),
            ],
        ),
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_CALDAV_URL: "https://example.com/dav/",
                CONF_CALDAV_USERNAME: "u",
                CONF_CALDAV_PASSWORD: "p",
            },
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "caldav_calendar"

    # The CONF_CALDAV_CALENDAR selector should expose 2 options.
    schema = result["data_schema"]
    # voluptuous Schema → walk to find CONF_CALDAV_CALENDAR's selector options
    found_options: list = []
    for key, validator in getattr(schema, "schema", {}).items():
        key_name = getattr(key, "schema", key)
        if key_name == CONF_CALDAV_CALENDAR:
            # HA selector wraps options; selectors expose .config or are inspectable
            cfg = getattr(validator, "config", None)
            if isinstance(cfg, dict):
                found_options = list(cfg.get("options", []))
            else:
                # Fallback: voluptuous In([...]) – options are positional
                inner = getattr(validator, "container", None)
                if inner is not None:
                    found_options = list(inner)
            break
    assert len(found_options) == 2, (
        f"CONF_CALDAV_CALENDAR dropdown must expose 2 options; got {found_options!r}"
    )


# ---------------------------------------------------------------------------
# CALDAV-02 — selecting a calendar persists it (and the password carries through)
# ---------------------------------------------------------------------------


async def test_caldav_calendar_step_persists_selection(
    hass, enable_custom_integrations
):
    """CALDAV-02: selecting a calendar in the dropdown writes CONF_CALDAV_CALENDAR
    AND the password from the prior step is carried via self._options."""
    entry = _make_entry(hass)

    result = await _reach_caldav_step(hass, entry)
    assert result["step_id"] == "caldav"

    with (
        patch(
            "custom_components.asp_parking.config_flow.caldav_sync.validate_connection",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.asp_parking.config_flow.caldav_sync.list_calendars",
            new_callable=AsyncMock,
            return_value=[("https://srv/cal/work/", "Work")],
        ),
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_CALDAV_URL: "https://example.com/dav/",
                CONF_CALDAV_USERNAME: "u",
                CONF_CALDAV_PASSWORD: "secretpw",
            },
        )

    assert result["step_id"] == "caldav_calendar"

    # Submit calendar selection
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_CALDAV_CALENDAR: "https://srv/cal/work/"},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_CALDAV_CALENDAR] == "https://srv/cal/work/"

    # Password carries through self._options (was not lost between steps)
    assert result["data"].get(CONF_CALDAV_PASSWORD) == "secretpw"


# ---------------------------------------------------------------------------
# CALDAV-03 — custom safety window value round-trips
# ---------------------------------------------------------------------------


async def test_caldav_calendar_step_safety_window_persisted(
    hass, enable_custom_integrations
):
    """CALDAV-03: a non-default CONF_CALDAV_SAFETY_WINDOW value round-trips to entry.options."""
    entry = _make_entry(hass)

    result = await _reach_caldav_step(hass, entry)
    assert result["step_id"] == "caldav"

    with (
        patch(
            "custom_components.asp_parking.config_flow.caldav_sync.validate_connection",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.asp_parking.config_flow.caldav_sync.list_calendars",
            new_callable=AsyncMock,
            return_value=[("https://srv/cal/work/", "Work")],
        ),
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_CALDAV_URL: "https://example.com/dav/",
                CONF_CALDAV_USERNAME: "u",
                CONF_CALDAV_PASSWORD: "p",
                CONF_CALDAV_SAFETY_WINDOW: 30,
            },
        )

    assert result["step_id"] == "caldav_calendar"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_CALDAV_CALENDAR: "https://srv/cal/work/"},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_CALDAV_SAFETY_WINDOW] == 30


# ---------------------------------------------------------------------------
# D-04 — blank title template falls back to DEFAULT_CALDAV_EVENT_TITLE_TEMPLATE
# ---------------------------------------------------------------------------


async def test_caldav_calendar_step_default_template_used_when_blank(
    hass, enable_custom_integrations
):
    """D-04: blank CONF_CALDAV_EVENT_TITLE_TEMPLATE → fallback to 'ASP: {street}'."""
    entry = _make_entry(hass)

    result = await _reach_caldav_step(hass, entry)
    assert result["step_id"] == "caldav"

    with (
        patch(
            "custom_components.asp_parking.config_flow.caldav_sync.validate_connection",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.asp_parking.config_flow.caldav_sync.list_calendars",
            new_callable=AsyncMock,
            return_value=[("https://srv/cal/work/", "Work")],
        ),
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_CALDAV_URL: "https://example.com/dav/",
                CONF_CALDAV_USERNAME: "u",
                CONF_CALDAV_PASSWORD: "p",
                CONF_CALDAV_EVENT_TITLE_TEMPLATE: "",
            },
        )

    assert result["step_id"] == "caldav_calendar"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_CALDAV_CALENDAR: "https://srv/cal/work/"},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert (
        result["data"][CONF_CALDAV_EVENT_TITLE_TEMPLATE]
        == DEFAULT_CALDAV_EVENT_TITLE_TEMPLATE
    )


# ---------------------------------------------------------------------------
# CALDAV-01 security regression — probe runs against just-submitted creds
# ---------------------------------------------------------------------------


async def test_caldav_step_validate_connection_called_with_submitted_creds(
    hass, enable_custom_integrations
):
    """CALDAV-01 security regression: validate_connection must be called with the
    URL/username/password from THIS submission, not stale entry.options."""
    # Pre-populate entry.options with a stale URL we DO NOT want the probe to use.
    stale = {
        CONF_CALDAV_URL: "https://stale.example.com/dav/",
        CONF_CALDAV_USERNAME: "stale_user",
        CONF_CALDAV_PASSWORD: "stale_pw",
    }
    entry = _make_entry(hass, options=stale)

    result = await _reach_caldav_step(hass, entry)
    assert result["step_id"] == "caldav"

    submitted = {
        CONF_CALDAV_URL: "https://NEW.example.com/dav/",
        CONF_CALDAV_USERNAME: "new_user",
        CONF_CALDAV_PASSWORD: "new_pw",
    }

    with (
        patch(
            "custom_components.asp_parking.config_flow.caldav_sync.validate_connection",
            new_callable=AsyncMock,
        ) as mock_validate,
        patch(
            "custom_components.asp_parking.config_flow.caldav_sync.list_calendars",
            new_callable=AsyncMock,
            return_value=[("https://srv/cal/work/", "Work")],
        ),
    ):
        await hass.config_entries.options.async_configure(result["flow_id"], submitted)

    mock_validate.assert_awaited_once()
    call_kwargs = mock_validate.await_args.kwargs
    # The probe MUST run against the just-submitted values, not the stale ones.
    assert call_kwargs.get("url") == submitted[CONF_CALDAV_URL]
    assert call_kwargs.get("username") == submitted[CONF_CALDAV_USERNAME]
    assert call_kwargs.get("password") == submitted[CONF_CALDAV_PASSWORD]


# ---------------------------------------------------------------------------
# T-34-01 — password form default must be '' on re-render after error
# ---------------------------------------------------------------------------


async def test_caldav_step_invalid_credentials_password_not_echoed(
    hass, enable_custom_integrations
):
    """T-34-01 (WR-04): on form re-render after failed auth probe, the
    CONF_CALDAV_PASSWORD field's default value MUST be ``""`` -- never the
    password the user just submitted (or any stored password).

    Rationale: echoing the password back into the form leaks it to anyone
    who can shoulder-surf the screen, persists it in HA's config_flow
    state, and increases the risk surface for the credentials-in-memory
    threat. config_flow.py:643-647 hardcodes the default to ``""``; this
    test guards against an accidental refactor that re-introduces the
    echo.
    """
    from custom_components.asp_parking.caldav_sync import CalDAVAuthError

    entry = _make_entry(hass)

    result = await _reach_caldav_step(hass, entry)
    assert result["step_id"] == "caldav"

    with patch(
        "custom_components.asp_parking.config_flow.caldav_sync.validate_connection",
        new_callable=AsyncMock,
        side_effect=CalDAVAuthError("bad creds"),
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_CALDAV_URL: "https://example.com/dav/",
                CONF_CALDAV_USERNAME: "u",
                CONF_CALDAV_PASSWORD: "secret123",
            },
        )

    # Form re-rendered with the auth error
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "caldav"

    schema = result["data_schema"]
    password_default = None
    found_key = False
    for key in getattr(schema, "schema", {}):
        key_name = getattr(key, "schema", key)
        if key_name == CONF_CALDAV_PASSWORD:
            found_key = True
            default_attr = getattr(key, "default", None)
            # ``default`` is a callable (vol.UNDEFINED-like) or a value;
            # accept both shapes.
            password_default = (
                default_attr() if callable(default_attr) else default_attr
            )
            break

    assert found_key, (
        "CONF_CALDAV_PASSWORD field must be present in the re-rendered "
        "form schema after a failed auth probe"
    )
    assert password_default == "", (
        "T-34-01 regression: CONF_CALDAV_PASSWORD form default must remain "
        f"'' after error re-render to prevent credential echo. Got: {password_default!r}"
    )
