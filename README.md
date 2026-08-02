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

- **Sensor** — number of enrolled cards, with the full list (UID + manager/user) as attributes.
- **Service `revoke_card`** — remove a card by its UID. Takes effect immediately, no reboot.
- **Service `revoke_room`** — remove every card bound to a room id.
- **Service `set_pin`** — change a user's PIN code.
- **Service `refresh`** — re-read the card database on demand.

### What this integration cannot do

**Adding a card is not possible over the network.** The firmware exposes no "add card"
command — enrolment only happens through the RFID reader itself (present a *master* card,
then the new card). This is a firmware design decision, confirmed by disassembly, not a
limitation of this integration. Use the physical master-card procedure to enrol, then manage
(list / revoke / rotate PINs) from Home Assistant.

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

---

## Entities

| Entity | Description |
|---|---|
| `sensor.doorbell_<host>_enrolled_cards` | State = card count. Attributes: `cards` (list of `{uid, type}`), `managers`, `users`. |

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
