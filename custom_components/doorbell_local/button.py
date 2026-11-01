"""Entités `button` par code : supprimer, ou copier sur les autres doorbells.

Appuyer régénère le fichier ICCardDB concerné (il faudra ensuite « Appliquer »
pour que la doorbell en tienne compte).
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
        return [
            (f"{uid:08x}_delete", lambda u=uid: _DeleteButton(roster, entry, u)),
            (f"{uid:08x}_copy", lambda u=uid: _CopyButton(hass, roster, entry, u)),
        ]

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
        # « <libellé> — Supprimer » pour se ranger avec les champs du même code
        # quand auto-entities/la page appareil trie par nom.
        return f"{label} — Supprimer"

    async def async_press(self) -> None:
        if self._roster.remove(self._uid):
            await self._roster.commit()


class _CopyButton(ButtonEntity):
    """Recopie cette entrée sur TOUTES les autres doorbells configurées.

    Le fichier ICCardDB fait autorité : une doorbell accepte la carte qu'il
    décrit, même si son lecteur ne l'a jamais enrôlée. Recopier l'UID d'un
    roster à l'autre suffit donc à faire ouvrir le même badge partout — c'est
    ce que ce bouton automatise pour un badge inscrit après coup sur une seule
    porte.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:content-duplicate"

    def __init__(
        self, hass: HomeAssistant, roster: Roster, entry: ConfigEntry, uid: int
    ) -> None:
        self._hass = hass
        self._roster = roster
        self._entry_id = entry.entry_id
        self._uid = uid
        self._attr_unique_id = f"{entry.entry_id}_{uid:08x}_copy"
        self._attr_device_info = device_info(entry)

    @property
    def name(self) -> str:
        item = self._roster._find(self._uid)
        label = (item.get("label") if item else "") or f"{self._uid:08x}"
        return f"{label} — Copier sur les autres portes"

    @property
    def available(self) -> bool:
        # Inutile — et trompeur — tant qu'il n'y a qu'une seule doorbell.
        return len(self._hass.data.get(DOMAIN, {})) > 1

    async def async_press(self) -> None:
        item = self._roster._find(self._uid)
        if not item:
            return
        done = []
        for other_id, ctx in self._hass.data.get(DOMAIN, {}).items():
            if other_id == self._entry_id:
                continue
            other: Roster = ctx["roster"]
            added = other.add_card(
                self._uid,
                label=item.get("label", ""),
                pin=item.get("pin", ""),
                email=item.get("email", ""),
                phone=item.get("phone", ""),
            )
            if added:
                await other.commit()
                done.append(other_id)
        # Le roster ne vaut rien tant qu'il n'est pas pousse : le dire, plutot
        # que de laisser croire que la porte est deja ouverte a ce badge.
        await self._hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Doorbell",
                "message": (
                    f"Badge {self._uid:08x} recopié sur {len(done)} autre(s) "
                    "porte(s). Clique « Appliquer » sur CHACUNE pour que ce "
                    "soit effectif."
                ),
                "notification_id": f"doorbell_copy_{self._uid:08x}",
            },
            blocking=False,
        )
