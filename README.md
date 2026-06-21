# homelab-ha-aux-lan

Home Assistant custom component for local LAN control of AUX air conditioners.
Uses BroadLink DNA protocol (UDP port 80) — no cloud, no AC Freedom app required.

## Devices
- AUX ACs with BroadLink WiFi modules (device type 0x4e2a)
- Confirmed working: AUX split units with MAC prefix 24:df:a7

## Protocol
BroadLink LAN (UDP port 80, AES-128-CBC). See `docs/broadlink-lan-protocol.md`.

