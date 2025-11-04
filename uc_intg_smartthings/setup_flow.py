"""
:copyright: (c) 2025 by Meir Miyara
:license: MPL-2.0, see LICENSE for more details
"""

import logging
from typing import Any, Dict, List, Optional
import asyncio
import webbrowser
import urllib.parse

from ucapi.api_definitions import (
    SetupDriver, DriverSetupRequest, UserDataResponse, UserConfirmationResponse,
    RequestUserInput, RequestUserConfirmation, SetupComplete, SetupError, 
    IntegrationSetupError
)

from uc_intg_smartthings.client import SmartThingsClient, SmartThingsDevice, SmartThingsAPIError, SmartThingsOAuth2Error, OAuth2TokenData
from uc_intg_smartthings.config import ConfigManager, get_recommended_polling_settings

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
        
        if "button" in capabilities or "momentary" in capabilities:
            return "button"
        
        climate_caps = {"thermostat", "thermostatCoolingSetpoint", "thermostatHeatingSetpoint", "airConditioner"}
        if climate_caps.intersection(capabilities):
            return "climate"
        
        media_caps = {"mediaPlayback", "audioVolume", "tvChannel", "mediaTrackControl", "speechSynthesis"}
        media_keywords = ["tv", "television", "soundbar", "speaker", "audio", "receiver", "stereo", "music"]
        
        if (media_caps.intersection(capabilities) or 
            any(keyword in device_name_lower for keyword in media_keywords) or
            any(keyword in device_type_lower for keyword in media_keywords)):
            return "media_player"
        
        cover_caps = {"doorControl", "windowShade", "garageDoorControl"}
        if cover_caps.intersection(capabilities):
            return "cover"
        
        light_caps = {"switchLevel", "colorControl", "colorTemperature"}
        if light_caps.intersection(capabilities):
            excluded_caps = {
                "lock", "doorControl", "windowShade", "garageDoorControl",
                "thermostat", "mediaPlayback", "audioVolume", "speechSynthesis",
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
            "soundSensor", "dustSensor", "airQualitySensor"
        }
        
        if sensor_caps.intersection(capabilities):
            return "sensor"
        
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
        samsung_tv_indicators = [
            "samsung" and "tv" in device_name,
            "samsung" and any(model in device_name for model in ["au5000", "q70", "qled", "neo"]),
            "tv" in device_type,
            "television" in device_type,
            {"switch", "audioVolume"}.issubset(capabilities),
            {"switch", "speechSynthesis"}.issubset(capabilities),
        ]
        
        return any(samsung_tv_indicators)

    @staticmethod
    def _is_samsung_soundbar(device_name: str, device_type: str, capabilities: set) -> bool:
        samsung_soundbar_indicators = [
            "samsung" and "soundbar" in device_name,
            "samsung" and "q70t" in device_name,
            "samsung" and "q90r" in device_name,
            "samsung" and "q950t" in device_name,
            "soundbar" in device_name,
            "soundbar" in device_type,
            "speaker" in device_type and "samsung" in device_name,
            "network audio" in device_type,
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
        self.client_session = None
        
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
            await self._cleanup_client()

    async def _cleanup_client(self):
        if self.client_session:
            try:
                await self.client_session.close()
                self.client_session = None
                _LOG.debug("Setup client session cleaned up")
            except Exception as e:
                _LOG.warning(f"Error cleaning up setup client: {e}")

    async def _handle_initial_setup(self, setup_data: Dict[str, Any], reconfigure: bool = False) -> Any:
        _LOG.info(f"Starting SmartThings OAuth2 setup using WORKING method (reconfigure={reconfigure})")
        
        if reconfigure:
            self.setup_state = self.config_manager.load_config()
            _LOG.debug("Loaded existing configuration for reconfigure")
        
        self.setup_state["redirect_uri"] = "https://httpbin.org/get"
        
        if not setup_data.get("client_id") or not setup_data.get("client_secret"):
            return self._request_client_credentials()
        
        self.setup_state["client_id"] = setup_data["client_id"].strip()
        self.setup_state["client_secret"] = setup_data["client_secret"].strip()
        
        if not setup_data.get("authorization_code"):
            return self._request_authorization_code()
        
        try:
            _LOG.info("Exchanging authorization code for tokens")
            self.client_session = SmartThingsClient(
                client_id=self.setup_state["client_id"],
                client_secret=self.setup_state["client_secret"]
            )
            
            oauth_tokens = await self.client_session.exchange_code_for_tokens(
                setup_data["authorization_code"].strip(),
                self.setup_state["redirect_uri"]
            )
            
            self.setup_state["oauth2_tokens"] = oauth_tokens.to_dict()
            
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
                    
        except SmartThingsOAuth2Error as e:
            _LOG.error(f"OAuth2 setup failed: {e}")
            return SetupError(IntegrationSetupError.AUTHORIZATION_ERROR)
        except Exception as e:
            _LOG.error(f"Unexpected error during OAuth2 setup: {e}", exc_info=True)
            return SetupError(IntegrationSetupError.OTHER)

    def _request_client_credentials(self) -> RequestUserInput:
        return RequestUserInput(
            title={"en": "SmartThings SmartApp Credentials"},
            settings=[
                {
                    "id": "client_id",
                    "label": {"en": "Client ID"},
                    "field": {
                        "text": {
                            "value": self.setup_state.get("client_id", "")
                        }
                    }
                },
                {
                    "id": "client_secret",
                    "label": {"en": "Client Secret"},
                    "field": {
                        "text": {
                            "value": self.setup_state.get("client_secret", "")
                        }
                    }
                },
                {
                    "id": "credentials_help",
                    "label": {"en": "Use your WORKING SmartApp:"},
                    "field": {
                        "label": {
                            "value": {
                                "en": "Client ID: 2cf82914-6990-48a7-8ef8-4ecf2b0f49d2\nClient Secret: d3f4a18f-c92f-4b74-b326-60d83626cb83\n\n✅ This SmartApp uses https://httpbin.org/get\n✅ OAuth flow confirmed working\n\nCopy and paste these values above, then click 'Next'"
                            }
                        }
                    }
                }
            ]
        )

    def _request_authorization_code(self) -> RequestUserInput:
        try:
            client = SmartThingsClient(
                client_id=self.setup_state["client_id"],
                client_secret=self.setup_state["client_secret"]
            )
            
            redirect_uri = self.setup_state["redirect_uri"]
            auth_url = client.generate_auth_url(redirect_uri, state="uc-integration")
            
            try:
                webbrowser.open(auth_url)
                _LOG.info("Opened browser for SmartThings authorization")
            except Exception as e:
                _LOG.warning(f"Could not open browser: {e}")
            
            return RequestUserInput(
                title={"en": "SmartThings Authorization ✅"},
                settings=[
                    {
                        "id": "auth_instructions",
                        "label": {"en": "Authorization Steps:"},
                        "field": {
                            "label": {
                                "value": {
                                    "en": f"1. Click this link to authorize:\n{auth_url}\n\n2. Log in to SmartThings\n3. Authorize the integration\n4. You'll be redirected to httpbin.org/get\n5. Look for 'code=' in the URL or JSON response\n6. Copy ONLY the code value and paste it below\n\n✅ Using proven working method"
                                }
                            }
                        }
                    },
                    {
                        "id": "authorization_code",
                        "label": {"en": "Authorization Code"},
                        "field": {
                            "text": {
                                "value": ""
                            }
                        }
                    },
                    {
                        "id": "code_help",
                        "label": {"en": "Help:"},
                        "field": {
                            "label": {
                                "value": {
                                    "en": "After authorization, you'll see the httpbin.org page.\nLook for 'code=XXXXXXX' in the URL or in the JSON args.\nCopy just the code value (not 'code=').\n\nExample: If you see 'code=ABC123', copy 'ABC123'"
                                }
                            }
                        }
                    }
                ]
            )
            
        except Exception as e:
            _LOG.error(f"Error generating authorization URL: {e}")
            return SetupError(IntegrationSetupError.OTHER)

    def _request_location_selection(self, locations: List[Dict[str, Any]]) -> RequestUserInput:
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
            "label": {"en": "✅ OAuth Success!"},
            "field": {
                "label": {
                    "value": {"en": f"Location: {self.setup_state.get('location_name', 'Unknown Location')}\nDevices Found: {len(devices_raw)}\n✅ SmartThings OAuth2 authentication successful!"}
                }
            }
        })
        
        for category, info in device_categories.items():
            if info["count"] > 0:
                default_selected = category in ["light", "switch", "climate", "cover", "media_player", "button"]
                
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
        
        return categories

    async def _handle_user_data_response(self, input_values: Dict[str, Any]) -> Any:
        _LOG.debug(f"Processing user data response: {list(input_values.keys())}")
        
        if "redirect_uri" not in self.setup_state:
            self.setup_state["redirect_uri"] = "https://httpbin.org/get"
        
        self.setup_state.update(input_values)
        
        if ("client_id" in input_values and "client_secret" in input_values and 
            "authorization_code" not in self.setup_state):
            
            if not input_values["client_id"].strip() or not input_values["client_secret"].strip():
                _LOG.error("Client ID and Client Secret are required")
                return self._request_client_credentials()
            
            _LOG.info("Step 1: Client credentials received, requesting authorization code")
            return self._request_authorization_code()
        
        if ("authorization_code" in input_values and
            "client_id" in self.setup_state and "client_secret" in self.setup_state and
            "oauth2_tokens" not in self.setup_state):
            
            if not input_values["authorization_code"].strip():
                _LOG.error("Authorization code is required")
                return self._request_authorization_code()
            
            _LOG.info("Step 2: Authorization code received, exchanging for tokens")
            
            try:
                self.client_session = SmartThingsClient(
                    client_id=self.setup_state["client_id"],
                    client_secret=self.setup_state["client_secret"]
                )
                
                oauth_tokens = await self.client_session.exchange_code_for_tokens(
                    input_values["authorization_code"].strip(),
                    self.setup_state["redirect_uri"]
                )
                
                self.setup_state["oauth2_tokens"] = oauth_tokens.to_dict()
                
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
                        
            except SmartThingsOAuth2Error as e:
                _LOG.error(f"OAuth2 token exchange failed: {e}")
                return SetupError(IntegrationSetupError.AUTHORIZATION_ERROR)
            except Exception as e:
                _LOG.error(f"Error during token exchange: {e}", exc_info=True)
                return SetupError(IntegrationSetupError.OTHER)
        
        if ("location_id" in input_values and 
            "oauth2_tokens" in self.setup_state):
            
            location_id = input_values["location_id"]
            
            locations = self.setup_state.get("locations", [])
            for location in locations:
                if location["locationId"] == location_id:
                    self.setup_state["location_name"] = location["name"]
                    break
            
            try:
                if not self.client_session:
                    oauth2_tokens = self.setup_state.get("oauth2_tokens")
                    if oauth2_tokens:
                        tokens = OAuth2TokenData.from_dict(oauth2_tokens)
                        self.client_session = SmartThingsClient(
                            client_id=self.setup_state["client_id"],
                            client_secret=self.setup_state["client_secret"],
                            oauth_tokens=tokens
                        )
                
                return await self._discover_and_configure_devices(self.client_session)
            except Exception as e:
                _LOG.error(f"Error discovering devices: {e}")
                return SetupError(IntegrationSetupError.OTHER)
        
        if (any(key.startswith("include_") or key == "polling_interval" for key in input_values.keys()) and
            "oauth2_tokens" in self.setup_state):
            _LOG.info("Step 4: Device configuration received, finalizing setup")
            return await self._finalize_setup()
        
        _LOG.warning(f"Unexpected user data response state. Setup state keys: {list(self.setup_state.keys())}")
        _LOG.warning(f"Input values keys: {list(input_values.keys())}")
        return SetupError(IntegrationSetupError.OTHER)

    async def _handle_user_confirmation(self, confirm: bool) -> Any:
        if confirm:
            return await self._finalize_setup()
        else:
            _LOG.info("User cancelled setup")
            return SetupError(IntegrationSetupError.OTHER)

    async def _finalize_setup(self) -> Any:
        _LOG.info("Finalizing SmartThings OAuth2 integration setup")
        
        try:
            final_config = {
                "client_id": self.setup_state.get("client_id"),
                "client_secret": self.setup_state.get("client_secret"),
                "redirect_uri": self.setup_state.get("redirect_uri"),
                "oauth2_tokens": self.setup_state.get("oauth2_tokens"),
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
                _LOG.info(f"OAuth2 configuration saved successfully for {device_count} devices")
                
                summary = self._create_setup_summary(final_config, device_count)
                _LOG.info(f"Setup Summary: {summary}")
                
                return SetupComplete()
            else:
                _LOG.error("Failed to save OAuth2 configuration")
                return SetupError(IntegrationSetupError.OTHER)
                
        except Exception as e:
            _LOG.error(f"Error during OAuth2 setup finalization: {e}", exc_info=True)
            return SetupError(IntegrationSetupError.OTHER)

    def _create_setup_summary(self, config: Dict[str, Any], device_count: int) -> Dict[str, Any]:
        enabled_types = []
        for entity_type in ["lights", "switches", "sensors", "climate", "covers", "media_players", "buttons"]:
            if config.get(f"include_{entity_type}", False):
                enabled_types.append(entity_type)
        
        return {
            "location": config.get("location_name", "Unknown"),
            "total_devices": device_count,
            "enabled_entity_types": enabled_types,
            "polling_interval": config.get("polling_interval"),
            "auth_method": "oauth2_httpbin_working",
        }