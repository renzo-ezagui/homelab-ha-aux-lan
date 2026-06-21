"""Config flow for AUX LAN."""
from __future__ import annotations

import logging
import re

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from . import DOMAIN
from .broadlink import BroadlinkAuthError, BroadlinkLanDevice, BroadlinkTimeoutError

_LOGGER = logging.getLogger(__name__)

MAC_RE = re.compile(r"^[0-9a-fA-F]{12}$|^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")

STEP_SCHEMA = vol.Schema(
    {
        vol.Required("name"): str,
        vol.Required("ip"): str,
        vol.Required("mac"): str,
        vol.Optional("scan_interval", default=30): vol.All(
            vol.Coerce(int), vol.Range(min=10, max=300)
        ),
    }
)


def _normalize_mac(mac: str) -> str:
    return mac.replace(":", "").lower()


async def _validate_device(hass: HomeAssistant, ip: str, mac: str) -> None:
    device = BroadlinkLanDevice(ip, mac)
    await hass.async_add_executor_job(device._send_recv_sync, _build_auth_packet(device))


def _build_auth_packet(device: BroadlinkLanDevice) -> bytes:
    from .broadlink import CMD_AUTH, DEFAULT_KEY, _build_packet
    payload = bytearray(0x50)
    payload[0x04:0x10] = b"\x31" * 12
    payload[0x1E] = 0x01
    payload[0x2D] = 0x01
    payload[0x30:0x37] = b"aux_lan"
    return _build_packet(CMD_AUTH, device.mac, b"\x00" * 4, DEFAULT_KEY, bytes(payload))


class AuxLanConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}

        if user_input is not None:
            name = user_input["name"].strip()
            ip = user_input["ip"].strip()
            mac_raw = user_input["mac"].strip()

            if not MAC_RE.match(mac_raw):
                errors["mac"] = "invalid_mac"
            else:
                mac = _normalize_mac(mac_raw)
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured()

                device = BroadlinkLanDevice(ip, mac)
                try:
                    await device.auth()
                    _LOGGER.info("config_flow: auth ok for %s at %s", name, ip)
                except BroadlinkAuthError:
                    errors["base"] = "cannot_connect"
                except BroadlinkTimeoutError:
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception("config_flow: unexpected error for %s", ip)
                    errors["base"] = "unknown"

                if not errors:
                    return self.async_create_entry(
                        title=name,
                        data={
                            "name": name,
                            "ip": ip,
                            "mac": mac,
                            "scan_interval": user_input.get("scan_interval", 30),
                        },
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_SCHEMA,
            errors=errors,
        )
