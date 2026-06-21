"""Select for AUX LAN AC vane position (fixation_v)."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, AuxLanCoordinator
from .broadlink import AcState

_LOGGER = logging.getLogger(__name__)

VANE_OPTIONS = [
    "Closed (1)",
    "Mid (3)",
    "Open (5)",
    "Swing (6)",
    "Auto (7)",
]

WIRE_TO_OPTION = {1: "Closed (1)", 3: "Mid (3)", 5: "Open (5)", 6: "Swing (6)", 7: "Auto (7)"}
OPTION_TO_WIRE = {v: k for k, v in WIRE_TO_OPTION.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AuxLanCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AuxLanVaneSelect(coordinator, entry)])


class AuxLanVaneSelect(CoordinatorEntity, SelectEntity):
    _attr_has_entity_name = True
    _attr_name = "Vane position"
    _attr_icon = "mdi:air-conditioner"
    _attr_options = VANE_OPTIONS

    def __init__(
        self,
        coordinator: AuxLanCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"aux_lan_{entry.data['mac']}_fixation_v"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data["mac"])},
        )

    @property
    def current_option(self) -> str | None:
        s: AcState | None = self.coordinator.data
        if s is None:
            return None
        return WIRE_TO_OPTION.get(s.fixation_v)

    async def async_select_option(self, option: str) -> None:
        wire_val = OPTION_TO_WIRE.get(option)
        if wire_val is None:
            return
        s: AcState | None = self.coordinator.data
        if s is None:
            return
        await self.coordinator.device.set_state(
            power=s.power,
            temp=s.target_temp,
            mode=s.mode,
            fan_speed=s.fan_speed,
            turbo=s.turbo,
            mute=s.mute,
            sleep=s.sleep,
            health=s.health,
            display=s.display,
            clean=s.clean,
            mildew=s.mildew,
            fixation_v=wire_val,
            fixation_h=s.fixation_h,
            caller="select_fixation_v",
        )
        await self.coordinator.async_request_refresh()
