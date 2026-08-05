"""Config flow for Renson Healthbox integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol


from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.core import callback

from homeassistant.const import CONF_HOST, CONF_API_KEY
from pyhealthbox3.healthbox3 import (
    Healthbox3,
    Healthbox3ApiClientAuthenticationError,
    Healthbox3ApiClientCommunicationError,
    Healthbox3ApiClientError,
)

from .const import DOMAIN, LOGGER
from .discovery import async_fetch_serial


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Renson Healthbox."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                if CONF_API_KEY in user_input:
                    await self._test_credentials(
                        ipaddress=user_input[CONF_HOST],
                        apikey=user_input[CONF_API_KEY],
                    )
                else:
                    await self._test_connectivity(ipaddress=user_input[CONF_HOST])
            except Healthbox3ApiClientAuthenticationError as exception:
                LOGGER.warning(exception)
                errors["base"] = "auth"
            except Healthbox3ApiClientCommunicationError as exception:
                LOGGER.error(exception)
                errors["base"] = "connection"
            except Healthbox3ApiClientError as exception:
                LOGGER.exception(exception)
                errors["base"] = "unknown"
            else:
                serial = await async_fetch_serial(
                    user_input[CONF_HOST], async_create_clientsession(self.hass)
                )
                await self.async_set_unique_id(
                    serial or f"{DOMAIN}_{user_input[CONF_HOST]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_HOST],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST,
                        default=(user_input or {}).get(CONF_HOST),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT
                        ),
                    ),
                    vol.Optional(CONF_API_KEY): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        ),
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a reconfiguration flow, e.g. when the device's IP address changes."""
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is not None:
            try:
                if CONF_API_KEY in user_input:
                    await self._test_credentials(
                        ipaddress=user_input[CONF_HOST],
                        apikey=user_input[CONF_API_KEY],
                    )
                else:
                    await self._test_connectivity(ipaddress=user_input[CONF_HOST])
            except Healthbox3ApiClientAuthenticationError as exception:
                LOGGER.warning(exception)
                errors["base"] = "auth"
            except Healthbox3ApiClientCommunicationError as exception:
                LOGGER.error(exception)
                errors["base"] = "connection"
            except Healthbox3ApiClientError as exception:
                LOGGER.exception(exception)
                errors["base"] = "unknown"
            else:
                serial = await async_fetch_serial(
                    user_input[CONF_HOST], async_create_clientsession(self.hass)
                )
                if serial is not None:
                    await self.async_set_unique_id(serial)
                    self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data=user_input,
                )

        current = user_input or reconfigure_entry.data
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST,
                        default=current.get(CONF_HOST),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT
                        ),
                    ),
                    vol.Optional(
                        CONF_API_KEY,
                        default=current.get(CONF_API_KEY),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        ),
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> FlowResult:
        """Handle passive DHCP discovery: relocate a known device, never create a new one.

        Healthbox 3 units request a DHCP hostname of the form
        "HEALTHBOX3<serial>" (confirmed on real hardware, see manifest.json's
        "dhcp" key). This fires whenever such a request is seen on the
        network - including for a device that isn't configured in HA at
        all - so it must verify the serial and silently no-op unless it
        matches an already-configured entry.
        """
        serial = await async_fetch_serial(
            discovery_info.ip, async_create_clientsession(self.hass)
        )
        if serial is None:
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(serial)
        self._abort_if_unique_id_configured(updates={CONF_HOST: discovery_info.ip})
        return self.async_abort(reason="no_matching_entry")

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Handle reauth when the API key stops working (e.g. after a device factory reset).

        Triggered by coordinator.py raising ConfigEntryAuthFailed - HA
        core calls this automatically, we just need to collect a new key.
        """
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask for a replacement API key and verify it before saving."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            try:
                await self._test_credentials(
                    ipaddress=reauth_entry.data[CONF_HOST],
                    apikey=user_input[CONF_API_KEY],
                )
            except Healthbox3ApiClientAuthenticationError as exception:
                LOGGER.warning(exception)
                errors["base"] = "auth"
            except Healthbox3ApiClientCommunicationError as exception:
                LOGGER.error(exception)
                errors["base"] = "connection"
            except Healthbox3ApiClientError as exception:
                LOGGER.exception(exception)
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data={**reauth_entry.data, CONF_API_KEY: user_input[CONF_API_KEY]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        ),
                    ),
                }
            ),
            errors=errors,
        )

    async def _test_credentials(self, ipaddress: str, apikey: str) -> None:
        """Validate credentials."""
        client = Healthbox3(
            host=ipaddress,
            api_key=apikey,
            session=async_create_clientsession(self.hass),
        )
        await client.async_enable_advanced_api_features()

    async def _test_connectivity(self, ipaddress: str) -> None:
        """Validate connectivity."""
        client = Healthbox3(
            host=ipaddress,
            api_key=None,
            session=async_create_clientsession(self.hass),
        )
        await client.async_validate_connectivity()


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Options Flow for the Config Entry."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""

        errors = {}
        host: str = self.entry.data.get(CONF_HOST, "")
        if user_input is not None:
            if (api_key := user_input.get(CONF_API_KEY)) is None:
                errors[CONF_API_KEY] = "invalid_auth"
            else:
                hb3 = Healthbox3(host=host, api_key=api_key)
                try:
                    await hb3.async_enable_advanced_api_features(pre_validation=False)
                except Healthbox3ApiClientAuthenticationError:
                    errors[CONF_API_KEY] = "invalid_auth"
                finally:
                    await hb3.close()

                if not errors:
                    self.hass.config_entries.async_update_entry(
                        entry=self.entry,
                        data={CONF_HOST: host, CONF_API_KEY: api_key},
                    )
                    return self.async_create_entry(
                        title="", data=user_input | {CONF_API_KEY: api_key}
                    )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_API_KEY, default=self.entry.data.get(
                            CONF_API_KEY, "")
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    )
                }
            ),
            errors=errors,
        )
