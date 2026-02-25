"""
SmartThings entity factories and implementations.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

import logging
from typing import Any

from ucapi import light, switch, sensor, climate, cover, media_player, button, select
from ucapi import StatusCodes
from ucapi.light import Light, Features as LightFeatures, Attributes as LightAttrs, States as LightStates
from ucapi.switch import Switch, Features as SwitchFeatures, Attributes as SwitchAttrs, States as SwitchStates
from ucapi.sensor import Sensor, Attributes as SensorAttrs, States as SensorStates, DeviceClasses as SensorDeviceClasses, Options as SensorOptions
from ucapi.climate import Climate, Features as ClimateFeatures, Attributes as ClimateAttrs, States as ClimateStates
from ucapi.cover import Cover, Features as CoverFeatures, Attributes as CoverAttrs, States as CoverStates
from ucapi.media_player import MediaPlayer, Features as MPFeatures, Attributes as MPAttrs, States as MPStates
from ucapi.button import Button, Attributes as ButtonAttrs, States as ButtonStates
from ucapi.select import Select, Attributes as SelectAttrs, States as SelectStates, Commands as SelectCommands

from uc_intg_smartthings.device import SmartThingsDevice
from uc_intg_smartthings.config import SmartThingsConfig, SmartThingsDeviceInfo

_LOG = logging.getLogger(__name__)


CAPABILITY_LIGHT = ["switchLevel", "colorControl", "colorTemperature"]
CAPABILITY_SWITCH = ["switch"]
CAPABILITY_SENSOR_TEMP = ["temperatureMeasurement"]
CAPABILITY_SENSOR_HUMIDITY = ["relativeHumidityMeasurement"]
CAPABILITY_SENSOR_MOTION = ["motionSensor"]
CAPABILITY_SENSOR_CONTACT = ["contactSensor"]
CAPABILITY_SENSOR_BATTERY = ["battery"]
CAPABILITY_CLIMATE = ["thermostat", "thermostatMode", "thermostatCoolingSetpoint", "thermostatHeatingSetpoint"]
CAPABILITY_COVER = ["windowShade", "doorControl", "garageDoorControl"]
CAPABILITY_MEDIA_PLAYER = ["audioVolume", "mediaPlayback", "mediaInputSource"]
CAPABILITY_BUTTON = ["button", "momentary"]


def has_capability(device: dict, capability: str) -> bool:
    """Check if a device has a specific capability."""
    components = device.get("components", [])
    for component in components:
        capabilities = component.get("capabilities", [])
        for cap in capabilities:
            cap_id = cap.get("id", "") if isinstance(cap, dict) else cap
            if cap_id == capability:
                return True
    return False


def has_any_capability(device: dict, capabilities: list[str]) -> bool:
    """Check if a device has any of the specified capabilities."""
    return any(has_capability(device, cap) for cap in capabilities)


def get_device_capabilities(device: dict) -> list[str]:
    """Get all capabilities for a device."""
    caps = []
    components = device.get("components", [])
    for component in components:
        capabilities = component.get("capabilities", [])
        for cap in capabilities:
            cap_id = cap.get("id", "") if isinstance(cap, dict) else cap
            if cap_id:
                caps.append(cap_id)
    return caps


def detect_entity_type(device: dict) -> str | None:
    """Detect the primary entity type for a device."""
    caps = get_device_capabilities(device)

    if has_any_capability(device, CAPABILITY_CLIMATE):
        return "climate"

    if has_any_capability(device, CAPABILITY_COVER):
        return "cover"

    if has_any_capability(device, CAPABILITY_MEDIA_PLAYER):
        return "media_player"

    if has_any_capability(device, CAPABILITY_LIGHT):
        if not has_any_capability(device, ["lock", "doorControl", "thermostat"]):
            return "light"

    if has_any_capability(device, CAPABILITY_BUTTON):
        return "button"

    if has_any_capability(device, CAPABILITY_SWITCH):
        if not has_any_capability(device, CAPABILITY_LIGHT + CAPABILITY_COVER + CAPABILITY_CLIMATE):
            return "switch"

    return None


def get_sensor_types(device: dict) -> list[str]:
    """Get sensor types for a device."""
    sensors = []
    if has_capability(device, "temperatureMeasurement"):
        sensors.append("temperature")
    if has_capability(device, "relativeHumidityMeasurement"):
        sensors.append("humidity")
    if has_capability(device, "motionSensor"):
        sensors.append("motion")
    if has_capability(device, "contactSensor"):
        sensors.append("contact")
    if has_capability(device, "battery"):
        sensors.append("battery")
    if has_capability(device, "powerMeter"):
        sensors.append("power")
    if has_capability(device, "energyMeter"):
        sensors.append("energy")
    if has_capability(device, "presenceSensor"):
        sensors.append("presence")
    if has_capability(device, "illuminanceMeasurement"):
        sensors.append("illuminance")
    return sensors


class SmartThingsEntityFactory:
    """Factory for creating SmartThings entities."""

    def __init__(self, st_device: SmartThingsDevice, config: SmartThingsConfig):
        """Initialize the entity factory."""
        self.st_device = st_device
        self.config = config
        self._entities: dict[str, Any] = {}

    def _device_info_to_dict(self, dev_info: SmartThingsDeviceInfo) -> dict:
        """Convert SmartThingsDeviceInfo to dict format for capability checks."""
        return {
            "deviceId": dev_info.device_id,
            "label": dev_info.name,
            "components": [{"capabilities": [{"id": c} for c in dev_info.capabilities]}],
        }

    def _detect_entity_type_from_caps(self, capabilities: list[str]) -> str | None:
        """Detect entity type from capability list."""
        caps_set = set(capabilities)

        if caps_set & set(CAPABILITY_CLIMATE):
            return "climate"
        if caps_set & set(CAPABILITY_COVER):
            return "cover"
        if caps_set & set(CAPABILITY_MEDIA_PLAYER):
            return "media_player"
        if caps_set & set(CAPABILITY_LIGHT):
            if not (caps_set & {"lock", "doorControl", "thermostat"}):
                return "light"
        if caps_set & set(CAPABILITY_BUTTON):
            return "button"
        if caps_set & set(CAPABILITY_SWITCH):
            if not (caps_set & set(CAPABILITY_LIGHT + CAPABILITY_COVER + CAPABILITY_CLIMATE)):
                return "switch"
        return None

    def _get_sensor_types_from_caps(self, capabilities: list[str]) -> list[str]:
        """Get sensor types from capability list."""
        sensors = []
        if "temperatureMeasurement" in capabilities:
            sensors.append("temperature")
        if "relativeHumidityMeasurement" in capabilities:
            sensors.append("humidity")
        if "motionSensor" in capabilities:
            sensors.append("motion")
        if "contactSensor" in capabilities:
            sensors.append("contact")
        if "battery" in capabilities:
            sensors.append("battery")
        if "powerMeter" in capabilities:
            sensors.append("power")
        if "energyMeter" in capabilities:
            sensors.append("energy")
        if "presenceSensor" in capabilities:
            sensors.append("presence")
        if "illuminanceMeasurement" in capabilities:
            sensors.append("illuminance")
        return sensors

    def _has_capability(self, capabilities: list[str], cap: str) -> bool:
        """Check if capability is in list."""
        return cap in capabilities

    def create_entities(
        self,
        include_lights: bool = True,
        include_switches: bool = True,
        include_sensors: bool = True,
        include_climate: bool = True,
        include_covers: bool = True,
        include_media_players: bool = True,
        include_buttons: bool = True,
    ) -> list[Any]:
        """Create all entities from config data (stored during setup)."""
        entities = []

        for dev_info in self.config.devices:
            device_id = dev_info.device_id
            device_name = dev_info.name
            room_name = dev_info.room
            device = self._device_info_to_dict(dev_info)
            entity_type = self._detect_entity_type_from_caps(dev_info.capabilities)

            _LOG.debug(
                "Device %s (%s) detected as: %s",
                device_name,
                device_id,
                entity_type or "sensor-only",
            )

            if entity_type == "light" and include_lights:
                entity = self._create_light_entity(device_id, device, device_name, room_name)
                if entity:
                    entities.append(entity)
                    self._entities[entity.id] = entity

            elif entity_type == "switch" and include_switches:
                entity = self._create_switch_entity(device_id, device, device_name, room_name)
                if entity:
                    entities.append(entity)
                    self._entities[entity.id] = entity

            elif entity_type == "climate" and include_climate:
                entity = self._create_climate_entity(device_id, device, device_name, room_name)
                if entity:
                    entities.append(entity)
                    self._entities[entity.id] = entity

            elif entity_type == "cover" and include_covers:
                entity = self._create_cover_entity(device_id, device, device_name, room_name)
                if entity:
                    entities.append(entity)
                    self._entities[entity.id] = entity

            elif entity_type == "media_player" and include_media_players:
                entity = self._create_media_player_entity(device_id, device, device_name, room_name)
                if entity:
                    entities.append(entity)
                    self._entities[entity.id] = entity

            elif entity_type == "button" and include_buttons:
                entity = self._create_button_entity(device_id, device, device_name, room_name)
                if entity:
                    entities.append(entity)
                    self._entities[entity.id] = entity

            if include_sensors:
                sensor_types = self._get_sensor_types_from_caps(dev_info.capabilities)
                sensor_entities = self._create_sensor_entities_from_types(
                    device_id, device_name, room_name, sensor_types
                )
                for sensor_entity in sensor_entities:
                    entities.append(sensor_entity)
                    self._entities[sensor_entity.id] = sensor_entity

        scene_select = self._create_scene_select()
        if scene_select:
            entities.append(scene_select)
            self._entities[scene_select.id] = scene_select

        mode_select = self._create_mode_select()
        if mode_select:
            entities.append(mode_select)
            self._entities[mode_select.id] = mode_select

        _LOG.info("Created %d entities", len(entities))
        return entities

    def _create_light_entity(
        self, device_id: str, device: dict, name: str, area: str | None
    ) -> Light | None:
        """Create a light entity."""
        features = [LightFeatures.ON_OFF, LightFeatures.TOGGLE]

        if has_capability(device, "switchLevel"):
            features.append(LightFeatures.DIM)

        if has_capability(device, "colorControl"):
            features.append(LightFeatures.COLOR)

        if has_capability(device, "colorTemperature"):
            features.append(LightFeatures.COLOR_TEMPERATURE)

        entity_id = f"light.st_{device_id}"

        async def cmd_handler(entity: Light, cmd_id: str, params: dict | None) -> StatusCodes:
            return await self._handle_light_command(device_id, cmd_id, params)

        return Light(
            entity_id,
            name,
            features,
            {
                LightAttrs.STATE: LightStates.UNKNOWN,
                LightAttrs.BRIGHTNESS: 0,
            },
            area=area,
            cmd_handler=cmd_handler,
        )

    def _create_switch_entity(
        self, device_id: str, device: dict, name: str, area: str | None
    ) -> Switch | None:
        """Create a switch entity."""
        features = [SwitchFeatures.ON_OFF, SwitchFeatures.TOGGLE]
        entity_id = f"switch.st_{device_id}"

        async def cmd_handler(entity: Switch, cmd_id: str, params: dict | None) -> StatusCodes:
            return await self._handle_switch_command(device_id, cmd_id, params)

        return Switch(
            entity_id,
            name,
            features,
            {SwitchAttrs.STATE: SwitchStates.UNKNOWN},
            area=area,
            cmd_handler=cmd_handler,
        )

    def _create_climate_entity(
        self, device_id: str, device: dict, name: str, area: str | None
    ) -> Climate | None:
        """Create a climate entity."""
        features = [ClimateFeatures.ON_OFF]

        if has_capability(device, "thermostatHeatingSetpoint"):
            features.append(ClimateFeatures.TARGET_TEMPERATURE)
            features.append(ClimateFeatures.HEAT)

        if has_capability(device, "thermostatCoolingSetpoint"):
            features.append(ClimateFeatures.TARGET_TEMPERATURE)
            features.append(ClimateFeatures.COOL)

        if has_capability(device, "thermostatMode"):
            features.append(ClimateFeatures.HVAC_MODES)

        if has_capability(device, "thermostatFanMode"):
            features.append(ClimateFeatures.FAN)

        entity_id = f"climate.st_{device_id}"

        async def cmd_handler(entity: Climate, cmd_id: str, params: dict | None) -> StatusCodes:
            return await self._handle_climate_command(device_id, cmd_id, params)

        return Climate(
            entity_id,
            name,
            features,
            {
                ClimateAttrs.STATE: ClimateStates.UNKNOWN,
                ClimateAttrs.CURRENT_TEMPERATURE: None,
                ClimateAttrs.TARGET_TEMPERATURE: None,
            },
            area=area,
            cmd_handler=cmd_handler,
        )

    def _create_cover_entity(
        self, device_id: str, device: dict, name: str, area: str | None
    ) -> Cover | None:
        """Create a cover entity."""
        features = [CoverFeatures.OPEN, CoverFeatures.CLOSE]

        if has_capability(device, "windowShadeLevel"):
            features.append(CoverFeatures.POSITION)

        if has_capability(device, "windowShade"):
            features.append(CoverFeatures.STOP)

        entity_id = f"cover.st_{device_id}"

        async def cmd_handler(entity: Cover, cmd_id: str, params: dict | None) -> StatusCodes:
            return await self._handle_cover_command(device_id, cmd_id, params)

        return Cover(
            entity_id,
            name,
            features,
            {
                CoverAttrs.STATE: CoverStates.UNKNOWN,
                CoverAttrs.POSITION: 0,
            },
            area=area,
            cmd_handler=cmd_handler,
        )

    def _create_media_player_entity(
        self, device_id: str, device: dict, name: str, area: str | None
    ) -> MediaPlayer | None:
        """Create a media player entity."""
        features = [MPFeatures.ON_OFF]

        if has_capability(device, "audioVolume"):
            features.extend([MPFeatures.VOLUME, MPFeatures.VOLUME_UP_DOWN, MPFeatures.MUTE])

        if has_capability(device, "mediaPlayback"):
            features.extend([MPFeatures.PLAY_PAUSE, MPFeatures.STOP])

        if has_capability(device, "mediaInputSource"):
            features.append(MPFeatures.SELECT_SOURCE)

        entity_id = f"media_player.st_{device_id}"

        async def cmd_handler(entity: MediaPlayer, cmd_id: str, params: dict | None) -> StatusCodes:
            return await self._handle_media_player_command(device_id, cmd_id, params)

        return MediaPlayer(
            entity_id,
            name,
            features,
            {
                MPAttrs.STATE: MPStates.UNKNOWN,
                MPAttrs.VOLUME: 0,
                MPAttrs.MUTED: False,
            },
            area=area,
            cmd_handler=cmd_handler,
        )

    def _create_button_entity(
        self, device_id: str, device: dict, name: str, area: str | None
    ) -> Button | None:
        """Create a button entity."""
        entity_id = f"button.st_{device_id}"

        async def cmd_handler(entity: Button, cmd_id: str, params: dict | None) -> StatusCodes:
            return await self._handle_button_command(device_id, cmd_id, params)

        return Button(
            entity_id,
            name,
            cmd_handler=cmd_handler,
            area=area,
        )

    def _create_sensor_entities_from_types(
        self, device_id: str, name: str, area: str | None, sensor_types: list[str]
    ) -> list[Sensor]:
        """Create sensor entities from sensor type list."""
        sensors = []

        for sensor_type in sensor_types:
            entity_id = f"sensor.st_{device_id}_{sensor_type}"
            sensor_name = f"{name} {sensor_type.title()}"

            if sensor_type == "temperature":
                sensor_entity = Sensor(
                    entity_id,
                    sensor_name,
                    features=[],
                    attributes={
                        SensorAttrs.STATE: SensorStates.UNKNOWN,
                        SensorAttrs.VALUE: None,
                    },
                    device_class=SensorDeviceClasses.TEMPERATURE,
                    options={SensorOptions.NATIVE_UNIT: "C"},
                    area=area,
                )
            elif sensor_type == "humidity":
                sensor_entity = Sensor(
                    entity_id,
                    sensor_name,
                    features=[],
                    attributes={
                        SensorAttrs.STATE: SensorStates.UNKNOWN,
                        SensorAttrs.VALUE: None,
                    },
                    device_class=SensorDeviceClasses.HUMIDITY,
                    area=area,
                )
            elif sensor_type == "battery":
                sensor_entity = Sensor(
                    entity_id,
                    sensor_name,
                    features=[],
                    attributes={
                        SensorAttrs.STATE: SensorStates.UNKNOWN,
                        SensorAttrs.VALUE: None,
                    },
                    device_class=SensorDeviceClasses.BATTERY,
                    area=area,
                )
            elif sensor_type == "power":
                sensor_entity = Sensor(
                    entity_id,
                    sensor_name,
                    features=[],
                    attributes={
                        SensorAttrs.STATE: SensorStates.UNKNOWN,
                        SensorAttrs.VALUE: None,
                    },
                    device_class=SensorDeviceClasses.POWER,
                    area=area,
                )
            elif sensor_type == "energy":
                sensor_entity = Sensor(
                    entity_id,
                    sensor_name,
                    features=[],
                    attributes={
                        SensorAttrs.STATE: SensorStates.UNKNOWN,
                        SensorAttrs.VALUE: None,
                    },
                    device_class=SensorDeviceClasses.ENERGY,
                    area=area,
                )
            elif sensor_type == "illuminance":
                sensor_entity = Sensor(
                    entity_id,
                    sensor_name,
                    features=[],
                    attributes={
                        SensorAttrs.STATE: SensorStates.UNKNOWN,
                        SensorAttrs.VALUE: None,
                    },
                    device_class=SensorDeviceClasses.CUSTOM,
                    options={SensorOptions.CUSTOM_UNIT: "lux"},
                    area=area,
                )
            elif sensor_type in ("motion", "contact", "presence"):
                sensor_entity = Sensor(
                    entity_id,
                    sensor_name,
                    features=[],
                    attributes={
                        SensorAttrs.STATE: SensorStates.UNKNOWN,
                        SensorAttrs.VALUE: None,
                    },
                    device_class=SensorDeviceClasses.CUSTOM,
                    options={SensorOptions.CUSTOM_UNIT: sensor_type},
                    area=area,
                )
            else:
                sensor_entity = Sensor(
                    entity_id,
                    sensor_name,
                    features=[],
                    attributes={
                        SensorAttrs.STATE: SensorStates.UNKNOWN,
                        SensorAttrs.VALUE: None,
                    },
                    device_class=SensorDeviceClasses.CUSTOM,
                    options={SensorOptions.CUSTOM_UNIT: sensor_type},
                    area=area,
                )

            sensors.append(sensor_entity)

        return sensors

    def _create_scene_select(self) -> Select | None:
        """Create a select entity for scenes."""
        if not self.config.scenes:
            return None

        scene_names = [s.get("sceneName", "Unknown") for s in self.config.scenes]
        if not scene_names:
            return None

        entity_id = f"select.st_{self.config.identifier}_scenes"

        async def cmd_handler(entity: Select, cmd_id: str, params: dict | None) -> StatusCodes:
            return await self._handle_scene_select_command(cmd_id, params)

        return Select(
            entity_id,
            f"{self.config.name} Scenes",
            {
                SelectAttrs.STATE: SelectStates.ON,
                SelectAttrs.OPTIONS: scene_names,
                SelectAttrs.CURRENT_OPTION: scene_names[0] if scene_names else None,
            },
            cmd_handler=cmd_handler,
        )

    def _create_mode_select(self) -> Select | None:
        """Create a select entity for location modes."""
        if not self.config.modes:
            return None

        mode_names = [m.get("name", "Unknown") for m in self.config.modes]
        if not mode_names:
            return None

        entity_id = f"select.st_{self.config.identifier}_modes"
        current = mode_names[0] if mode_names else None

        async def cmd_handler(entity: Select, cmd_id: str, params: dict | None) -> StatusCodes:
            return await self._handle_mode_select_command(cmd_id, params)

        return Select(
            entity_id,
            f"{self.config.name} Mode",
            {
                SelectAttrs.STATE: SelectStates.ON,
                SelectAttrs.OPTIONS: mode_names,
                SelectAttrs.CURRENT_OPTION: current,
            },
            cmd_handler=cmd_handler,
        )

    async def _handle_light_command(
        self, device_id: str, cmd_id: str, params: dict | None
    ) -> StatusCodes:
        """Handle light commands."""
        if cmd_id == light.Commands.ON:
            success = await self.st_device.execute_command(device_id, "switch", "on")
        elif cmd_id == light.Commands.OFF:
            success = await self.st_device.execute_command(device_id, "switch", "off")
        elif cmd_id == light.Commands.TOGGLE:
            current = self.st_device.get_device_capability_status(device_id, "switch", "switch")
            cmd = "off" if current == "on" else "on"
            success = await self.st_device.execute_command(device_id, "switch", cmd)
        elif cmd_id == light.Commands.BRIGHTNESS:
            level = params.get("brightness", 100) if params else 100
            success = await self.st_device.execute_command(
                device_id, "switchLevel", "setLevel", [level]
            )
        elif cmd_id == light.Commands.COLOR_TEMPERATURE:
            temp = params.get("color_temperature", 4000) if params else 4000
            success = await self.st_device.execute_command(
                device_id, "colorTemperature", "setColorTemperature", [temp]
            )
        elif cmd_id == light.Commands.COLOR:
            hue = params.get("hue", 0) if params else 0
            sat = params.get("saturation", 100) if params else 100
            success = await self.st_device.execute_command(
                device_id, "colorControl", "setHue", [hue]
            )
            if success:
                success = await self.st_device.execute_command(
                    device_id, "colorControl", "setSaturation", [sat]
                )
        else:
            _LOG.warning("Unknown light command: %s", cmd_id)
            return StatusCodes.NOT_IMPLEMENTED

        return StatusCodes.OK if success else StatusCodes.SERVER_ERROR

    async def _handle_switch_command(
        self, device_id: str, cmd_id: str, params: dict | None
    ) -> StatusCodes:
        """Handle switch commands."""
        if cmd_id == switch.Commands.ON:
            success = await self.st_device.execute_command(device_id, "switch", "on")
        elif cmd_id == switch.Commands.OFF:
            success = await self.st_device.execute_command(device_id, "switch", "off")
        elif cmd_id == switch.Commands.TOGGLE:
            current = self.st_device.get_device_capability_status(device_id, "switch", "switch")
            cmd = "off" if current == "on" else "on"
            success = await self.st_device.execute_command(device_id, "switch", cmd)
        else:
            _LOG.warning("Unknown switch command: %s", cmd_id)
            return StatusCodes.NOT_IMPLEMENTED

        return StatusCodes.OK if success else StatusCodes.SERVER_ERROR

    async def _handle_climate_command(
        self, device_id: str, cmd_id: str, params: dict | None
    ) -> StatusCodes:
        """Handle climate commands."""
        if cmd_id == climate.Commands.ON:
            success = await self.st_device.execute_command(
                device_id, "thermostatMode", "auto"
            )
        elif cmd_id == climate.Commands.OFF:
            success = await self.st_device.execute_command(
                device_id, "thermostatMode", "off"
            )
        elif cmd_id == climate.Commands.HVAC_MODE:
            mode = params.get("hvac_mode", "auto") if params else "auto"
            success = await self.st_device.execute_command(
                device_id, "thermostatMode", "setThermostatMode", [mode]
            )
        elif cmd_id == climate.Commands.TARGET_TEMPERATURE:
            temp = params.get("temperature", 21) if params else 21
            success = await self.st_device.execute_command(
                device_id, "thermostatHeatingSetpoint", "setHeatingSetpoint", [temp]
            )
        else:
            _LOG.warning("Unknown climate command: %s", cmd_id)
            return StatusCodes.NOT_IMPLEMENTED

        return StatusCodes.OK if success else StatusCodes.SERVER_ERROR

    async def _handle_cover_command(
        self, device_id: str, cmd_id: str, params: dict | None
    ) -> StatusCodes:
        """Handle cover commands."""
        if cmd_id == cover.Commands.OPEN:
            success = await self.st_device.execute_command(device_id, "windowShade", "open")
        elif cmd_id == cover.Commands.CLOSE:
            success = await self.st_device.execute_command(device_id, "windowShade", "close")
        elif cmd_id == cover.Commands.STOP:
            success = await self.st_device.execute_command(device_id, "windowShade", "pause")
        elif cmd_id == cover.Commands.POSITION:
            position = params.get("position", 50) if params else 50
            success = await self.st_device.execute_command(
                device_id, "windowShadeLevel", "setShadeLevel", [position]
            )
        else:
            _LOG.warning("Unknown cover command: %s", cmd_id)
            return StatusCodes.NOT_IMPLEMENTED

        return StatusCodes.OK if success else StatusCodes.SERVER_ERROR

    async def _handle_media_player_command(
        self, device_id: str, cmd_id: str, params: dict | None
    ) -> StatusCodes:
        """Handle media player commands."""
        if cmd_id == media_player.Commands.ON:
            success = await self.st_device.execute_command(device_id, "switch", "on")
        elif cmd_id == media_player.Commands.OFF:
            success = await self.st_device.execute_command(device_id, "switch", "off")
        elif cmd_id == media_player.Commands.TOGGLE:
            current = self.st_device.get_device_capability_status(device_id, "switch", "switch")
            cmd = "off" if current == "on" else "on"
            success = await self.st_device.execute_command(device_id, "switch", cmd)
        elif cmd_id == media_player.Commands.VOLUME:
            volume = params.get("volume", 50) if params else 50
            success = await self.st_device.execute_command(
                device_id, "audioVolume", "setVolume", [volume]
            )
        elif cmd_id == media_player.Commands.VOLUME_UP:
            success = await self.st_device.execute_command(
                device_id, "audioVolume", "volumeUp"
            )
        elif cmd_id == media_player.Commands.VOLUME_DOWN:
            success = await self.st_device.execute_command(
                device_id, "audioVolume", "volumeDown"
            )
        elif cmd_id == media_player.Commands.MUTE_TOGGLE:
            current = self.st_device.get_device_capability_status(device_id, "audioMute", "mute")
            cmd = "unmute" if current == "muted" else "mute"
            success = await self.st_device.execute_command(device_id, "audioMute", cmd)
        elif cmd_id == media_player.Commands.PLAY_PAUSE:
            current = self.st_device.get_device_capability_status(
                device_id, "mediaPlayback", "playbackStatus"
            )
            cmd = "pause" if current == "playing" else "play"
            success = await self.st_device.execute_command(device_id, "mediaPlayback", cmd)
        elif cmd_id == media_player.Commands.STOP:
            success = await self.st_device.execute_command(device_id, "mediaPlayback", "stop")
        elif cmd_id == media_player.Commands.SELECT_SOURCE:
            source = params.get("source", "") if params else ""
            success = await self.st_device.execute_command(
                device_id, "mediaInputSource", "setInputSource", [source]
            )
        else:
            _LOG.warning("Unknown media player command: %s", cmd_id)
            return StatusCodes.NOT_IMPLEMENTED

        return StatusCodes.OK if success else StatusCodes.SERVER_ERROR

    async def _handle_button_command(
        self, device_id: str, cmd_id: str, params: dict | None
    ) -> StatusCodes:
        """Handle button commands."""
        if cmd_id == button.Commands.PUSH:
            success = await self.st_device.execute_command(device_id, "momentary", "push")
            if not success:
                success = await self.st_device.execute_command(device_id, "button", "push")
        else:
            _LOG.warning("Unknown button command: %s", cmd_id)
            return StatusCodes.NOT_IMPLEMENTED

        return StatusCodes.OK if success else StatusCodes.SERVER_ERROR

    async def _handle_scene_select_command(
        self, cmd_id: str, params: dict | None
    ) -> StatusCodes:
        """Handle scene select commands (ucapi 0.5.2 full command support)."""
        scene_names = [s.get("sceneName", "Unknown") for s in self.config.scenes]
        if not scene_names:
            return StatusCodes.NOT_FOUND

        entity_id = f"select.st_{self.config.identifier}_scenes"
        entity = self._entities.get(entity_id)
        current = entity.attributes.get(SelectAttrs.CURRENT_OPTION) if entity else scene_names[0]
        current_idx = scene_names.index(current) if current in scene_names else 0

        if cmd_id == SelectCommands.SELECT_OPTION:
            selected = params.get("option") if params else None
        elif cmd_id == SelectCommands.SELECT_FIRST:
            selected = scene_names[0]
        elif cmd_id == SelectCommands.SELECT_LAST:
            selected = scene_names[-1]
        elif cmd_id == SelectCommands.SELECT_NEXT:
            selected = scene_names[(current_idx + 1) % len(scene_names)]
        elif cmd_id == SelectCommands.SELECT_PREVIOUS:
            selected = scene_names[(current_idx - 1) % len(scene_names)]
        else:
            return StatusCodes.NOT_IMPLEMENTED

        if not selected:
            return StatusCodes.BAD_REQUEST

        for scene in self.config.scenes:
            if scene.get("sceneName") == selected:
                scene_id = scene.get("sceneId")
                if scene_id:
                    success = await self.st_device.execute_scene(scene_id)
                    if success and entity:
                        entity.attributes[SelectAttrs.CURRENT_OPTION] = selected
                    return StatusCodes.OK if success else StatusCodes.SERVER_ERROR

        return StatusCodes.NOT_FOUND

    async def _handle_mode_select_command(
        self, cmd_id: str, params: dict | None
    ) -> StatusCodes:
        """Handle mode select commands (ucapi 0.5.2 full command support)."""
        mode_names = [m.get("name", "Unknown") for m in self.config.modes]
        if not mode_names:
            return StatusCodes.NOT_FOUND

        entity_id = f"select.st_{self.config.identifier}_modes"
        entity = self._entities.get(entity_id)
        current = entity.attributes.get(SelectAttrs.CURRENT_OPTION) if entity else mode_names[0]
        current_idx = mode_names.index(current) if current in mode_names else 0

        if cmd_id == SelectCommands.SELECT_OPTION:
            selected = params.get("option") if params else None
        elif cmd_id == SelectCommands.SELECT_FIRST:
            selected = mode_names[0]
        elif cmd_id == SelectCommands.SELECT_LAST:
            selected = mode_names[-1]
        elif cmd_id == SelectCommands.SELECT_NEXT:
            selected = mode_names[(current_idx + 1) % len(mode_names)]
        elif cmd_id == SelectCommands.SELECT_PREVIOUS:
            selected = mode_names[(current_idx - 1) % len(mode_names)]
        else:
            return StatusCodes.NOT_IMPLEMENTED

        if not selected:
            return StatusCodes.BAD_REQUEST

        for mode in self.config.modes:
            if mode.get("name") == selected:
                mode_id = mode.get("id")
                if mode_id:
                    success = await self.st_device.set_mode(mode_id)
                    if success and entity:
                        entity.attributes[SelectAttrs.CURRENT_OPTION] = selected
                    return StatusCodes.OK if success else StatusCodes.SERVER_ERROR

        return StatusCodes.NOT_FOUND

    def update_entity_states(self, device_id: str, status: dict) -> dict[str, dict]:
        """Update entity states from device status and return changed attributes."""
        updates = {}
        components = status.get("components", {})
        main = components.get("main", {})

        for entity_id, entity in self._entities.items():
            if device_id not in entity_id:
                continue

            old_attrs = dict(entity.attributes)
            new_attrs = {}

            if isinstance(entity, Light):
                switch_val = main.get("switch", {}).get("switch", {}).get("value")
                if switch_val:
                    new_attrs[LightAttrs.STATE] = LightStates.ON if switch_val == "on" else LightStates.OFF

                level = main.get("switchLevel", {}).get("level", {}).get("value")
                if level is not None:
                    new_attrs[LightAttrs.BRIGHTNESS] = level

            elif isinstance(entity, Switch):
                switch_val = main.get("switch", {}).get("switch", {}).get("value")
                if switch_val:
                    new_attrs[SwitchAttrs.STATE] = SwitchStates.ON if switch_val == "on" else SwitchStates.OFF

            elif isinstance(entity, Climate):
                mode = main.get("thermostatMode", {}).get("thermostatMode", {}).get("value")
                if mode:
                    if mode == "off":
                        new_attrs[ClimateAttrs.STATE] = ClimateStates.OFF
                    elif mode == "heat":
                        new_attrs[ClimateAttrs.STATE] = ClimateStates.HEAT
                    elif mode == "cool":
                        new_attrs[ClimateAttrs.STATE] = ClimateStates.COOL
                    else:
                        new_attrs[ClimateAttrs.STATE] = ClimateStates.AUTO

                temp = main.get("temperatureMeasurement", {}).get("temperature", {}).get("value")
                if temp is not None:
                    new_attrs[ClimateAttrs.CURRENT_TEMPERATURE] = temp

            elif isinstance(entity, Cover):
                shade = main.get("windowShade", {}).get("windowShade", {}).get("value")
                if shade:
                    if shade == "open":
                        new_attrs[CoverAttrs.STATE] = CoverStates.OPEN
                    elif shade == "closed":
                        new_attrs[CoverAttrs.STATE] = CoverStates.CLOSED
                    else:
                        new_attrs[CoverAttrs.STATE] = CoverStates.UNKNOWN

                position = main.get("windowShadeLevel", {}).get("shadeLevel", {}).get("value")
                if position is not None:
                    new_attrs[CoverAttrs.POSITION] = position

            elif isinstance(entity, MediaPlayer):
                switch_val = main.get("switch", {}).get("switch", {}).get("value")
                if switch_val:
                    new_attrs[MPAttrs.STATE] = MPStates.ON if switch_val == "on" else MPStates.OFF

                volume = main.get("audioVolume", {}).get("volume", {}).get("value")
                if volume is not None:
                    new_attrs[MPAttrs.VOLUME] = volume

                mute = main.get("audioMute", {}).get("mute", {}).get("value")
                if mute is not None:
                    new_attrs[MPAttrs.MUTED] = mute == "muted"

            elif isinstance(entity, Sensor):
                if "temperature" in entity_id:
                    temp = main.get("temperatureMeasurement", {}).get("temperature", {}).get("value")
                    if temp is not None:
                        new_attrs[SensorAttrs.STATE] = SensorStates.ON
                        new_attrs[SensorAttrs.VALUE] = temp
                elif "humidity" in entity_id:
                    humidity = main.get("relativeHumidityMeasurement", {}).get("humidity", {}).get("value")
                    if humidity is not None:
                        new_attrs[SensorAttrs.STATE] = SensorStates.ON
                        new_attrs[SensorAttrs.VALUE] = humidity
                elif "battery" in entity_id:
                    battery = main.get("battery", {}).get("battery", {}).get("value")
                    if battery is not None:
                        new_attrs[SensorAttrs.STATE] = SensorStates.ON
                        new_attrs[SensorAttrs.VALUE] = battery
                elif "motion" in entity_id:
                    motion = main.get("motionSensor", {}).get("motion", {}).get("value")
                    if motion is not None:
                        new_attrs[SensorAttrs.STATE] = SensorStates.ON
                        new_attrs[SensorAttrs.VALUE] = motion
                elif "contact" in entity_id:
                    contact = main.get("contactSensor", {}).get("contact", {}).get("value")
                    if contact is not None:
                        new_attrs[SensorAttrs.STATE] = SensorStates.ON
                        new_attrs[SensorAttrs.VALUE] = contact

            if new_attrs and new_attrs != {k: old_attrs.get(k) for k in new_attrs}:
                entity.attributes.update(new_attrs)
                updates[entity_id] = new_attrs

        return updates

    def get_entity(self, entity_id: str) -> Any:
        """Get an entity by ID."""
        return self._entities.get(entity_id)

    def get_all_entities(self) -> list[Any]:
        """Get all entities."""
        return list(self._entities.values())
