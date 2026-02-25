"""
SmartThings device wrapper with polling support.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

import asyncio
import logging
from enum import IntEnum
from typing import Any

from pyee.asyncio import AsyncIOEventEmitter

from uc_intg_smartthings.client import SmartThingsClient, SmartThingsAPIError
from uc_intg_smartthings.config import SmartThingsConfig, OAuth2Tokens

_LOG = logging.getLogger(__name__)


class DeviceEvents(IntEnum):
    """Device events."""

    CONNECTED = 1
    DISCONNECTED = 2
    UPDATE = 3
    ERROR = 4


class SmartThingsDevice:
    """SmartThings device wrapper with polling support."""

    def __init__(
        self,
        config: SmartThingsConfig,
        on_token_update: Any = None,
    ):
        """Initialize the SmartThings device."""
        self.config = config
        self._on_token_update = on_token_update
        self.events = AsyncIOEventEmitter()

        tokens = config.oauth2_tokens
        self.client = SmartThingsClient(
            client_id=config.client_id,
            client_secret=config.client_secret,
            access_token=tokens.access_token if tokens else None,
            refresh_token=tokens.refresh_token if tokens else None,
            expires_at=tokens.expires_at if tokens else None,
        )
        self.client.set_token_refresh_callback(self._on_token_refresh)

        self._is_connected = False
        self._polling_task: asyncio.Task | None = None
        self._polling_interval = config.polling_interval
        self._devices_cache: dict[str, dict] = {}
        self._device_status_cache: dict[str, dict] = {}
        self._rooms_cache: dict[str, str] = {}
        self._scenes_cache: list[dict] = []
        self._modes_cache: list[dict] = []
        self._current_mode: str | None = None

    @property
    def identifier(self) -> str:
        """Get the device identifier."""
        return self.config.identifier

    @property
    def name(self) -> str:
        """Get the device name."""
        return self.config.name

    @property
    def location_id(self) -> str:
        """Get the location ID."""
        return self.config.location_id

    @property
    def is_connected(self) -> bool:
        """Check if the device is connected."""
        return self._is_connected

    @property
    def devices(self) -> dict[str, dict]:
        """Get cached devices."""
        return self._devices_cache

    @property
    def device_status(self) -> dict[str, dict]:
        """Get cached device status."""
        return self._device_status_cache

    @property
    def rooms(self) -> dict[str, str]:
        """Get cached rooms (device_id -> room_name)."""
        return self._rooms_cache

    @property
    def scenes(self) -> list[dict]:
        """Get cached scenes."""
        return self._scenes_cache

    @property
    def modes(self) -> list[dict]:
        """Get cached modes."""
        return self._modes_cache

    @property
    def current_mode(self) -> str | None:
        """Get the current mode."""
        return self._current_mode

    async def _on_token_refresh(
        self, access_token: str, refresh_token: str, expires_at: float
    ) -> None:
        """Handle token refresh callback."""
        _LOG.debug("Tokens refreshed, updating configuration")
        self.config.oauth2_tokens = OAuth2Tokens(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
        )
        if self._on_token_update:
            await self._on_token_update(self.config)

    async def connect(self) -> bool:
        """Connect to SmartThings API and start polling."""
        _LOG.info("Connecting to SmartThings for location: %s", self.config.location_name)

        try:
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

            await self._poll_device_status()

            self._is_connected = True
            self.events.emit(DeviceEvents.CONNECTED, self.identifier)

            self._start_polling()

            return True

        except SmartThingsAPIError as e:
            _LOG.error("Failed to connect to SmartThings: %s", e)
            self._is_connected = False
            self.events.emit(DeviceEvents.ERROR, self.identifier, str(e))
            return False
        except Exception as e:
            _LOG.error("Unexpected error connecting to SmartThings: %s", e)
            self._is_connected = False
            self.events.emit(DeviceEvents.ERROR, self.identifier, str(e))
            return False

    async def disconnect(self) -> None:
        """Disconnect from SmartThings."""
        _LOG.info("Disconnecting from SmartThings")
        self._stop_polling()
        await self.client.close()
        self._is_connected = False
        self.events.emit(DeviceEvents.DISCONNECTED, self.identifier)

    def _start_polling(self) -> None:
        """Start the polling task."""
        if self._polling_task is None or self._polling_task.done():
            self._polling_task = asyncio.create_task(self._polling_loop())

    def _stop_polling(self) -> None:
        """Stop the polling task."""
        if self._polling_task and not self._polling_task.done():
            self._polling_task.cancel()
            self._polling_task = None

    async def _polling_loop(self) -> None:
        """Main polling loop."""
        _LOG.info("Starting polling loop (interval: %ds)", self._polling_interval)

        while True:
            try:
                await asyncio.sleep(self._polling_interval)
                await self._poll_device_status()
            except asyncio.CancelledError:
                _LOG.debug("Polling loop cancelled")
                break
            except Exception as e:
                _LOG.error("Polling error: %s", e)
                await asyncio.sleep(5)

    async def _poll_device_status(self) -> None:
        """Poll status for all devices."""
        _LOG.debug("Polling device status...")

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
        """Execute a command on a device."""
        try:
            await self.client.execute_command(device_id, capability, command, args)
            _LOG.debug(
                "Executed command %s.%s on device %s", capability, command, device_id
            )
            await asyncio.sleep(0.5)
            try:
                status = await self.client.get_device_status(device_id)
                self._device_status_cache[device_id] = status
                self.events.emit(DeviceEvents.UPDATE, device_id, status)
            except Exception as e:
                _LOG.debug("Failed to get post-command status: %s", e)

            return True
        except SmartThingsAPIError as e:
            _LOG.error(
                "Failed to execute command %s.%s on device %s: %s",
                capability,
                command,
                device_id,
                e,
            )
            return False

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
