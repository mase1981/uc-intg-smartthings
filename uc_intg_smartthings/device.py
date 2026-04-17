"""
SmartThings device wrapper using PollingDevice from ucapi-framework.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

import asyncio
import logging
from typing import Any

from ucapi_framework.device import PollingDevice, DeviceEvents

from uc_intg_smartthings.client import SmartThingsClient, SmartThingsAPIError
from uc_intg_smartthings.config import SmartThingsConfig

_LOG = logging.getLogger(__name__)


class SmartThingsDevice(PollingDevice):
    """SmartThings device wrapper using framework PollingDevice."""

    def __init__(self, device_config: SmartThingsConfig, **kwargs):
        super().__init__(device_config, poll_interval=device_config.polling_interval, **kwargs)
        self.config = device_config

        self.client = SmartThingsClient(
            client_id=device_config.client_id,
            client_secret=device_config.client_secret,
            access_token=device_config.access_token or None,
            refresh_token=device_config.refresh_token or None,
            expires_at=device_config.expires_at or None,
        )
        self.client.set_token_refresh_callback(self._on_token_refresh)

        self._is_connected = False
        self._devices_cache: dict[str, dict] = {}
        self._device_status_cache: dict[str, dict] = {}
        self._rooms_cache: dict[str, str] = {}
        self._scenes_cache: list[dict] = []
        self._modes_cache: list[dict] = []
        self._current_mode: str | None = None

    @property
    def identifier(self) -> str:
        return self.config.identifier

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def address(self) -> str:
        return "SmartThings Cloud"

    @property
    def log_id(self) -> str:
        return f"smartthings[{self.config.identifier}]"

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @property
    def state(self) -> dict | None:
        if not self._is_connected:
            return None
        return {
            "connected": self._is_connected,
            "devices": len(self._devices_cache),
            "modes": len(self._modes_cache),
            "scenes": len(self._scenes_cache),
        }

    @property
    def location_id(self) -> str:
        return self.config.location_id

    @property
    def devices(self) -> dict[str, dict]:
        return self._devices_cache

    @property
    def device_status(self) -> dict[str, dict]:
        return self._device_status_cache

    @property
    def rooms(self) -> dict[str, str]:
        return self._rooms_cache

    @property
    def scenes(self) -> list[dict]:
        return self._scenes_cache

    @property
    def modes(self) -> list[dict]:
        return self._modes_cache

    @property
    def current_mode(self) -> str | None:
        return self._current_mode

    async def _on_token_refresh(
        self, access_token: str, refresh_token: str, expires_at: float
    ) -> None:
        _LOG.info("Tokens refreshed, persisting to config")
        try:
            self.update_config(
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
            )
        except Exception as e:
            _LOG.error("Failed to persist refreshed tokens: %s", e)
            self.config.access_token = access_token
            self.config.refresh_token = refresh_token
            self.config.expires_at = expires_at

    async def establish_connection(self) -> None:
        """Connect to SmartThings API and populate caches."""
        _LOG.info("Connecting to SmartThings for location: %s", self.config.name)

        devices = await self.client.get_devices(self.location_id)
        self._devices_cache = {d["deviceId"]: d for d in devices}
        _LOG.info("Found %d devices in location", len(devices))

        rooms = await self.client.get_rooms(self.location_id)
        self._rooms_cache = {}
        for room in rooms:
            room_id = room.get("roomId")
            room_name = room.get("name", "Unknown")
            for device in devices:
                if device.get("roomId") == room_id:
                    self._rooms_cache[device["deviceId"]] = room_name

        try:
            scenes = await self.client.get_scenes(self.location_id)
            self._scenes_cache = scenes
            _LOG.info("Found %d scenes", len(scenes))
        except SmartThingsAPIError as e:
            _LOG.warning("Could not fetch scenes: %s", e)
            self._scenes_cache = []

        try:
            modes = await self.client.get_location_modes(self.location_id)
            self._modes_cache = modes
            _LOG.info("Found %d modes", len(modes))
            current = await self.client.get_current_mode(self.location_id)
            self._current_mode = current.get("name")
        except SmartThingsAPIError as e:
            _LOG.warning("Could not fetch modes: %s", e)
            self._modes_cache = []

        await self._poll_all_device_status()
        self._is_connected = True
        self.events.emit(DeviceEvents.CONNECTED, self.identifier)

    async def poll_device(self) -> None:
        """Called periodically by PollingDevice to refresh device status."""
        await self._poll_all_device_status()

    async def disconnect(self) -> None:
        """Disconnect from SmartThings."""
        _LOG.info("Disconnecting from SmartThings")
        self._is_connected = False
        await self.client.close()
        await super().disconnect()

    async def _poll_all_device_status(self) -> None:
        """Poll status for all configured devices."""
        for device_id in list(self._devices_cache.keys()):
            if self.config.device_ids and device_id not in self.config.device_ids:
                continue

            try:
                status = await self.client.get_device_status(device_id)
                old_status = self._device_status_cache.get(device_id)
                self._device_status_cache[device_id] = status

                if old_status != status:
                    self.events.emit(DeviceEvents.UPDATE, device_id, status)

            except SmartThingsAPIError as e:
                _LOG.debug("Failed to get status for device %s: %s", device_id, e)
            except Exception as e:
                _LOG.error("Error polling device %s: %s", device_id, e)

    async def execute_command(
        self,
        device_id: str,
        capability: str,
        command: str,
        args: list | None = None,
    ) -> bool:
        """Execute a command on a device. Only polls on success (Bug Fix #2)."""
        try:
            await self.client.execute_command(device_id, capability, command, args)
            _LOG.debug("Executed command %s.%s on device %s", capability, command, device_id)
        except SmartThingsAPIError as e:
            _LOG.error("Failed to execute command %s.%s on device %s: %s", capability, command, device_id, e)
            return False

        await asyncio.sleep(0.5)
        try:
            status = await self.client.get_device_status(device_id)
            self._device_status_cache[device_id] = status
            self.events.emit(DeviceEvents.UPDATE, device_id, status)
        except Exception as e:
            _LOG.debug("Failed to get post-command status: %s", e)

        return True

    async def execute_scene(self, scene_id: str) -> bool:
        """Execute a scene."""
        try:
            await self.client.execute_scene(scene_id)
            _LOG.info("Executed scene %s", scene_id)
            return True
        except SmartThingsAPIError as e:
            _LOG.error("Failed to execute scene %s: %s", scene_id, e)
            return False

    async def set_mode(self, mode_id: str) -> bool:
        """Set the location mode."""
        try:
            await self.client.set_mode(self.location_id, mode_id)
            current = await self.client.get_current_mode(self.location_id)
            self._current_mode = current.get("name")
            _LOG.info("Set mode to %s", self._current_mode)
            return True
        except SmartThingsAPIError as e:
            _LOG.error("Failed to set mode %s: %s", mode_id, e)
            return False

    def get_device_capability_status(
        self, device_id: str, capability: str, attribute: str
    ) -> Any:
        """Get a specific attribute value from device status."""
        status = self._device_status_cache.get(device_id, {})
        components = status.get("components", {})
        main = components.get("main", {})
        cap_status = main.get(capability, {})
        attr_data = cap_status.get(attribute, {})
        return attr_data.get("value")
