"""Intégration doorbell_local : gestion réseau des cartes/PIN d'une doorbell Tuya/sun8i.

Ouverture de porte = relais Tuya via LocalTuya (séparé). Cette intégration couvre
le MSG server (TCP 34952) : lister / révoquer des cartes, changer un PIN.
L'ajout de carte n'existe PAS côté réseau (carte master physique requise).
"""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_ENTRY_ID,
    ATTR_PIN,
    ATTR_ROOM,
    ATTR_UID,
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SERVICE_REFRESH,
    SERVICE_REVOKE_CARD,
    SERVICE_REVOKE_ROOM,
    SERVICE_SET_PIN,
)
from .coordinator import DoorbellCoordinator
from .protocol import DoorbellClient, DoorbellError

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


def _parse_uid(value) -> int:
    """Accepte un UID en hex ('940cbbe1', '0x940cbbe1') ou en entier."""
    if isinstance(value, int):
        return value
    text = str(value).strip().lower()
    try:
        return int(text, 16) if not text.startswith("0x") else int(text, 16)
    except ValueError as err:
        raise HomeAssistantError(f"UID invalide : {value!r}") from err


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configure une doorbell depuis une entrée de config."""
    client = DoorbellClient(
        entry.data[CONF_HOST], entry.data.get(CONF_PORT, DEFAULT_PORT)
    )
    coordinator = DoorbellCoordinator(
        hass, client, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Décharge une doorbell."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            _async_unregister_services(hass)
    return unload_ok


def _resolve_coordinator(hass: HomeAssistant, call: ServiceCall) -> DoorbellCoordinator:
    entries: dict[str, DoorbellCoordinator] = hass.data.get(DOMAIN, {})
    if not entries:
        raise HomeAssistantError("Aucune doorbell configurée")
    entry_id = call.data.get(ATTR_ENTRY_ID)
    if entry_id:
        if entry_id not in entries:
            raise HomeAssistantError(f"entry_id inconnu : {entry_id}")
        return entries[entry_id]
    if len(entries) == 1:
        return next(iter(entries.values()))
    raise HomeAssistantError(
        "Plusieurs doorbells configurées : préciser 'entry_id'"
    )


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_REVOKE_CARD):
        return

    async def _run(call: ServiceCall, fn, *args) -> None:
        coordinator = _resolve_coordinator(hass, call)
        try:
            await hass.async_add_executor_job(fn(coordinator.client), *args)
        except DoorbellError as err:
            raise HomeAssistantError(str(err)) from err
        await coordinator.async_request_refresh()

    async def handle_revoke_card(call: ServiceCall) -> None:
        uid = _parse_uid(call.data[ATTR_UID])
        await _run(call, lambda c: c.revoke_card, uid)

    async def handle_revoke_room(call: ServiceCall) -> None:
        await _run(call, lambda c: c.revoke_room, int(call.data[ATTR_ROOM]))

    async def handle_set_pin(call: ServiceCall) -> None:
        # NB : le PIN n'est jamais loggué.
        await _run(call, lambda c: c.set_pin, int(call.data[ATTR_ROOM]), str(call.data[ATTR_PIN]))

    async def handle_refresh(call: ServiceCall) -> None:
        coordinator = _resolve_coordinator(hass, call)
        await coordinator.async_request_refresh()

    entry_field = {vol.Optional(ATTR_ENTRY_ID): cv.string}

    hass.services.async_register(
        DOMAIN, SERVICE_REVOKE_CARD, handle_revoke_card,
        schema=vol.Schema({vol.Required(ATTR_UID): cv.string, **entry_field}),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REVOKE_ROOM, handle_revoke_room,
        schema=vol.Schema({vol.Required(ATTR_ROOM): vol.Coerce(int), **entry_field}),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_PIN, handle_set_pin,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ROOM): vol.Coerce(int),
                vol.Required(ATTR_PIN): cv.string,
                **entry_field,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REFRESH, handle_refresh,
        schema=vol.Schema(entry_field),
    )


def _async_unregister_services(hass: HomeAssistant) -> None:
    for service in (
        SERVICE_REVOKE_CARD,
        SERVICE_REVOKE_ROOM,
        SERVICE_SET_PIN,
        SERVICE_REFRESH,
    ):
        hass.services.async_remove(DOMAIN, service)
