"""Outils partagés pour les entités par-code (créées/supprimées dynamiquement).

Chaque code du roster expose plusieurs entités (PIN éditable, email, téléphone,
bouton Supprimer). Elles apparaissent et disparaissent au rythme du roster : le
gestionnaire ci-dessous s'abonne au signal `roster_updated` et synchronise le
jeu d'entités (ajoute les nouvelles, retire — registre compris — les obsolètes).
"""
from __future__ import annotations

from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_HOST, DOMAIN
from .roster import Roster, roster_signal

# type d'un « spec » : pour une entrée du roster, renvoie [(clé_unique, fabrique)]
EntitySpecs = Callable[[dict], list[tuple[str, Callable[[], Entity]]]]


def device_info(entry: ConfigEntry) -> DeviceInfo:
    host = entry.data[CONF_HOST]
    return DeviceInfo(
        identifiers={(DOMAIN, host)},
        name=f"Doorbell {host}",
        manufacturer="Tuya / sun8i (X5_83225)",
        model="RFID door controller",
    )


def setup_dynamic_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    roster: Roster,
    async_add_entities: AddEntitiesCallback,
    specs: EntitySpecs,
) -> None:
    """Crée/retire des entités au fil des changements du roster.

    `specs(entry)` renvoie, pour une entrée, la liste (clé unique, fabrique
    d'entité). Une clé jamais vue est instanciée ; une clé disparue est retirée
    du registre. Idempotent : réappelable à chaque signal.
    """
    known: dict[str, Entity] = {}

    @callback
    def _sync() -> None:
        want: dict[str, Callable[[], Entity]] = {}
        for item in roster.entries:
            for key, factory in specs(item):
                want[key] = factory

        new: list[Entity] = []
        for key, factory in want.items():
            if key not in known:
                ent = factory()
                known[key] = ent
                new.append(ent)
        if new:
            async_add_entities(new)

        for key in list(known):
            if key not in want:
                ent = known.pop(key)
                hass.async_create_task(_async_remove(hass, ent))

    _sync()
    entry.async_on_unload(
        async_dispatcher_connect(hass, roster_signal(entry.entry_id), _sync)
    )


async def _async_remove(hass: HomeAssistant, ent: Entity) -> None:
    """Retire une entité de HA ET du registre (sinon elle reste « indisponible »)."""
    entity_id = getattr(ent, "entity_id", None)
    if entity_id:
        registry = er.async_get(hass)
        if registry.async_get(entity_id):
            registry.async_remove(entity_id)
            return
    await ent.async_remove(force_remove=True)


def door_name(hass: HomeAssistant, entry_id: str) -> str:
    """Le nom de la doorbell tel que l'utilisateur le voit.

    On passe par le registre des appareils, et non par le titre de l'entree de
    configuration : c'est l'appareil que l'on renomme dans l'interface, et un
    interrupteur qui dirait encore « Doorbell 192.168.68.55 » apres un
    renommage serait un piege de plus.
    """
    reg = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(reg, entry_id)
    if devices:
        return devices[0].name_by_user or devices[0].name or entry_id[:8]
    return entry_id[:8]


async def propagate_identity(
    hass: HomeAssistant, origin_entry_id: str, uid: int, fields: dict
) -> None:
    """Recopie l'identite d'un badge sur toutes les portes qui le connaissent.

    Un meme badge vit dans plusieurs rosters, un par porte. Sans cela, corriger
    un email obligerait a le ressaisir porte par porte — et la premiere oubliee
    ferait diverger la fiche en silence. L'APPARTENANCE reste par porte (c'est
    le role des interrupteurs) ; seule l'IDENTITE suit le badge.
    """
    for other_id, ctx in hass.data.get(DOMAIN, {}).items():
        if other_id == origin_entry_id:
            continue
        other: Roster = ctx["roster"]
        if other._find(uid) is None:
            continue
        if other.update(uid, fields):
            await other.commit()
