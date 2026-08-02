"""Construction du fichier binaire ICCardDB0.ext (base cartes/PIN de la doorbell).

Format (little-endian), validé par reverse + tests live (cf msg_server_findings /
iccard.py) :
  en-tête 12 o : [u32 seq][u32 count][magic 01 43 44 49 = \x01CDI]
  N records de 21 o :
    [0]      index (04,05,06...  = 4 + position)
    [1:5]    UID carte  (u32 LE)
    [5:9]    PIN        (4 chiffres, 1 octet/chiffre ; 0000/vide = pas de PIN)
    [9:17]   roomid/réservé = 0
    [17]     type : 00 = manager, 01 = user
    [18:21]  réservé = 0

Le clavier compare le code tapé à record[5:9] SANS exiger le badge physique :
un record « carte virtuelle » (UID bidon + PIN) = un PIN indépendant qui ouvre.
"""
from __future__ import annotations

import struct

MAGIC = bytes([0x01, 0x43, 0x44, 0x49])
RECSZ = 21


def pin_bytes(pin: str | None) -> bytes:
    """4 chiffres -> 4 octets (valeur du chiffre). Vide/'0000' -> 00 00 00 00."""
    if not pin or pin == "0000":
        return bytes(4)
    if not (pin.isdigit() and len(pin) == 4):
        raise ValueError("PIN de carte = exactement 4 chiffres")
    return bytes(int(c) for c in pin)


def build_iccarddb(seq: int, entries: list[dict]) -> bytes:
    """Assemble le fichier depuis le roster.

    entries: liste de dicts {uid:int, type:'user'|'manager', pin:str}.
    """
    out = bytearray(struct.pack("<II", seq & 0xFFFFFFFF, len(entries)) + MAGIC)
    for i, e in enumerate(entries):
        r = bytearray(RECSZ)
        r[0] = (4 + i) & 0xFF
        struct.pack_into("<I", r, 1, int(e["uid"]) & 0xFFFFFFFF)
        r[5:9] = pin_bytes(e.get("pin", ""))
        r[17] = 0 if e.get("type") == "manager" else 1
        out += bytes(r)
    return bytes(out)
