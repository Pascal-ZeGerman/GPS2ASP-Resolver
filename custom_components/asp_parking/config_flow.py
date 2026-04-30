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

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_DEBUG_DATETIME,
    CONF_DEBUG_ENABLED,
    CONF_DEBUG_LAT,
    CONF_DEBUG_LON,
    CONF_DEVICE_TRACKER,
    CONF_MOVEMENT_THRESHOLD,
    CONF_NOTIFY_LEAD_TIME,
    CONF_NOTIFY_SERVICE,
    CONF_NYC311_API_KEY,
    CONF_NYC311_ENTITY,
    CONF_REFRESH_INTERVAL,
    CONF_STALE_TIMEOUT,
    CONF_SUPPRESS_NOTIFICATIONS,
    DEFAULT_DEBUG_DATETIME,
    DEFAULT_DEBUG_ENABLED,
    DEFAULT_DEBUG_LAT,
    DEFAULT_DEBUG_LON,
    DEFAULT_MOVEMENT_THRESHOLD,
    DEFAULT_NOTIFY_LEAD_TIME,
    DEFAULT_NOTIFY_SERVICE,
    DEFAULT_NYC311_ENTITY,
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_STALE_TIMEOUT,
    DEFAULT_SUPPRESS_NOTIFICATIONS,
    DOMAIN,
)
from .gps2asp.suspension import NYC311Client
from .gps2asp.suspension.poller import NYC311AuthError


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
    stale_timeout = int(
        user_input.get(CONF_STALE_TIMEOUT, DEFAULT_STALE_TIMEOUT)
    )

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
            data_schema=vol.Schema({
                vol.Optional(CONF_NYC311_API_KEY, default=""): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.PASSWORD,
                    )
                ),
            }),
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
            nyc311_entity = user_input.get(CONF_NYC311_ENTITY, "").strip()
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
                options = {**cleaned}
                if nyc311_entity:
                    options[CONF_NYC311_ENTITY] = nyc311_entity
                if api_key:
                    options[CONF_NYC311_API_KEY] = api_key
                elif CONF_NYC311_API_KEY in self.config_entry.options and api_key is None:
                    # User cleared the key -- remove it
                    options.pop(CONF_NYC311_API_KEY, None)
                # Carry notify_service forward to debug step
                notify_svc = user_input.get(CONF_NOTIFY_SERVICE, "").strip()
                if notify_svc:
                    options[CONF_NOTIFY_SERVICE] = notify_svc
                lead_time_raw = user_input.get(CONF_NOTIFY_LEAD_TIME)
                if lead_time_raw is not None:
                    options[CONF_NOTIFY_LEAD_TIME] = int(lead_time_raw)
                self._options = options
                return await self.async_step_debug()

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
            ).extend({
                vol.Optional(
                    CONF_NYC311_ENTITY,
                    default=self.config_entry.options.get(
                        CONF_NYC311_ENTITY, DEFAULT_NYC311_ENTITY
                    ),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="binary_sensor",
                    )
                ),
                vol.Optional(
                    CONF_NYC311_API_KEY,
                    default=self.config_entry.options.get(CONF_NYC311_API_KEY, ""),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.PASSWORD,
                    )
                ),
                vol.Optional(
                    CONF_NOTIFY_SERVICE,
                    default=self.config_entry.options.get(
                        CONF_NOTIFY_SERVICE, DEFAULT_NOTIFY_SERVICE
                    ),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="notify",
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
            }),
            errors=errors,
        )

    async def async_step_debug(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        """Debug overrides step -- for testing only."""
        errors: dict[str, str] = {}

        if user_input is not None:
            options = {**getattr(self, "_options", {})}
            options[CONF_DEBUG_ENABLED] = user_input.get(
                CONF_DEBUG_ENABLED, DEFAULT_DEBUG_ENABLED
            )
            # Store lat/lon only if provided; clear from options when blank so stale
            # values don't persist across saves (WR-02)
            debug_lat = user_input.get(CONF_DEBUG_LAT)
            debug_lon = user_input.get(CONF_DEBUG_LON)
            if debug_lat is not None:
                options[CONF_DEBUG_LAT] = float(debug_lat)
            else:
                options.pop(CONF_DEBUG_LAT, None)
            if debug_lon is not None:
                options[CONF_DEBUG_LON] = float(debug_lon)
            else:
                options.pop(CONF_DEBUG_LON, None)
            # Store datetime string if provided; clear when blank so stale ISO
            # strings don't re-activate the override at startup (WR-03)
            debug_dt = user_input.get(CONF_DEBUG_DATETIME)
            if debug_dt:
                options[CONF_DEBUG_DATETIME] = debug_dt
            else:
                options.pop(CONF_DEBUG_DATETIME, None)
            options[CONF_SUPPRESS_NOTIFICATIONS] = user_input.get(
                CONF_SUPPRESS_NOTIFICATIONS, DEFAULT_SUPPRESS_NOTIFICATIONS
            )
            return self.async_create_entry(title="", data=options)

        return self.async_show_form(
            step_id="debug",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_DEBUG_ENABLED,
                    default=self.config_entry.options.get(
                        CONF_DEBUG_ENABLED, DEFAULT_DEBUG_ENABLED
                    ),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_DEBUG_LAT,
                    default=self.config_entry.options.get(
                        CONF_DEBUG_LAT, DEFAULT_DEBUG_LAT
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=-90,
                        max=90,
                        step=0.000001,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_DEBUG_LON,
                    default=self.config_entry.options.get(
                        CONF_DEBUG_LON, DEFAULT_DEBUG_LON
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=-180,
                        max=180,
                        step=0.000001,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_DEBUG_DATETIME,
                    default=self.config_entry.options.get(
                        CONF_DEBUG_DATETIME, DEFAULT_DEBUG_DATETIME
                    ),
                ): selector.DateTimeSelector(),
                vol.Optional(
                    CONF_SUPPRESS_NOTIFICATIONS,
                    default=self.config_entry.options.get(
                        CONF_SUPPRESS_NOTIFICATIONS, DEFAULT_SUPPRESS_NOTIFICATIONS
                    ),
                ): selector.BooleanSelector(),
            }),
            errors=errors,
        )
