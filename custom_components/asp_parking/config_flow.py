"""Config flow and options flow for the ASP Parking integration.

Provides a 3-step setup wizard:
  1. VW CarNet login stub (placeholder for future integration)
  2. Vehicle device_tracker selection (EntitySelector dropdown)
  3. Threshold settings (movement, refresh interval, stale timeout)

Options flow allows reconfiguring thresholds without removing the integration.
"""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_DEVICE_TRACKER,
    CONF_MOVEMENT_THRESHOLD,
    CONF_REFRESH_INTERVAL,
    CONF_STALE_TIMEOUT,
    DEFAULT_MOVEMENT_THRESHOLD,
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_STALE_TIMEOUT,
    DOMAIN,
)


class ASPParkingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Multi-step config flow for ASP Parking Monitor.

    Step 1 (user): VW CarNet login stub -- renders informational text.
    Step 2 (vehicle): Select device_tracker entity via dropdown.
    Step 3 (settings): Configure movement threshold, refresh interval, stale timeout.
    """

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._device_tracker: str = ""

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 1: VW CarNet login stub.

        Shows informational text about future VW CarNet integration.
        Clicking Submit advances to the vehicle selection step.
        """
        if user_input is not None:
            return await self.async_step_vehicle()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
        )

    async def async_step_vehicle(
        self, user_input: dict[str, str] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2: Select the device_tracker entity.

        Uses EntitySelector for a proper dropdown instead of raw text input.
        """
        if user_input is not None:
            self._device_tracker = user_input[CONF_DEVICE_TRACKER]
            return await self.async_step_settings()

        return self.async_show_form(
            step_id="vehicle",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_TRACKER): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="device_tracker"),
                    ),
                }
            ),
        )

    async def async_step_settings(
        self, user_input: dict[str, float | int] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 3: Configure thresholds.

        Device tracker goes in entry.data (immutable).
        Thresholds go in entry.options (reconfigurable via options flow).
        """
        if user_input is not None:
            return self.async_create_entry(
                title="ASP Parking Monitor",
                data={CONF_DEVICE_TRACKER: self._device_tracker},
                options={
                    CONF_MOVEMENT_THRESHOLD: user_input.get(
                        CONF_MOVEMENT_THRESHOLD, DEFAULT_MOVEMENT_THRESHOLD
                    ),
                    CONF_REFRESH_INTERVAL: user_input.get(
                        CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL
                    ),
                    CONF_STALE_TIMEOUT: user_input.get(
                        CONF_STALE_TIMEOUT, DEFAULT_STALE_TIMEOUT
                    ),
                },
            )

        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_MOVEMENT_THRESHOLD,
                        default=DEFAULT_MOVEMENT_THRESHOLD,
                    ): vol.Coerce(float),
                    vol.Optional(
                        CONF_REFRESH_INTERVAL,
                        default=DEFAULT_REFRESH_INTERVAL,
                    ): vol.Coerce(int),
                    vol.Optional(
                        CONF_STALE_TIMEOUT,
                        default=DEFAULT_STALE_TIMEOUT,
                    ): vol.Coerce(int),
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ASPParkingOptionsFlow:
        """Return the options flow handler."""
        return ASPParkingOptionsFlow(config_entry)


class ASPParkingOptionsFlow(config_entries.OptionsFlow):
    """Options flow for reconfiguring ASP Parking thresholds.

    Allows changing movement threshold, refresh interval, and stale timeout
    without removing and re-adding the integration.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize the options flow.

        Args:
            config_entry: The config entry being reconfigured.
        """
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, float | int] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Present the options form with current values as defaults."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_MOVEMENT_THRESHOLD,
                        default=self.config_entry.options.get(
                            CONF_MOVEMENT_THRESHOLD,
                            DEFAULT_MOVEMENT_THRESHOLD,
                        ),
                    ): vol.Coerce(float),
                    vol.Optional(
                        CONF_REFRESH_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_REFRESH_INTERVAL,
                            DEFAULT_REFRESH_INTERVAL,
                        ),
                    ): vol.Coerce(int),
                    vol.Optional(
                        CONF_STALE_TIMEOUT,
                        default=self.config_entry.options.get(
                            CONF_STALE_TIMEOUT,
                            DEFAULT_STALE_TIMEOUT,
                        ),
                    ): vol.Coerce(int),
                }
            ),
        )
