"""Capteur : nombre de cartes enrôlées (+ liste en attributs)."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HOST, DOMAIN
from .coordinator import DoorbellCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DoorbellCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DoorbellCardsSensor(coordinator, entry)])


class DoorbellCardsSensor(CoordinatorEntity[DoorbellCoordinator], SensorEntity):
    """État = nombre de cartes ; attribut `cards` = liste {uid, type}."""

    _attr_has_entity_name = True
    _attr_name = "Enrolled cards"
    _attr_icon = "mdi:card-account-details"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: DoorbellCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        host = entry.data[CONF_HOST]
        self._attr_unique_id = f"{entry.entry_id}_cards"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, host)},
            name=f"Doorbell {host}",
            manufacturer="Tuya / sun8i (X5_83225)",
            model="RFID door controller",
            configuration_url=None,
        )

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
