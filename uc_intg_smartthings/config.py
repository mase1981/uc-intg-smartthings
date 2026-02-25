"""
SmartThings configuration for Unfolded Circle integration.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

from dataclasses import dataclass, field


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
