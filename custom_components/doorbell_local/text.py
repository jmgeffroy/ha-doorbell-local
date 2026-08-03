"""Entités `text` par code : PIN, email et téléphone éditables en ligne.

Modifier le PIN d'une entrée = le réécrire dans le roster puis régénérer le
fichier ICCardDB (il faudra ensuite « Appliquer » pour pousser sur la doorbell).

NB : le PIN devient VISIBLE dans l'état HA (nécessaire pour l'éditer dans le
tableau). HA est local et réservé à l'admin — compromis assumé.
"""
from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entities import device_info, setup_dynamic_entities
from .roster import Roster, roster_signal

# champ -> (suffixe nom, icône, mode, pattern, min, max)
# NB : le motif du PIN accepte le VIDE ([0-9]{0,4}) — sinon HA marque l'entité
# `unavailable` pour tout code/badge sans PIN (la valeur "" ne matcherait pas
# {4}). La contrainte stricte « 4 chiffres » est appliquée dans async_set_value.
_FIELDS = {
    "pin": ("PIN", "mdi:dialpad", TextMode.TEXT, r"[0-9]{0,4}", 0, 4),
    "phone": ("Téléphone", "mdi:phone", TextMode.TEXT, None, 0, 24),
    "email": ("Email", "mdi:email", TextMode.TEXT, None, 0, 100),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    roster: Roster = hass.data[DOMAIN][entry.entry_id]["roster"]

    def specs(item: dict) -> list:
        uid = item["uid"]
        return [
            (f"{uid:08x}_{field}", (lambda f=field, u=uid: _RosterText(roster, entry, u, f)))
            for field in _FIELDS
        ]

    setup_dynamic_entities(hass, entry, roster, async_add_entities, specs)


class _RosterText(TextEntity):
    """Un champ éditable (pin/phone/email) rattaché à un UID du roster."""

    _attr_has_entity_name = True

    def __init__(self, roster: Roster, entry: ConfigEntry, uid: int, field: str) -> None:
        name, icon, mode, pattern, minlen, maxlen = _FIELDS[field]
        self._roster = roster
        self._entry_id = entry.entry_id
        self._uid = uid
        self._field = field
        self._attr_unique_id = f"{entry.entry_id}_{uid:08x}_{field}"
        self._attr_icon = icon
        self._attr_mode = mode
        self._attr_native_min = minlen
        self._attr_native_max = maxlen
        if pattern:
            self._attr_pattern = pattern
        self._attr_device_info = device_info(entry)
        self._name_suffix = name

    @property
    def name(self) -> str:
        entry = self._roster._find(self._uid)
        label = (entry.get("label") if entry else "") or f"{self._uid:08x}"
        return f"{label} — {self._name_suffix}"

    @property
    def native_value(self) -> str:
        entry = self._roster._find(self._uid)
        return (entry.get(self._field, "") if entry else "") or ""

    async def async_set_value(self, value: str) -> None:
        value = value.strip()
        if self._field == "pin" and value and not (value.isdigit() and len(value) == 4):
            raise HomeAssistantError("PIN = exactement 4 chiffres")
        self._roster.update(self._uid, {self._field: value})
        await self._roster.commit()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, roster_signal(self._entry_id), self._refresh
            )
        )

    @callback
    def _refresh(self) -> None:
        # l'entrée existe encore : le gestionnaire gère la suppression, ici on
        # se contente de rafraîchir la valeur affichée.
        if self._roster._find(self._uid) is not None:
            self.async_write_ha_state()
