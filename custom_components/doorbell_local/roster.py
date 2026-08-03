"""Roster détenu par HA = source de vérité des cartes/PIN.

Le device n'expose PAS les PIN (le `list` réseau ne rend que UID+type). HA doit
donc mémoriser lui-même l'état voulu {uid, type, pin, label}, en reconstruire le
fichier ICCardDB0.ext et le publier dans /config/www/ (servi à /local/...).
L'application effective (wget + reboot côté doorbell) est faite ensuite par le
pont UART (ESP ou machine locale) — hors de ce composant.
"""
from __future__ import annotations

import logging
import os

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .iccarddb import build_iccarddb

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
WWW_FILENAME = "ICCardDB0.ext"
VIRTUAL_UID_BASE = 0xF0000000  # plage des UID « cartes virtuelles » (PIN autonomes)
SEQ_START = 1000  # seq de départ (dépasse largement les seq réels du device)


def roster_signal(entry_id: str) -> str:
    """Nom du signal dispatcher émis quand le roster change."""
    return f"{DOMAIN}_roster_updated_{entry_id}"


class Roster:
    """Roster persistant + génération du fichier ICCardDB dans /config/www/."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._store = Store(hass, STORE_VERSION, f"doorbell_local_{entry_id}_roster")
        self.entries: list[dict] = []
        self.seq: int = SEQ_START

    async def load(self) -> None:
        data = await self._store.async_load()
        if data:
            self.entries = data.get("entries", [])
            self.seq = data.get("seq", SEQ_START)

    async def _save(self) -> None:
        await self._store.async_save({"entries": self.entries, "seq": self.seq})

    # -- manipulation du roster --------------------------------------------
    def _find(self, uid: int) -> dict | None:
        return next((e for e in self.entries if e["uid"] == uid), None)

    def set_pin(
        self,
        uid: int,
        pin: str,
        type_: str = "user",
        email: str = "",
        phone: str = "",
    ) -> None:
        entry = self._find(uid)
        if entry:
            entry["pin"] = pin
            if email:
                entry["email"] = email
            if phone:
                entry["phone"] = phone
        else:
            self.entries.append(
                {
                    "uid": uid,
                    "type": type_,
                    "pin": pin,
                    "label": "",
                    "email": email,
                    "phone": phone,
                    "virtual": False,
                }
            )

    def add_code(self, pin: str, label: str, email: str = "", phone: str = "") -> int:
        """Ajoute un PIN indépendant (carte virtuelle, UID auto). Retourne l'UID."""
        used = {e["uid"] for e in self.entries}
        uid = VIRTUAL_UID_BASE
        while uid in used:
            uid += 1
        self.entries.append(
            {
                "uid": uid,
                "type": "user",
                "pin": pin,
                "label": label,
                "email": email,
                "phone": phone,
                "virtual": True,
            }
        )
        return uid

    def update(self, uid: int, fields: dict) -> bool:
        """Met à jour un ou plusieurs champs (pin/label/email/phone) d'une entrée."""
        entry = self._find(uid)
        if not entry:
            return False
        for key in ("pin", "label", "email", "phone"):
            if key in fields:
                entry[key] = fields[key]
        return True

    def remove(self, uid: int) -> bool:
        before = len(self.entries)
        self.entries = [e for e in self.entries if e["uid"] != uid]
        return len(self.entries) != before

    def import_cards(self, cards: list[dict]) -> int:
        """Fusionne les cartes lues sur le device (coordinator.data) sans écraser
        les PIN déjà connus. cards = [{uid_int, type, ...}]. Retourne le nb ajoutés."""
        added = 0
        for c in cards:
            if not self._find(c["uid_int"]):
                self.entries.append(
                    {
                        "uid": c["uid_int"],
                        "type": c.get("type", "user"),
                        "pin": "",
                        "label": "",
                        "email": "",
                        "phone": "",
                        "virtual": False,
                    }
                )
                added += 1
        return added

    # -- génération du fichier ---------------------------------------------
    def _www_path(self) -> str:
        return self._hass.config.path("www", WWW_FILENAME)

    def _write_file(self) -> str:
        self.seq += 1
        data = build_iccarddb(self.seq, self.entries)
        path = self._www_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        _LOGGER.info(
            "ICCardDB généré : %d entrées, seq=%d -> %s (%d o)",
            len(self.entries),
            self.seq,
            path,
            len(data),
        )
        return path

    async def commit(self) -> str:
        """Écrit le fichier (executor) + persiste le roster + notifie les capteurs."""
        path = await self._hass.async_add_executor_job(self._write_file)
        await self._save()
        async_dispatcher_send(self._hass, roster_signal(self._entry_id))
        return path
