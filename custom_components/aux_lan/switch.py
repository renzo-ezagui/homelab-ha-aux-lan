"""Switches for AUX LAN AC attributes (display, health, clean, mildew)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, AuxLanCoordinator
from .broadlink import AcState

_LOGGER = logging.getLogger(__name__)

SWITCH_ATTRS = {
    "display": {"name": "Panel light", "icon": "mdi:led-on"},
    "health": {"name": "Health filter", "icon": "mdi:air-filter"},
    "clean": {"name": "Self-clean", "icon": "mdi:spray-bottle"},
    "mildew": {"name": "Anti-mildew", "icon": "mdi:mold"},
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AuxLanCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        AuxLanSwitch(coordinator, entry, attr, cfg)
        for attr, cfg in SWITCH_ATTRS.items()
    )


class AuxLanSwitch(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AuxLanCoordinator,
        entry: ConfigEntry,
        attr: str,
        cfg: dict,
    ) -> None:
        super().__init__(coordinator)
        self._attr = attr
        self._attr_name = cfg["name"]
        self._attr_unique_id = f"aux_lan_{entry.data['mac']}_{attr}"
        self._attr_icon = cfg["icon"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data["mac"])},
        )

    @property
    def is_on(self) -> bool | None:
        s: AcState | None = self.coordinator.data
        if s is None:
            return None
        return getattr(s, self._attr)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, value: bool) -> None:
        s: AcState | None = self.coordinator.data
        if s is None:
            return
        _LOGGER.info("[%s] switch %s → %s", self.coordinator.device_name, self._attr, value)
        kwargs = {
            "power": s.power,
            "temp": s.target_temp,
            "mode": s.mode,
            "fan_speed": s.fan_speed,
            "turbo": s.turbo,
            "mute": s.mute,
            "sleep": s.sleep,
            "health": s.health,
            "display": s.display,
            "clean": s.clean,
            "mildew": s.mildew,
            "fixation_v": s.fixation_v,
            "fixation_h": s.fixation_h,
            "caller": f"switch_{self._attr}",
        }
        kwargs[self._attr] = value
        await self.coordinator.device.set_state(**kwargs)
        await self.coordinator.async_request_refresh()
