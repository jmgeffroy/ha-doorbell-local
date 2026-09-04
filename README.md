# Doorbell Local — RFID card & PIN management for Home Assistant

[![hacs][hacs-badge]][hacs-url]

Local, cloud-free management of the **RFID cards and PIN codes** of a Tuya/sun8i RFID
door controller (sold as **X5_83225** and similar white-label doorbell/access units).

The integration talks directly to the device's on-board **MSG server over TCP**, on your LAN.
No cloud, no account, **no root**, no firmware modification — the server is running from
the factory, so this works on an unmodified device.

> **Scope:** this integration manages *cards and PINs*. Opening the door is handled by
> whatever relay your unit drives — commonly a Tuya relay via
> [LocalTuya](https://github.com/xZetsubou/hass-localtuya). See [Opening the door](#opening-the-door).

---

## Features

**Network (MSG server, instant, no reboot):**
- **Sensor** `enrolled cards` — count + full list (UID + manager/user) as attributes.
- **Service `revoke_card`** — remove a card by its UID. Immediate.
- **Service `refresh`** — re-read the card database on demand.

**PIN management (v2 — via the ICCardDB file + a UART bridge):**
- **Sensor** `staged PIN codes` — the HA-held roster.
- **Service `set_pin`** — set a 4-digit PIN on a badge.
- **Service `add_code`** — create a **standalone PIN** (a "virtual card": opens with no
  physical badge), with an optional label, owner **email and phone** (both optional).
- **Service `update_contact`** — change an entry's label / email / phone (leaves the PIN).
- **Services `remove_entry` / `import_cards` / `stage`** — manage the roster / regenerate the file.

**Per-code entities (v2.1):** every code exposes editable `text` entities (PIN, phone,
email) and a `button` to delete it. They appear/disappear as codes are created/removed, so
you can manage everything inline from a dashboard (see [`dashboard/`](dashboard/)) or from
the device page. A phone number lets the dashboard build a one-tap **WhatsApp** link
(`wa.me`) to send the owner their code.

> ⚠️ Since v2.1 the roster sensor and the PIN text entity expose the **PIN value** (needed
> to edit/send it from the table). Home Assistant is local and admin-only — an accepted
> trade-off; the component still never writes PINs to the log.

HA is the source of truth for PINs (the device does not expose them). These services
(re)generate `/config/www/ICCardDB0.ext`, served at `/local/ICCardDB0.ext`. A small
**UART bridge** at the device (an ESP32, or any always-on machine wired to the doorbell's
serial console — which is an unauthenticated root shell) then applies it with one line:
`wget -O /data/ICCardDB0.ext http://<ha>:8123/local/ICCardDB0.ext ; rm -f /data/ICCardDB1.ext ; sync ; reboot`.
Applying a PIN change requires that bridge + a reboot (~1 min); listing/revoking do not.

A ready-made dashboard + scripts (create a code, email it to its owner) is in
[`dashboard/`](dashboard/).

### On adding cards

There is **no network "add card" command** — over the network you can only list and revoke.
But with the UART bridge above you *can* add cards (and set PINs) by regenerating the ICCardDB
file. Without the bridge, enrol via the physical master-card procedure, then manage from HA.

---

## Installation

### HACS (recommended)

1. HACS → **Integrations** → ⋮ → **Custom repositories**
2. Add `https://github.com/jmgeffroy/ha-doorbell-local`, category **Integration**
3. Install **Doorbell Local**, then **restart Home Assistant**

### Manual

Copy `custom_components/doorbell_local/` into your Home Assistant `/config/custom_components/`
directory and restart.

### Configuration

**Settings → Devices & Services → Add Integration → “Doorbell Local”**, then enter the
device's **IP address** (default port `34952`). The config flow verifies the connection
before creating the entry.

> 💡 **Reserve the device's IP in your router's DHCP settings.** These units use DHCP and
> the integration is addressed by IP.
>
> 💡 **Finding the IP:** the device does not always announce itself. If you cannot find it in
> your router's client list, a serial (UART) console gives it up with `ifconfig eth0`.
> Note that port scanners often report the port as *filtered* — the server only answers
> properly framed connections, so trust the integration, not `nmap`.

### Several doorbells (v2.2)

Add one config entry per device. Each entry keeps its **own roster**, and each publishes
its **own ICCardDB file** — that is what the **ICCardDB file name** field is for.

| Doorbell | File name | Served at |
|---|---|---|
| first (default) | `ICCardDB0.ext` | `/local/ICCardDB0.ext` |
| second | e.g. `ICCardDB0_gate.ext` | `/local/ICCardDB0_gate.ext` |

Leaving the default on an existing entry changes nothing: **upgrading to v2.2 requires no
migration.** Give every additional doorbell a distinct name — the config flow refuses a
name already taken, because two entries sharing one file would overwrite each other and
“Apply” on one would push the *other* one's codes.

Each doorbell then needs its own entry in the UART agent, pointing at its own URL:

```python
DOORBELLS = {
    "front":  {"port": "/dev/ttyUSB0", "file_url": "http://ha.local:8123/local/ICCardDB0.ext"},
    "gate":   {"port": "/dev/ttyUSB1", "file_url": "http://ha.local:8123/local/ICCardDB0_gate.ext"},
}
```

and one `rest_command` per doorbell, addressing it with `?id=`:

```yaml
rest_command:
  doorbell_apply_front:
    url: "http://AGENT_HOST:8765/apply?id=front"
    method: POST
    headers:
      X-Token: "your-token"
```

The `staged_file` attribute of the *staged PIN codes* sensor always tells you which URL a
given entry publishes — copy it into `file_url`.

> ⚠️ Each USB-UART adapter must expose a **unique serial number**, otherwise the port names
> are not stable (many CH340 clones share one, which makes them impossible to tell apart).

---

## Entities

| Entity | Description |
|---|---|
| `sensor.doorbell_<host>_enrolled_cards` | State = card count. Attributes: `cards` (list of `{uid, type}`), `managers`, `users`. |
| `sensor.doorbell_<host>_staged_pin_codes` | State = number of staged PINs. Attribute `entries` (list of `{uid, label, type, email, phone, pin, virtual}`). |
| `text.doorbell_<host>_<label>_pin` / `_phone` / `_email` | One per code — editable inline (v2.1). Setting the PIN regenerates the file. |
| `button.doorbell_<host>_supprimer_<label>` | One per code — deletes it from the roster (v2.1). |

## Services

### `doorbell_local.revoke_card`
| Field | Required | Description |
|---|---|---|
| `uid` | yes | Card UID in hex, e.g. `940cbbe1` — exactly as shown in the sensor attributes. |
| `entry_id` | no | Only needed if you have several doorbells configured. |

### `doorbell_local.revoke_room`
| Field | Required | Description |
|---|---|---|
| `room` | yes | Room id. Cards enrolled by the default procedure use room `0`. |
| `entry_id` | no | |

### `doorbell_local.set_pin`
| Field | Required | Description |
|---|---|---|
| `room` | yes | Room / user id whose code is being changed. |
| `pin` | yes | Digits only (4 for a user code, 6 for admin/public). |
| `entry_id` | no | |

PINs are **never written to the log**. The code `914900` is reserved and rejected by the firmware.

### `doorbell_local.refresh`
Forces an immediate re-read of the card database.

---

## Opening the door

This integration deliberately does **not** drive the lock — on these units the strike is wired
to a relay that is usually exposed as its own Tuya device. With
[LocalTuya](https://github.com/xZetsubou/hass-localtuya) providing a switch entity, a template
lock gives you a proper `lock.*` entity (the relay is momentary / "inching", so it releases itself):

```yaml
lock:
  - platform: template
    name: Front door
    unique_id: front_door_strike
    value_template: "{{ is_state('switch.YOUR_RELAY', 'off') }}"
    lock:
      - service: switch.turn_off
        target: { entity_id: switch.YOUR_RELAY }
    unlock:
      - service: switch.turn_on
        target: { entity_id: switch.YOUR_RELAY }
```

---

## Examples

Revoke a lost badge from a dashboard input:

```yaml
alias: Revoke badge
trigger:
  - platform: state
    entity_id: input_button.revoke_badge
action:
  - service: doorbell_local.revoke_card
    data:
      uid: "{{ states('input_text.badge_uid') }}"
```

Rotate a tenant's PIN monthly:

```yaml
alias: Monthly PIN rotation
trigger:
  - platform: time
    at: "04:00:00"
condition:
  - condition: template
    value_template: "{{ now().day == 1 }}"
action:
  - service: doorbell_local.set_pin
    data:
      room: 3
      pin: "{{ range(1000, 9999) | random }}"
```

---

## Protocol notes

The device exposes a message server on **TCP 34952**. Requests use a 20-byte little-endian
header — a `0x6666AAAA` marker, a 32-bit command id, a 64-bit room/user id — optionally followed
by a payload; one TCP connection per command. The card list comes back as 5-byte records
(`type` byte + `uid` u32 LE).

**There is no authentication.** Anyone able to reach TCP 34952 can list and revoke cards.
Keep these devices on a trusted or isolated VLAN, and do not expose that port to the internet.

## Compatibility

Developed against an **X5_83225** (Allwinner sun8i, Tuya firmware). Other white-label units
built on the same firmware are likely to work. Reports welcome via
[issues](https://github.com/jmgeffroy/ha-doorbell-local/issues).

## Disclaimer

Not affiliated with Tuya or any device manufacturer. This integration was developed by
analysing a device the author owns, for interoperability with Home Assistant. It manages a
**physical access control system** — test changes carefully, and keep a physical master card
and a way back in.

## License

MIT — see [LICENSE](LICENSE).

[hacs-badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
[hacs-url]: https://github.com/hacs/integration
