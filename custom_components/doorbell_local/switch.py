"""Entités `switch` par code : quelles portes ce badge ouvre-t-il ?

Un interrupteur par code et par AUTRE doorbell configurée. Allumé = l'UID
figure dans le roster de cette porte-là ; l'éteindre l'en retire.

POURQUOI UN INTERRUPTEUR ET PAS UN BOUTON « copier ». Un bouton ne sait
qu'ajouter : il agit sans jamais montrer l'état obtenu, et il n'a pas de retour
en arrière. L'interrupteur répond à la question « ce badge ouvre-t-il cette
porte ? » au même endroit où on la modifie.

Rien n'apparaît tant qu'une seule doorbell est configurée — il n'y aurait
aucune autre porte à désigner. Une doorbell ajoutée plus tard n'est prise en
compte qu'au redémarrage de Home Assistant : le jeu d'entités ne se recalcule
qu'aux changements de roster.
"""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entities import device_info, door_name, setup_dynamic_entities
from .roster import Roster, roster_signal


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    roster: Roster = hass.data[DOMAIN][entry.entry_id]["roster"]

    def specs(item: dict) -> list:
        uid = item["uid"]
        others = [k for k in hass.data.get(DOMAIN, {}) if k != entry.entry_id]
        return [
            (
                f"{uid:08x}_door_{other}",
                lambda u=uid, o=other: _DoorSwitch(hass, roster, entry, u, o),
            )
            for other in others
        ]

    setup_dynamic_entities(hass, entry, roster, async_add_entities, specs)


class _DoorSwitch(SwitchEntity):
    """« Ce badge ouvre-t-il la porte X ? » — état et commande au même endroit."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:door-closed-lock"

    def __init__(
        self,
        hass: HomeAssistant,
        roster: Roster,
        entry: ConfigEntry,
        uid: int,
        other_id: str,
    ) -> None:
        self._hass = hass
        self._roster = roster
        self._entry_id = entry.entry_id
        self._uid = uid
        self._other_id = other_id
        self._attr_unique_id = f"{entry.entry_id}_{uid:08x}_door_{other_id}"
        self._attr_device_info = device_info(entry)

    def _other(self) -> Roster | None:
        ctx = self._hass.data.get(DOMAIN, {}).get(self._other_id)
        return ctx["roster"] if ctx else None

    @property
    def name(self) -> str:
        item = self._roster._find(self._uid)
        label = (item.get("label") if item else "") or f"{self._uid:08x}"
        return f"{label} — ouvre {door_name(self._hass, self._other_id)}"

    @property
    def available(self) -> bool:
        return self._other() is not None

    @property
    def is_on(self) -> bool:
        other = self._other()
        return bool(other and other._find(self._uid))

    async def async_turn_on(self, **kwargs) -> None:
        other, item = self._other(), self._roster._find(self._uid)
        if not other or not item:
            return
        # L'identite suit le badge ; seule l'appartenance se decide ici.
        if other.add_card(
            self._uid,
            label=item.get("label", ""),
            pin=item.get("pin", ""),
            email=item.get("email", ""),
            phone=item.get("phone", ""),
        ):
            await other.commit()
        await self._notify()

    async def async_turn_off(self, **kwargs) -> None:
        other = self._other()
        if other and other.remove(self._uid):
            await other.commit()
        await self._notify()

    async def _notify(self) -> None:
        # Un roster qui n'est pas pousse n'ouvre ni ne ferme rien. Le taire
        # laisserait croire que la porte a change d'avis — elle n'en sait rien.
        await self._hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Doorbell",
                "message": (
                    f"Accès modifié pour {door_name(self._hass, self._other_id)}. "
                    "Clique « Appliquer » sur CETTE porte pour que ce soit effectif."
                ),
                "notification_id": f"doorbell_access_{self._other_id}",
            },
            blocking=False,
        )
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        # S'abonner AUX DEUX rosters : le sien pour le libelle affiche, celui
        # d'en face pour l'etat de l'interrupteur.
        for entry_id in (self._entry_id, self._other_id):
            self.async_on_remove(
                async_dispatcher_connect(
                    self.hass, roster_signal(entry_id), self._refresh
                )
            )

    @callback
    def _refresh(self) -> None:
        self.async_write_ha_state()
