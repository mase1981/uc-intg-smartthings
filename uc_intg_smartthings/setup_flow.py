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

from client import SmartThingsClient, SmartThingsAPIError, SmartThingsDevice
from config import ConfigManager, validate_smartthings_token, get_recommended_polling_settings

_LOG = logging.getLogger(__name__)

class DeviceAnalyzer:
    
    @staticmethod
    def determine_entity_type(capabilities: set, device_name: str) -> Optional[str]:
        device_name_lower = device_name.lower()
        
        light_caps = {"switchLevel", "colorControl", "colorTemperature"}
        if light_caps.intersection(capabilities):
            excluded_caps = {
                "lock", "doorControl", "windowShade", "garageDoorControl",
                "thermostat", "mediaPlayback", "audioVolume",
                "dryerOperatingState", "washerOperatingState", "ovenOperatingState"
            }
            if not excluded_caps.intersection(capabilities):
                return "light"
        
        if "switch" in capabilities and any(word in device_name_lower for word in ["light", "lamp", "bulb", "led"]):
            return "light"
        
        sensor_caps = {
            "lock", "contactSensor", "motionSensor", "presenceSensor", 
            "temperatureMeasurement", "relativeHumidityMeasurement",
            "battery", "powerMeter", "energyMeter", "illuminanceMeasurement",
            "accelerationSensor", "threeAxis", "ultravioletIndex",
            "carbonMonoxideDetector", "smokeDetector", "waterSensor",
            "button"
        }
        
        if sensor_caps.intersection(capabilities):
            return "sensor"
        
        if "switch" in capabilities:
            excluded_caps = {
                "switchLevel", "colorControl", "colorTemperature",
                "doorControl", "windowShade", "garageDoorControl",  
                "thermostat", "thermostatCoolingSetpoint", "thermostatHeatingSetpoint",
                "mediaPlayback", "audioVolume"
            }
            
            if not excluded_caps.intersection(capabilities):
                return "switch"
        
        return None

class SmartThingsSetupFlow:
    
    def __init__(self, api, config_manager: ConfigManager):
        self.api = api
        self.config_manager = config_manager
        self.setup_state = {}
        self.discovered_devices = []
        
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
            async with SmartThingsClient(token) as client:
                locations = await client.get_locations()
                
                if not locations:
                    _LOG.error("No SmartThings locations found")
                    return SetupError(IntegrationSetupError.NOT_FOUND)
                
                self.setup_state["locations"] = locations
                _LOG.info(f"Found {len(locations)} SmartThings locations")
                
                if len(locations) == 1:
                    location = locations[0]
                    self.setup_state["location_id"] = location["locationId"]
                    self.setup_state["location_name"] = location["name"]
                    return await self._discover_and_configure_devices(client)
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
        
        device_categories = self._categorize_devices_corrected(devices_raw)
        
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

    def _categorize_devices_corrected(self, devices_raw: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        categories = {
            "light": {"count": 0, "examples": [], "display_name": "Lights"},
            "switch": {"count": 0, "examples": [], "display_name": "Switches"}, 
            "sensor": {"count": 0, "examples": [], "display_name": "Sensors"},
            "climate": {"count": 0, "examples": [], "display_name": "Climate"},
            "cover": {"count": 0, "examples": [], "display_name": "Covers & Doors"},
            "media_player": {"count": 0, "examples": [], "display_name": "Media Players"},
        }
        
        for device_data in devices_raw:
            try:
                device_name = device_data.get("label") or device_data.get("name") or "Unknown Device"
                
                capabilities = set()
                components = device_data.get("components", [])
                for component in components:
                    caps = component.get("capabilities", [])
                    for cap in caps:
                        cap_id = cap.get("id", "")
                        if cap_id:
                            capabilities.add(cap_id)
                
                entity_type = DeviceAnalyzer.determine_entity_type(capabilities, device_name)
                
                if entity_type and entity_type in categories:
                    categories[entity_type]["count"] += 1
                    
                    if len(categories[entity_type]["examples"]) < 5:
                        categories[entity_type]["examples"].append(device_name)
                
                _LOG.debug(f"Device: {device_name}, Capabilities: {capabilities}, Type: {entity_type}")
                        
            except Exception as e:
                device_name = device_data.get("label", "Unknown")
                _LOG.warning(f"Error categorizing device {device_name}: {e}")
        
        _LOG.info(f"Device categorization summary: Lights={categories['light']['count']}, Switches={categories['switch']['count']}, Sensors={categories['sensor']['count']}")
        
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
                async with SmartThingsClient(token) as client:
                    locations = await client.get_locations()
                    if not locations:
                        return SetupError(IntegrationSetupError.NOT_FOUND)
                    
                    self.setup_state["locations"] = locations
                    
                    if len(locations) == 1:
                        location = locations[0]
                        self.setup_state["location_id"] = location["locationId"]
                        self.setup_state["location_name"] = location["name"]
                        return await self._discover_and_configure_devices(client)
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
                async with SmartThingsClient(token) as client:
                    return await self._discover_and_configure_devices(client)
            except Exception as e:
                _LOG.error(f"Error discovering devices: {e}")
                return SetupError(IntegrationSetupError.OTHER)
        
        if any(key.startswith("include_") for key in input_values.keys()):
            return await self._finalize_setup()
        
        _LOG.warning("Unexpected user data response state")
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
        for entity_type in ["lights", "switches", "sensors", "climate", "covers", "media_players"]:
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
            
            async with SmartThingsClient(token) as client:
                devices = await client.get_devices(location_id)
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