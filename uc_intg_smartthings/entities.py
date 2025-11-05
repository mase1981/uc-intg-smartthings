"""
:copyright: (c) 2025 by Meir Miyara
:license: MPL-2.0, see LICENSE for more details.
"""

import logging
import asyncio
import time
from typing import Any, Dict, Optional, Union

from ucapi import IntegrationAPI
from ucapi.light import Light, Features as LightFeatures, Attributes as LightAttr, States as LightStates
from ucapi.switch import Switch, Features as SwitchFeatures, Attributes as SwitchAttr, States as SwitchStates
from ucapi.sensor import Sensor, Attributes as SensorAttr, States as SensorStates, DeviceClasses as SensorClasses
from ucapi.cover import Cover, Features as CoverFeatures, Attributes as CoverAttr, States as CoverStates, DeviceClasses as CoverClasses
from ucapi.button import Button, Attributes as ButtonAttr, States as ButtonStates
from ucapi.media_player import MediaPlayer, Features as MediaFeatures, Attributes as MediaAttr, States as MediaStates, DeviceClasses as MediaClasses
from ucapi.climate import Climate, Features as ClimateFeatures,Attributes as ClimateAttr, States as ClimateStates
from ucapi.api_definitions import StatusCodes

from uc_intg_smartthings.client import SmartThingsDevice, SmartThingsClient

_LOG = logging.getLogger(__name__)

class EntityType:
    LIGHT = "light"
    SWITCH = "switch"
    SENSOR = "sensor"
    COVER = "cover"
    BUTTON = "button"
    MEDIA_PLAYER = "media_player"
    CLIMATE = "climate"

class SmartThingsEntityFactory:
    
    def __init__(self, client: SmartThingsClient, api: IntegrationAPI):
        self.client = client
        self.api = api
        self.command_in_progress = {}
        self.command_queue = {}
        self.last_command_time = {}
        self.command_callback = None
        self.source_cycling_active = {}

    def determine_entity_type(self, device: SmartThingsDevice) -> Optional[str]:
        capabilities = device.capabilities
        device_name = (device.label or device.name or "").lower()
        device_type = getattr(device, 'type', '').lower()
        
        _LOG.info(f"Analyzing device: {device.label}")
        _LOG.info(f"  - Capabilities: {list(capabilities)}")
        _LOG.info(f"  - Device Type: {device_type}")
        _LOG.info(f"  - Device Name: {device_name}")
        
        if self._is_samsung_tv(device_name, device_type, capabilities):
            _LOG.info(f"Samsung TV detected: {device.label} -> MEDIA_PLAYER")
            return EntityType.MEDIA_PLAYER
            
        if self._is_samsung_soundbar(device_name, device_type, capabilities):
            _LOG.info(f"Samsung Soundbar detected: {device.label} -> MEDIA_PLAYER")
            return EntityType.MEDIA_PLAYER
        
        if "button" in capabilities or "momentary" in capabilities:
            _LOG.info(f"Button {device.label} -> BUTTON (has button capability)")
            return EntityType.BUTTON
        
        climate_caps = {"thermostat", "thermostatCoolingSetpoint", "thermostatHeatingSetpoint", "airConditioner"}
        if climate_caps.intersection(capabilities):
            _LOG.info(f"Climate {device.label} -> CLIMATE (has {climate_caps.intersection(capabilities)})")
            return EntityType.CLIMATE
        
        media_caps = {"mediaPlayback", "audioVolume", "tvChannel", "mediaTrackControl", "speechSynthesis"}
        media_keywords = ["tv", "television", "soundbar", "speaker", "audio", "receiver", "stereo", "music"]
        
        if (media_caps.intersection(capabilities) or 
            any(keyword in device_name for keyword in media_keywords) or
            any(keyword in device_type for keyword in media_keywords)):
            _LOG.info(f"Media Player {device.label} -> MEDIA_PLAYER (caps: {media_caps.intersection(capabilities)}, name match: {any(keyword in device_name for keyword in media_keywords)})")
            return EntityType.MEDIA_PLAYER
        
        cover_caps = {"doorControl", "windowShade", "garageDoorControl"}
        if cover_caps.intersection(capabilities):
            _LOG.info(f"Cover {device.label} -> COVER (has {cover_caps.intersection(capabilities)})")
            return EntityType.COVER
        
        if "lock" in capabilities and "switch" not in capabilities:
            _LOG.info(f"Lock {device.label} -> SWITCH (lock as switch for control)")
            return EntityType.SWITCH
        
        light_caps = {"switchLevel", "colorControl", "colorTemperature"}
        light_indicators = light_caps.intersection(capabilities)
        light_keywords = ["light", "lamp", "bulb", "led", "fixture", "sconce", "chandelier", "dimmer"]
        
        if light_indicators or ("switch" in capabilities and any(word in device_name for word in light_keywords)):
            excluded_caps = {
                "lock", "doorControl", "windowShade", "garageDoorControl",
                "thermostat", "mediaPlayback", "audioVolume", "speechSynthesis",
                "dryerOperatingState", "washerOperatingState", "ovenOperatingState"
            }
            if not excluded_caps.intersection(capabilities):
                if light_indicators:
                    _LOG.info(f"Light {device.label} -> LIGHT (has {light_indicators})")
                else:
                    _LOG.info(f"Light {device.label} -> LIGHT (name contains light keyword)")
                return EntityType.LIGHT
        
        sensor_caps = {
            "contactSensor", "motionSensor", "presenceSensor", 
            "temperatureMeasurement", "relativeHumidityMeasurement",
            "illuminanceMeasurement", "battery", "powerMeter", "energyMeter",
            "carbonMonoxideDetector", "smokeDetector", "waterSensor",
            "accelerationSensor", "threeAxis", "ultravioletIndex",
            "soundSensor", "dustSensor", "airQualitySensor"
        }
        
        sensor_matches = sensor_caps.intersection(capabilities)
        if sensor_matches:
            _LOG.info(f"Sensor {device.label} -> SENSOR (has {sensor_matches})")
            return EntityType.SENSOR
        
        if "switch" in capabilities:
            excluded_caps = {
                "switchLevel", "colorControl", "colorTemperature",
                "doorControl", "windowShade", "garageDoorControl",
                "thermostat", "thermostatCoolingSetpoint", "thermostatHeatingSetpoint",
                "mediaPlayback", "audioVolume", "speechSynthesis", "button"
            }
            
            if not excluded_caps.intersection(capabilities):
                _LOG.info(f"Switch {device.label} -> SWITCH (basic switch capability)")
                return EntityType.SWITCH
        
        _LOG.warning(f"Unknown device type for {device.label}")
        _LOG.warning(f"  - Capabilities: {capabilities}")
        _LOG.warning(f"  - Device Type: {device_type}")
        _LOG.warning(f"  - Device Name: {device_name}")
        return None

    def _is_samsung_tv(self, device_name: str, device_type: str, capabilities: set) -> bool:
        samsung_tv_indicators = [
            "samsung" in device_name and "tv" in device_name,
            "samsung" in device_name and any(model in device_name for model in ["au5000", "q70", "qled", "neo"]),
            "tv" in device_type,
            "television" in device_type,
            {"switch", "audioVolume"}.issubset(capabilities),
            {"switch", "speechSynthesis"}.issubset(capabilities),
        ]
        
        return any(samsung_tv_indicators)

    def _is_samsung_soundbar(self, device_name: str, device_type: str, capabilities: set) -> bool:
        samsung_soundbar_indicators = [
            "samsung" in device_name and "soundbar" in device_name,
            "samsung" in device_name and "q70t" in device_name,
            "samsung" in device_name and "q90r" in device_name,
            "samsung" in device_name and "q950t" in device_name,
            "soundbar" in device_name,
            "soundbar" in device_type,
            "network audio" in device_type,
            "speaker" in device_type and "samsung" in device_name,
            {"audioVolume", "switch"}.issubset(capabilities),
            "audioVolume" in capabilities and "mediaPlayback" not in capabilities,
        ]
        
        return any(samsung_soundbar_indicators)

    def create_entity(self, device_data: Dict[str, Any], config: Dict[str, Any], area: Optional[str] = None) -> Optional[Union[Light, Switch, Sensor, Cover, Button, MediaPlayer, Climate]]:
        try:
            device = SmartThingsDevice(**device_data)
            entity_type = self.determine_entity_type(device)

            if not entity_type:
                _LOG.warning(f"Could not determine entity type for {device.label}")
                return None

            if not self._should_include(entity_type, config):
                _LOG.info(f"Excluding {device.label} - {entity_type} not enabled in config")
                return None

            entity_id = f"st_{device.id}"
            label = device.label or device.name or "Unknown Device"
            
            self.command_in_progress[device.id] = False
            self.command_queue[device.id] = []
            self.last_command_time[device.id] = 0

            entity = None
            
            if entity_type == EntityType.LIGHT:
                entity = self._create_light(entity_id, label, device, area)
            elif entity_type == EntityType.SWITCH:
                entity = self._create_switch(entity_id, label, device, area)
            elif entity_type == EntityType.SENSOR:
                entity = self._create_sensor(entity_id, label, device, area)
            elif entity_type == EntityType.COVER:
                entity = self._create_cover(entity_id, label, device, area)
            elif entity_type == EntityType.BUTTON:
                entity = self._create_button(entity_id, label, device, area)
            elif entity_type == EntityType.MEDIA_PLAYER:
                entity = self._create_media_player(entity_id, label, device, device_data, area)
            elif entity_type == EntityType.CLIMATE:
                entity = self._create_climate(entity_id, label, device, area)
            
            if entity:
                setattr(entity, 'entity_type', entity_type)
                setattr(entity, 'smartthings_capabilities', device.capabilities)
                setattr(entity, 'device_id', device.id)
                
                initial_attributes = self._get_default_attributes(entity_type, device.capabilities)
                entity.attributes.update(initial_attributes)
                
                _LOG.info(f"Successfully created {entity_type} entity: {entity_id} ({label})")
                return entity
            else:
                _LOG.error(f"Failed to create entity for {label}")
                
        except Exception as e:
            device_name = device_data.get("label", device_data.get("name", "Unknown"))
            _LOG.error(f"Error creating entity for {device_name}: {e}", exc_info=True)
        
        return None

    def _should_include(self, entity_type: Optional[str], config: Dict[str, Any]) -> bool:
        if not entity_type: 
            return False
        
        config_mappings = {
            EntityType.LIGHT: "include_lights",
            EntityType.SWITCH: "include_switches", 
            EntityType.SENSOR: "include_sensors",
            EntityType.COVER: "include_covers",
            EntityType.BUTTON: "include_buttons",
            EntityType.MEDIA_PLAYER: "include_media_players",
            EntityType.CLIMATE: "include_climate"
        }
        
        config_key = config_mappings.get(entity_type)
        if not config_key:
            return False
            
        default_value = entity_type in [EntityType.LIGHT, EntityType.SWITCH, EntityType.COVER, EntityType.BUTTON, EntityType.MEDIA_PLAYER, EntityType.CLIMATE]
        return config.get(config_key, default_value)

    def _get_default_attributes(self, entity_type: str, capabilities: set) -> Dict[str, Any]:
        if entity_type == EntityType.LIGHT:
            attrs = {LightAttr.STATE: LightStates.UNKNOWN}
            if "switchLevel" in capabilities:
                attrs[LightAttr.BRIGHTNESS] = 0
            if "colorControl" in capabilities:
                attrs[LightAttr.HUE] = 0
                attrs[LightAttr.SATURATION] = 0
            if "colorTemperature" in capabilities:
                attrs[LightAttr.COLOR_TEMPERATURE] = 2700
            return attrs
        elif entity_type == EntityType.SWITCH:
            return {SwitchAttr.STATE: SwitchStates.UNKNOWN}
        elif entity_type == EntityType.SENSOR:
            return {SensorAttr.STATE: SensorStates.ON, SensorAttr.VALUE: "unknown"}
        elif entity_type == EntityType.COVER:
            return {CoverAttr.STATE: CoverStates.UNKNOWN}
        elif entity_type == EntityType.BUTTON:
            return {ButtonAttr.STATE: ButtonStates.AVAILABLE}
        elif entity_type == EntityType.MEDIA_PLAYER:
            return {MediaAttr.STATE: MediaStates.UNKNOWN}
        elif entity_type == EntityType.CLIMATE:
            return {ClimateAttr.STATE: ClimateStates.UNKNOWN}
        return {}

    def _create_light(self, entity_id: str, name: str, device: SmartThingsDevice, area: Optional[str]) -> Light:
        features = [LightFeatures.ON_OFF, LightFeatures.TOGGLE]
        
        if "switchLevel" in device.capabilities:
            features.append(LightFeatures.DIM)
        if "colorControl" in device.capabilities:
            features.append(LightFeatures.COLOR)
        if "colorTemperature" in device.capabilities:
            features.append(LightFeatures.COLOR_TEMPERATURE)
        
        return Light(
            entity_id, name, features, {}, area=area, cmd_handler=self._handle_command
        )

    def _create_switch(self, entity_id: str, name: str, device: SmartThingsDevice, area: Optional[str]) -> Switch:
        return Switch(
            entity_id, name, [SwitchFeatures.ON_OFF, SwitchFeatures.TOGGLE], 
            {}, area=area, cmd_handler=self._handle_command
        )

    def _create_sensor(self, entity_id: str, name: str, device: SmartThingsDevice, area: Optional[str]) -> Sensor:
        device_class = SensorClasses.CUSTOM
        
        if "lock" in device.capabilities:
            device_class = SensorClasses.CUSTOM
        elif "temperatureMeasurement" in device.capabilities:
            device_class = SensorClasses.TEMPERATURE
        elif "battery" in device.capabilities:
            device_class = SensorClasses.BATTERY
        elif "powerMeter" in device.capabilities:
            device_class = SensorClasses.POWER
        elif "energyMeter" in device.capabilities:
            device_class = SensorClasses.ENERGY
        elif "relativeHumidityMeasurement" in device.capabilities:
            device_class = SensorClasses.HUMIDITY
        elif "voltageMeasurement" in device.capabilities:
            device_class = SensorClasses.VOLTAGE
        
        return Sensor(entity_id, name, [], {}, device_class=device_class, area=area)

    def _create_cover(self, entity_id: str, name: str, device: SmartThingsDevice, area: Optional[str]) -> Cover:
        features = [CoverFeatures.OPEN, CoverFeatures.CLOSE, CoverFeatures.STOP]
        
        if "windowShadeLevel" in device.capabilities:
            features.append(CoverFeatures.POSITION)
        
        device_class = CoverClasses.SHADE
        device_name = (device.label or device.name or "").lower()
        
        if "doorControl" in device.capabilities or "garageDoorControl" in device.capabilities:
            if any(word in device_name for word in ["garage", "gate"]):
                device_class = CoverClasses.GARAGE
            else:
                device_class = CoverClasses.DOOR
        elif "windowShade" in device.capabilities:
            if "curtain" in device_name:
                device_class = CoverClasses.CURTAIN
            elif "blind" in device_name:
                device_class = CoverClasses.BLIND
        
        return Cover(entity_id, name, features, {}, device_class=device_class, area=area, cmd_handler=self._handle_command)

    def _create_button(self, entity_id: str, name: str, device: SmartThingsDevice, area: Optional[str]) -> Button:
        return Button(entity_id, name, area=area, cmd_handler=self._handle_command)

    async def _get_supported_input_sources(self, device_data: Dict[str, Any]) -> list:
        """Fetch actual supported input sources from device status"""
        device_id = device_data.get("deviceId")
        if not device_id:
            return []
        
        try:
            async with self.client:
                device_status = await self.client.get_device_status(device_id)
                
            if not device_status:
                return []
            
            main_component = device_status.get("components", {}).get("main", {})
            
            # Try samsungvd.audioInputSource first (for soundbars)
            if "samsungvd.audioInputSource" in main_component:
                audio_input_source = main_component["samsungvd.audioInputSource"]
                supported = audio_input_source.get("supportedInputSources", {}).get("value", [])
                if supported:
                    _LOG.info(f"✅ Found {len(supported)} supported inputs from samsungvd.audioInputSource: {supported}")
                    return supported
            
            # Try mediaInputSource (for TVs)
            if "mediaInputSource" in main_component:
                media_input_source = main_component["mediaInputSource"]
                supported = media_input_source.get("supportedInputSources", {}).get("value", [])
                if supported:
                    _LOG.info(f"✅ Found {len(supported)} supported inputs from mediaInputSource: {supported}")
                    return supported
            
            # Try samsungvd.mediaInputSource
            if "samsungvd.mediaInputSource" in main_component:
                samsung_input_source = main_component["samsungvd.mediaInputSource"]
                supported = samsung_input_source.get("supportedInputSources", {}).get("value", [])
                if supported:
                    _LOG.info(f"✅ Found {len(supported)} supported inputs from samsungvd.mediaInputSource: {supported}")
                    return supported
            
            _LOG.warning(f"No supportedInputSources found in device status")
            return []
            
        except Exception as e:
            _LOG.error(f"Failed to fetch supported input sources: {e}")
            return []

    def _create_media_player(self, entity_id: str, name: str, device: SmartThingsDevice, device_data: Dict[str, Any], area: Optional[str]) -> MediaPlayer:
        features = []
        
        if "switch" in device.capabilities:
            features.extend([MediaFeatures.ON_OFF, MediaFeatures.TOGGLE])
        if "audioVolume" in device.capabilities:
            features.extend([MediaFeatures.VOLUME, MediaFeatures.VOLUME_UP_DOWN, MediaFeatures.MUTE_TOGGLE])
        if "mediaPlayback" in device.capabilities:
            features.extend([MediaFeatures.PLAY_PAUSE, MediaFeatures.STOP])
        if "mediaInputSource" in device.capabilities or "samsungvd.mediaInputSource" in device.capabilities or "samsungvd.audioInputSource" in device.capabilities:
            features.append(MediaFeatures.SELECT_SOURCE)
        
        device_class = MediaClasses.SPEAKER
        device_name = (device.label or device.name or "").lower()
        device_type = getattr(device, 'type', '').lower()
        
        if any(word in device_name for word in ["tv", "television"]) or "tv" in device_type:
            device_class = MediaClasses.TV
        elif any(word in device_name for word in ["soundbar", "q70t", "q90r", "q950t"]) or "soundbar" in device_type or "network audio" in device_type:
            device_class = MediaClasses.SPEAKER
        elif any(word in device_name for word in ["receiver", "amplifier"]):
            device_class = MediaClasses.RECEIVER

        initial_attributes = {MediaAttr.STATE: MediaStates.UNKNOWN}
        
        # FIX: Fetch actual supported inputs dynamically instead of hardcoding
        if ("mediaInputSource" in device.capabilities or "samsungvd.mediaInputSource" in device.capabilities or "samsungvd.audioInputSource" in device.capabilities):
            # Create a task to fetch supported inputs asynchronously
            # For now, use a reasonable default that will be updated on first status poll
            initial_attributes[MediaAttr.SOURCE_LIST] = [
                "HDMI1", "HDMI2", "digital", "bluetooth", "wifi"
            ]
            _LOG.info(f"Will fetch actual supported inputs for {name} during first status update")
        
        return MediaPlayer(entity_id, name, features, initial_attributes, device_class=device_class, area=area, cmd_handler=self._handle_command)

    def _create_climate(self, entity_id: str, name: str, device: SmartThingsDevice, area: Optional[str]) -> Climate:
        features = []
        
        if "thermostat" in device.capabilities:
            features.extend([ClimateFeatures.HEAT, ClimateFeatures.COOL, ClimateFeatures.TARGET_TEMPERATURE])
        if "temperatureMeasurement" in device.capabilities:
            features.append(ClimateFeatures.CURRENT_TEMPERATURE)
        if "fan" in device.capabilities:
            features.append(ClimateFeatures.FAN)
        
        return Climate(entity_id, name, features, {}, area=area, cmd_handler=self._handle_command)

    def update_entity_attributes(self, entity: Any, device_status: Dict[str, Any]):
        main_component = device_status.get("components", {}).get("main", {})
        if not main_component: 
            return

        entity_type = getattr(entity, 'entity_type', None)
        capabilities = getattr(entity, 'smartthings_capabilities', set())
        
        if not entity_type:
            return
        
        old_attributes = dict(entity.attributes)
        
        try:
            if entity_type == EntityType.LIGHT:
                self._update_light_attributes(entity, main_component)
            elif entity_type == EntityType.SWITCH:
                if "lock" in capabilities:
                    self._update_lock_as_switch_attributes(entity, main_component)
                else:
                    self._update_switch_attributes(entity, main_component)
            elif entity_type == EntityType.SENSOR:
                self._update_sensor_attributes(entity, main_component)
            elif entity_type == EntityType.COVER:
                self._update_cover_attributes(entity, main_component)
            elif entity_type == EntityType.BUTTON:
                self._update_button_attributes(entity, main_component)
            elif entity_type == EntityType.MEDIA_PLAYER:
                self._update_media_player_attributes(entity, main_component)
            elif entity_type == EntityType.CLIMATE:
                self._update_climate_attributes(entity, main_component)
            
            if old_attributes != entity.attributes:
                _LOG.info(f"Real state update: {entity.name} -> {entity.attributes}")
                
        except Exception as e:
            _LOG.error(f"Error updating attributes for {entity.id}: {e}")
            entity.attributes.update(old_attributes)

    def _update_light_attributes(self, entity: Light, main_component: Dict[str, Any]):
        if "switch" in main_component:
            switch_value = main_component["switch"].get("switch", {}).get("value")
            if switch_value:
                new_state = LightStates.ON if switch_value == "on" else LightStates.OFF
                entity.attributes[LightAttr.STATE] = new_state
        
        if "switchLevel" in main_component:
            level_value = main_component["switchLevel"].get("level", {}).get("value")
            if level_value is not None:
                entity.attributes[LightAttr.BRIGHTNESS] = int(level_value)

    def _update_switch_attributes(self, entity: Switch, main_component: Dict[str, Any]):
        if "switch" in main_component:
            switch_value = main_component["switch"].get("switch", {}).get("value")
            if switch_value:
                new_state = SwitchStates.ON if switch_value == "on" else SwitchStates.OFF
                entity.attributes[SwitchAttr.STATE] = new_state

    def _update_lock_as_switch_attributes(self, entity: Switch, main_component: Dict[str, Any]):
        if "lock" in main_component:
            lock_value = main_component["lock"].get("lock", {}).get("value")
            if lock_value:
                new_state = SwitchStates.ON if lock_value == "locked" else SwitchStates.OFF
                entity.attributes[SwitchAttr.STATE] = new_state

    def _update_sensor_attributes(self, entity: Sensor, main_component: Dict[str, Any]):
        entity.attributes[SensorAttr.STATE] = SensorStates.ON
        
        if "lock" in main_component:
            lock_value = main_component["lock"].get("lock", {}).get("value")
            if lock_value:
                entity.attributes[SensorAttr.VALUE] = str(lock_value).title()
        elif "contactSensor" in main_component:
            contact_value = main_component["contactSensor"].get("contact", {}).get("value")
            if contact_value:
                entity.attributes[SensorAttr.VALUE] = str(contact_value).title()
        elif "temperatureMeasurement" in main_component:
            temp_value = main_component["temperatureMeasurement"].get("temperature", {}).get("value")
            if temp_value is not None:
                entity.attributes[SensorAttr.VALUE] = round(float(temp_value), 1)
                entity.attributes[SensorAttr.UNIT] = "°C"
        elif "battery" in main_component:
            battery_value = main_component["battery"].get("battery", {}).get("value")
            if battery_value is not None:
                entity.attributes[SensorAttr.VALUE] = int(battery_value)
                entity.attributes[SensorAttr.UNIT] = "%"

    def _update_cover_attributes(self, entity: Cover, main_component: Dict[str, Any]):
        if "doorControl" in main_component:
            door_value = main_component["doorControl"].get("door", {}).get("value")
            if door_value:
                state_map = {
                    "open": CoverStates.OPEN,
                    "closed": CoverStates.CLOSED,
                    "opening": CoverStates.OPENING,
                    "closing": CoverStates.CLOSING
                }
                entity.attributes[CoverAttr.STATE] = state_map.get(door_value, CoverStates.UNKNOWN)

    def _update_button_attributes(self, entity: Button, main_component: Dict[str, Any]):
        entity.attributes[ButtonAttr.STATE] = ButtonStates.AVAILABLE

    def _update_media_player_attributes(self, entity: MediaPlayer, main_component: Dict[str, Any]):
        # Update power state
        if "switch" in main_component:
            switch_value = main_component["switch"].get("switch", {}).get("value")
            if switch_value:
                entity.attributes[MediaAttr.STATE] = MediaStates.ON if switch_value == "on" else MediaStates.OFF
        
        # Update volume
        if "audioVolume" in main_component:
            volume_value = main_component["audioVolume"].get("volume", {}).get("value")
            if volume_value is not None:
                entity.attributes[MediaAttr.VOLUME] = int(volume_value)
            
            mute_value = main_component["audioVolume"].get("mute", {}).get("value")
            if mute_value is not None:
                entity.attributes[MediaAttr.MUTED] = mute_value == "muted"
        
        if "audioMute" in main_component:
            mute_value = main_component["audioMute"].get("mute", {}).get("value")
            if mute_value is not None:
                entity.attributes[MediaAttr.MUTED] = mute_value == "muted"
        
        # FIX: Update current source AND supported source list dynamically
        if "samsungvd.audioInputSource" in main_component:
            audio_input = main_component["samsungvd.audioInputSource"]
            
            # Current source
            current_source = audio_input.get("inputSource", {}).get("value")
            if current_source is not None:
                entity.attributes[MediaAttr.SOURCE] = str(current_source)
                _LOG.debug(f"Updated current source to: {current_source}")
            
            # Supported sources - CRITICAL FIX
            supported_sources = audio_input.get("supportedInputSources", {}).get("value", [])
            if supported_sources:
                entity.attributes[MediaAttr.SOURCE_LIST] = supported_sources
                _LOG.info(f"✅ Updated SOURCE_LIST from device: {supported_sources}")
        
        elif "mediaInputSource" in main_component:
            media_input = main_component["mediaInputSource"]
            
            source_value = media_input.get("inputSource", {}).get("value")
            if source_value is not None:
                entity.attributes[MediaAttr.SOURCE] = str(source_value)
            
            supported_sources = media_input.get("supportedInputSources", {}).get("value", [])
            if supported_sources:
                entity.attributes[MediaAttr.SOURCE_LIST] = supported_sources
                _LOG.info(f"✅ Updated SOURCE_LIST from device: {supported_sources}")
        
        elif "samsungvd.mediaInputSource" in main_component:
            samsung_input = main_component["samsungvd.mediaInputSource"]
            
            source_value = samsung_input.get("inputSource", {}).get("value")
            if source_value is not None:
                entity.attributes[MediaAttr.SOURCE] = str(source_value)
            
            supported_sources = samsung_input.get("supportedInputSources", {}).get("value", [])
            if supported_sources:
                entity.attributes[MediaAttr.SOURCE_LIST] = supported_sources
                _LOG.info(f"✅ Updated SOURCE_LIST from device: {supported_sources}")

    def _update_climate_attributes(self, entity: Climate, main_component: Dict[str, Any]):
        if "thermostat" in main_component:
            mode_value = main_component["thermostat"].get("thermostatMode", {}).get("value")
            if mode_value:
                state_map = {
                    "heat": ClimateStates.HEAT,
                    "cool": ClimateStates.COOL,
                    "auto": ClimateStates.AUTO,
                    "off": ClimateStates.OFF
                }
                entity.attributes[ClimateAttr.STATE] = state_map.get(mode_value, ClimateStates.UNKNOWN)

    async def _handle_command(self, entity, cmd_id: str, params: Dict[str, Any] = None) -> StatusCodes:
        if params is None:
            params = {}
            
        device_id = getattr(entity, 'device_id', entity.id[3:])
        entity_type = getattr(entity, 'entity_type', None)
        capabilities = getattr(entity, 'smartthings_capabilities', set())
        
        _LOG.info(f"Command received: {entity.name} -> {cmd_id} {params}")
        
        if not self.client:
            _LOG.error(f"No client available for command: {entity.name}")
            return StatusCodes.SERVICE_UNAVAILABLE
        
        if self.command_in_progress.get(device_id, False):
            _LOG.warning(f"Command already in progress for {entity.name}, ignoring new command")
            return StatusCodes.CONFLICT
        
        now = time.time()
        last_cmd_time = self.last_command_time.get(device_id, 0)
        if now - last_cmd_time < 0.5:
            _LOG.warning(f"Commands too frequent for {entity.name}, ignoring")
            return StatusCodes.CONFLICT
        
        self.last_command_time[device_id] = now
        
        if cmd_id == 'select_source' and entity_type == EntityType.MEDIA_PLAYER:
            current_state = entity.attributes.get(MediaAttr.STATE)
            if current_state != MediaStates.ON:
                _LOG.warning(f"Cannot select input source on {entity.name}: device is {current_state}. Device must be ON first.")
                return StatusCodes.BAD_REQUEST
        
        try:
            self.command_in_progress[device_id] = True
            
            if self.command_callback:
                self.command_callback(entity.id)
            
            capability, command, args = self._map_command(entity_type, cmd_id, params, entity, capabilities)
            
            # FIX: Enhanced cycling logic using ACTUAL device source list
            if cmd_id == 'select_source' and capability == 'samsungvd.audioInputSource' and command == 'setNextInputSource':
                self.source_cycling_active[device_id] = True
                
                target_input = params.get('source')
                supported_inputs = entity.attributes.get(MediaAttr.SOURCE_LIST, [])
                
                _LOG.info(f"🔄 Samsung soundbar source cycling: {entity.name} to '{target_input}'")
                _LOG.info(f"📋 Supported inputs: {supported_inputs}")
                
                if not supported_inputs:
                    _LOG.error(f"❌ No SOURCE_LIST available for {entity.name}")
                    self.source_cycling_active[device_id] = False
                    return StatusCodes.BAD_REQUEST
                
                if target_input not in supported_inputs:
                    _LOG.error(f"❌ Target '{target_input}' not in supported list: {supported_inputs}")
                    self.source_cycling_active[device_id] = False
                    return StatusCodes.BAD_REQUEST
                
                max_attempts = len(supported_inputs) + 2  # Full cycle + buffer
                attempt = 0
                cycle_delay = 3.5  # Slightly longer delay for reliability
                
                async with self.client:
                    await asyncio.sleep(1.5)
                    
                    while attempt < max_attempts:
                        attempt += 1
                        
                        try:
                            device_status = await self.client.get_device_status(device_id)
                            if device_status:
                                main_component = device_status.get("components", {}).get("main", {})
                                audio_input = main_component.get("samsungvd.audioInputSource", {})
                                current_input = audio_input.get("inputSource", {}).get("value")
                                
                                _LOG.info(f"🔍 Attempt {attempt}/{max_attempts}: Current='{current_input}', Target='{target_input}'")
                                
                                if current_input == target_input:
                                    _LOG.info(f"✅ Reached target '{target_input}'!")
                                    entity.attributes[MediaAttr.SOURCE] = target_input
                                    self.api.configured_entities.update_attributes(entity.id, entity.attributes)
                                    self.source_cycling_active[device_id] = False
                                    return StatusCodes.OK
                            else:
                                _LOG.warning(f"⚠️ No status data on attempt {attempt}")
                        except Exception as e:
                            _LOG.warning(f"⚠️ Status check failed on attempt {attempt}: {e}")
                        
                        _LOG.info(f"🔄 Cycling attempt {attempt}/{max_attempts}")
                        
                        success = await self.client.execute_command(
                            device_id,
                            'samsungvd.audioInputSource',
                            'setNextInputSource',
                            []
                        )
                        
                        if not success:
                            _LOG.error(f"❌ Cycle command failed on attempt {attempt}")
                            self.source_cycling_active[device_id] = False
                            return StatusCodes.SERVER_ERROR
                        
                        await asyncio.sleep(cycle_delay)
                    
                    _LOG.error(f"❌ Failed to reach '{target_input}' after {max_attempts} attempts")
                    
                    try:
                        await asyncio.sleep(1.0)
                        device_status = await self.client.get_device_status(device_id)
                        if device_status:
                            main_component = device_status.get("components", {}).get("main", {})
                            audio_input = main_component.get("samsungvd.audioInputSource", {})
                            final_input = audio_input.get("inputSource", {}).get("value")
                            if final_input:
                                entity.attributes[MediaAttr.SOURCE] = final_input
                                self.api.configured_entities.update_attributes(entity.id, entity.attributes)
                                _LOG.warning(f"⚠️ Stopped at '{final_input}' instead of '{target_input}'")
                    except Exception as e:
                        _LOG.error(f"Could not update final state: {e}")
                    
                    self.source_cycling_active[device_id] = False
                    return StatusCodes.SERVER_ERROR
            
            if not capability or not command:
                _LOG.warning(f"Unhandled command '{cmd_id}' for entity type '{entity_type}'")
                return StatusCodes.NOT_IMPLEMENTED
            
            async with self.client:
                command_success = await self.client.execute_command(device_id, capability, command, args)
            
            if not command_success:
                _LOG.error(f"Command failed for {entity.name}: {cmd_id}")
                return StatusCodes.SERVER_ERROR
            
            await self._verify_command_result(entity, device_id, cmd_id)
            
            _LOG.info(f"Command completed successfully: {entity.name} -> {cmd_id}")
            return StatusCodes.OK
                
        except Exception as e:
            _LOG.error(f"Command failed for {entity.name}: {e}")
            return StatusCodes.SERVER_ERROR
        finally:
            self.command_in_progress[device_id] = False
            if device_id in self.source_cycling_active:
                self.source_cycling_active[device_id] = False

    async def _verify_command_result(self, entity, device_id: str, cmd_id: str):
        try:
            if hasattr(self.client, '_last_rate_limit') and time.time() - self.client._last_rate_limit < 30:
                _LOG.info(f"Skipping verification due to recent rate limit, polling will catch up: {entity.name}")
                return
                
            await asyncio.sleep(0.5)
            
            try:
                async with self.client:
                    device_status = await self.client.get_device_status(device_id)
                    
                if device_status:
                    old_attributes = dict(entity.attributes)
                    self.update_entity_attributes(entity, device_status)
                    
                    if old_attributes != entity.attributes:
                        self.api.configured_entities.update_attributes(entity.id, entity.attributes)
                        _LOG.info(f"Command verification success: {entity.name} -> {entity.attributes}")
                    else:
                        _LOG.debug(f"No state change yet for {entity.name}, polling will catch up")
                else:
                    _LOG.debug(f"No status returned for {entity.name}, polling will catch up")
                    
            except Exception as e:
                if "409" in str(e):
                    _LOG.info(f"Rate limited during verification for {entity.name}, polling will catch up")
                    self.client._last_rate_limit = time.time()
                else:
                    _LOG.warning(f"Verification failed for {entity.name}: {e}")
                        
        except Exception as e:
            _LOG.error(f"Command verification error for {entity.name}: {e}")

    def _map_command(self, entity_type: str, cmd_id: str, params: Dict[str, Any], entity, capabilities: set) -> tuple:
        capability = command = args = None
        
        if entity_type == EntityType.SWITCH:
            if "lock" in capabilities:
                if cmd_id == 'on':
                    capability, command = 'lock', 'lock'
                elif cmd_id == 'off':
                    capability, command = 'lock', 'unlock'
                elif cmd_id == 'toggle':
                    current_state = entity.attributes.get(SwitchAttr.STATE)
                    if current_state == SwitchStates.ON:
                        capability, command = 'lock', 'unlock'
                    else:
                        capability, command = 'lock', 'lock'
            else:
                if cmd_id == 'on':
                    capability, command = 'switch', 'on'
                elif cmd_id == 'off':
                    capability, command = 'switch', 'off'
                elif cmd_id == 'toggle':
                    current_state = entity.attributes.get(SwitchAttr.STATE)
                    if current_state == SwitchStates.ON:
                        capability, command = 'switch', 'off'
                    else:
                        capability, command = 'switch', 'on'
        
        elif entity_type == EntityType.LIGHT:
            if cmd_id == 'on':
                capability, command = 'switch', 'on'
            elif cmd_id == 'off':
                capability, command = 'switch', 'off'
            elif cmd_id == 'toggle':
                current_state = entity.attributes.get(LightAttr.STATE)
                if current_state == LightStates.ON:
                    capability, command = 'switch', 'off'
                else:
                    capability, command = 'switch', 'on'
        
        elif entity_type == EntityType.COVER:
            if cmd_id == 'open':
                if "doorControl" in capabilities:
                    capability, command = 'doorControl', 'open'
                elif "windowShade" in capabilities:
                    capability, command = 'windowShade', 'open'
            elif cmd_id == 'close':
                if "doorControl" in capabilities:
                    capability, command = 'doorControl', 'close'
                elif "windowShade" in capabilities:
                    capability, command = 'windowShade', 'close'
            elif cmd_id == 'stop':
                if "doorControl" in capabilities:
                    capability, command = 'doorControl', 'stop'
                elif "windowShade" in capabilities:
                    capability, command = 'windowShade', 'stop'
        
        elif entity_type == EntityType.MEDIA_PLAYER:
            if cmd_id == 'on':
                capability, command = 'switch', 'on'
            elif cmd_id == 'off':
                capability, command = 'switch', 'off'
            elif cmd_id == 'toggle':
                current_state = entity.attributes.get(MediaAttr.STATE)
                if current_state == MediaStates.ON:
                    capability, command = 'switch', 'off'
                else:
                    capability, command = 'switch', 'on'
            elif cmd_id == 'volume_up':
                if "audioVolume" in capabilities:
                    capability, command = 'audioVolume', 'volumeUp'
            elif cmd_id == 'volume_down':
                if "audioVolume" in capabilities:
                    capability, command = 'audioVolume', 'volumeDown'
            elif cmd_id == 'mute_toggle':
                current_muted = entity.attributes.get(MediaAttr.MUTED, False)
                _LOG.info(f"Mute toggle: current muted state = {current_muted}")
                
                if "audioMute" in capabilities:
                    if current_muted:
                        capability, command = 'audioMute', 'unmute'
                        _LOG.info(f"Using audioMute.unmute for {entity.name}")
                    else:
                        capability, command = 'audioMute', 'mute'
                        _LOG.info(f"Using audioMute.mute for {entity.name}")
                elif "audioVolume" in capabilities:
                    if current_muted:
                        capability, command = 'audioVolume', 'unmute'
                        _LOG.info(f"Using audioVolume.unmute for {entity.name}")
                    else:
                        capability, command = 'audioVolume', 'mute'
                        _LOG.info(f"Using audioVolume.mute for {entity.name}")
                else:
                    _LOG.warning(f"No mute capability found for {entity.name}")
                    
            elif cmd_id == 'select_source':
                source_param = params.get('source')
                if source_param:
                    # FIX: Use setNextInputSource for Samsung soundbars with audioInputSource
                    if "samsungvd.audioInputSource" in capabilities:
                        capability, command = 'samsungvd.audioInputSource', 'setNextInputSource'
                        args = []
                        _LOG.info(f"🔄 Will cycle to input source: {source_param}")
                    elif "mediaInputSource" in capabilities:
                        capability, command = 'mediaInputSource', 'setInputSource'
                        args = [source_param]
                        _LOG.info(f"Setting input source to: {source_param}")
                    elif "samsungvd.mediaInputSource" in capabilities:
                        capability, command = 'samsungvd.mediaInputSource', 'setInputSource'
                        args = [source_param]
                        _LOG.info(f"Setting Samsung VD input source to: {source_param}")
                    else:
                        _LOG.warning(f"No input source capability found for {entity.name}")
        
        elif entity_type == EntityType.CLIMATE:
            if cmd_id == 'on':
                capability, command = 'thermostat', 'auto'
            elif cmd_id == 'off':
                capability, command = 'thermostat', 'off'
        
        elif entity_type == EntityType.BUTTON:
            if cmd_id == 'push':
                capability, command = 'momentary', 'push'
        
        return capability, command, args