"""Intégration doorbell_local (Tuya/sun8i RFID door controller).

Deux canaux :
- RÉSEAU (MSG server, TCP 34952) : lister / révoquer des cartes — instantané.
- FICHIER (ICCardDB) : gérer les PIN. HA est la source de vérité du roster, génère
  `/config/www/ICCardDB0.ext` (servi à /local/ICCardDB0.ext) ; l'application effective
  sur la doorbell (wget + reboot) est faite par un pont UART (ESP / machine locale).

Un PIN peut être rattaché à un badge (set_pin) OU indépendant (add_code = carte
virtuelle : le clavier accepte le PIN sans badge physique).
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
    ATTR_EMAIL,
    ATTR_ENTRY_ID,
    ATTR_LABEL,
    ATTR_PHONE,
    ATTR_PIN,
    ATTR_UID,
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SERVICE_ADD_CODE,
    SERVICE_IMPORT_CARDS,
    SERVICE_REFRESH,
    SERVICE_REMOVE_ENTRY,
    SERVICE_REVOKE_CARD,
    SERVICE_SET_PIN,
    SERVICE_STAGE,
    SERVICE_UPDATE_CONTACT,
)
from .coordinator import DoorbellCoordinator
from .protocol import DoorbellClient, DoorbellError
from .roster import Roster

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.TEXT, Platform.BUTTON]

_SERVICES = (
    SERVICE_REVOKE_CARD,
    SERVICE_REFRESH,
    SERVICE_SET_PIN,
    SERVICE_ADD_CODE,
    SERVICE_REMOVE_ENTRY,
    SERVICE_UPDATE_CONTACT,
    SERVICE_IMPORT_CARDS,
    SERVICE_STAGE,
)


def _parse_uid(value) -> int:
    """Accepte un UID hex ('940cbbe1', '0x940cbbe1') ou entier."""
    if isinstance(value, int):
        return value
    text = str(value).strip().lower()
    try:
        return int(text, 16)
    except ValueError as err:
        raise HomeAssistantError(f"UID invalide : {value!r}") from err


def _validate_pin(pin: str) -> str:
    if not (pin.isdigit() and len(pin) == 4):
        raise HomeAssistantError("PIN = exactement 4 chiffres")
    return pin


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configure une doorbell."""
    client = DoorbellClient(entry.data[CONF_HOST], entry.data.get(CONF_PORT, DEFAULT_PORT))
    coordinator = DoorbellCoordinator(
        hass, client, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )
    await coordinator.async_config_entry_first_refresh()

    roster = Roster(hass, entry.entry_id)
    await roster.load()
    # amorçage : importe les cartes du device (UID+type) si le roster est vierge
    if roster.import_cards(coordinator.data or []):
        await roster.commit()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "roster": roster,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            for service in _SERVICES:
                hass.services.async_remove(DOMAIN, service)
    return unload_ok


def _resolve(hass: HomeAssistant, call: ServiceCall) -> dict:
    entries: dict[str, dict] = hass.data.get(DOMAIN, {})
    if not entries:
        raise HomeAssistantError("Aucune doorbell configurée")
    entry_id = call.data.get(ATTR_ENTRY_ID)
    if entry_id:
        if entry_id not in entries:
            raise HomeAssistantError(f"entry_id inconnu : {entry_id}")
        return entries[entry_id]
    if len(entries) == 1:
        return next(iter(entries.values()))
    raise HomeAssistantError("Plusieurs doorbells : préciser 'entry_id'")


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SET_PIN):
        return

    # -- réseau (MSG server) -----------------------------------------------
    async def handle_revoke_card(call: ServiceCall) -> None:
        ctx = _resolve(hass, call)
        coordinator = ctx["coordinator"]
        uid = _parse_uid(call.data[ATTR_UID])
        try:
            await hass.async_add_executor_job(coordinator.client.revoke_card, uid)
        except DoorbellError as err:
            raise HomeAssistantError(str(err)) from err
        await coordinator.async_request_refresh()

    async def handle_refresh(call: ServiceCall) -> None:
        await _resolve(hass, call)["coordinator"].async_request_refresh()

    # -- roster / fichier ICCardDB -----------------------------------------
    async def handle_set_pin(call: ServiceCall) -> None:
        # le PIN n'est jamais loggué
        ctx = _resolve(hass, call)
        roster = ctx["roster"]
        uid = _parse_uid(call.data[ATTR_UID])
        roster.set_pin(
            uid,
            _validate_pin(str(call.data[ATTR_PIN])),
            email=call.data.get(ATTR_EMAIL, ""),
            phone=call.data.get(ATTR_PHONE, ""),
        )
        await roster.commit()

    async def handle_add_code(call: ServiceCall) -> None:
        ctx = _resolve(hass, call)
        roster = ctx["roster"]
        roster.add_code(
            _validate_pin(str(call.data[ATTR_PIN])),
            call.data.get(ATTR_LABEL, ""),
            call.data.get(ATTR_EMAIL, ""),
            call.data.get(ATTR_PHONE, ""),
        )
        await roster.commit()

    async def handle_update_contact(call: ServiceCall) -> None:
        ctx = _resolve(hass, call)
        roster = ctx["roster"]
        uid = _parse_uid(call.data[ATTR_UID])
        fields = {
            key: str(call.data[attr])
            for key, attr in (("label", ATTR_LABEL), ("email", ATTR_EMAIL), ("phone", ATTR_PHONE))
            if attr in call.data
        }
        if not roster.update(uid, fields):
            raise HomeAssistantError("UID absent du roster")
        await roster.commit()

    async def handle_remove_entry(call: ServiceCall) -> None:
        ctx = _resolve(hass, call)
        roster = ctx["roster"]
        if not roster.remove(_parse_uid(call.data[ATTR_UID])):
            raise HomeAssistantError("UID absent du roster")
        await roster.commit()

    async def handle_import_cards(call: ServiceCall) -> None:
        ctx = _resolve(hass, call)
        ctx["roster"].import_cards(ctx["coordinator"].data or [])
        await ctx["roster"].commit()

    async def handle_stage(call: ServiceCall) -> None:
        await _resolve(hass, call)["roster"].commit()

    entry_field = {vol.Optional(ATTR_ENTRY_ID): cv.string}

    hass.services.async_register(
        DOMAIN, SERVICE_REVOKE_CARD, handle_revoke_card,
        schema=vol.Schema({vol.Required(ATTR_UID): cv.string, **entry_field}),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REFRESH, handle_refresh, schema=vol.Schema(entry_field),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_PIN, handle_set_pin,
        schema=vol.Schema(
            {
                vol.Required(ATTR_UID): cv.string,
                vol.Required(ATTR_PIN): cv.string,
                vol.Optional(ATTR_EMAIL, default=""): cv.string,
                vol.Optional(ATTR_PHONE, default=""): cv.string,
                **entry_field,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_ADD_CODE, handle_add_code,
        schema=vol.Schema(
            {
                vol.Required(ATTR_PIN): cv.string,
                vol.Optional(ATTR_LABEL, default=""): cv.string,
                vol.Optional(ATTR_EMAIL, default=""): cv.string,
                vol.Optional(ATTR_PHONE, default=""): cv.string,
                **entry_field,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_UPDATE_CONTACT, handle_update_contact,
        schema=vol.Schema(
            {
                vol.Required(ATTR_UID): cv.string,
                vol.Optional(ATTR_LABEL): cv.string,
                vol.Optional(ATTR_EMAIL): cv.string,
                vol.Optional(ATTR_PHONE): cv.string,
                **entry_field,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE_ENTRY, handle_remove_entry,
        schema=vol.Schema({vol.Required(ATTR_UID): cv.string, **entry_field}),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_IMPORT_CARDS, handle_import_cards, schema=vol.Schema(entry_field),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_STAGE, handle_stage, schema=vol.Schema(entry_field),
    )
