#!/usr/bin/env python3
"""Pont UART <-> HTTP pour la doorbell (alternative à l'ESP).

À lancer sur la machine (ex. l'hôte de la VM Home Assistant) reliée à la console
série (root, sans mot de passe) de la doorbell via un adaptateur USB-UART — par
exemple à travers les paires libres du câble Ethernet 100M qui va à la doorbell.

Home Assistant l'appelle en HTTP pour pousser le fichier ICCardDB + rebooter,
sans que HA ait besoin d'un accès direct à l'UART.

Installer :  pip install pyserial
Lancer    :  python doorbell_uart_agent.py

Endpoints (jeton partagé obligatoire dans l'en-tête X-Token) :
  POST /apply            -> pousse /data/ICCardDB0.ext depuis HA + reboot
  POST /send {"cmd":"…"} -> exécute une commande shell arbitraire sur la doorbell
  GET  /read             -> dernières lignes de la console UART (debug / capter un UID)

SÉCURITÉ : cet agent relaie un SHELL ROOT. À n'exposer que sur un LAN de confiance
(idéalement un VLAN isolé), change le TOKEN, et ne l'ouvre JAMAIS sur Internet.
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import serial  # pip install pyserial

# ----------------------- À ADAPTER -----------------------
SERIAL_PORT = "COM3"              # port de l'adaptateur (Windows: Gestionnaire de périphériques ; Linux: /dev/ttyUSB0)
BAUD = 115200
HTTP_PORT = 8765
TOKEN = "change-me"               # jeton partagé — à recopier côté HA
HA_FILE_URL = "http://homeassistant.local:8123/local/ICCardDB0.ext"
APPLY_CMD = (
    f"wget -O /data/ICCardDB0.ext {HA_FILE_URL}"
    " ; rm -f /data/ICCardDB1.ext ; sync ; reboot"
)
# ---------------------------------------------------------

_ser_lock = threading.Lock()
_lines: deque[str] = deque(maxlen=400)   # buffer des dernières lignes UART
_ser: serial.Serial | None = None


def _open_serial() -> serial.Serial:
    while True:
        try:
            s = serial.Serial(SERIAL_PORT, BAUD, timeout=1)
            print(f"[agent] port serie {SERIAL_PORT} @ {BAUD} ouvert")
            return s
        except Exception as err:  # noqa: BLE001
            print(f"[agent] echec ouverture {SERIAL_PORT}: {err} - nouvel essai dans 3 s")
            time.sleep(3)


def _reader() -> None:
    """Lit l'UART en continu et bufferise les lignes (pour /read)."""
    global _ser
    buf = b""
    while True:
        try:
            data = _ser.read(256)
            if data:
                buf += data
                while b"\n" in buf:
                    raw, buf = buf.split(b"\n", 1)
                    _lines.append(raw.decode(errors="replace").rstrip("\r"))
        except Exception as err:  # noqa: BLE001
            print(f"[agent] lecture serie: {err} - reouverture")
            time.sleep(1)
            with _ser_lock:
                _ser = _open_serial()


def send_line(cmd: str) -> None:
    with _ser_lock:
        _ser.write((cmd + "\r\n").encode())
        _ser.flush()


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

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/read":
            if self._auth():
                self._json(200, {"lines": list(_lines)[-60:]})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._auth():
            return
        n = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(n).decode() if n else ""
        if self.path == "/apply":
            send_line(APPLY_CMD)
            self._json(200, {"status": "apply sent"})
        elif self.path == "/send":
            try:
                cmd = json.loads(body).get("cmd", "")
            except Exception:  # noqa: BLE001
                cmd = ""
            if not cmd:
                self._json(400, {"error": "missing cmd"})
                return
            send_line(cmd)
            self._json(200, {"status": "sent", "cmd": cmd})
        else:
            self._json(404, {"error": "not found"})

    def log_message(self, *args) -> None:  # silence
        pass


def main() -> None:
    global _ser
    _ser = _open_serial()
    threading.Thread(target=_reader, daemon=True).start()
    print(f"[agent] HTTP sur 0.0.0.0:{HTTP_PORT} - endpoints /apply /send /read")
    ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
