"""AUX LAN climate entity."""
from __future__ import annotations

import logging

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.components.climate.const import (
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    PRESET_BOOST,
    PRESET_NONE,
    PRESET_SLEEP,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, AuxLanCoordinator
from .broadlink import AcFanSpeed, AcMode, AcState

_LOGGER = logging.getLogger(__name__)

FAN_TURBO = "turbo"

HVAC_TO_MODE: dict[HVACMode, AcMode] = {
    HVACMode.AUTO: AcMode.AUTO,
    HVACMode.COOL: AcMode.COOLING,
    HVACMode.HEAT: AcMode.HEATING,
    HVACMode.DRY: AcMode.DRY,
    HVACMode.FAN_ONLY: AcMode.FAN,
}

MODE_TO_HVAC: dict[AcMode, HVACMode] = {v: k for k, v in HVAC_TO_MODE.items()}

FAN_TO_SPEED: dict[str, AcFanSpeed] = {
    FAN_HIGH: AcFanSpeed.HIGH,
    FAN_MEDIUM: AcFanSpeed.MEDIUM,
    FAN_LOW: AcFanSpeed.LOW,
    FAN_TURBO: AcFanSpeed.TURBO,
    FAN_AUTO: AcFanSpeed.AUTO,
}

SPEED_TO_FAN: dict[AcFanSpeed, str] = {v: k for k, v in FAN_TO_SPEED.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AuxLanCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AuxLanClimate(coordinator, entry)])


class AuxLanClimate(CoordinatorEntity, ClimateEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_min_temp = 16.0
    _attr_max_temp = 32.0
    _attr_hvac_modes = [
        HVACMode.OFF,
        HVACMode.AUTO,
        HVACMode.COOL,
        HVACMode.HEAT,
        HVACMode.DRY,
        HVACMode.FAN_ONLY,
    ]
    _attr_fan_modes = [FAN_AUTO, FAN_HIGH, FAN_MEDIUM, FAN_LOW, FAN_TURBO]
    _attr_preset_modes = [PRESET_NONE, PRESET_BOOST, "mute", PRESET_SLEEP]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: AuxLanCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"aux_lan_{entry.data['mac']}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data["mac"])},
            name=entry.data["name"],
            manufacturer="AUX",
            model="BroadLink WiFi AC",
        )

    @property
    def _state(self) -> AcState | None:
        return self.coordinator.data

    @property
    def available(self) -> bool:
        s = self._state
        return s is not None and s.available

    @property
    def hvac_mode(self) -> HVACMode:
        s = self._state
        if s is None or not s.power:
            return HVACMode.OFF
        return MODE_TO_HVAC.get(s.mode, HVACMode.COOL)

    @property
    def target_temperature(self) -> float | None:
        s = self._state
        return s.target_temp if s else None

    @property
    def current_temperature(self) -> float | None:
        s = self._state
        return s.ambient_temp if s else None

    @property
    def fan_mode(self) -> str | None:
        s = self._state
        if s is None:
            return None
        return SPEED_TO_FAN.get(s.fan_speed, FAN_AUTO)

    @property
    def preset_mode(self) -> str:
        s = self._state
        if s is None:
            return PRESET_NONE
        if s.turbo:
            return PRESET_BOOST
        if s.mute:
            return "mute"
        if s.sleep:
            return PRESET_SLEEP
        return PRESET_NONE

    @property
    def extra_state_attributes(self) -> dict:
        s = self._state
        if s is None:
            return {}
        return {
            "health": s.health,
            "display": s.display,
            "clean": s.clean,
            "mildew": s.mildew,
            "fixation_v": s.fixation_v,
            "fixation_h": s.fixation_h,
        }

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        s = self._state
        if s is None:
            return
        turbo = s.turbo
        mute = s.mute
        sleep = s.sleep
        if preset_mode == PRESET_NONE:
            turbo = False
            mute = False
            sleep = False
        elif preset_mode == PRESET_BOOST:
            turbo = True
            mute = False
        elif preset_mode == "mute":
            mute = True
            turbo = False
        elif preset_mode == PRESET_SLEEP:
            sleep = True
        await self.coordinator.device.set_state(
            power=s.power,
            temp=s.target_temp,
            mode=s.mode,
            fan_speed=s.fan_speed,
            turbo=turbo,
            mute=mute,
            sleep=sleep,
            health=s.health,
            display=s.display,
            clean=s.clean,
            mildew=s.mildew,
            fixation_v=s.fixation_v,
            fixation_h=s.fixation_h,
        )
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        s = self._state
        if s is None:
            return
        _LOGGER.debug("[%s] set_hvac_mode %s", self._entry.data["name"], hvac_mode)
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.device.set_state(
                power=False,
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
                fixation_v=s.fixation_v,
                fixation_h=s.fixation_h,
            )
        else:
            ac_mode = HVAC_TO_MODE.get(hvac_mode, AcMode.COOLING)
            await self.coordinator.device.set_state(
                power=True,
                temp=s.target_temp,
                mode=ac_mode,
                fan_speed=s.fan_speed,
                turbo=s.turbo,
                mute=s.mute,
                sleep=s.sleep,
                health=s.health,
                display=s.display,
                clean=s.clean,
                mildew=s.mildew,
                fixation_v=s.fixation_v,
                fixation_h=s.fixation_h,
            )
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs) -> None:
        s = self._state
        if s is None:
            return
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        _LOGGER.debug("[%s] set_temperature %s", self._entry.data["name"], temp)
        await self.coordinator.device.set_state(
            power=s.power,
            temp=float(temp),
            mode=s.mode,
            fan_speed=s.fan_speed,
            turbo=s.turbo,
            mute=s.mute,
            sleep=s.sleep,
            health=s.health,
            display=s.display,
            clean=s.clean,
            mildew=s.mildew,
            fixation_v=s.fixation_v,
            fixation_h=s.fixation_h,
        )
        await self.coordinator.async_request_refresh()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        s = self._state
        if s is None:
            return
        speed = FAN_TO_SPEED.get(fan_mode, AcFanSpeed.AUTO)
        _LOGGER.debug("[%s] set_fan_mode %s → %s", self._entry.data["name"], fan_mode, speed)
        await self.coordinator.device.set_state(
            power=s.power,
            temp=s.target_temp,
            mode=s.mode,
            fan_speed=speed,
            turbo=speed == AcFanSpeed.TURBO,
            mute=s.mute,
            sleep=s.sleep,
            health=s.health,
            display=s.display,
            clean=s.clean,
            mildew=s.mildew,
            fixation_v=s.fixation_v,
            fixation_h=s.fixation_h,
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(
            MODE_TO_HVAC.get(self._state.mode if self._state else AcMode.COOLING, HVACMode.COOL)
        )

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)
