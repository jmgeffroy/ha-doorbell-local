"""Protocole MSG server de la doorbell Tuya/sun8i (X5_83225), TCP 34952.

Framing décodé et VALIDÉ EN LIVE (voir msg_server_findings.md, dispatcher fcn.0x35630) :
  En-tête requête = 20 o LE : [0]=marker 0x6666AAAA [4]=cmd [8..0xf]=roomid/userid u64 [0x10]=param2
  puis payload N octets.  Gate = SEULEMENT le marqueur (pas de nom, pas d'auth).
  ACK = 24 o (SendAck) ou, pour list, en-tête 20 o + N*5 o ; response_id toujours à l'offset 4.

Client SYNCHRONE (socket bloquant) : à appeler depuis HA via hass.async_add_executor_job().
Aucune dépendance externe (stdlib seule).
"""
from __future__ import annotations

import socket
import struct

DEFAULT_PORT = 34952
MARKER = 0x6666AAAA

CMD_LIST = 0x00020119
CMD_DELONE = 0x0002010B
CMD_DELROOM = 0x00020105
CMD_SETPIN = 0x00020201

# response_id attendu par commande (permet de confirmer le succès)
_EXPECTED_RESP = {
    CMD_LIST: 0x0002011A,
    CMD_DELONE: 0x0002010C,
    CMD_DELROOM: 0x00020106,
    CMD_SETPIN: 0x00020202,
}

RESERVED_PIN = "914900"  # refusé par le firmware
CARD_TYPES = {0: "manager", 1: "user"}


class DoorbellError(Exception):
    """Erreur de communication ou de protocole avec la doorbell."""


class DoorbellClient:
    """Client synchrone du MSG server. Une connexion TCP par commande."""

    def __init__(self, host: str, port: int = DEFAULT_PORT, timeout: float = 4.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    # -- bas niveau ---------------------------------------------------------
    @staticmethod
    def _header(cmd: int, room: int = 0, param2: int = 0) -> bytes:
        return struct.pack(
            "<IIIII", MARKER, cmd, room & 0xFFFFFFFF, (room >> 32) & 0xFFFFFFFF, param2
        )

    def _txn(self, cmd: int, room: int = 0, param2: int = 0, payload: bytes = b"") -> tuple[int, bytes]:
        """Envoie l'en-tête (+payload) et aspire toute la réponse.

        Retourne (response_id, buffer_complet). Lève DoorbellError sur échec réseau
        ou marqueur de réponse invalide.
        """
        hdr = self._header(cmd, room, param2)
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
                sock.settimeout(self.timeout)
                sock.sendall(hdr)
                if payload:
                    sock.sendall(payload)
                buf = b""
                try:
                    while len(buf) < 20:
                        chunk = sock.recv(4096)
                        if not chunk:
                            break
                        buf += chunk
                    sock.settimeout(1.0)
                    while True:  # aspire la suite éventuelle (records de list)
                        chunk = sock.recv(4096)
                        if not chunk:
                            break
                        buf += chunk
                except socket.timeout:
                    pass
        except OSError as err:
            raise DoorbellError(f"connexion {self.host}:{self.port} : {err}") from err

        if len(buf) < 8:
            raise DoorbellError(f"réponse trop courte ({len(buf)} o)")
        marker, rid = struct.unpack("<II", buf[:8])
        if marker != MARKER:
            raise DoorbellError(f"marqueur de réponse invalide {marker:#010x}")
        return rid, buf

    def _txn_checked(self, cmd: int, **kw) -> int:
        """Comme _txn mais vérifie le response_id attendu. Retourne le response_id."""
        rid, _ = self._txn(cmd, **kw)
        expected = _EXPECTED_RESP[cmd]
        if rid != expected:
            raise DoorbellError(
                f"réponse inattendue {rid:#010x} (attendu {expected:#010x}) pour cmd {cmd:#010x}"
            )
        return rid

    # -- haut niveau --------------------------------------------------------
    def list_cards(self, room: int = 0) -> list[dict]:
        """Liste les cartes du roomid donné (0 = cartes enrôlées par défaut).

        Retourne une liste de dicts {index, uid (hex str), uid_int, type}.
        """
        rid, buf = self._txn(CMD_LIST, room=room)
        if rid != _EXPECTED_RESP[CMD_LIST]:
            raise DoorbellError(f"réponse list inattendue {rid:#010x}")
        reclen = struct.unpack("<I", buf[16:20])[0] if len(buf) >= 20 else 0
        records = buf[20 : 20 + reclen] if reclen else buf[20:]
        cards: list[dict] = []
        for i in range(len(records) // 5):
            typ = records[i * 5]
            uid_int = struct.unpack("<I", records[i * 5 + 1 : i * 5 + 5])[0]
            cards.append(
                {
                    "index": i,
                    "uid": f"{uid_int:08x}",
                    "uid_int": uid_int,
                    "type": CARD_TYPES.get(typ, f"type{typ}"),
                }
            )
        return cards

    def revoke_card(self, uid: int) -> None:
        """Révoque une carte par son UID (u32). L'UID part en little-endian."""
        self._txn_checked(CMD_DELONE, payload=struct.pack("<I", uid & 0xFFFFFFFF))

    def revoke_room(self, room: int) -> None:
        """Révoque toutes les cartes d'un roomid."""
        self._txn_checked(CMD_DELROOM, room=room, payload=struct.pack("<I", 0))

    def set_pin(self, room: int, pin: str) -> None:
        """Change le PIN d'un user/room. `pin` = chiffres (UTF-16LE, padding 32 o)."""
        if pin == RESERVED_PIN:
            raise DoorbellError(f"PIN {RESERVED_PIN} réservé (refusé par le firmware)")
        if not pin.isdigit():
            raise DoorbellError("PIN : chiffres uniquement")
        body = pin.encode("utf-16-le")
        if len(body) > 32:
            raise DoorbellError("PIN trop long (max 16 chiffres)")
        payload = body + b"\x00" * (32 - len(body))
        self._txn_checked(CMD_SETPIN, room=room, payload=payload)
