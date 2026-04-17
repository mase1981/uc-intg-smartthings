"""
SmartThings Integration driver for Unfolded Circle Remote using ucapi-framework.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

import logging
from typing import Any

from ucapi.light import Attributes as LightAttrs, States as LightStates
from ucapi.switch import Attributes as SwitchAttrs, States as SwitchStates
from ucapi.climate import Attributes as ClimateAttrs, States as ClimateStates
from ucapi.cover import Attributes as CoverAttrs, States as CoverStates
from ucapi.media_player import Attributes as MPAttrs, States as MPStates
from ucapi.sensor import Attributes as SensorAttrs, States as SensorStates
from ucapi_framework import BaseIntegrationDriver
from ucapi_framework.device import DeviceEvents

from uc_intg_smartthings.config import SmartThingsConfig
from uc_intg_smartthings.device import SmartThingsDevice
from uc_intg_smartthings.light import create_lights
from uc_intg_smartthings.switch_entity import create_switches
from uc_intg_smartthings.climate import create_climate_entities
from uc_intg_smartthings.cover import create_covers
from uc_intg_smartthings.media_player import create_media_players
from uc_intg_smartthings.button_entity import create_buttons
from uc_intg_smartthings.sensor import create_sensors
from uc_intg_smartthings.select_entity import create_selects

_LOG = logging.getLogger(__name__)

_SENSOR_CAP_MAP = {
    "temperature": ("temperatureMeasurement", "temperature"),
    "humidity": ("relativeHumidityMeasurement", "humidity"),
    "battery": ("battery", "battery"),
    "motion": ("motionSensor", "motion"),
    "contact": ("contactSensor", "contact"),
    "power": ("powerMeter", "power"),
    "energy": ("energyMeter", "energy"),
    "presence": ("presenceSensor", "presence"),
    "illuminance": ("illuminanceMeasurement", "illuminance"),
}


class SmartThingsDriver(BaseIntegrationDriver[SmartThingsDevice, SmartThingsConfig]):
    """SmartThings integration driver using ucapi-framework."""

    def __init__(self):
        super().__init__(
            device_class=SmartThingsDevice,
            entity_classes=[
                lambda cfg, dev: create_media_players(cfg, dev),
                lambda cfg, dev: create_lights(cfg, dev),
                lambda cfg, dev: create_switches(cfg, dev),
                lambda cfg, dev: create_sensors(cfg, dev),
                lambda cfg, dev: create_climate_entities(cfg, dev),
                lambda cfg, dev: create_covers(cfg, dev),
                lambda cfg, dev: create_buttons(cfg, dev),
                lambda cfg, dev: create_selects(cfg, dev),
            ],
            driver_id="smartthings",
        )
        self._device_to_config: dict[str, str] = {}

    def device_from_entity_id(self, entity_id: str) -> str | None:
        """Map entity ID to config identifier."""
        if not entity_id:
            return None

        parts = entity_id.split(".")
        if len(parts) < 2:
            return None

        entity_suffix = parts[1]
        if entity_suffix.startswith("st_"):
            device_part = entity_suffix[3:]
            st_device_id = device_part.split("_")[0]
            config_id = self._device_to_config.get(st_device_id)
            return config_id

        return None

    def on_device_added(self, config: SmartThingsConfig) -> None:
        """Handle device added — populate mapping, then call super."""
        for dev_info in config.devices:
            self._device_to_config[dev_info.device_id] = config.identifier
        self._device_to_config[config.identifier] = config.identifier

        super().on_device_added(config)

    async def on_device_update(
        self,
        entity_id: str | None = None,
        update: dict[str, Any] | None = None,
        clear_media_when_off: bool = True,
    ) -> None:
        """Handle device status update — parse ST status into per-entity updates.

        The framework passes (entity_id=st_device_id, update=status_dict) from
        the device's DeviceEvents.UPDATE emission.
        """
        device_id = entity_id
        status = update
        if device_id is None or status is None:
            return

        if device_id == "__token_save__":
            self._handle_token_save()
            return

        main = status.get("components", {}).get("main", {})

        self._update_light(device_id, main)
        self._update_switch(device_id, main)
        self._update_climate(device_id, main)
        self._update_cover(device_id, main)
        self._update_media_player(device_id, main)
        self._update_sensors(device_id, main)

    def _update_light(self, device_id: str, main: dict) -> None:
        entity_id = f"light.st_{device_id}"
        if not self.api.configured_entities.contains(entity_id):
            return

        attrs = {}
        switch_val = main.get("switch", {}).get("switch", {}).get("value")
        if switch_val:
            attrs[LightAttrs.STATE] = LightStates.ON if switch_val == "on" else LightStates.OFF
        level = main.get("switchLevel", {}).get("level", {}).get("value")
        if level is not None:
            attrs[LightAttrs.BRIGHTNESS] = level

        if attrs:
            self.api.configured_entities.update_attributes(entity_id, attrs)

    def _update_switch(self, device_id: str, main: dict) -> None:
        entity_id = f"switch.st_{device_id}"
        if not self.api.configured_entities.contains(entity_id):
            return

        switch_val = main.get("switch", {}).get("switch", {}).get("value")
        if switch_val:
            attrs = {SwitchAttrs.STATE: SwitchStates.ON if switch_val == "on" else SwitchStates.OFF}
            self.api.configured_entities.update_attributes(entity_id, attrs)

    def _update_climate(self, device_id: str, main: dict) -> None:
        entity_id = f"climate.st_{device_id}"
        if not self.api.configured_entities.contains(entity_id):
            return

        attrs = {}
        mode = main.get("thermostatMode", {}).get("thermostatMode", {}).get("value")
        if mode:
            if mode == "off":
                attrs[ClimateAttrs.STATE] = ClimateStates.OFF
            elif mode == "heat":
                attrs[ClimateAttrs.STATE] = ClimateStates.HEAT
            elif mode == "cool":
                attrs[ClimateAttrs.STATE] = ClimateStates.COOL
            else:
                attrs[ClimateAttrs.STATE] = ClimateStates.AUTO

        temp = main.get("temperatureMeasurement", {}).get("temperature", {}).get("value")
        if temp is not None:
            attrs[ClimateAttrs.CURRENT_TEMPERATURE] = temp

        if attrs:
            self.api.configured_entities.update_attributes(entity_id, attrs)

    def _update_cover(self, device_id: str, main: dict) -> None:
        entity_id = f"cover.st_{device_id}"
        if not self.api.configured_entities.contains(entity_id):
            return

        attrs = {}
        shade = main.get("windowShade", {}).get("windowShade", {}).get("value")
        if shade:
            if shade == "open":
                attrs[CoverAttrs.STATE] = CoverStates.OPEN
            elif shade == "closed":
                attrs[CoverAttrs.STATE] = CoverStates.CLOSED
            else:
                attrs[CoverAttrs.STATE] = CoverStates.UNKNOWN

        position = main.get("windowShadeLevel", {}).get("shadeLevel", {}).get("value")
        if position is not None:
            attrs[CoverAttrs.POSITION] = position

        if attrs:
            self.api.configured_entities.update_attributes(entity_id, attrs)

    def _update_media_player(self, device_id: str, main: dict) -> None:
        entity_id = f"media_player.st_{device_id}"
        if not self.api.configured_entities.contains(entity_id):
            return

        attrs = {}
        switch_val = main.get("switch", {}).get("switch", {}).get("value")
        if switch_val:
            attrs[MPAttrs.STATE] = MPStates.ON if switch_val == "on" else MPStates.OFF

        volume = main.get("audioVolume", {}).get("volume", {}).get("value")
        if volume is not None:
            attrs[MPAttrs.VOLUME] = volume

        mute = main.get("audioMute", {}).get("mute", {}).get("value")
        if mute is None:
            mute = main.get("audioVolume", {}).get("mute", {}).get("value")
        if mute is not None:
            attrs[MPAttrs.MUTED] = mute == "muted"

        source = main.get("mediaInputSource", {}).get("inputSource", {}).get("value")
        if source is None:
            source = main.get("samsungvd.mediaInputSource", {}).get("inputSource", {}).get("value")
        if source is None:
            source = main.get("samsungvd.audioInputSource", {}).get("inputSource", {}).get("value")
        if source is not None:
            attrs[MPAttrs.SOURCE] = str(source)

        if attrs:
            self.api.configured_entities.update_attributes(entity_id, attrs)

    def _update_sensors(self, device_id: str, main: dict) -> None:
        for sensor_type, (cap_name, attr_name) in _SENSOR_CAP_MAP.items():
            entity_id = f"sensor.st_{device_id}_{sensor_type}"
            if not self.api.configured_entities.contains(entity_id):
                continue

            value = main.get(cap_name, {}).get(attr_name, {}).get("value")
            if value is not None:
                self.api.configured_entities.update_attributes(
                    entity_id, {SensorAttrs.STATE: SensorStates.ON, SensorAttrs.VALUE: value}
                )

    def _handle_token_save(self) -> None:
        """Save updated tokens back to config."""
        if not self.config_manager:
            return

        for config in self.config_manager.all():
            if hasattr(config, "token_needs_save"):
                continue
            try:
                self.config_manager.update(config)
                _LOG.debug("Saved refreshed tokens for %s", config.identifier)
            except Exception as e:
                _LOG.error("Failed to save tokens: %s", e)

    def on_device_removed(
        self, device_or_config: SmartThingsDevice | SmartThingsConfig | None
    ) -> None:
        """Handle device removed — clean up mappings."""
        if device_or_config is None:
            self._device_to_config.clear()
            return

        config_id = device_or_config.identifier
        keys_to_remove = [k for k, v in self._device_to_config.items() if v == config_id]
        for key in keys_to_remove:
            self._device_to_config.pop(key, None)
        _LOG.info("Cleaned up mappings for %s", config_id)
