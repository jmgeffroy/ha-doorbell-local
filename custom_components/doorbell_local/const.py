"""Constantes de l'intégration doorbell_local."""
from __future__ import annotations

DOMAIN = "doorbell_local"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_PORT = 34952
DEFAULT_SCAN_INTERVAL = 300  # secondes ; la liste de cartes change rarement

# Services réseau (MSG server, instantanés, sans reboot)
SERVICE_REVOKE_CARD = "revoke_card"
SERVICE_REFRESH = "refresh"

# Services roster/fichier (gestion des PIN via ICCardDB + pont UART)
SERVICE_SET_PIN = "set_pin"           # PIN d'un badge (ou crée l'entrée)
SERVICE_ADD_CODE = "add_code"         # PIN indépendant (carte virtuelle)
SERVICE_REMOVE_ENTRY = "remove_entry"
SERVICE_UPDATE_CONTACT = "update_contact"  # change label/email/phone d'une entrée
SERVICE_IMPORT_CARDS = "import_cards"  # amorcer le roster depuis le device
SERVICE_STAGE = "stage"               # régénérer le fichier sans changement

ATTR_ENTRY_ID = "entry_id"
ATTR_UID = "uid"
ATTR_PIN = "pin"
ATTR_LABEL = "label"
ATTR_EMAIL = "email"
ATTR_PHONE = "phone"
