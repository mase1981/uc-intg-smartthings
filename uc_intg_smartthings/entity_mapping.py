"""
:copyright: (c) 2025 by Meir Miyara
:license: MPL-2.0, see LICENSE for more details.
"""
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from ucapi.light import Light, Features as LightFeatures, Attributes as LightAttributes, States as LightStates
from ucapi.switch import Switch, Features as SwitchFeatures, Attributes as SwitchAttributes, States as SwitchStates
from ucapi.sensor import Sensor, Features as SensorFeatures, Attributes as SensorAttributes, States as SensorStates, DeviceClasses as SensorDeviceClasses
from ucapi.media_player import MediaPlayer, Features as MediaFeatures, Attributes as MediaAttributes, States as MediaStates, DeviceClasses as MediaDeviceClasses
from ucapi.climate import Climate, Features as ClimateFeatures, Attributes as ClimateAttributes, States as ClimateStates
from ucapi.cover import Cover, Features as CoverFeatures, Attributes as CoverAttributes, States as CoverStates, DeviceClasses as CoverDeviceClasses
from ucapi.button import Button, Attributes as ButtonAttributes, States as ButtonStates

_LOG = logging.getLogger(__name__)


class ValidatedEntityMapper:
    CAPABILITY_PATTERNS = {
        "switch": {
            "path": ["switch", "switch", "value"],
            "values": ["on", "off"],
            "entity_types": ["light", "switch", "media_player"]
        },
        "switchLevel": {
            "path": ["switchLevel", "level", "value"],
            "values": [0, 100],
            "entity_types": ["light"]
        },
        "fanSpeed": {
            "path": ["fanSpeed", "fanSpeed", "value"],
            "values": [0, 1, 2, 3, 4, 5],
            "entity_types": ["light"]
        },
        "doorControl": {
            "path": ["doorControl", "door", "value"],
            "values": ["open", "closed", "opening", "closing"],
            "entity_types": ["cover"]
        },
        "lock": {
            "path": ["lock", "lock", "value"],
            "values": ["locked", "unlocked"],
            "entity_types": ["sensor"]
        },
        "contactSensor": {
            "path": ["contactSensor", "contact", "value"],
            "values": ["open", "closed"],
            "entity_types": ["sensor"]
        },
        "motionSensor": {
            "path": ["motionSensor", "motion", "value"],
            "values": ["active", "inactive"],
            "entity_types": ["sensor"]
        },
        "button": {
            "path": ["button", "button", "value"],
            "values": ["pushed", "held", "double"],
            "entity_types": ["button"]
        },
        "battery": {
            "path": ["battery", "battery", "value"],
            "values": [0, 100],
            "entity_types": ["sensor"]
        },
        "temperatureMeasurement": {
            "path": ["temperatureMeasurement", "temperature", "value"],
            "values": [-50.0, 100.0],
            "entity_types": ["sensor", "climate"]
        },
        "colorControl": {
            "hue_path": ["colorControl", "hue", "value"],
            "saturation_path": ["colorControl", "saturation", "value"],
            "values": {"hue": [0, 360], "saturation": [0, 100]},
            "entity_types": ["light"]
        },
        "colorTemperature": {
            "path": ["colorTemperature", "colorTemperature", "value"],
            "values": [2000, 6500],
            "entity_types": ["light"]
        },
        "windowShade": {
            "path": ["windowShade", "windowShade", "value"],
            "values": ["open", "closed", "opening", "closing", "partially open"],
            "entity_types": ["cover"]
        },
        "windowShadeLevel": {
            "path": ["windowShadeLevel", "shadeLevel", "value"],
            "values": [0, 100],
            "entity_types": ["cover"]
        },
        "thermostat": {
            "mode_path": ["thermostat", "thermostatMode", "value"],
            "heating_path": ["thermostat", "heatingSetpoint", "value"],
            "cooling_path": ["thermostat", "coolingSetpoint", "value"],
            "values": {
                "mode": ["off", "heat", "cool", "auto", "emergency heat"],
                "temperature": [10.0, 35.0]
            },
            "entity_types": ["climate"]
        },
        "mediaPlayback": {
            "path": ["mediaPlayback", "playbackStatus", "value"],
            "values": ["playing", "paused", "stopped"],
            "entity_types": ["media_player"]
        },
        "audioVolume": {
            "volume_path": ["audioVolume", "volume", "value"],
            "mute_path": ["audioVolume", "mute", "value"],
            "values": {"volume": [0, 100], "mute": ["muted", "unmuted"]},
            "entity_types": ["media_player"]
        }
    }
    
    @classmethod
    def determine_entity_type(cls, device: Dict[str, Any]) -> Optional[str]:
        capabilities = cls._get_device_capabilities(device)
        
        entity_priorities = [
            ("media_player", ["mediaPlayback", "audioVolume", "tvChannel"]),
            ("climate", ["thermostat", "thermostatCoolingSetpoint", "thermostatHeatingSetpoint", "airConditioner"]),
            ("cover", ["windowShade", "doorControl", "garageDoorControl"]),
            ("light", ["switch", "switchLevel", "colorControl", "colorTemperature"]),
            ("sensor", ["contactSensor", "motionSensor", "temperatureMeasurement", "relativeHumidityMeasurement", "powerMeter", "energyMeter", "battery"]),
            ("button", ["button", "momentary"]),
            ("switch", ["switch"])
        ]
        
        for entity_type, required_caps in entity_priorities:
            if any(cap in capabilities for cap in required_caps):
                if entity_type == "light":
                    exclusions = ["mediaPlayback", "thermostat", "windowShade", "doorControl", "contactSensor", "motionSensor", "button"]
                    if not any(cap in capabilities for cap in exclusions):
                        return entity_type
                else:
                    return entity_type
        
        return None
    
    @classmethod
    def _get_device_capabilities(cls, device: Dict[str, Any]) -> Set[str]:
        capabilities = set()
        components = device.get("components", [])
        for component in components:
            comp_capabilities = component.get("capabilities", [])
            for cap in comp_capabilities:
                capabilities.add(cap.get("id", ""))
        return capabilities
    
    @classmethod
    def create_light_entity(cls, device: Dict[str, Any], cmd_handler) -> Light:
        capabilities = cls._get_device_capabilities(device)
        
        features = [LightFeatures.ON_OFF]
        attributes = {LightAttributes.STATE: LightStates.UNKNOWN}
        
        if "switchLevel" in capabilities:
            features.append(LightFeatures.DIM)
            attributes[LightAttributes.BRIGHTNESS] = 0
        
        if "colorControl" in capabilities:
            features.append(LightFeatures.COLOR)
            attributes[LightAttributes.HUE] = 0
            attributes[LightAttributes.SATURATION] = 0
        
        if "colorTemperature" in capabilities:
            features.append(LightFeatures.COLOR_TEMPERATURE)
            attributes[LightAttributes.COLOR_TEMPERATURE] = 2700
        
        return Light(
            identifier=device["deviceId"],
            name=device.get("label", device.get("name", "Unknown Light")),
            features=features,
            attributes=attributes,
            cmd_handler=cmd_handler
        )
    
    @classmethod
    def create_switch_entity(cls, device: Dict[str, Any], cmd_handler) -> Switch:
        features = [SwitchFeatures.ON_OFF]
        attributes = {SwitchAttributes.STATE: SwitchStates.UNKNOWN}
        
        device_class = None
        capabilities = cls._get_device_capabilities(device)
        if "outlet" in capabilities:
            from ucapi.switch import DeviceClasses as SwitchDeviceClasses
            device_class = SwitchDeviceClasses.OUTLET
        
        return Switch(
            identifier=device["deviceId"],
            name=device.get("label", device.get("name", "Unknown Switch")),
            features=features,
            attributes=attributes,
            device_class=device_class,
            cmd_handler=cmd_handler
        )
    
    @classmethod
    def create_sensor_entity(cls, device: Dict[str, Any]) -> Sensor:
        capabilities = cls._get_device_capabilities(device)
        
        attributes = {SensorAttributes.STATE: SensorStates.UNKNOWN}
        device_class = SensorDeviceClasses.CUSTOM
        
        if "temperatureMeasurement" in capabilities:
            device_class = SensorDeviceClasses.TEMPERATURE
            attributes[SensorAttributes.VALUE] = 0
            attributes[SensorAttributes.UNIT] = "Â°C"
        elif "relativeHumidityMeasurement" in capabilities:
            device_class = SensorDeviceClasses.HUMIDITY
            attributes[SensorAttributes.VALUE] = 0
            attributes[SensorAttributes.UNIT] = "%"
        elif "powerMeter" in capabilities:
            device_class = SensorDeviceClasses.POWER
            attributes[SensorAttributes.VALUE] = 0
            attributes[SensorAttributes.UNIT] = "W"
        elif "energyMeter" in capabilities:
            device_class = SensorDeviceClasses.ENERGY
            attributes[SensorAttributes.VALUE] = 0
            attributes[SensorAttributes.UNIT] = "kWh"
        elif "battery" in capabilities:
            device_class = SensorDeviceClasses.BATTERY
            attributes[SensorAttributes.VALUE] = 0
            attributes[SensorAttributes.UNIT] = "%"
        elif "contactSensor" in capabilities:
            attributes[SensorAttributes.VALUE] = "closed"
        elif "motionSensor" in capabilities:
            attributes[SensorAttributes.VALUE] = "inactive"
        elif "lock" in capabilities:
            attributes[SensorAttributes.VALUE] = "locked"
        
        return Sensor(
            identifier=device["deviceId"],
            name=device.get("label", device.get("name", "Unknown Sensor")),
            features=[],
            attributes=attributes,
            device_class=device_class
        )
    
    @classmethod
    def create_media_player_entity(cls, device: Dict[str, Any], cmd_handler) -> MediaPlayer:
        capabilities = cls._get_device_capabilities(device)
        
        features = []
        attributes = {MediaAttributes.STATE: MediaStates.UNKNOWN}
        
        if "switch" in capabilities:
            features.append(MediaFeatures.ON_OFF)
        
        if "audioVolume" in capabilities:
            features.extend([MediaFeatures.VOLUME, MediaFeatures.VOLUME_UP_DOWN, MediaFeatures.MUTE_TOGGLE])
            attributes[MediaAttributes.VOLUME] = 0
            attributes[MediaAttributes.MUTED] = False
        
        if "mediaPlayback" in capabilities:
            features.extend([MediaFeatures.PLAY_PAUSE, MediaFeatures.STOP, MediaFeatures.NEXT, MediaFeatures.PREVIOUS])
        
        device_class = MediaDeviceClasses.SPEAKER
        device_type = device.get("deviceTypeName", "").lower()
        if "tv" in device_type:
            device_class = MediaDeviceClasses.TV
        elif "receiver" in device_type or "amplifier" in device_type:
            device_class = MediaDeviceClasses.RECEIVER
        elif "streaming" in device_type or "player" in device_type:
            device_class = MediaDeviceClasses.STREAMING_BOX
        
        return MediaPlayer(
            identifier=device["deviceId"],
            name=device.get("label", device.get("name", "Unknown Media Player")),
            features=features,
            attributes=attributes,
            device_class=device_class,
            cmd_handler=cmd_handler
        )
    
    @classmethod
    def create_climate_entity(cls, device: Dict[str, Any], cmd_handler) -> Climate:
        capabilities = cls._get_device_capabilities(device)
        
        features = []
        attributes = {ClimateAttributes.STATE: ClimateStates.UNKNOWN}
        
        if "thermostat" in capabilities:
            features.extend([ClimateFeatures.HEAT, ClimateFeatures.COOL, ClimateFeatures.TARGET_TEMPERATURE])
            attributes[ClimateAttributes.TARGET_TEMPERATURE] = 21
        
        if "temperatureMeasurement" in capabilities:
            features.append(ClimateFeatures.CURRENT_TEMPERATURE)
            attributes[ClimateAttributes.CURRENT_TEMPERATURE] = 20
        
        if "fan" in capabilities:
            features.append(ClimateFeatures.FAN)
            attributes[ClimateAttributes.FAN_MODE] = "auto"
        
        options = {
            "temperature_unit": "Â°C",
            "target_temperature_step": 1,
            "min_temperature": 10,
            "max_temperature": 35
        }
        
        return Climate(
            identifier=device["deviceId"],
            name=device.get("label", device.get("name", "Unknown Climate")),
            features=features,
            attributes=attributes,
            options=options,
            cmd_handler=cmd_handler
        )
    
    @classmethod
    def create_cover_entity(cls, device: Dict[str, Any], cmd_handler) -> Cover:
        capabilities = cls._get_device_capabilities(device)
        
        features = [CoverFeatures.OPEN, CoverFeatures.CLOSE]
        attributes = {CoverAttributes.STATE: CoverStates.UNKNOWN}
        
        if "windowShadeLevel" in capabilities:
            features.append(CoverFeatures.POSITION)
            attributes[CoverAttributes.POSITION] = 0
        
        device_class = CoverDeviceClasses.SHADE
        if "doorControl" in capabilities or "garageDoorControl" in capabilities:
            device_class = CoverDeviceClasses.GARAGE
        elif "windowShade" in capabilities:
            device_class = CoverDeviceClasses.BLIND
        
        return Cover(
            identifier=device["deviceId"],
            name=device.get("label", device.get("name", "Unknown Cover")),
            features=features,
            attributes=attributes,
            device_class=device_class,
            cmd_handler=cmd_handler
        )
    
    @classmethod
    def create_button_entity(cls, device: Dict[str, Any], cmd_handler) -> Button:
        return Button(
            identifier=device["deviceId"],
            name=device.get("label", device.get("name", "Unknown Button")),
            cmd_handler=cmd_handler
        )
    
    @classmethod
    def update_entity_attributes(cls, entity, device_status: Dict[str, Any]) -> None:
        try:
            main_component = device_status.get("main", {})
            
            if isinstance(entity, Light):
                cls._update_light_attributes_validated(entity, main_component)
            elif isinstance(entity, Switch):
                cls._update_switch_attributes_validated(entity, main_component)
            elif isinstance(entity, Sensor):
                cls._update_sensor_attributes_validated(entity, main_component)
            elif isinstance(entity, MediaPlayer):
                cls._update_media_player_attributes_validated(entity, main_component)
            elif isinstance(entity, Climate):
                cls._update_climate_attributes_validated(entity, main_component)
            elif isinstance(entity, Cover):
                cls._update_cover_attributes_validated(entity, main_component)
            elif isinstance(entity, Button):
                cls._update_button_attributes_validated(entity, main_component)
                
        except Exception as e:
            _LOG.error("Failed to update entity attributes for %s: %s", entity.id, e)
            import traceback
            _LOG.debug("Attribute update error traceback: %s", traceback.format_exc())
    
    @classmethod
    def _safe_get_value(cls, status: Dict[str, Any], *path) -> Any:
        current = status
        for key in path:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None
        return current
    
    @classmethod
    def _safe_int(cls, value, default=0) -> int:
        if value is None:
            return default
        try:
            return int(value)
        except (ValueError, TypeError):
            return default
    
    @classmethod
    def _safe_float(cls, value, default=0.0) -> float:
        if value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
    
    @classmethod
    def _update_light_attributes_validated(cls, entity: Light, status: Dict[str, Any]) -> None:
        _LOG.debug("Updating light %s with validated patterns", entity.name)
        
        switch_value = cls._safe_get_value(status, "switch", "switch", "value")
        if switch_value is not None:
            new_state = LightStates.ON if switch_value == "on" else LightStates.OFF
            old_state = entity.attributes.get(LightAttributes.STATE)
            entity.attributes[LightAttributes.STATE] = new_state
            _LOG.info("âœ… Light %s state: %s -> %s", entity.name, old_state, new_state)
        
        level_value = cls._safe_get_value(status, "switchLevel", "level", "value")
        if level_value is not None:
            entity.attributes[LightAttributes.BRIGHTNESS] = cls._safe_int(level_value)
            _LOG.debug("Light %s brightness: %s", entity.name, level_value)
        
        fan_value = cls._safe_get_value(status, "fanSpeed", "fanSpeed", "value")
        if fan_value is not None:
            fan_speed = cls._safe_int(fan_value)
            brightness = min(100, max(0, fan_speed * 20))
            entity.attributes[LightAttributes.BRIGHTNESS] = brightness
            _LOG.debug("Fan light %s speed->brightness: %s->%s", entity.name, fan_speed, brightness)
        
        hue_value = cls._safe_get_value(status, "colorControl", "hue", "value")
        if hue_value is not None:
            entity.attributes[LightAttributes.HUE] = cls._safe_int(hue_value)
        
        sat_value = cls._safe_get_value(status, "colorControl", "saturation", "value")
        if sat_value is not None:
            entity.attributes[LightAttributes.SATURATION] = cls._safe_int(sat_value)
        
        temp_value = cls._safe_get_value(status, "colorTemperature", "colorTemperature", "value")
        if temp_value is not None:
            entity.attributes[LightAttributes.COLOR_TEMPERATURE] = cls._safe_int(temp_value)
    
    @classmethod
    def _update_switch_attributes_validated(cls, entity: Switch, status: Dict[str, Any]) -> None:
        _LOG.debug("Updating switch %s with validated patterns", entity.name)
        
        switch_value = cls._safe_get_value(status, "switch", "switch", "value")
        if switch_value is not None:
            new_state = SwitchStates.ON if switch_value == "on" else SwitchStates.OFF
            old_state = entity.attributes.get(SwitchAttributes.STATE)
            entity.attributes[SwitchAttributes.STATE] = new_state
            _LOG.info("âœ… Switch %s state: %s -> %s", entity.name, old_state, new_state)
    
    @classmethod
    def _update_sensor_attributes_validated(cls, entity: Sensor, status: Dict[str, Any]) -> None:
        entity.attributes[SensorAttributes.STATE] = SensorStates.ON
        
        temp_value = cls._safe_get_value(status, "temperatureMeasurement", "temperature", "value")
        if temp_value is not None:
            entity.attributes[SensorAttributes.VALUE] = cls._safe_float(temp_value)
            return
        
        humidity_value = cls._safe_get_value(status, "relativeHumidityMeasurement", "humidity", "value")
        if humidity_value is not None:
            entity.attributes[SensorAttributes.VALUE] = cls._safe_float(humidity_value)
            return
        
        power_value = cls._safe_get_value(status, "powerMeter", "power", "value")
        if power_value is not None:
            entity.attributes[SensorAttributes.VALUE] = cls._safe_float(power_value)
            return
        
        energy_value = cls._safe_get_value(status, "energyMeter", "energy", "value")
        if energy_value is not None:
            entity.attributes[SensorAttributes.VALUE] = cls._safe_float(energy_value)
            return
        
        battery_value = cls._safe_get_value(status, "battery", "battery", "value")
        if battery_value is not None:
            entity.attributes[SensorAttributes.VALUE] = cls._safe_int(battery_value)
            return
        
        contact_value = cls._safe_get_value(status, "contactSensor", "contact", "value")
        if contact_value is not None:
            entity.attributes[SensorAttributes.VALUE] = str(contact_value)
            return
        
        motion_value = cls._safe_get_value(status, "motionSensor", "motion", "value")
        if motion_value is not None:
            entity.attributes[SensorAttributes.VALUE] = str(motion_value)
            return
        
        lock_value = cls._safe_get_value(status, "lock", "lock", "value")
        if lock_value is not None:
            entity.attributes[SensorAttributes.VALUE] = str(lock_value)
            return
    
    @classmethod
    def _update_media_player_attributes_validated(cls, entity: MediaPlayer, status: Dict[str, Any]) -> None:
        switch_value = cls._safe_get_value(status, "switch", "switch", "value")
        if switch_value is not None:
            entity.attributes[MediaAttributes.STATE] = (
                MediaStates.ON if switch_value == "on" else MediaStates.OFF
            )
        
        volume_value = cls._safe_get_value(status, "audioVolume", "volume", "value")
        if volume_value is not None:
            entity.attributes[MediaAttributes.VOLUME] = cls._safe_int(volume_value)
        
        mute_value = cls._safe_get_value(status, "audioVolume", "mute", "value")
        if mute_value is not None:
            entity.attributes[MediaAttributes.MUTED] = mute_value == "muted"
        
        playback_value = cls._safe_get_value(status, "mediaPlayback", "playbackStatus", "value")
        if playback_value is not None:
            if playback_value == "playing":
                entity.attributes[MediaAttributes.STATE] = MediaStates.PLAYING
            elif playback_value == "paused":
                entity.attributes[MediaAttributes.STATE] = MediaStates.PAUSED
            elif playback_value == "stopped":
                entity.attributes[MediaAttributes.STATE] = MediaStates.ON
    
    @classmethod
    def _update_climate_attributes_validated(cls, entity: Climate, status: Dict[str, Any]) -> None:
        mode_value = cls._safe_get_value(status, "thermostat", "thermostatMode", "value")
        if mode_value is not None:
            if mode_value == "heat":
                entity.attributes[ClimateAttributes.STATE] = ClimateStates.HEAT
            elif mode_value == "cool":
                entity.attributes[ClimateAttributes.STATE] = ClimateStates.COOL
            elif mode_value == "auto":
                entity.attributes[ClimateAttributes.STATE] = ClimateStates.AUTO
            elif mode_value == "off":
                entity.attributes[ClimateAttributes.STATE] = ClimateStates.OFF
        
        heating_value = cls._safe_get_value(status, "thermostat", "heatingSetpoint", "value")
        if heating_value is not None:
            entity.attributes[ClimateAttributes.TARGET_TEMPERATURE] = cls._safe_float(heating_value)
        
        cooling_value = cls._safe_get_value(status, "thermostat", "coolingSetpoint", "value")
        if cooling_value is not None and heating_value is None:
            entity.attributes[ClimateAttributes.TARGET_TEMPERATURE] = cls._safe_float(cooling_value)
        
        temp_value = cls._safe_get_value(status, "temperatureMeasurement", "temperature", "value")
        if temp_value is not None:
            entity.attributes[ClimateAttributes.CURRENT_TEMPERATURE] = cls._safe_float(temp_value)
    
    @classmethod
    def _update_cover_attributes_validated(cls, entity: Cover, status: Dict[str, Any]) -> None:
        door_value = cls._safe_get_value(status, "doorControl", "door", "value")
        if door_value is not None:
            if door_value == "open":
                entity.attributes[CoverAttributes.STATE] = CoverStates.OPEN
            elif door_value == "closed":
                entity.attributes[CoverAttributes.STATE] = CoverStates.CLOSED
            elif door_value == "opening":
                entity.attributes[CoverAttributes.STATE] = CoverStates.OPENING
            elif door_value == "closing":
                entity.attributes[CoverAttributes.STATE] = CoverStates.CLOSING
            _LOG.info("âœ… Cover %s door state: %s", entity.name, door_value)
            return
        
        shade_value = cls._safe_get_value(status, "windowShade", "windowShade", "value")
        if shade_value is not None:
            if shade_value == "open":
                entity.attributes[CoverAttributes.STATE] = CoverStates.OPEN
            elif shade_value == "closed":
                entity.attributes[CoverAttributes.STATE] = CoverStates.CLOSED
            elif shade_value == "opening":
                entity.attributes[CoverAttributes.STATE] = CoverStates.OPENING
            elif shade_value == "closing":
                entity.attributes[CoverAttributes.STATE] = CoverStates.CLOSING
        
        level_value = cls._safe_get_value(status, "windowShadeLevel", "shadeLevel", "value")
        if level_value is not None:
            entity.attributes[CoverAttributes.POSITION] = cls._safe_int(level_value)
    
    @classmethod
    def _update_button_attributes_validated(cls, entity: Button, status: Dict[str, Any]) -> None:
        entity.attributes[ButtonAttributes.STATE] = ButtonStates.AVAILABLE
    
    @classmethod
    def validate_device_status(cls, device_name: str, device_status: Dict[str, Any]) -> Dict[str, Any]:
        validation_results = {
            "device_name": device_name,
            "validated_capabilities": [],
            "unknown_capabilities": [],
            "mapping_errors": [],
            "recommendations": []
        }
        
        main_component = device_status.get("main", {})
        
        for capability_name in main_component.keys():
            if capability_name in cls.CAPABILITY_PATTERNS:
                pattern = cls.CAPABILITY_PATTERNS[capability_name]
                
                if "path" in pattern:
                    test_value = cls._safe_get_value(main_component, *pattern["path"][1:])
                    validation_results["validated_capabilities"].append({
                        "capability": capability_name,
                        "pattern": " -> ".join(pattern["path"]),
                        "value_found": test_value,
                        "pattern_works": test_value is not None
                    })
                else:
                    sub_validations = {}
                    for sub_key, sub_pattern in pattern.items():
                        if sub_key.endswith("_path"):
                            test_value = cls._safe_get_value(main_component, *sub_pattern[1:])
                            sub_validations[sub_key] = {
                                "pattern": " -> ".join(sub_pattern),
                                "value": test_value,
                                "works": test_value is not None
                            }
                    
                    validation_results["validated_capabilities"].append({
                        "capability": capability_name,
                        "sub_patterns": sub_validations
                    })
            else:
                validation_results["unknown_capabilities"].append(capability_name)
        
        return validation_results


EntityMapper = ValidatedEntityMapper