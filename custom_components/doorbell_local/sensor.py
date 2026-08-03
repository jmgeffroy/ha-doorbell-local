"""Capteurs : cartes enrôlées sur le device + roster de PIN détenu par HA."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HOST, DOMAIN
from .coordinator import DoorbellCoordinator
from .roster import Roster, roster_signal


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    ctx = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            DoorbellCardsSensor(ctx["coordinator"], entry),
            DoorbellRosterSensor(ctx["roster"], entry),
        ]
    )


def _device_info(host: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, host)},
        name=f"Doorbell {host}",
        manufacturer="Tuya / sun8i (X5_83225)",
        model="RFID door controller",
    )


class DoorbellCardsSensor(CoordinatorEntity[DoorbellCoordinator], SensorEntity):
    """État = nombre de cartes enrôlées sur le DEVICE ; attribut `cards`."""

    _attr_has_entity_name = True
    _attr_name = "Enrolled cards"
    _attr_icon = "mdi:card-account-details"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: DoorbellCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_cards"
        self._attr_device_info = _device_info(entry.data[CONF_HOST])

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data or [])

    @property
    def extra_state_attributes(self) -> dict:
        cards = self.coordinator.data or []
        return {
            "cards": cards,
            "managers": [c["uid"] for c in cards if c["type"] == "manager"],
            "users": [c["uid"] for c in cards if c["type"] == "user"],
        }


class DoorbellRosterSensor(SensorEntity):
    """État = nombre de PIN posés dans le roster HA.

    Depuis la 2.1, l'attribut `entries` expose la VALEUR du PIN (pour l'éditer/
    l'envoyer depuis le tableau). HA est local et réservé à l'admin — assumé.
    """

    _attr_has_entity_name = True
    _attr_name = "Staged PIN codes"
    _attr_icon = "mdi:form-textbox-password"
    _attr_should_poll = False

    def __init__(self, roster: Roster, entry: ConfigEntry) -> None:
        self._roster = roster
        self._entry_id = entry.entry_id
        self._attr_unique_id = f"{entry.entry_id}_roster"
        self._attr_device_info = _device_info(entry.data[CONF_HOST])

    async def async_added_to_hass(self) -> None:
        """Se rafraîchit dès que le roster change (signal émis par commit())."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                roster_signal(self._entry_id),
                self.async_write_ha_state,
            )
        )

    @callback
    def _entry_view(self, e: dict) -> dict:
        return {
            "uid": f"{e['uid']:08x}",
            "type": e.get("type", "user"),
            "label": e.get("label", ""),
            "email": e.get("email", ""),
            "phone": e.get("phone", ""),
            "virtual": e.get("virtual", False),
            "pin_set": bool(e.get("pin")),
            # le PIN est exposé pour le tableau/lien WhatsApp (HA local, admin only)
            "pin": e.get("pin", ""),
        }

    @property
    def native_value(self) -> int:
        return sum(1 for e in self._roster.entries if e.get("pin"))

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "entries": [self._entry_view(e) for e in self._roster.entries],
            "staged_file": "/local/ICCardDB0.ext",
            "seq": self._roster.seq,
        }
