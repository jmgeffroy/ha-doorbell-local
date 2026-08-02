"""Constantes de l'intégration doorbell_local."""
from __future__ import annotations

DOMAIN = "doorbell_local"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_PORT = 34952
DEFAULT_SCAN_INTERVAL = 300  # secondes ; la liste de cartes change rarement

# Services
SERVICE_REVOKE_CARD = "revoke_card"
SERVICE_REVOKE_ROOM = "revoke_room"
SERVICE_SET_PIN = "set_pin"
SERVICE_REFRESH = "refresh"

ATTR_ENTRY_ID = "entry_id"
ATTR_UID = "uid"
ATTR_ROOM = "room"
ATTR_PIN = "pin"
