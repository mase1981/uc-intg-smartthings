"""
SmartThings configuration for Unfolded Circle integration.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SmartThingsDeviceInfo:
    """Information about a SmartThings device."""

    device_id: str
    name: str
    room: str = ""
    capabilities: list[str] = field(default_factory=list)


@dataclass
class SmartThingsConfig:
    """SmartThings device configuration."""

    identifier: str
    name: str
    client_id: str
    client_secret: str
    location_id: str
    access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0
    include_lights: bool = True
    include_switches: bool = True
    include_sensors: bool = True
    include_climate: bool = True
    include_covers: bool = True
    include_media_players: bool = True
    include_buttons: bool = True
    polling_interval: int = 10
    device_ids: list[str] = field(default_factory=list)
    devices: list[SmartThingsDeviceInfo] = field(default_factory=list)
    scenes: list[dict] = field(default_factory=list)
    modes: list[dict] = field(default_factory=list)

    def __post_init__(self):
        """Convert devices from dicts to SmartThingsDeviceInfo if needed."""
        converted = []
        for device in self.devices:
            if isinstance(device, dict):
                converted.append(SmartThingsDeviceInfo(**device))
            else:
                converted.append(device)
        self.devices = converted

    def add_device(self, device_id: str, name: str, room: str = "", capabilities: list[str] | None = None) -> None:
        """Add a device to the configuration."""
        for existing in self.devices:
            if existing.device_id == device_id:
                existing.name = name
                existing.room = room
                if capabilities:
                    existing.capabilities = capabilities
                return
        self.devices.append(SmartThingsDeviceInfo(
            device_id=device_id,
            name=name,
            room=room,
            capabilities=capabilities or [],
        ))
