"""Config flow and options flow for the ASP Parking integration.

Three-step setup wizard:
  1. Vehicle device_tracker selection (EntitySelector dropdown)
  2. Threshold settings with NumberSelector widgets and validation
  3. Optional NYC 311 API key for weather/emergency suspension alerts

Options flow allows reconfiguring thresholds and API key without removing
the integration. Shared helpers (_settings_schema, _validate_settings) keep
both flows in sync.
"""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

# Phase 34: caldav_sync is provided by Plan 02 (parallel wave). Import at
# module level so unittest.mock.patch("...config_flow.caldav_sync.*") can
# resolve the attribute. In the brief window before Plan 02 merges (and
# in case the optional caldav dependency is missing at runtime) we fall
# back to a sentinel module so config_flow remains importable; the new
# caldav step methods will surface a translated error if invoked before
# Plan 02 lands.
try:
    from . import caldav_sync
except ImportError:  # pragma: no cover - parallel-wave merge fallback
    import sys as _sys
    import types as _types

    caldav_sync = _types.ModuleType(  # type: ignore[assignment]
        "custom_components.asp_parking.caldav_sync"
    )

    class _MissingCalDAVAuthError(Exception):
        """Fallback CalDAVAuthError until Plan 02's module is merged."""

    async def _missing_validate_connection(
        *, url: str, username: str, password: str
    ) -> None:  # pragma: no cover
        raise _MissingCalDAVAuthError(
            "caldav_sync module not yet installed; rerun setup after merge"
        )

    async def _missing_list_calendars(
        *, url: str, username: str, password: str
    ) -> list[tuple[str, str]]:  # pragma: no cover
        return []

    caldav_sync.CalDAVAuthError = _MissingCalDAVAuthError  # type: ignore[assignment, misc]
    caldav_sync.validate_connection = _missing_validate_connection  # type: ignore[attr-defined]
    caldav_sync.list_calendars = _missing_list_calendars  # type: ignore[attr-defined]
    # Register in sys.modules so `from custom_components.asp_parking import
    # caldav_sync` (and submodule imports from tests) resolve to this stub.
    _sys.modules["custom_components.asp_parking.caldav_sync"] = caldav_sync

from .const import (
    CONF_CALDAV_APPLE_RADIUS_M,
    CONF_CALDAV_CALENDAR,
    CONF_CALDAV_EVENT_TITLE_TEMPLATE,
    CONF_CALDAV_INCLUDE_LOCATION,
    CONF_CALDAV_PASSWORD,
    CONF_CALDAV_SAFETY_WINDOW,
    CONF_CALDAV_URL,
    CONF_CALDAV_USERNAME,
    CONF_DEBUG_DATETIME,
    CONF_DEBUG_LAT,
    CONF_DEBUG_LON,
    CONF_DEVICE_TRACKER,
    CONF_MOVEMENT_THRESHOLD,
    CONF_NOTIFY_LEAD_TIME,
    CONF_NOTIFY_SERVICE,
    CONF_NYC311_API_KEY,
    CONF_NYC311_ENTITY,
    CONF_PARKING_LAT,
    CONF_PARKING_LON,
    CONF_PARKING_RADIUS,
    CONF_REFRESH_INTERVAL,
    CONF_STALE_TIMEOUT,
    CONF_SUPPRESS_NOTIFICATIONS,
    DEFAULT_CALDAV_APPLE_RADIUS_M,
    DEFAULT_CALDAV_EVENT_TITLE_TEMPLATE,
    DEFAULT_CALDAV_INCLUDE_LOCATION,
    DEFAULT_CALDAV_SAFETY_WINDOW,
    DEFAULT_MOVEMENT_THRESHOLD,
    DEFAULT_NOTIFY_LEAD_TIME,
    DEFAULT_NOTIFY_SERVICE,
    DEFAULT_PARKING_RADIUS,
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_STALE_TIMEOUT,
    DOMAIN,
)
from .gps2asp.suspension import NYC311Client
from .gps2asp.suspension.poller import NYC311AuthError

# Allowed characters in a CalDAV event title template: printable text plus
# the {placeholder} syntax. Rejects attribute access ({x.y}) and index
# access ({x[y]}) to prevent unintended format_map surface area.
_TEMPLATE_RE = re.compile(r"^[^{}]*(?:\{[A-Za-z_][A-Za-z0-9_]*\}[^{}]*)*$")


def _settings_schema(
    movement_threshold: float = DEFAULT_MOVEMENT_THRESHOLD,
    refresh_interval: int = DEFAULT_REFRESH_INTERVAL,
    stale_timeout: int = DEFAULT_STALE_TIMEOUT,
) -> vol.Schema:
    """Return the settings schema with NumberSelector widgets.

    Shared between the config flow settings step and the options flow
    so both always render identically.
    """
    return vol.Schema(
        {
            vol.Optional(CONF_MOVEMENT_THRESHOLD, default=movement_threshold): (
                selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=10_000,
                        step=1,
                        unit_of_measurement="m",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                )
            ),
            vol.Optional(CONF_REFRESH_INTERVAL, default=refresh_interval): (
                selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=168,
                        step=1,
                        unit_of_measurement="h",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                )
            ),
            vol.Optional(CONF_STALE_TIMEOUT, default=stale_timeout): (
                selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=168,
                        step=1,
                        unit_of_measurement="h",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                )
            ),
        }
    )


def _validate_settings(
    user_input: dict,
) -> tuple[dict[str, float | int], dict[str, str]]:
    """Coerce types and validate settings values.

    NumberSelector always returns float; refresh_interval and stale_timeout
    are cast to int. Returns (cleaned_data, errors).
    """
    errors: dict[str, str] = {}

    movement_threshold = float(
        user_input.get(CONF_MOVEMENT_THRESHOLD, DEFAULT_MOVEMENT_THRESHOLD)
    )
    refresh_interval = int(
        user_input.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL)
    )
    stale_timeout = int(user_input.get(CONF_STALE_TIMEOUT, DEFAULT_STALE_TIMEOUT))

    if movement_threshold < 1:
        errors[CONF_MOVEMENT_THRESHOLD] = "movement_threshold_too_small"
    if refresh_interval < 1:
        errors[CONF_REFRESH_INTERVAL] = "refresh_interval_too_small"
    if stale_timeout < 1:
        errors[CONF_STALE_TIMEOUT] = "stale_timeout_too_small"

    return (
        {
            CONF_MOVEMENT_THRESHOLD: movement_threshold,
            CONF_REFRESH_INTERVAL: refresh_interval,
            CONF_STALE_TIMEOUT: stale_timeout,
        },
        errors,
    )


class ASPParkingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Two-step config flow for ASP Parking Monitor.

    Step 1 (user): Select device_tracker entity via dropdown.
    Step 2 (settings): Configure movement threshold, refresh interval, stale timeout.
    """

    VERSION = 2

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._device_tracker: str = ""
        self._settings: dict = {}

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 1: Select the device_tracker entity."""
        if user_input is not None:
            self._device_tracker = user_input[CONF_DEVICE_TRACKER]
            return await self.async_step_settings()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_TRACKER): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="device_tracker"),
                    ),
                }
            ),
        )

    async def async_step_settings(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2: Configure thresholds."""
        errors: dict[str, str] = {}

        if user_input is not None:
            cleaned, errors = _validate_settings(user_input)
            if not errors:
                self._settings = cleaned
                return await self.async_step_api_keys()

        return self.async_show_form(
            step_id="settings",
            data_schema=_settings_schema(),
            errors=errors,
        )

    async def async_step_api_keys(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 3: Optional NYC 311 API key for weather/emergency suspensions."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api_key = user_input.get(CONF_NYC311_API_KEY, "").strip() or None
            if api_key:
                try:
                    client = NYC311Client(api_key=api_key)
                    await client.fetch_status()
                except NYC311AuthError:
                    errors[CONF_NYC311_API_KEY] = "invalid_api_key"
                except Exception:  # noqa: BLE001
                    pass  # Network error during validation -- accept key anyway
            if not errors:
                options = {**self._settings}
                if api_key:
                    options[CONF_NYC311_API_KEY] = api_key
                return self.async_create_entry(
                    title="ASP Parking Monitor",
                    data={CONF_DEVICE_TRACKER: self._device_tracker},
                    options=options,
                )

        return self.async_show_form(
            step_id="api_keys",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_NYC311_API_KEY, default=""
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ASPParkingOptionsFlow:
        """Return the options flow handler."""
        return ASPParkingOptionsFlow()


class ASPParkingOptionsFlow(config_entries.OptionsFlow):
    """Options flow for reconfiguring ASP Parking thresholds.

    Allows changing movement threshold, refresh interval, and stale timeout
    without removing and re-adding the integration.
    self.config_entry is injected by HA's OptionsFlow base class.
    """

    def __init__(self) -> None:
        """Initialize the options flow."""
        self._options: dict = {}

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        """Present options form with current values as defaults."""
        errors: dict[str, str] = {}

        if user_input is not None:
            cleaned, errors = _validate_settings(user_input)
            nyc311_entity = (user_input.get(CONF_NYC311_ENTITY) or "").strip()
            api_key = (user_input.get(CONF_NYC311_API_KEY) or "").strip() or None
            if api_key:
                try:
                    client = NYC311Client(api_key=api_key)
                    await client.fetch_status()
                except NYC311AuthError:
                    errors[CONF_NYC311_API_KEY] = "invalid_api_key"
                except Exception:  # noqa: BLE001
                    pass  # Network error during validation -- accept key anyway
            if not errors:
                options: dict[str, Any] = {**cleaned}
                if nyc311_entity:
                    options[CONF_NYC311_ENTITY] = nyc311_entity  # type: ignore[assignment]
                if api_key:
                    options[CONF_NYC311_API_KEY] = api_key
                elif CONF_NYC311_API_KEY in self.config_entry.options:
                    # Empty submission means "keep existing key unchanged"
                    options[CONF_NYC311_API_KEY] = self.config_entry.options[
                        CONF_NYC311_API_KEY
                    ]
                # else: no key was set and none provided — omit from options
                notify_svc = (user_input.get(CONF_NOTIFY_SERVICE) or "").strip()
                options[CONF_NOTIFY_SERVICE] = notify_svc  # type: ignore[assignment]
                lead_time_raw = user_input.get(CONF_NOTIFY_LEAD_TIME)
                options[CONF_NOTIFY_LEAD_TIME] = (
                    int(float(lead_time_raw))
                    if lead_time_raw is not None
                    else DEFAULT_NOTIFY_LEAD_TIME
                )
                # Carry forward existing debug + parking options unchanged —
                # debug step is bypassed in the options flow; parking values
                # carry through so a re-save of init alone preserves them.
                # NOTE: CONF_DEBUG_ENABLED is intentionally absent — the
                # coordinator unconditionally resets _debug_enabled = False
                # on async_start (D-02); writing it to options is misleading.
                for key in (
                    CONF_DEBUG_LAT,
                    CONF_DEBUG_LON,
                    CONF_DEBUG_DATETIME,
                    CONF_PARKING_LAT,
                    CONF_PARKING_LON,
                    CONF_PARKING_RADIUS,
                ):
                    if key in self.config_entry.options:
                        options[key] = self.config_entry.options[key]
                # Do NOT carry forward CONF_SUPPRESS_NOTIFICATIONS —
                # its purpose is to suppress notifications during debug mode,
                # which resets to False on restart. Carrying it forward causes
                # permanent silent suppression with no UI indicator.
                options[CONF_SUPPRESS_NOTIFICATIONS] = False
                self._options = options
                return await self.async_step_parking_area()

        notify_options = [
            f"notify.{svc}"
            for svc in self.hass.services.async_services_for_domain("notify")
        ]
        current_notify = self.config_entry.options.get(
            CONF_NOTIFY_SERVICE, DEFAULT_NOTIFY_SERVICE
        )
        if current_notify and current_notify not in notify_options:
            notify_options.insert(0, current_notify)

        return self.async_show_form(
            step_id="init",
            data_schema=_settings_schema(
                movement_threshold=self.config_entry.options.get(
                    CONF_MOVEMENT_THRESHOLD, DEFAULT_MOVEMENT_THRESHOLD
                ),
                refresh_interval=self.config_entry.options.get(
                    CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL
                ),
                stale_timeout=self.config_entry.options.get(
                    CONF_STALE_TIMEOUT, DEFAULT_STALE_TIMEOUT
                ),
            ).extend(
                {
                    **(
                        {
                            vol.Optional(
                                CONF_NYC311_ENTITY,
                                default=self.config_entry.options.get(
                                    CONF_NYC311_ENTITY, ""
                                ),
                            ): selector.EntitySelector(
                                selector.EntitySelectorConfig(domain="binary_sensor")
                            ),
                        }
                        if self.config_entry.options.get(CONF_NYC311_ENTITY)
                        else {
                            vol.Optional(CONF_NYC311_ENTITY): selector.EntitySelector(
                                selector.EntitySelectorConfig(domain="binary_sensor")
                            ),
                        }
                    ),
                    vol.Optional(
                        CONF_NYC311_API_KEY,
                        default="",
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                        )
                    ),
                    vol.Optional(
                        CONF_NOTIFY_SERVICE,
                        default=current_notify,
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=notify_options,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            custom_value=True,
                        )
                    ),
                    vol.Optional(
                        CONF_NOTIFY_LEAD_TIME,
                        default=self.config_entry.options.get(
                            CONF_NOTIFY_LEAD_TIME, DEFAULT_NOTIFY_LEAD_TIME
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=15,
                            max=480,
                            step=1,
                            unit_of_measurement="min",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_parking_area(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        """Optional home parking area for SODA cache pre-seeding (AREA-01).

        Three optional fields (lat/lon/radius). Empty submission is valid (D-07);
        in that case CONF_PARKING_* keys are removed from entry.options entirely.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            options = {**getattr(self, "_options", {})}
            lat_val = user_input.get(CONF_PARKING_LAT)
            lon_val = user_input.get(CONF_PARKING_LON)
            radius_val = user_input.get(CONF_PARKING_RADIUS)
            # Persist lat/lon only when BOTH are present — a half-configured
            # pair (lat without lon, or vice versa) is semantically invalid and
            # would silently disable the cache feature. If either is missing,
            # remove all three parking keys so the feature is fully disabled.
            if lat_val is not None and lon_val is not None:
                options[CONF_PARKING_LAT] = float(lat_val)
                options[CONF_PARKING_LON] = float(lon_val)
                options[CONF_PARKING_RADIUS] = (
                    int(radius_val)
                    if radius_val is not None
                    else DEFAULT_PARKING_RADIUS
                )
            else:
                options.pop(CONF_PARKING_LAT, None)
                options.pop(CONF_PARKING_LON, None)
                options.pop(CONF_PARKING_RADIUS, None)
            self._options = options
            return await self.async_step_caldav()

        opts = self.config_entry.options
        # NOTE: step="any" is used (not 0.000001) because HA 2026.2.3's
        # NumberSelectorConfig schema enforces step>=0.001 — the literal "any"
        # is the documented escape hatch for arbitrary-precision inputs (GPS
        # coordinates). The existing debug step uses step=0.000001 but is
        # bypassed in the options flow (Phase 25 commit 64fbf6d) so it never
        # triggers the validation. This step is reachable, so we must use "any".
        parking_schema: dict = {
            **(
                {
                    vol.Optional(
                        CONF_PARKING_LAT, default=opts[CONF_PARKING_LAT]
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=-90,
                            max=90,
                            step="any",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
                if CONF_PARKING_LAT in opts
                else {
                    vol.Optional(CONF_PARKING_LAT): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=-90,
                            max=90,
                            step="any",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
            **(
                {
                    vol.Optional(
                        CONF_PARKING_LON, default=opts[CONF_PARKING_LON]
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=-180,
                            max=180,
                            step="any",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
                if CONF_PARKING_LON in opts
                else {
                    vol.Optional(CONF_PARKING_LON): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=-180,
                            max=180,
                            step="any",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
            vol.Optional(
                CONF_PARKING_RADIUS,
                default=opts.get(CONF_PARKING_RADIUS, DEFAULT_PARKING_RADIUS),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=50,
                    max=5000,
                    step=50,
                    unit_of_measurement="m",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
        }
        return self.async_show_form(
            step_id="parking_area",
            data_schema=vol.Schema(parking_schema),
            errors=errors,
        )

    async def async_step_caldav(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        """CalDAV credentials step (Phase 34 — CALDAV-01).

        Submitting an empty URL is a complete no-op (D-02): all CalDAV keys
        are stripped from options and the entry is created without any
        CalDAV state. Otherwise we probe the server via
        caldav_sync.validate_connection. ANY probe failure (auth, network,
        DNS, TLS) is mapped to the same translated error key
        ``caldav_auth_failed`` (D-03 — never leak server details).

        T-34-02 mitigation: bad credentials are NEVER persisted because the
        ``if not errors`` gate is the ONLY code path that writes to
        ``self._options``. T-34-01 mitigation: the password form default is
        hardcoded to ``""`` so a re-render after error does NOT echo it back.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            url = (user_input.get(CONF_CALDAV_URL) or "").strip()
            if not url:
                # D-02: empty URL = complete no-op. Strip any pre-existing
                # CalDAV keys carried in self._options so the entry has no
                # CalDAV state at all.
                options = {**getattr(self, "_options", {})}
                for k in (
                    CONF_CALDAV_URL,
                    CONF_CALDAV_USERNAME,
                    CONF_CALDAV_PASSWORD,
                    CONF_CALDAV_CALENDAR,
                    CONF_CALDAV_SAFETY_WINDOW,
                    CONF_CALDAV_EVENT_TITLE_TEMPLATE,
                    CONF_CALDAV_APPLE_RADIUS_M,
                    CONF_CALDAV_INCLUDE_LOCATION,
                ):
                    options.pop(k, None)
                return self.async_create_entry(title="", data=options)

            username = user_input.get(CONF_CALDAV_USERNAME, "") or ""
            password = user_input.get(CONF_CALDAV_PASSWORD, "") or ""

            try:
                await caldav_sync.validate_connection(
                    url=url, username=username, password=password
                )
            except caldav_sync.CalDAVAuthError:
                errors["base"] = "caldav_auth_failed"
            except Exception:  # noqa: BLE001
                # D-03: treat ALL probe failures the same — never leak
                # server-internal details (DNS, TLS, etc.) to the UI.
                errors["base"] = "caldav_auth_failed"

            if not errors:
                # Stash validated creds into self._options for the
                # caldav_calendar step. NOTE: this writes to the in-memory
                # accumulator; entry.options is not mutated until
                # async_create_entry is called by the calendar step.
                safety_window = int(
                    user_input.get(
                        CONF_CALDAV_SAFETY_WINDOW, DEFAULT_CALDAV_SAFETY_WINDOW
                    )
                )
                apple_radius_m = int(
                    user_input.get(
                        CONF_CALDAV_APPLE_RADIUS_M, DEFAULT_CALDAV_APPLE_RADIUS_M
                    )
                )
                include_location = bool(
                    user_input.get(
                        CONF_CALDAV_INCLUDE_LOCATION, DEFAULT_CALDAV_INCLUDE_LOCATION
                    )
                )
                template = (
                    user_input.get(CONF_CALDAV_EVENT_TITLE_TEMPLATE)
                    or DEFAULT_CALDAV_EVENT_TITLE_TEMPLATE
                )
                if not _TEMPLATE_RE.fullmatch(template):
                    errors[CONF_CALDAV_EVENT_TITLE_TEMPLATE] = "caldav_invalid_template"
            if not errors:
                self._options[CONF_CALDAV_URL] = url
                self._options[CONF_CALDAV_USERNAME] = username
                self._options[CONF_CALDAV_PASSWORD] = password
                self._options[CONF_CALDAV_SAFETY_WINDOW] = safety_window
                self._options[CONF_CALDAV_APPLE_RADIUS_M] = apple_radius_m
                self._options[CONF_CALDAV_INCLUDE_LOCATION] = include_location
                self._options[CONF_CALDAV_EVENT_TITLE_TEMPLATE] = template
                return await self.async_step_caldav_calendar()

        opts = self.config_entry.options
        caldav_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_CALDAV_URL,
                    default=opts.get(CONF_CALDAV_URL, "") or "",
                ): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.URL,
                    )
                ),
                vol.Optional(
                    CONF_CALDAV_USERNAME,
                    default=opts.get(CONF_CALDAV_USERNAME, "") or "",
                ): selector.TextSelector(),
                # T-34-01: password default is HARDCODED to "" — never echo
                # back what the user just typed (or what is stored).
                vol.Optional(
                    CONF_CALDAV_PASSWORD,
                    default="",
                ): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.PASSWORD,
                    )
                ),
                vol.Optional(
                    CONF_CALDAV_SAFETY_WINDOW,
                    default=opts.get(
                        CONF_CALDAV_SAFETY_WINDOW, DEFAULT_CALDAV_SAFETY_WINDOW
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=240,
                        step=1,
                        unit_of_measurement="min",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_CALDAV_APPLE_RADIUS_M,
                    default=opts.get(
                        CONF_CALDAV_APPLE_RADIUS_M, DEFAULT_CALDAV_APPLE_RADIUS_M
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10,
                        max=1000,
                        step=1,
                        unit_of_measurement="m",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_CALDAV_INCLUDE_LOCATION,
                    default=opts.get(
                        CONF_CALDAV_INCLUDE_LOCATION, DEFAULT_CALDAV_INCLUDE_LOCATION
                    ),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_CALDAV_EVENT_TITLE_TEMPLATE,
                    default=opts.get(
                        CONF_CALDAV_EVENT_TITLE_TEMPLATE,
                        DEFAULT_CALDAV_EVENT_TITLE_TEMPLATE,
                    ),
                ): selector.TextSelector(),
            }
        )
        return self.async_show_form(
            step_id="caldav",
            data_schema=caldav_schema,
            errors=errors,
        )

    async def async_step_caldav_calendar(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        """CalDAV calendar selection step (Phase 34 — CALDAV-02).

        Populates a dropdown from caldav_sync.list_calendars() using the
        just-validated creds (still in self._options, not yet persisted).
        Submitting a selection commits the entire self._options dict to
        entry.options via async_create_entry.

        Pitfall 6 fallback: any error during list_calendars defensively
        re-shows the credentials form rather than presenting an empty
        dropdown the user cannot escape from.
        """
        if user_input is not None:
            self._options[CONF_CALDAV_CALENDAR] = user_input[CONF_CALDAV_CALENDAR]
            return self.async_create_entry(title="", data=self._options)

        try:
            calendars = await caldav_sync.list_calendars(
                url=self._options[CONF_CALDAV_URL],
                username=self._options[CONF_CALDAV_USERNAME],
                password=self._options[CONF_CALDAV_PASSWORD],
            )
        except Exception:  # noqa: BLE001
            # Pitfall 6: defensive fallback — re-show credentials step
            # rather than render an empty dropdown the user can't escape.
            return await self.async_step_caldav()

        options_list = [
            selector.SelectOptionDict(value=url, label=name or url)
            for (url, name) in calendars
        ]
        current = self.config_entry.options.get(CONF_CALDAV_CALENDAR, "") or ""
        default_value = (
            current if current else (options_list[0]["value"] if options_list else "")
        )
        return self.async_show_form(
            step_id="caldav_calendar",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CALDAV_CALENDAR,
                        default=default_value,
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options_list,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )
