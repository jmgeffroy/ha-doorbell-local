"""Config flow (UI) pour doorbell_local."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import (
    CONF_FILE_NAME,
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    DEFAULT_FILE_NAME,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .protocol import DoorbellClient, DoorbellError


class DoorbellLocalConfigFlow(ConfigFlow, domain=DOMAIN):
    """Assistant de configuration : demande l'IP et teste la connexion."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            file_name = user_input[CONF_FILE_NAME]
            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()
            # Deux doorbells qui publieraient le même fichier s'écraseraient :
            # « Appliquer » sur l'une pousserait les codes de l'autre.
            taken = {
                other.data.get(CONF_FILE_NAME, DEFAULT_FILE_NAME)
                for other in self._async_current_entries()
            }
            if file_name in taken:
                errors[CONF_FILE_NAME] = "file_name_in_use"
            else:
                client = DoorbellClient(host, port)
                try:
                    await self.hass.async_add_executor_job(client.list_cards)
                except DoorbellError:
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_create_entry(
                        title=f"Doorbell {host}", data=user_input
                    )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                ): int,
                vol.Optional(CONF_FILE_NAME, default=DEFAULT_FILE_NAME): str,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )
