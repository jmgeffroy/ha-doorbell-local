#!/usr/bin/env python3
"""Pont UART <-> HTTP MULTI-doorbell (alternative à l'ESP).

À lancer sur la machine (ex. l'hôte de la VM Home Assistant) reliée aux consoles
série (root, sans mot de passe) des doorbells via des adaptateurs USB-UART — par
exemple à travers les paires libres des câbles Ethernet qui vont aux doorbells.

Home Assistant l'appelle en HTTP pour pousser le fichier ICCardDB + rebooter la
BONNE doorbell, sans que HA ait besoin d'un accès direct à l'UART.

Chaque doorbell = une entrée du dict DOORBELLS : son port série + l'URL du fichier
ICCardDB généré par HA pour ELLE. On adresse une doorbell par son `id` (paramètre
d'URL `?id=...` ou champ `"id"` du corps JSON). Avec une seule doorbell configurée,
l'`id` est optionnel.

⚠️ CÂBLAGE : mets une résistance série ~2,2 kΩ sur TX(adaptateur)->RX(doorbell) et
un GND commun, sinon le courant fantôme peut empêcher la doorbell de booter.
⚠️ NUMÉROS DE SÉRIE : chaque adaptateur doit avoir un serial UNIQUE pour un nom de
port stable (les CH340 sans serial partagent le même nom = ingérable).

Installer :  pip install pyserial
Lancer    :  python doorbell_uart_agent.py

Endpoints (jeton partagé obligatoire dans l'en-tête X-Token) :
  POST /apply?id=<nom>             -> pousse /data/ICCardDB0.ext depuis HA + reboot
  POST /send  {"id":"<nom>","cmd"} -> commande shell arbitraire sur la doorbell
  GET  /read?id=<nom>              -> dernières lignes de la console UART

SÉCURITÉ : cet agent relaie des SHELLS ROOT. À n'exposer que sur un LAN de
confiance (idéalement un VLAN isolé), change le TOKEN, ne l'ouvre JAMAIS sur Internet.
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import serial  # pip install pyserial

# ----------------------- À ADAPTER -----------------------
BAUD = 115200
HTTP_PORT = 8765
TOKEN = "change-me"                 # jeton partagé — à recopier côté HA

# Une entrée par doorbell. `file_url` = l'URL du fichier ICCardDB que HA génère
# POUR cette doorbell (chaque doorbell doit avoir son propre fichier côté HA).
DOORBELLS = {
    "perron": {
        "port": "/dev/ttyUSB0",     # Windows: "COM3" ; macOS: "/dev/cu.usbserial-XXXX"
        "file_url": "http://homeassistant.local:8123/local/ICCardDB0.ext",
    },
    # "portail": {
    #     "port": "/dev/ttyUSB1",
    #     "file_url": "http://homeassistant.local:8123/local/ICCardDB0_portail.ext",
    # },
}
# ---------------------------------------------------------


def apply_cmd(file_url: str) -> str:
    return (
        f"wget -O /data/ICCardDB0.ext {file_url}"
        " ; rm -f /data/ICCardDB1.ext ; sync ; reboot"
    )


class Link:
    """Une liaison série vers une doorbell (thread lecteur + buffer + envoi)."""

    def __init__(self, name: str, port: str, file_url: str) -> None:
        self.name = name
        self.port = port
        self.file_url = file_url
        self._lock = threading.Lock()
        self._lines: deque[str] = deque(maxlen=400)
        self._ser: serial.Serial | None = None
        threading.Thread(target=self._reader, daemon=True).start()

    def _open(self) -> serial.Serial:
        while True:
            try:
                s = serial.Serial(self.port, BAUD, timeout=1)
                print(f"[{self.name}] port {self.port} @ {BAUD} ouvert")
                return s
            except Exception as err:  # noqa: BLE001
                print(f"[{self.name}] echec ouverture {self.port}: {err} - retry 3 s")
                time.sleep(3)

    def _reader(self) -> None:
        self._ser = self._open()
        buf = b""
        while True:
            try:
                data = self._ser.read(256)
                if data:
                    buf += data
                    while b"\n" in buf:
                        raw, buf = buf.split(b"\n", 1)
                        self._lines.append(raw.decode(errors="replace").rstrip("\r"))
            except Exception as err:  # noqa: BLE001
                print(f"[{self.name}] lecture: {err} - reouverture")
                time.sleep(1)
                with self._lock:
                    self._ser = self._open()

    def send_line(self, cmd: str) -> None:
        with self._lock:
            self._ser.write(b"\x15")   # Ctrl-U : efface toute saisie résiduelle
            self._ser.flush()
            time.sleep(0.25)
            self._ser.write((cmd + "\n").encode())
            self._ser.flush()

    def tail(self, n: int = 60) -> list[str]:
        return list(self._lines)[-n:]


LINKS: dict[str, Link] = {
    name: Link(name, cfg["port"], cfg["file_url"]) for name, cfg in DOORBELLS.items()
}


class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth(self) -> bool:
        if self.headers.get("X-Token") != TOKEN:
            self._json(403, {"error": "bad token"})
            return False
        return True

    def _link(self, name: str) -> "Link | None":
        """Résout l'id ; défaut si une seule doorbell est configurée."""
        if not name and len(LINKS) == 1:
            name = next(iter(LINKS))
        link = LINKS.get(name)
        if not link:
            self._json(404, {"error": f"doorbell inconnue: {name!r}", "known": list(LINKS)})
            return None
        return link

    def do_GET(self) -> None:  # noqa: N802
        if not self._auth():
            return
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if parsed.path == "/read":
            link = self._link((qs.get("id") or [""])[0])
            if link:
                self._json(200, {"id": link.name, "lines": link.tail()})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._auth():
            return
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        n = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(n).decode() if n else ""
        try:
            data = json.loads(raw) if raw else {}
        except Exception:  # noqa: BLE001
            data = {}
        name = (qs.get("id") or [data.get("id", "")])[0]

        if parsed.path == "/apply":
            link = self._link(name)
            if link:
                link.send_line(apply_cmd(link.file_url))
                self._json(200, {"status": "apply sent", "id": link.name})
        elif parsed.path == "/send":
            link = self._link(name)
            if not link:
                return
            cmd = data.get("cmd", "")
            if not cmd:
                self._json(400, {"error": "missing cmd"})
                return
            link.send_line(cmd)
            self._json(200, {"status": "sent", "id": link.name, "cmd": cmd})
        else:
            self._json(404, {"error": "not found"})

    def log_message(self, *args) -> None:  # silence
        pass


def main() -> None:
    if not LINKS:
        raise SystemExit("Aucune doorbell configurée (dict DOORBELLS vide).")
    print(f"[agent] doorbells: {', '.join(LINKS)}")
    print(f"[agent] HTTP sur 0.0.0.0:{HTTP_PORT} - endpoints /apply /send /read (param id)")
    ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
