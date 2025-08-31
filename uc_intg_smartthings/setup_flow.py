"""
:copyright: (c) 2025 by Meir Miyara
:license: MPL-2.0, see LICENSE for more details
"""

import logging
from typing import Any, Dict, List, Optional
import asyncio

from ucapi.api_definitions import (
    SetupDriver, DriverSetupRequest, UserDataResponse, UserConfirmationResponse,
    RequestUserInput, RequestUserConfirmation, SetupComplete, SetupError, 
    IntegrationSetupError
)

from uc_intg_smartthings.client import SmartThingsClient, SmartThingsAPIError, SmartThingsDevice
from uc_intg_smartthings.config import ConfigManager, validate_smartthings_token, get_recommended_polling_settings

_LOG = logging.getLogger(__name__)

class DeviceAnalyzer:
    
    @staticmethod
    def determine_entity_type(capabilities: set, device_name: str, device_type: str = "") -> Optional[str]:
        device_name_lower = device_name.lower()
        device_type_lower = device_type.lower()
        
        _LOG.debug(f"Analyzing device: {device_name}")
        _LOG.debug(f"  Capabilities: {capabilities}")
        _LOG.debug(f"  Device Type: {device_type}")
        
        if DeviceAnalyzer._is_samsung_tv(device_name_lower, device_type_lower, capabilities):
            _LOG.info(f"Samsung TV detected: {device_name} -> media_player")
            return "media_player"
            
        if DeviceAnalyzer._is_samsung_soundbar(device_name_lower, device_type_lower, capabilities):
            _LOG.info(f"Samsung Soundbar detected: {device_name} -> media_player") 
            return "media_player"
        
        # Button detection
        if "button" in capabilities or "momentary" in capabilities:
            return "button"
        
        # Climate detection
        climate_caps = {"thermostat", "thermostatCoolingSetpoint", "thermostatHeatingSetpoint", "airConditioner"}
        if climate_caps.intersection(capabilities):
            return "climate"
        
        # Media player detection
        media_caps = {"mediaPlayback", "audioVolume", "tvChannel", "mediaTrackControl", "speechSynthesis"}
        media_keywords = ["tv", "television", "soundbar", "speaker", "audio", "receiver", "stereo", "music"]
        
        if (media_caps.intersection(capabilities) or 
            any(keyword in device_name_lower for keyword in media_keywords) or
            any(keyword in device_type_lower for keyword in media_keywords)):
            return "media_player"
        
        # Cover detection
        cover_caps = {"doorControl", "windowShade", "garageDoorControl"}
        if cover_caps.intersection(capabilities):
            return "cover"
        
        # Light detection
        light_caps = {"switchLevel", "colorControl", "colorTemperature"}
        if light_caps.intersection(capabilities):
            excluded_caps = {
                "lock", "doorControl", "windowShade", "garageDoorControl",
                "thermostat", "mediaPlayback", "audioVolume", "speechSynthesis",
                "dryerOperatingState", "washerOperatingState", "ovenOperatingState"
            }
            if not excluded_caps.intersection(capabilities):
                return "light"
        
        # Light detection by name
        if "switch" in capabilities and any(word in device_name_lower for word in ["light", "lamp", "bulb", "led"]):
            return "light"
        
        # Sensor detection
        sensor_caps = {
            "lock", "contactSensor", "motionSensor", "presenceSensor", 
            "temperatureMeasurement", "relativeHumidityMeasurement",
            "battery", "powerMeter", "energyMeter", "illuminanceMeasurement",
            "accelerationSensor", "threeAxis", "ultravioletIndex",
            "carbonMonoxideDetector", "smokeDetector", "waterSensor",
            "soundSensor", "dustSensor", "airQualitySensor"
        }
        
        if sensor_caps.intersection(capabilities):
            return "sensor"
        
        # Basic switch detection (fallback)
        if "switch" in capabilities:
            excluded_caps = {
                "switchLevel", "colorControl", "colorTemperature",
                "doorControl", "windowShade", "garageDoorControl",  
                "thermostat", "thermostatCoolingSetpoint", "thermostatHeatingSetpoint",
                "mediaPlayback", "audioVolume", "speechSynthesis"
            }
            
            if not excluded_caps.intersection(capabilities):
                return "switch"
        
        _LOG.warning(f"Could not determine entity type for {device_name}")
        _LOG.warning(f"  Capabilities: {capabilities}")
        return None

    @staticmethod
    def _is_samsung_tv(device_name: str, device_type: str, capabilities: set) -> bool:
        """Enhanced Samsung TV detection"""
        samsung_tv_indicators = [
            # Direct name matches
            "samsung" in device_name and "tv" in device_name,
            "samsung" in device_name and any(model in device_name for model in ["au5000", "q70", "qled", "neo"]),
            # Device type matches
            "tv" in device_type,
            "television" in device_type,
            # Capability patterns common to Samsung TVs
            {"switch", "audioVolume"}.issubset(capabilities),
            {"switch", "speechSynthesis"}.issubset(capabilities),
        ]
        
        return any(samsung_tv_indicators)

    @staticmethod
    def _is_samsung_soundbar(device_name: str, device_type: str, capabilities: set) -> bool:
        """Enhanced Samsung Soundbar detection"""
        samsung_soundbar_indicators = [
            # Direct name matches
            "samsung" in device_name and "soundbar" in device_name,
            "samsung" in device_name and "q70t" in device_name,
            "samsung" in device_name and "q90r" in device_name,  # Added Q90R detection
            "soundbar" in device_name,
            # Device type matches
            "soundbar" in device_type,
            "speaker" in device_type and "samsung" in device_name,
            # Capability patterns common to Samsung soundbars
            {"audioVolume", "switch"}.issubset(capabilities),
            "audioVolume" in capabilities and "mediaPlayback" not in capabilities,
        ]
        
        return any(samsung_soundbar_indicators)

class SmartThingsSetupFlow:
    
    def __init__(self, api, config_manager: ConfigManager):
        self.api = api
        self.config_manager = config_manager
        self.setup_state = {}
        self.discovered_devices = []
        self.client_session = None  # Track client session for proper cleanup
        
    async def handle_setup_request(self, msg: SetupDriver) -> Any:
        try:
            if isinstance(msg, DriverSetupRequest):
                return await self._handle_initial_setup(msg.setup_data, msg.reconfigure)
            elif isinstance(msg, UserDataResponse):
                return await self._handle_user_data_response(msg.input_values)
            elif isinstance(msg, UserConfirmationResponse):
                return await self._handle_user_confirmation(msg.confirm)
            else:
                _LOG.warning(f"Unsupported setup message type: {type(msg)}")
                return SetupError(IntegrationSetupError.OTHER)
                
        except Exception as e:
            _LOG.error(f"Setup request handling failed: {e}", exc_info=True)
            return SetupError(IntegrationSetupError.OTHER)
        finally:
            # Ensure client cleanup
            await self._cleanup_client()

    async def _cleanup_client(self):
        """Properly cleanup client session"""
        if self.client_session:
            try:
                await self.client_session.close()
                self.client_session = None
                _LOG.debug("Setup client session cleaned up")
            except Exception as e:
                _LOG.warning(f"Error cleaning up setup client: {e}")

    async def _handle_initial_setup(self, setup_data: Dict[str, Any], reconfigure: bool = False) -> Any:
        _LOG.info(f"Starting SmartThings setup (reconfigure={reconfigure})")
        
        if reconfigure:
            self.setup_state = self.config_manager.load_config()
            _LOG.debug("Loaded existing configuration for reconfigure")
        
        token = setup_data.get("token") or self.setup_state.get("access_token")
        
        if not token:
            return self._request_access_token()
        
        if not validate_smartthings_token(token):
            _LOG.warning("Invalid SmartThings token format provided")
            return self._request_access_token(error_message="Invalid token format. Please check your Personal Access Token.")
        
        self.setup_state["access_token"] = token
        
        try:
            # Create and store client session for proper cleanup
            self.client_session = SmartThingsClient(token)
            
            async with self.client_session:
                locations = await self.client_session.get_locations()
                
                if not locations:
                    _LOG.error("No SmartThings locations found")
                    return SetupError(IntegrationSetupError.NOT_FOUND)
                
                self.setup_state["locations"] = locations
                _LOG.info(f"Found {len(locations)} SmartThings locations")
                
                if len(locations) == 1:
                    location = locations[0]
                    self.setup_state["location_id"] = location["locationId"]
                    self.setup_state["location_name"] = location["name"]
                    return await self._discover_and_configure_devices(self.client_session)
                else:
                    return self._request_location_selection(locations)
                    
        except SmartThingsAPIError as e:
            _LOG.error(f"SmartThings API error during setup: {e}")
            if e.status_code == 401:
                return SetupError(IntegrationSetupError.AUTHORIZATION_ERROR)
            elif e.status_code == 404:
                return SetupError(IntegrationSetupError.NOT_FOUND)
            else:
                return SetupError(IntegrationSetupError.OTHER)
        except Exception as e:
            _LOG.error(f"Unexpected error during initial setup: {e}", exc_info=True)
            return SetupError(IntegrationSetupError.OTHER)

    def _request_access_token(self, error_message: Optional[str] = None) -> RequestUserInput:
        """Request SmartThings Personal Access Token with helpful instructions."""
        settings = [
            {
                "id": "token",
                "label": {"en": "Personal Access Token"},
                "field": {
                    "text": {
                        "value": "",
                        "regex": "^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"
                    }
                }
            }
        ]
        
        if error_message:
            settings.insert(0, {
                "id": "error_info",
                "label": {"en": "Error"},
                "field": {
                    "label": {
                        "value": {"en": f"Warning: {error_message}"}
                    }
                }
            })
        
        settings.append({
            "id": "instructions",
            "label": {"en": "Setup Instructions"},
            "field": {
                "label": {
                    "value": {
                        "en": "1. Go to: https://account.smartthings.com/tokens\n"
                             "2. Click 'Generate new token'\n"
                             "3. Enter a name: 'UC Remote Integration'\n"
                             "4. Select these permissions:\n"
                             "   - Devices: List, See, Control all devices\n"
                             "   - Locations: See all locations\n"
                             "   - Apps: List, See, Manage all apps\n"
                             "   - Scenes: List, See, Control all scenes\n"
                             "5. Click 'Generate token'\n"
                             "6. Copy the token and paste it above"
                    }
                }
            }
        })
        
        return RequestUserInput(
            title={"en": "SmartThings Access Token"},
            settings=settings
        )

    def _request_location_selection(self, locations: List[Dict[str, Any]]) -> RequestUserInput:
        """Request user to select SmartThings location."""
        location_options = []
        for location in locations:
            location_options.append({
                "id": location["locationId"],
                "label": location["name"]
            })
        
        return RequestUserInput(
            title={"en": "Select SmartThings Location"},
            settings=[
                {
                    "id": "location_id",
                    "label": {"en": "Location"},
                    "field": {
                        "dropdown": {
                            "value": self.setup_state.get("location_id", ""),
                            "items": location_options
                        }
                    }
                }
            ]
        )

    async def _discover_and_configure_devices(self, client: SmartThingsClient) -> RequestUserInput:
        location_id = self.setup_state["location_id"]
        
        _LOG.info(f"Discovering devices in location: {self.setup_state.get('location_name', location_id)}")
        
        devices_raw = await client.get_devices(location_id)
        self.discovered_devices = devices_raw
        
        device_categories = self._categorize_devices_improved(devices_raw)
        
        settings = []
        
        settings.append({
            "id": "location_info",
            "label": {"en": "Selected Location"},
            "field": {
                "label": {
                    "value": {"en": f"Location: {self.setup_state.get('location_name', 'Unknown Location')}\nDevices Found: {len(devices_raw)}"}
                }
            }
        })
        
        for category, info in device_categories.items():
            if info["count"] > 0:
                default_selected = category in ["light", "switch", "climate", "cover", "media_player"]
                
                settings.append({
                    "id": f"include_{category}s",
                    "label": {"en": f"{info['display_name']} ({info['count']} devices)"},
                    "field": {
                        "checkbox": {
                            "value": self.setup_state.get(f"include_{category}s", default_selected)
                        }
                    }
                })
                
                if info["examples"]:
                    examples_text = "Examples: " + ", ".join(info["examples"][:3])
                    if len(info["examples"]) > 3:
                        examples_text += f" and {len(info['examples']) - 3} more"
                    
                    settings.append({
                        "id": f"{category}_examples",
                        "label": {"en": " "},
                        "field": {
                            "label": {
                                "value": {"en": f"   - {examples_text}"}
                            }
                        }
                    })
        
        recommended_polling = get_recommended_polling_settings(len(devices_raw))
        
        settings.extend([
            {
                "id": "polling_section",
                "label": {"en": "Smart Polling Settings"},
                "field": {
                    "label": {
                        "value": {"en": "Configure how often device states are checked"}
                    }
                }
            },
            {
                "id": "polling_interval",
                "label": {"en": "Base Polling Interval (seconds)"},
                "field": {
                    "number": {
                        "value": self.setup_state.get("polling_interval", recommended_polling["polling_interval"]),
                        "min": 3,
                        "max": 60,
                        "steps": 1
                    }
                }
            }
        ])
        
        return RequestUserInput(
            title={"en": "Configure SmartThings Devices"},
            settings=settings
        )

    def _categorize_devices_improved(self, devices_raw: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        categories = {
            "light": {"count": 0, "examples": [], "display_name": "Lights"},
            "switch": {"count": 0, "examples": [], "display_name": "Switches"}, 
            "sensor": {"count": 0, "examples": [], "display_name": "Sensors"},
            "climate": {"count": 0, "examples": [], "display_name": "Climate"},
            "cover": {"count": 0, "examples": [], "display_name": "Covers & Doors"},
            "media_player": {"count": 0, "examples": [], "display_name": "Media Players"},
            "button": {"count": 0, "examples": [], "display_name": "Buttons"},
        }
        
        for device_data in devices_raw:
            try:
                device_name = device_data.get("label") or device_data.get("name") or "Unknown Device"
                device_type = device_data.get("deviceTypeName", "")
                
                capabilities = set()
                components = device_data.get("components", [])
                for component in components:
                    caps = component.get("capabilities", [])
                    for cap in caps:
                        cap_id = cap.get("id", "")
                        if cap_id:
                            capabilities.add(cap_id)
                
                _LOG.debug(f"Processing device: {device_name}")
                _LOG.debug(f"  Raw capabilities: {capabilities}")
                _LOG.debug(f"  Device type: {device_type}")
                
                entity_type = DeviceAnalyzer.determine_entity_type(capabilities, device_name, device_type)
                
                if entity_type and entity_type in categories:
                    categories[entity_type]["count"] += 1
                    
                    if len(categories[entity_type]["examples"]) < 5:
                        categories[entity_type]["examples"].append(device_name)
                    
                    _LOG.info(f"Categorized: {device_name} -> {entity_type}")
                else:
                    _LOG.warning(f"Could not categorize device: {device_name} (capabilities: {capabilities})")
                        
            except Exception as e:
                device_name = device_data.get("label", "Unknown")
                _LOG.error(f"Error categorizing device {device_name}: {e}", exc_info=True)
        
        _LOG.info(f"Device categorization summary: "
                 f"Lights={categories['light']['count']}, "
                 f"Switches={categories['switch']['count']}, "
                 f"Sensors={categories['sensor']['count']}, "
                 f"Media Players={categories['media_player']['count']}, "
                 f"Climate={categories['climate']['count']}, "
                 f"Covers={categories['cover']['count']}, "
                 f"Buttons={categories['button']['count']}")
        
        return categories

    async def _handle_user_data_response(self, input_values: Dict[str, Any]) -> Any:
        _LOG.debug(f"Processing user data response: {list(input_values.keys())}")
        
        self.setup_state.update(input_values)
        
        if "token" in input_values:
            token = input_values["token"]
            if not validate_smartthings_token(token):
                return self._request_access_token(
                    error_message="Invalid token format. Please check your Personal Access Token."
                )
            
            self.setup_state["access_token"] = token
            
            try:
                # Create and store client for cleanup
                self.client_session = SmartThingsClient(token)
                async with self.client_session:
                    locations = await self.client_session.get_locations()
                    if not locations:
                        return SetupError(IntegrationSetupError.NOT_FOUND)
                    
                    self.setup_state["locations"] = locations
                    
                    if len(locations) == 1:
                        location = locations[0]
                        self.setup_state["location_id"] = location["locationId"]
                        self.setup_state["location_name"] = location["name"]
                        return await self._discover_and_configure_devices(self.client_session)
                    else:
                        return self._request_location_selection(locations)
                        
            except SmartThingsAPIError as e:
                if e.status_code == 401:
                    return self._request_access_token(
                        error_message="Invalid or expired token. Please generate a new one."
                    )
                else:
                    return SetupError(IntegrationSetupError.OTHER)
        
        if "location_id" in input_values:
            location_id = input_values["location_id"]
            
            locations = self.setup_state.get("locations", [])
            for location in locations:
                if location["locationId"] == location_id:
                    self.setup_state["location_name"] = location["name"]
                    break
            
            try:
                token = self.setup_state["access_token"]
                if not self.client_session:
                    self.client_session = SmartThingsClient(token)
                async with self.client_session:
                    return await self._discover_and_configure_devices(self.client_session)
            except Exception as e:
                _LOG.error(f"Error discovering devices: {e}")
                return SetupError(IntegrationSetupError.OTHER)
        
        if any(key.startswith("include_") or key == "polling_interval" for key in input_values.keys()):
            return await self._finalize_setup()
        
        _LOG.warning("Unexpected user data response state - no matching input pattern")
        _LOG.warning(f"Input keys: {list(input_values.keys())}")
        _LOG.warning(f"Setup state keys: {list(self.setup_state.keys())}")
        return SetupError(IntegrationSetupError.OTHER)

    async def _handle_user_confirmation(self, confirm: bool) -> Any:
        if confirm:
            return await self._finalize_setup()
        else:
            _LOG.info("User cancelled setup")
            return SetupError(IntegrationSetupError.OTHER)

    async def _finalize_setup(self) -> Any:
        """Finalize setup with enhanced configuration validation."""
        _LOG.info("Finalizing SmartThings integration setup")
        
        try:
            final_config = {
                "access_token": self.setup_state.get("access_token"),
                "location_id": self.setup_state.get("location_id"),
                "location_name": self.setup_state.get("location_name"),
                
                "include_lights": self.setup_state.get("include_lights", True),
                "include_switches": self.setup_state.get("include_switches", True),
                "include_sensors": self.setup_state.get("include_sensors", False),
                "include_climate": self.setup_state.get("include_climate", True),
                "include_covers": self.setup_state.get("include_covers", True),
                "include_media_players": self.setup_state.get("include_media_players", True),
                "include_buttons": self.setup_state.get("include_buttons", True),
                
                "polling_interval": int(self.setup_state.get("polling_interval", 8)),
                
                "enable_optimistic_updates": True,
                "max_concurrent_requests": 5,
                "cache_ttl_seconds": 30,
                "command_verification_delay": 1.5,
            }
            
            device_count = len(self.discovered_devices)
            recommended_settings = get_recommended_polling_settings(device_count)
            final_config.update(recommended_settings)
            
            if self.config_manager.save_config(final_config):
                _LOG.info(f"Configuration saved successfully for {device_count} devices")
                
                summary = self._create_setup_summary(final_config, device_count)
                _LOG.info(f"Setup Summary: {summary}")
                
                return SetupComplete()
            else:
                _LOG.error("Failed to save configuration")
                return SetupError(IntegrationSetupError.OTHER)
                
        except Exception as e:
            _LOG.error(f"Error during setup finalization: {e}", exc_info=True)
            return SetupError(IntegrationSetupError.OTHER)

    def _create_setup_summary(self, config: Dict[str, Any], device_count: int) -> Dict[str, Any]:
        """Create a setup summary for logging and diagnostics."""
        enabled_types = []
        for entity_type in ["lights", "switches", "sensors", "climate", "covers", "media_players", "buttons"]:
            if config.get(f"include_{entity_type}", False):
                enabled_types.append(entity_type)
        
        return {
            "location": config.get("location_name", "Unknown"),
            "total_devices": device_count,
            "enabled_entity_types": enabled_types,
            "polling_interval": config.get("polling_interval"),
            "optimistic_updates": config.get("enable_optimistic_updates"),
        }

    async def _test_configuration(self, config: Dict[str, Any]) -> bool:
        """Test the configuration before finalizing setup."""
        try:
            token = config.get("access_token")
            location_id = config.get("location_id")
            
            if not token or not location_id:
                return False
            
            test_client = SmartThingsClient(token)
            async with test_client:
                devices = await test_client.get_devices(location_id)
                _LOG.debug(f"Configuration test successful: {len(devices)} devices accessible")
                return True
                
        except Exception as e:
            _LOG.error(f"Configuration test failed: {e}")
            return False

    def get_setup_progress(self) -> Dict[str, Any]:
        """Get current setup progress for diagnostics."""
        progress = {
            "step": "not_started",
            "has_token": bool(self.setup_state.get("access_token")),
            "has_location": bool(self.setup_state.get("location_id")),
            "devices_discovered": len(self.discovered_devices),
        }
        
        if progress["has_token"] and progress["has_location"]:
            progress["step"] = "device_configuration"
        elif progress["has_token"]:
            progress["step"] = "location_selection"
        elif self.setup_state:
            progress["step"] = "token_entry"
        
        return progress