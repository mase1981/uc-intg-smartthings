#!/usr/bin/env python3
"""
:copyright: (c) 2025 by Meir Miyara
:license: MPL-2.0, see LICENSE for more details.
"""
import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Set
import aiohttp
from pydantic import BaseModel, Field

_LOG = logging.getLogger(__name__)


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
    
    def get_ha_entity_type(self) -> Optional[str]:
        return HomeAssistantCapabilityMapping.determine_entity_type(self.capabilities)


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


class SmartThingsAPIError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class SmartThingsClient:

    def __init__(self, token: Optional[str] = None):
        self.base_url = "https://api.smartthings.com/v1"
        self._token = token
        self._session: Optional[aiohttp.ClientSession] = None
        
        self._device_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_timestamps: Dict[str, float] = {}
        self._cache_ttl = 15.0
        
        self._connection_pool_limit = 10
        self._request_timeout = 12
        self._max_retries = 2
        self._retry_delays = [0.5, 1.0]
        
        self._request_count = 0
        self._cache_hits = 0
        self._connection_errors = 0

    async def __aenter__(self):
        if not self._session or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=self._connection_pool_limit,
                limit_per_host=5,
                ttl_dns_cache=300,
                use_dns_cache=True,
                keepalive_timeout=30,
                enable_cleanup_closed=True
            )
            
            timeout = aiohttp.ClientTimeout(
                total=self._request_timeout,
                connect=5,
                sock_read=8
            )
            
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={"User-Agent": "UC-SmartThings-Integration/1.0"}
            )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            await asyncio.sleep(0.1)
            self._session = None
            _LOG.debug("SmartThings API session closed")

    async def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        if not self._token:
            raise SmartThingsAPIError("No access token provided")
        
        if not self._session or self._session.closed:
            await self.__aenter__()

        headers = kwargs.pop("headers", {})
        headers.update({"Authorization": f"Bearer {self._token}"})
        
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        self._request_count += 1
        _LOG.debug(f"ST API Request #{self._request_count}: {method} {endpoint}")
        
        for attempt in range(self._max_retries + 1):
            try:
                async with self._session.request(method, url, headers=headers, **kwargs) as response:
                    if response.status >= 400:
                        error_text = await response.text()
                        _LOG.error(f"SmartThings API Error {response.status}: {error_text}")
                        
                        if response.status == 401:
                            raise SmartThingsAPIError(
                                f"API request failed with status {response.status}", 
                                response.status
                            )
                        
                        if response.status >= 500 and attempt < self._max_retries:
                            await asyncio.sleep(self._retry_delays[min(attempt, len(self._retry_delays) - 1)])
                            continue
                            
                        raise SmartThingsAPIError(
                            f"API request failed with status {response.status}", 
                            response.status
                        )
                    
                    result = await response.json() if response.content_type == 'application/json' else {}
                    _LOG.debug(f"ST API Response #{self._request_count}: {response.status}")
                    return result
                    
            except aiohttp.ClientError as e:
                self._connection_errors += 1
                _LOG.warning(f"SmartThings HTTP Client Error (attempt {attempt + 1}): {e}")
                
                if attempt < self._max_retries:
                    await asyncio.sleep(self._retry_delays[min(attempt, len(self._retry_delays) - 1)])
                    if self._session and not self._session.closed:
                        await self._session.close()
                    await self.__aenter__()
                    continue
                
                raise SmartThingsAPIError(f"Connection error after {self._max_retries + 1} attempts: {e}")
            except asyncio.TimeoutError:
                _LOG.warning(f"SmartThings API Timeout (attempt {attempt + 1})")
                if attempt < self._max_retries:
                    await asyncio.sleep(self._retry_delays[min(attempt, len(self._retry_delays) - 1)])
                    continue
                raise SmartThingsAPIError(f"Request timeout after {self._max_retries + 1} attempts")

    async def get_locations(self) -> List[Dict[str, Any]]:
        response = await self._make_request("GET", "/locations")
        locations = response.get("items", [])
        _LOG.info(f"Found {len(locations)} SmartThings locations")
        return locations

    async def get_devices(self, location_id: str) -> List[Dict[str, Any]]:
        response = await self._make_request("GET", f"/devices?locationId={location_id}")
        devices = response.get("items", [])
        
        _LOG.info(f"Found {len(devices)} devices in location {location_id}")
        
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
        response = await self._make_request("GET", f"/locations/{location_id}/rooms")
        return response.get("items", [])

    async def get_device_status(self, device_id: str) -> Optional[Dict[str, Any]]:
        cache_key = f"status_{device_id}"
        now = time.time()
        
        if (cache_key in self._device_cache and 
            now - self._cache_timestamps.get(cache_key, 0) < self._cache_ttl):
            self._cache_hits += 1
            _LOG.debug(f"Cache hit for {device_id}")
            return self._device_cache[cache_key]
        
        try:
            response = await self._make_request("GET", f"/devices/{device_id}/status")
            
            if response:
                self._device_cache[cache_key] = response
                self._cache_timestamps[cache_key] = now
                _LOG.debug(f"Cached status for {device_id}")
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
            
            _LOG.info(f"✅ Command executed: {device_id} -> {capability}.{command}({args})")
            return True
            
        except SmartThingsAPIError as e:
            _LOG.error(f"❌ Command failed: {device_id} -> {capability}.{command}: {e}")
            return False
        except Exception as e:
            _LOG.error(f"❌ Command failed: {device_id} -> {capability}.{command}: {e}")
            return False

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
        }

    def clear_cache(self):
        self._device_cache.clear()
        self._cache_timestamps.clear()
        _LOG.debug("Device status cache cleared")

    async def batch_get_device_status(self, device_ids: List[str]) -> Dict[str, Optional[Dict[str, Any]]]:
        results = {}
        
        batch_size = 6
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
                await asyncio.sleep(0.05)
        
        return results

    async def health_check(self) -> bool:
        try:
            locations = await self.get_locations()
            return len(locations) >= 0
        except Exception as e:
            _LOG.error(f"SmartThings API health check failed: {e}")
            return False

    def get_connection_status(self) -> Dict[str, Any]:
        return {
            "session_active": self._session is not None and not self._session.closed,
            "cache_entries": len(self._device_cache),
            "performance": self.get_performance_stats(),
            "config": {
                "timeout": self._request_timeout,
                "max_retries": self._max_retries,
                "cache_ttl": self._cache_ttl,
                "pool_limit": self._connection_pool_limit
            }
        }