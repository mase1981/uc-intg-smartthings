"""
:copyright: (c) 2025 by Meir Miyara
:license: MPL-2.0, see LICENSE for more details
"""

import asyncio
import json
import logging
import ssl
import time
import webbrowser
import urllib.parse
import base64
from typing import Any, Dict, List, Optional, Set, Tuple
import aiohttp
import certifi
from pydantic import BaseModel, Field

_LOG = logging.getLogger(__name__)


class SmartThingsAPIError(Exception):
    """Custom exception for API errors."""
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class SmartThingsOAuth2Error(Exception):
    """Custom exception for OAuth2 errors."""
    def __init__(self, message, error_code=None):
        super().__init__(message)
        self.error_code = error_code


class SmartThingsDevice(BaseModel):
    id: str = Field(..., alias='deviceId')
    label: Optional[str] = None
    name: Optional[str] = None
    type: str = Field("Unknown", alias='deviceTypeName')
    room_id: Optional[str] = Field(None, alias='roomId')
    location_id: str = Field(..., alias='locationId')
    capabilities: Set[str] = Field(default_factory=set)
    raw_capabilities: Dict[str, Any] = Field(default_factory=dict)
    is_online: bool = Field(True, alias='status')

    class Config:
        extra = 'ignore'
        
    def __init__(self, **data: Any):
        status = data.get('status', {})
        data['status'] = status.get('state') == 'ONLINE'
        
        components = data.get('components', [])
        caps = set()
        raw_caps = {}
        
        if components and 'capabilities' in components[0]:
            for cap in components[0]['capabilities']:
                cap_id = cap.get('id', '')
                if cap_id:
                    caps.add(cap_id)
                    raw_caps[cap_id] = cap
                    
        data['capabilities'] = caps
        data['raw_capabilities'] = raw_caps
        
        super().__init__(**data)


class HomeAssistantCapabilityMapping:
    
    CAPABILITY_TO_ENTITY = {
        frozenset(["switch", "switchLevel"]): "light",
        frozenset(["switch", "colorControl"]): "light",
        frozenset(["switch", "colorTemperature"]): "light",
        frozenset(["switch", "switchLevel", "colorControl"]): "light",
        frozenset(["switch", "switchLevel", "colorTemperature"]): "light",
        frozenset(["switch", "switchLevel", "colorControl", "colorTemperature"]): "light",
        
        frozenset(["switch"]): "switch",
        
        frozenset(["doorControl"]): "cover",
        frozenset(["windowShade"]): "cover",
        frozenset(["garageDoorControl"]): "cover",
        frozenset(["windowShade", "windowShadeLevel"]): "cover",
        
        frozenset(["thermostat"]): "climate",
        frozenset(["airConditioner"]): "climate",
        frozenset(["thermostatCoolingSetpoint", "thermostatHeatingSetpoint"]): "climate",
        
        frozenset(["audioVolume", "mediaPlayback"]): "media_player",
        frozenset(["switch", "audioVolume"]): "media_player", 
        frozenset(["audioVolume"]): "media_player",
        
        frozenset(["temperatureMeasurement"]): "sensor",
        frozenset(["relativeHumidityMeasurement"]): "sensor",
        frozenset(["battery"]): "sensor",
        frozenset(["powerMeter"]): "sensor", 
        frozenset(["energyMeter"]): "sensor",
        frozenset(["illuminanceMeasurement"]): "sensor",
        frozenset(["contactSensor"]): "sensor",
        frozenset(["motionSensor"]): "sensor",
        
        frozenset(["lock"]): "sensor",
        
        frozenset(["button"]): "button",
        frozenset(["momentary"]): "button",
    }
    
    EXCLUSION_RULES = {
        "light": ["ovenOperatingState", "dishwasherOperatingState", "dryerOperatingState", "washerOperatingState"],
        "switch": ["lock", "contactSensor", "motionSensor", "temperatureMeasurement", "doorControl", "windowShade"],
        "sensor": [],
    }
    
    @classmethod
    def determine_entity_type(cls, device_capabilities: Set[str]) -> Optional[str]:
        capabilities_frozen = frozenset(device_capabilities)
        
        if capabilities_frozen in cls.CAPABILITY_TO_ENTITY:
            entity_type = cls.CAPABILITY_TO_ENTITY[capabilities_frozen] 
            
            if entity_type in cls.EXCLUSION_RULES:
                excluded_caps = cls.EXCLUSION_RULES[entity_type]
                if any(cap in device_capabilities for cap in excluded_caps):
                    return None
                    
            return entity_type
        
        best_match = None
        best_match_size = 0
        
        for capability_set, entity_type in cls.CAPABILITY_TO_ENTITY.items():
            if capability_set.issubset(capabilities_frozen):
                if entity_type in cls.EXCLUSION_RULES:
                    excluded_caps = cls.EXCLUSION_RULES[entity_type]
                    if any(cap in device_capabilities for cap in excluded_caps):
                        continue
                
                if len(capability_set) > best_match_size:
                    best_match = entity_type
                    best_match_size = len(capability_set)
        
        return best_match


class OAuth2TokenData:
    """OAuth2 token management - FIXED"""
    def __init__(self, access_token: str, refresh_token: str, expires_in: int, token_type: str = "Bearer"):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = time.time() + expires_in
        self.token_type = token_type
        
        _LOG.info(f"New OAuth2 token created: expires_in={expires_in}s, type={token_type}")
    
    @property
    def is_expired(self) -> bool:
        remaining = self.expires_at - time.time()
        is_expired = remaining < 300  # 5 minute buffer
        
        if remaining > 0:
            _LOG.debug(f"Token expires in {remaining:.0f} seconds")
        
        return is_expired
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "token_type": self.token_type
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'OAuth2TokenData':
        instance = cls.__new__(cls)
        instance.access_token = data["access_token"]
        instance.refresh_token = data["refresh_token"]
        instance.expires_at = data["expires_at"]
        instance.token_type = data.get("token_type", "Bearer")
        return instance


class SmartThingsClient:

    def __init__(self, client_id: Optional[str] = None, client_secret: Optional[str] = None, oauth_tokens: Optional[OAuth2TokenData] = None):
        self.base_url = "https://api.smartthings.com/v1"
        self.oauth_base_url = "https://api.smartthings.com/oauth"
        self.token_url = "https://api.smartthings.com/oauth/token"
        
        self._client_id = client_id
        self._client_secret = client_secret
        self._oauth_tokens = oauth_tokens
        self._session: Optional[aiohttp.ClientSession] = None
        
        self._device_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_timestamps: Dict[str, float] = {}
        self._cache_ttl = 30.0
        
        self._connection_pool_limit = 4
        self._request_timeout = 8
        self._max_retries = 0
        
        self._request_count = 0
        self._cache_hits = 0
        self._connection_errors = 0
        self._session_creation_lock = asyncio.Lock()
        
        # Rate limiting
        self._request_times = []
        self._rate_limit_window = 10
        self._max_requests_per_window = 8
        self._last_rate_limit = 0

    def _create_ssl_context(self) -> ssl.SSLContext:
        """Create SSL context with proper certificate verification for UC Remote."""
        try:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            ssl_context.check_hostname = True
            ssl_context.verify_mode = ssl.CERT_REQUIRED
            return ssl_context
        except Exception as e:
            _LOG.warning(f"Failed to create SSL context with certifi: {e}")
            return ssl.create_default_context()

    async def __aenter__(self):
        if not self._session or self._session.closed:
            async with self._session_creation_lock:
                if not self._session or self._session.closed:
                    await self._create_session()
        return self

    async def _create_session(self):
        """Create a new aiohttp session with optimized settings"""
        if self._session and not self._session.closed:
            await self._session.close()
            
        ssl_context = self._create_ssl_context()
        
        connector = aiohttp.TCPConnector(
            limit=self._connection_pool_limit,
            limit_per_host=3,
            ttl_dns_cache=600,
            use_dns_cache=True,
            keepalive_timeout=45,
            enable_cleanup_closed=True,
            ssl=ssl_context
        )
        
        timeout = aiohttp.ClientTimeout(
            total=self._request_timeout,
            connect=4,
            sock_read=6
        )
        
        self._session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={"User-Agent": "UC-SmartThings-Integration/2.0"}
        )
        
        _LOG.debug("Created new aiohttp session")

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            await asyncio.sleep(0.1)
            self._session = None
            _LOG.debug("SmartThings API session closed")

    async def _get_authorization_header(self) -> str:
        """Get authorization header, refreshing OAuth token if needed - FIXED"""
        if self._oauth_tokens:
            # Don't refresh immediately after getting a new token
            remaining_time = self._oauth_tokens.expires_at - time.time()
            
            if remaining_time < 300:  # Only refresh if less than 5 minutes left
                _LOG.info(f"OAuth token expires in {remaining_time:.0f}s, refreshing...")
                await self._refresh_oauth_token()
            else:
                _LOG.debug(f"OAuth token valid for {remaining_time:.0f}s")
            
            return f"Bearer {self._oauth_tokens.access_token}"
        else:
            raise SmartThingsAPIError("No authentication token available")

    async def _refresh_oauth_token(self):
        """Refresh OAuth2 access token using refresh token - FIXED with Basic Auth"""
        if not self._oauth_tokens or not self._oauth_tokens.refresh_token:
            raise SmartThingsAPIError("No refresh token available")
        
        if not self._client_id or not self._client_secret:
            raise SmartThingsAPIError("No client credentials available for token refresh")
        
        credentials = f"{self._client_id}:{self._client_secret}"
        credentials_b64 = base64.b64encode(credentials.encode()).decode()
        
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self._oauth_tokens.refresh_token
        }
        
        try:
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {credentials_b64}"
            }
            
            async with self._session.post(self.token_url, data=data, headers=headers) as response:
                if response.status == 200:
                    token_data = await response.json()
                    
                    self._oauth_tokens.access_token = token_data["access_token"]
                    if "refresh_token" in token_data:
                        self._oauth_tokens.refresh_token = token_data["refresh_token"]
                    self._oauth_tokens.expires_at = time.time() + token_data["expires_in"]
                    
                    _LOG.info("OAuth token refreshed successfully with Basic Auth")
                else:
                    error_text = await response.text()
                    _LOG.error(f"Token refresh failed: {response.status} - {error_text}")
                    raise SmartThingsAPIError(f"Token refresh failed: {response.status}")
                    
        except Exception as e:
            _LOG.error(f"Token refresh error: {e}")
            raise SmartThingsAPIError(f"Token refresh failed: {e}")

    async def _check_rate_limit(self):
        """Check if we're within rate limits, wait if necessary"""
        now = time.time()
        
        self._request_times = [t for t in self._request_times if now - t <= self._rate_limit_window]
        
        if len(self._request_times) >= self._max_requests_per_window:
            oldest_request = min(self._request_times)
            wait_time = self._rate_limit_window - (now - oldest_request) + 0.1
            
            if wait_time > 0:
                _LOG.info(f"Rate limit approaching, waiting {wait_time:.1f}s")
                await asyncio.sleep(wait_time)
        
        self._request_times.append(now)

    async def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make authenticated API request with enhanced error logging"""
        await self._check_rate_limit()
        
        if not self._session or self._session.closed:
            await self.__aenter__()

        headers = kwargs.pop("headers", {})
        auth_header = await self._get_authorization_header()
        headers.update({"Authorization": auth_header})
        
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        self._request_count += 1
        
        _LOG.debug(f"Making request: {method} {url}")
        _LOG.debug(f"Request headers: {headers}")
        
        try:
            async with self._session.request(method, url, headers=headers, **kwargs) as response:
                if response.status == 401:
                    if self._oauth_tokens:
                        _LOG.info("401 error, attempting token refresh...")
                        await self._refresh_oauth_token()
                        
                        auth_header = await self._get_authorization_header()
                        headers["Authorization"] = auth_header
                        
                        async with self._session.request(method, url, headers=headers, **kwargs) as retry_response:
                            if retry_response.status == 401:
                                raise SmartThingsAPIError("Authentication failed after token refresh", 401)
                            response = retry_response
                    else:
                        raise SmartThingsAPIError("Authentication failed", 401)
                
                if response.status == 429:
                    self._last_rate_limit = time.time()
                    error_text = await response.text()
                    _LOG.warning(f"Hit SmartThings rate limit: {error_text}")
                    raise SmartThingsAPIError(f"Rate limit exceeded", 429)
                
                if response.status >= 400:
                    error_text = await response.text()
                    
                    # Enhanced 403 error logging
                    if response.status == 403:
                        _LOG.error(f"403 FORBIDDEN ERROR for {method} {endpoint}")
                        _LOG.error(f"Response headers: {dict(response.headers)}")
                        _LOG.error(f"Response body: {error_text}")
                        _LOG.error(f"Request URL: {url}")
                        _LOG.error(f"Request headers used: {headers}")
                        
                        # Try to parse error details
                        try:
                            error_data = json.loads(error_text)
                            if 'error' in error_data:
                                _LOG.error(f"Error code: {error_data['error'].get('code', 'Unknown')}")
                                _LOG.error(f"Error message: {error_data['error'].get('message', 'Unknown')}")
                        except:
                            pass
                    
                    _LOG.error(f"SmartThings API Error {response.status}: {error_text}")
                    raise SmartThingsAPIError(
                        f"API request failed with status {response.status}: {error_text}", 
                        response.status
                    )
                
                result = await response.json() if response.content_type == 'application/json' else {}
                return result
                
        except aiohttp.ClientError as e:
            self._connection_errors += 1
            _LOG.warning(f"SmartThings HTTP Client Error: {e}")
            raise SmartThingsAPIError(f"Connection error: {e}")
        except asyncio.TimeoutError:
            _LOG.warning(f"SmartThings API Timeout")
            raise SmartThingsAPIError(f"Request timeout")

    def generate_auth_url(self, redirect_uri: str, state: str = None) -> str:
        if not self._client_id:
            raise SmartThingsOAuth2Error("No client ID available")
        
        scopes = [
            "r:devices:*",      # Read all devices
            "w:devices:*",      # Write all devices  
            "x:devices:*",      # Execute all devices
            "r:locations:*",    # Read locations (required for setup)
            "w:locations:*",    # Write locations
            "x:locations:*"     # Execute locations
        ]
        
        # Use space-separated format (OAuth2 standard)
        scope_string = " ".join(scopes)
        
        _LOG.info("=== CORRECTED SCOPE FORMAT ===")
        _LOG.info(f"Using wildcard-only scopes: '{scope_string}'")
        
        # Build URL with proper encoding
        params = {
            "client_id": self._client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": scope_string
        }
        
        if state:
            params["state"] = state
        
        # Use urllib.parse.urlencode for consistent encoding across environments
        query_string = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        auth_url = f"{self.oauth_base_url}/authorize?{query_string}"
        
        _LOG.info(f"Generated URL: '{auth_url}'")
        _LOG.info("=== END SCOPE CORRECTION ===")
        
        return auth_url

    async def exchange_code_for_tokens(self, authorization_code: str, redirect_uri: str) -> OAuth2TokenData:
        if not self._client_id or not self._client_secret:
            raise SmartThingsOAuth2Error("No client credentials available")
        
        _LOG.info(f"BASIC AUTH FIX: Starting token exchange")
        _LOG.info(f"   Client ID: {self._client_id}")
        _LOG.info(f"   Client Secret: {self._client_secret[:8]}...")
        _LOG.info(f"   Auth Code: {authorization_code}")
        _LOG.info(f"   Redirect URI: {redirect_uri}")
        _LOG.info(f"   Token URL: {self.token_url}")

        # Use Basic Authentication for client credentials
        credentials = f"{self._client_id}:{self._client_secret}"
        credentials_b64 = base64.b64encode(credentials.encode()).decode()
        
        _LOG.info(f"Basic Auth credentials: {credentials[:20]}...")
        _LOG.info(f"Basic Auth encoded: {credentials_b64[:20]}...")

        # Only include grant data, NOT client credentials in form
        data = {
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": redirect_uri
        }
        
        _LOG.info(f"Request data (without client creds): {data}")
        
        # Use Basic Auth header for client credentials
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {credentials_b64}"
        }
        
        _LOG.info(f"Request headers: {headers}")
        
        if not self._session:
            await self._create_session()
            _LOG.info("Created new aiohttp session")
        
        try:
            _LOG.info(f"Sending POST request to {self.token_url}")
            
            timeout = aiohttp.ClientTimeout(total=30)
            
            async with self._session.post(
                self.token_url, 
                data=data, 
                headers=headers, 
                timeout=timeout
            ) as response:
                
                _LOG.info(f"Response received:")
                _LOG.info(f"   Status: {response.status}")
                _LOG.info(f"   Reason: {response.reason}")
                _LOG.info(f"   Headers: {dict(response.headers)}")
                
                response_text = await response.text()
                _LOG.info(f"   Body: '{response_text}'")
                
                if response.status == 200:
                    try:
                        token_data = await response.json()
                        _LOG.info("SUCCESS! Token exchange worked with Basic Auth!")
                        _LOG.info(f"   Access Token: {token_data.get('access_token', 'N/A')[:20]}...")
                        _LOG.info(f"   Refresh Token: {token_data.get('refresh_token', 'N/A')[:20]}...")
                        _LOG.info(f"   Expires In: {token_data.get('expires_in', 'N/A')}")
                        _LOG.info(f"   Token Type: {token_data.get('token_type', 'N/A')}")
                        
                        # Handle token_type properly (SmartThings returns "bearer" lowercase)
                        token_type = token_data.get("token_type", "Bearer")
                        if token_type.lower() == "bearer":
                            token_type = "Bearer"  # Normalize to proper case
                        
                        oauth_tokens = OAuth2TokenData(
                            access_token=token_data["access_token"],
                            refresh_token=token_data["refresh_token"],
                            expires_in=token_data["expires_in"],
                            token_type=token_type
                        )
                        
                        self._oauth_tokens = oauth_tokens
                        _LOG.info("OAuth2 authentication completed successfully with Basic Auth")
                        return oauth_tokens
                        
                    except (KeyError, json.JSONDecodeError) as e:
                        _LOG.error(f"Failed to parse token response: {e}")
                        _LOG.error(f"Raw response: {response_text}")
                        raise SmartThingsOAuth2Error(f"Invalid token response: {e}")
                        
                elif response.status == 401:
                    _LOG.error(f"401 Unauthorized with Basic Auth")
                    _LOG.error(f"Response body: '{response_text}'")
                    
                    # Enhanced 401 error analysis
                    if "invalid_client" in response_text.lower():
                        _LOG.error("DIAGNOSIS: Invalid client credentials")
                    elif "invalid_grant" in response_text.lower():
                        _LOG.error("DIAGNOSIS: Invalid or expired authorization code")
                    elif "invalid_request" in response_text.lower():
                        _LOG.error("DIAGNOSIS: Malformed request")
                    else:
                        _LOG.error("DIAGNOSIS: Unknown 401 error with Basic Auth")
                    
                    # Log the exact request for manual testing
                    form_data = "&".join([f"{k}={v}" for k, v in data.items()])
                    _LOG.error(f"Form data sent: {form_data}")
                    _LOG.error(f"Test this manually with curl:")
                    _LOG.error(f"curl -X POST '{self.token_url}' \\")
                    _LOG.error(f"     -H 'Content-Type: application/x-www-form-urlencoded' \\")
                    _LOG.error(f"     -H 'Authorization: Basic {credentials_b64}' \\")
                    _LOG.error(f"     -d '{form_data}'")
                    
                    raise SmartThingsOAuth2Error(f"Authentication failed (401): {response_text}")
                    
                else:
                    _LOG.error(f"Token exchange failed: {response.status} - {response_text}")
                    raise SmartThingsOAuth2Error(f"Token exchange failed: {response.status} - {response_text}")
                    
        except aiohttp.ClientError as e:
            _LOG.error(f"Network error during token exchange: {e}")
            raise SmartThingsOAuth2Error(f"Network error: {e}")
        except asyncio.TimeoutError:
            _LOG.error(f"Timeout during token exchange")
            raise SmartThingsOAuth2Error("Request timeout during token exchange")
        except Exception as e:
            _LOG.error(f"Unexpected error during token exchange: {e}")
            raise SmartThingsOAuth2Error(f"Unexpected error: {e}")

    async def get_locations(self) -> List[Dict[str, Any]]:
        """Get user's SmartThings locations with enhanced error reporting and workaround."""
        _LOG.info("Attempting to get SmartThings locations...")
        try:
            response = await self._make_request("GET", "/locations")
            locations = response.get("items", [])
            _LOG.info(f"Successfully found {len(locations)} SmartThings locations")
            return locations
        except SmartThingsAPIError as e:
            if e.status_code == 403:
                _LOG.error("403 Forbidden when accessing /locations endpoint")
                _LOG.error("This suggests the SmartApp doesn't have location permissions")
                _LOG.error("Check your SmartApp configuration in SmartThings CLI")
                _LOG.error("Required scopes: r:locations:* w:locations:* x:locations:*")
                
                _LOG.info("WORKAROUND: Attempting to get location from installed app...")
                try:
                    app_response = await self._make_request("GET", "/installedapps")
                    apps = app_response.get("items", [])
                    if apps:
                        # Get location from first installed app
                        location_id = apps[0].get("locationId")
                        if location_id:
                            _LOG.info(f"Found location ID from installed app: {location_id}")
                            # Create a synthetic location object
                            return [{
                                "locationId": location_id,
                                "name": f"Location {location_id[:8]}...",
                                "countryCode": "US",
                                "locale": "en"
                            }]
                except Exception as app_error:
                    _LOG.error(f"Failed to get location from installed app: {app_error}")
                
                _LOG.info("FALLBACK: Attempting to get location from devices...")
                try:
                    devices_response = await self._make_request("GET", "/devices")
                    devices = devices_response.get("items", [])
                    if devices:
                        # Get location from first device
                        location_id = devices[0].get("locationId")
                        if location_id:
                            _LOG.info(f"Found location ID from device: {location_id}")
                            # Create a synthetic location object
                            return [{
                                "locationId": location_id,
                                "name": f"Smart Home ({location_id[:8]}...)",
                                "countryCode": "US",
                                "locale": "en"
                            }]
                except Exception as device_error:
                    _LOG.error(f"Failed to get location from devices: {device_error}")
                
            raise  # Re-raise the original error if no workaround succeeded

    async def get_devices(self, location_id: str = None) -> List[Dict[str, Any]]:
        """Get devices for a specific location."""
        _LOG.info(f"Getting devices for location: {location_id}")
        
        if location_id:
            response = await self._make_request("GET", f"/devices?locationId={location_id}")
        else:
            # Get all devices if no location specified
            response = await self._make_request("GET", "/devices")
        
        devices = response.get("items", [])
        
        _LOG.info(f"Found {len(devices)} devices")
        
        processed_devices = []
        for device_data in devices:
            try:
                device = SmartThingsDevice(**device_data)
                if device.capabilities:
                    processed_devices.append(device_data)
                    _LOG.debug(f"Device: {device.label} - Capabilities: {list(device.capabilities)[:5]}...")
                else:
                    _LOG.debug(f"Skipping device {device.label}: no capabilities")
            except Exception as e:
                _LOG.warning(f"Error processing device {device_data.get('label', 'Unknown')}: {e}")
        
        return processed_devices

    async def get_rooms(self, location_id: str) -> List[Dict[str, Any]]:
        """Get rooms for a specific location.""" 
        try:
            response = await self._make_request("GET", f"/locations/{location_id}/rooms")
            return response.get("items", [])
        except SmartThingsAPIError as e:
            if e.status_code == 403:
                _LOG.warning("Cannot access rooms - permission denied. Using empty rooms list.")
                return []
            raise

    async def get_device_status(self, device_id: str) -> Optional[Dict[str, Any]]:
        cache_key = f"status_{device_id}"
        now = time.time()
        
        if (cache_key in self._device_cache and 
            now - self._cache_timestamps.get(cache_key, 0) < self._cache_ttl):
            self._cache_hits += 1
            return self._device_cache[cache_key]
        
        try:
            response = await self._make_request("GET", f"/devices/{device_id}/status")
            
            if response:
                self._device_cache[cache_key] = response
                self._cache_timestamps[cache_key] = now
                return response
            
        except Exception as e:
            _LOG.warning(f"Failed to get status for device {device_id}: {e}")
            
        return None

    async def execute_command(self, device_id: str, capability: str, command: str, args: Optional[List] = None) -> bool:
        payload = {
            "commands": [{
                "component": "main",
                "capability": capability,
                "command": command,
                "arguments": args if args is not None else []
            }]
        }
        
        try:
            await self._make_request("POST", f"/devices/{device_id}/commands", json=payload)
            
            cache_key = f"status_{device_id}"
            if cache_key in self._device_cache:
                del self._device_cache[cache_key]
                del self._cache_timestamps[cache_key]
            
            _LOG.info(f"Command executed: {device_id} -> {capability}.{command}({args})")
            return True
            
        except SmartThingsAPIError as e:
            _LOG.error(f"Command failed: {device_id} -> {capability}.{command}: {e}")
            return False
        except Exception as e:
            _LOG.error(f"Command failed: {device_id} -> {capability}.{command}: {e}")
            return False

    def get_oauth_tokens(self) -> Optional[OAuth2TokenData]:
        """Get current OAuth tokens"""
        return self._oauth_tokens

    def set_oauth_tokens(self, tokens: OAuth2TokenData):
        """Set OAuth tokens"""
        self._oauth_tokens = tokens

    def get_performance_stats(self) -> Dict[str, Any]:
        cache_hit_rate = (self._cache_hits / max(self._request_count, 1)) * 100
        error_rate = (self._connection_errors / max(self._request_count, 1)) * 100
        
        return {
            "total_requests": self._request_count,
            "cache_hits": self._cache_hits,
            "cache_hit_rate": f"{cache_hit_rate:.1f}%",
            "cached_devices": len(self._device_cache),
            "connection_errors": self._connection_errors,
            "error_rate": f"{error_rate:.1f}%",
            "cache_ttl": self._cache_ttl,
            "auth_method": "oauth2",
            "token_expired": self._oauth_tokens.is_expired if self._oauth_tokens else None
        }

    def clear_cache(self):
        self._device_cache.clear()
        self._cache_timestamps.clear()
        _LOG.debug("Device status cache cleared")

    async def batch_get_device_status(self, device_ids: List[str]) -> Dict[str, Optional[Dict[str, Any]]]:
        results = {}
        
        batch_size = 4
        for i in range(0, len(device_ids), batch_size):
            batch = device_ids[i:i + batch_size]
            
            tasks = [self.get_device_status(device_id) for device_id in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for device_id, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    _LOG.warning(f"Batch status fetch failed for {device_id}: {result}")
                    results[device_id] = None
                else:
                    results[device_id] = result
            
            if i + batch_size < len(device_ids):
                await asyncio.sleep(0.1)
        
        return results

    async def health_check(self) -> bool:
        """Perform a health check on the SmartThings API connection."""
        try:
            locations = await self.get_locations()
            return len(locations) >= 0
        except Exception as e:
            _LOG.error(f"SmartThings API health check failed: {e}")
            return False

    def get_connection_status(self) -> Dict[str, Any]:
        """Get current connection status and statistics."""
        return {
            "session_active": self._session is not None and not self._session.closed,
            "cache_entries": len(self._device_cache),
            "performance": self.get_performance_stats(),
            "auth_method": "oauth2",
            "oauth_valid": not self._oauth_tokens.is_expired if self._oauth_tokens else None,
            "config": {
                "timeout": self._request_timeout,
                "max_retries": self._max_retries,
                "cache_ttl": self._cache_ttl,
                "pool_limit": self._connection_pool_limit
            }
        }