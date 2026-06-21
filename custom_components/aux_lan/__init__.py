"""AUX LAN — Home Assistant custom component for local BroadLink AC control."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .broadlink import AcState, BroadlinkAuthError, BroadlinkLanDevice, BroadlinkTimeoutError

_LOGGER = logging.getLogger(__name__)

DOMAIN = "aux_lan"
PLATFORMS = ["climate"]
SCAN_INTERVAL = timedelta(seconds=30)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ip = entry.data["ip"]
    mac = entry.data["mac"]
    name = entry.data["name"]

    _LOGGER.debug("[%s] setup entry ip=%s mac=%s", name, ip, mac)

    device = BroadlinkLanDevice(ip, mac)

    try:
        await device.auth()
    except BroadlinkAuthError as exc:
        _LOGGER.error("[%s] auth failed: %s", name, exc)
        raise ConfigEntryNotReady(f"Cannot authenticate with {name} at {ip}") from exc

    scan_interval = timedelta(seconds=entry.data.get("scan_interval", 30))
    coordinator = AuxLanCoordinator(hass, device, name, scan_interval)

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as exc:
        raise ConfigEntryNotReady(f"First poll failed for {name}") from exc

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


class AuxLanCoordinator(DataUpdateCoordinator):
    def __init__(
        self,
        hass: HomeAssistant,
        device: BroadlinkLanDevice,
        name: str,
        scan_interval: timedelta = SCAN_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"aux_lan_{name}",
            update_interval=scan_interval,
        )
        self.device = device
        self.device_name = name

    async def _async_update_data(self) -> AcState:
        try:
            state, ambient = await asyncio.gather(
                self.device.get_state(),
                self.device.get_info(),
            )
            state.ambient_temp = ambient
            _LOGGER.debug(
                "[%s] poll ok power=%s temp=%s mode=%s ambient=%s",
                self.device_name,
                state.power,
                state.target_temp,
                state.mode,
                ambient,
            )
            return state
        except BroadlinkAuthError:
            _LOGGER.warning("[%s] session expired, re-authing", self.device_name)
            try:
                await self.device.auth()
                state = await self.device.get_state()
                try:
                    state.ambient_temp = await self.device.get_info()
                except Exception:
                    state.ambient_temp = None
                return state
            except Exception as exc:
                raise UpdateFailed(f"Re-auth failed for {self.device_name}: {exc}") from exc
        except BroadlinkTimeoutError as exc:
            raise UpdateFailed(f"Timeout polling {self.device_name}") from exc
        except Exception as exc:
            raise UpdateFailed(f"Unexpected error polling {self.device_name}: {exc}") from exc
