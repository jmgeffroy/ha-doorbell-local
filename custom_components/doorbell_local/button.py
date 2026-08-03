"""Entité `button` par code : supprimer l'entrée du roster.

Appuyer retire l'entrée du roster et régénère le fichier ICCardDB (il faudra
ensuite « Appliquer » pour que la doorbell cesse d'accepter ce code).
"""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entities import device_info, setup_dynamic_entities
from .roster import Roster


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    roster: Roster = hass.data[DOMAIN][entry.entry_id]["roster"]

    def specs(item: dict) -> list:
        uid = item["uid"]
        return [(f"{uid:08x}_delete", lambda u=uid: _DeleteButton(roster, entry, u))]

    setup_dynamic_entities(hass, entry, roster, async_add_entities, specs)


class _DeleteButton(ButtonEntity):
    """Supprime l'entrée UID du roster."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:delete"

    def __init__(self, roster: Roster, entry: ConfigEntry, uid: int) -> None:
        self._roster = roster
        self._uid = uid
        self._attr_unique_id = f"{entry.entry_id}_{uid:08x}_delete"
        self._attr_device_info = device_info(entry)

    @property
    def name(self) -> str:
        entry = self._roster._find(self._uid)
        label = (entry.get("label") if entry else "") or f"{self._uid:08x}"
        return f"Supprimer {label}"

    async def async_press(self) -> None:
        if self._roster.remove(self._uid):
            await self._roster.commit()
