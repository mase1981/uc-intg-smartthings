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
from ucapi.climate import Climate, Features as ClimateFeatures, Attributes as ClimateAttr, States as ClimateStates
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
        self.command_timestamps = {}
        self.pending_verifications = {}

    def determine_entity_type(self, device: SmartThingsDevice) -> Optional[str]:
        capabilities = device.capabilities
        device_name = (device.label or device.name or "").lower()
        
        _LOG.debug(f"Determining entity type for {device.label}: capabilities={capabilities}")
        
        # Priority 1: BUTTONS - Handle first
        if "button" in capabilities or "momentary" in capabilities:
            _LOG.info(f"🔘 {device.label} -> BUTTON (has button capability)")
            return EntityType.BUTTON
        
        # Priority 2: CLIMATE - Handle thermostats
        climate_caps = {"thermostat", "thermostatCoolingSetpoint", "thermostatHeatingSetpoint", "airConditioner"}
        if climate_caps.intersection(capabilities):
            _LOG.info(f"🌡️ {device.label} -> CLIMATE (has {climate_caps.intersection(capabilities)})")
            return EntityType.CLIMATE
        
        # Priority 3: MEDIA PLAYERS - Handle audio/video devices
        media_caps = {"mediaPlayback", "audioVolume", "tvChannel", "mediaTrackControl"}
        if media_caps.intersection(capabilities):
            _LOG.info(f"📺 {device.label} -> MEDIA_PLAYER (has {media_caps.intersection(capabilities)})")
            return EntityType.MEDIA_PLAYER
        
        # Priority 4: COVERS - Handle doors, windows, shades
        cover_caps = {"doorControl", "windowShade", "garageDoorControl"}
        if cover_caps.intersection(capabilities):
            _LOG.info(f"🏠 {device.label} -> COVER (has {cover_caps.intersection(capabilities)})")
            return EntityType.COVER
        
        # Priority 5: LOCKS as SWITCHES - Special handling for locks
        if "lock" in capabilities and "switch" not in capabilities:
            _LOG.info(f"🔒 {device.label} -> SWITCH (lock as switch for control)")
            return EntityType.SWITCH
        
        # Priority 6: LIGHTS - Enhanced detection
        light_caps = {"switchLevel", "colorControl", "colorTemperature"}
        light_indicators = light_caps.intersection(capabilities)
        
        if light_indicators:
            excluded_caps = {
                "lock", "doorControl", "windowShade", "garageDoorControl",
                "thermostat", "mediaPlayback", "audioVolume",
                "dryerOperatingState", "washerOperatingState", "ovenOperatingState"
            }
            if not excluded_caps.intersection(capabilities):
                _LOG.info(f"💡 {device.label} -> LIGHT (has {light_indicators})")
                return EntityType.LIGHT
        
        # Name-based light detection
        light_keywords = ["light", "lamp", "bulb", "led", "fixture", "sconce", "chandelier"]
        if "switch" in capabilities and any(word in device_name for word in light_keywords):
            _LOG.info(f"💡 {device.label} -> LIGHT (name contains light keyword)")
            return EntityType.LIGHT
        
        # Priority 7: SENSORS - All measurement/status devices (excluding locks already handled)
        sensor_caps = {
            "contactSensor", "motionSensor", "presenceSensor", 
            "temperatureMeasurement", "relativeHumidityMeasurement",
            "illuminanceMeasurement", "battery", "powerMeter", "energyMeter",
            "carbonMonoxideDetector", "smokeDetector", "waterSensor",
            "accelerationSensor", "threeAxis", "ultravioletIndex"
        }
        
        sensor_matches = sensor_caps.intersection(capabilities)
        if sensor_matches:
            _LOG.info(f"📊 {device.label} -> SENSOR (has {sensor_matches})")
            return EntityType.SENSOR
        
        # Priority 8: SWITCHES - Basic on/off control
        if "switch" in capabilities:
            excluded_caps = {
                "switchLevel", "colorControl", "colorTemperature",
                "doorControl", "windowShade", "garageDoorControl",
                "thermostat", "thermostatCoolingSetpoint", "thermostatHeatingSetpoint",
                "mediaPlayback", "audioVolume", "button"
            }
            
            if not excluded_caps.intersection(capabilities):
                _LOG.info(f"🔌 {device.label} -> SWITCH (basic switch capability)")
                return EntityType.SWITCH
        
        _LOG.warning(f"❓ {device.label} -> NO TYPE DETECTED (capabilities: {capabilities})")
        return None

    def create_entity(self, device_data: Dict[str, Any], config: Dict[str, Any], area: Optional[str] = None) -> Optional[Union[Light, Switch, Sensor, Cover, Button, MediaPlayer, Climate]]:
        try:
            device = SmartThingsDevice(**device_data)
            entity_type = self.determine_entity_type(device)

            if not self._should_include(entity_type, config):
                _LOG.debug(f"Skipping {device.label}: entity type {entity_type} not included in config")
                return None

            entity_id = f"st_{device.id}"
            label = device.label or device.name or "Unknown Device"
            
            self.command_timestamps[device.id] = 0

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
                entity = self._create_media_player(entity_id, label, device, area)
            elif entity_type == EntityType.CLIMATE:
                entity = self._create_climate(entity_id, label, device, area)
            
            if entity:
                setattr(entity, 'entity_type', entity_type)
                setattr(entity, 'smartthings_capabilities', device.capabilities)
                setattr(entity, 'device_id', device.id)
                
                initial_attributes = self._get_default_attributes(entity_type, device.capabilities)
                entity.attributes.update(initial_attributes)
                
                _LOG.info(f"✅ Created {entity_type} entity: {entity_id} ({label})")
                return entity
                
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

    def _create_media_player(self, entity_id: str, name: str, device: SmartThingsDevice, area: Optional[str]) -> MediaPlayer:
        features = []
        
        if "switch" in device.capabilities:
            features.extend([MediaFeatures.ON_OFF, MediaFeatures.TOGGLE])
        if "audioVolume" in device.capabilities:
            features.extend([MediaFeatures.VOLUME, MediaFeatures.VOLUME_UP_DOWN, MediaFeatures.MUTE_TOGGLE])
        if "mediaPlayback" in device.capabilities:
            features.extend([MediaFeatures.PLAY_PAUSE, MediaFeatures.STOP])
        
        device_class = MediaClasses.SPEAKER
        
        return MediaPlayer(entity_id, name, features, {}, device_class=device_class, area=area, cmd_handler=self._handle_command)

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
        
        try:
            if entity_type == EntityType.LIGHT:
                self._update_light_attributes(entity, main_component)
            elif entity_type == EntityType.SWITCH:
                # Handle both regular switches and locks-as-switches
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
        except Exception as e:
            _LOG.error(f"Error updating attributes for {entity.id}: {e}")

    def _update_light_attributes(self, entity: Light, main_component: Dict[str, Any]):
        if "switch" in main_component:
            switch_value = main_component["switch"].get("switch", {}).get("value")
            if switch_value:
                entity.attributes[LightAttr.STATE] = LightStates.ON if switch_value == "on" else LightStates.OFF
        
        if "switchLevel" in main_component:
            level_value = main_component["switchLevel"].get("level", {}).get("value")
            if level_value is not None:
                entity.attributes[LightAttr.BRIGHTNESS] = int(level_value)

    def _update_switch_attributes(self, entity: Switch, main_component: Dict[str, Any]):
        if "switch" in main_component:
            switch_value = main_component["switch"].get("switch", {}).get("value")
            if switch_value:
                entity.attributes[SwitchAttr.STATE] = SwitchStates.ON if switch_value == "on" else SwitchStates.OFF

    def _update_lock_as_switch_attributes(self, entity: Switch, main_component: Dict[str, Any]):
        """Update lock device that's presented as a switch."""
        if "lock" in main_component:
            lock_value = main_component["lock"].get("lock", {}).get("value")
            if lock_value:
                # Map lock states to switch states: locked = ON, unlocked = OFF
                entity.attributes[SwitchAttr.STATE] = SwitchStates.ON if lock_value == "locked" else SwitchStates.OFF

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
        if "switch" in main_component:
            switch_value = main_component["switch"].get("switch", {}).get("value")
            if switch_value:
                entity.attributes[MediaAttr.STATE] = MediaStates.ON if switch_value == "on" else MediaStates.OFF

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

    def _track_command_timestamp(self, device_id: str):
        """Track when a command was sent to a device."""
        self.command_timestamps[device_id] = time.time()

    async def _handle_command(self, entity, cmd_id: str, params: Dict[str, Any] = None) -> StatusCodes:
        if params is None:
            params = {}
            
        device_id = getattr(entity, 'device_id', entity.id[3:])
        entity_type = getattr(entity, 'entity_type', None)
        capabilities = getattr(entity, 'smartthings_capabilities', set())
        
        _LOG.info(f"Command: {entity.name} -> {cmd_id} {params}")
        
        if not self.client:
            return StatusCodes.SERVICE_UNAVAILABLE
        
        # Track command timestamp
        self._track_command_timestamp(device_id)
        
        try:
            capability, command, args = self._map_command(entity_type, cmd_id, params, entity, capabilities)
            
            if not capability or not command:
                _LOG.warning(f"Unhandled command '{cmd_id}' for entity type '{entity_type}'")
                return StatusCodes.NOT_IMPLEMENTED
            
            self._apply_optimistic_update(entity, entity_type, cmd_id, capabilities)
            
            async with self.client:
                success = await self.client.execute_command(device_id, capability, command, args)
            
            if success:
                _LOG.info(f"✅ Command succeeded with optimistic update: {entity.name}")
                return StatusCodes.OK
            else:
                _LOG.warning(f"❌ Command failed, reverting optimistic update: {entity.name}")
                await self._revert_optimistic_update(entity, device_id)
                return StatusCodes.SERVER_ERROR
                
        except Exception as e:
            _LOG.error(f"Command failed for {entity.name}: {e}")
            await self._revert_optimistic_update(entity, device_id)
            return StatusCodes.SERVER_ERROR

    def _apply_optimistic_update(self, entity, entity_type: str, cmd_id: str, capabilities: set):
        """Apply optimistic state update immediately after command."""
        old_attributes = dict(entity.attributes)
        
        try:
            if entity_type == EntityType.SWITCH:
                if "lock" in capabilities:
                    if cmd_id in ['on', 'toggle']:
                        current_state = entity.attributes.get(SwitchAttr.STATE)
                        if cmd_id == 'toggle':
                            new_state = SwitchStates.OFF if current_state == SwitchStates.ON else SwitchStates.ON
                        else:
                            new_state = SwitchStates.ON
                        entity.attributes[SwitchAttr.STATE] = new_state
                        _LOG.debug(f"Optimistic lock update: {entity.name} -> {'LOCKED' if new_state == SwitchStates.ON else 'UNLOCKED'}")
                    elif cmd_id == 'off':
                        entity.attributes[SwitchAttr.STATE] = SwitchStates.OFF
                else:
                    if cmd_id == 'on':
                        entity.attributes[SwitchAttr.STATE] = SwitchStates.ON
                    elif cmd_id == 'off':
                        entity.attributes[SwitchAttr.STATE] = SwitchStates.OFF
                    elif cmd_id == 'toggle':
                        current_state = entity.attributes.get(SwitchAttr.STATE)
                        entity.attributes[SwitchAttr.STATE] = SwitchStates.OFF if current_state == SwitchStates.ON else SwitchStates.ON
            
            elif entity_type == EntityType.LIGHT:
                if cmd_id == 'on':
                    entity.attributes[LightAttr.STATE] = LightStates.ON
                elif cmd_id == 'off':
                    entity.attributes[LightAttr.STATE] = LightStates.OFF
                elif cmd_id == 'toggle':
                    current_state = entity.attributes.get(LightAttr.STATE)
                    entity.attributes[LightAttr.STATE] = LightStates.OFF if current_state == LightStates.ON else LightStates.ON
            
            elif entity_type == EntityType.COVER:
                if cmd_id == 'open':
                    entity.attributes[CoverAttr.STATE] = CoverStates.OPENING
                elif cmd_id == 'close':
                    entity.attributes[CoverAttr.STATE] = CoverStates.CLOSING
            
            # Push the optimistic update to UC Remote immediately
            if old_attributes != entity.attributes:
                self.api.configured_entities.update_attributes(entity.id, entity.attributes)
                _LOG.info(f"🚀 Optimistic update applied: {entity.name} -> {entity.attributes}")
            
        except Exception as e:
            _LOG.error(f"Error applying optimistic update: {e}")
            entity.attributes.update(old_attributes)  # Revert on error

    async def _revert_optimistic_update(self, entity, device_id: str):
        """Revert optimistic update by fetching real state from SmartThings."""
        try:
            _LOG.info(f"🔄 Reverting optimistic update for {entity.name}")
            async with self.client:
                device_status = await self.client.get_device_status(device_id)
                if device_status:
                    old_attributes = dict(entity.attributes)
                    self.update_entity_attributes(entity, device_status)
                    if old_attributes != entity.attributes:
                        self.api.configured_entities.update_attributes(entity.id, entity.attributes)
                        _LOG.info(f"↩️ Optimistic update reverted: {entity.name}")
        except Exception as e:
            _LOG.error(f"Error reverting optimistic update: {e}")

    def _map_command(self, entity_type: str, cmd_id: str, params: Dict[str, Any], entity, capabilities: set) -> tuple:
        capability = command = args = None
        
        if entity_type == EntityType.SWITCH:
            if "lock" in capabilities:
                # Handle lock devices mapped as switches
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
                # Regular switch handling
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
                capability, command = 'doorControl', 'open'
            elif cmd_id == 'close':
                capability, command = 'doorControl', 'close'
            elif cmd_id == 'stop':
                capability, command = 'doorControl', 'stop'
        
        elif entity_type == EntityType.BUTTON:
            if cmd_id == 'push':
                capability, command = 'button', 'pushed'
        
        return capability, command, args