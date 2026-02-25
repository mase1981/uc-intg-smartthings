"""
SmartThings configuration management.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from typing import Callable

_LOG = logging.getLogger(__name__)


@dataclass
class OAuth2Tokens:
    """OAuth2 token data."""

    access_token: str
    refresh_token: str
    expires_at: float
    token_type: str = "Bearer"


@dataclass
class SmartThingsConfig:
    """SmartThings device configuration."""

    identifier: str
    name: str
    client_id: str
    client_secret: str
    location_id: str
    location_name: str
    oauth2_tokens: OAuth2Tokens | None = None
    include_lights: bool = True
    include_switches: bool = True
    include_sensors: bool = True
    include_climate: bool = True
    include_covers: bool = True
    include_media_players: bool = True
    include_buttons: bool = True
    polling_interval: int = 10
    device_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        if self.oauth2_tokens:
            data["oauth2_tokens"] = asdict(self.oauth2_tokens)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "SmartThingsConfig":
        """Create from dictionary."""
        tokens_data = data.pop("oauth2_tokens", None)
        tokens = None
        if tokens_data and isinstance(tokens_data, dict):
            tokens = OAuth2Tokens(**tokens_data)
        return cls(**data, oauth2_tokens=tokens)


class SmartThingsConfigManager:
    """Configuration manager for SmartThings devices."""

    def __init__(
        self,
        config_dir: str,
        on_add: Callable[[SmartThingsConfig], None] | None = None,
        on_remove: Callable[[str], None] | None = None,
    ):
        """Initialize the configuration manager."""
        self.config_dir = config_dir
        self.config_file_path = os.path.join(config_dir, "config.json")
        self._on_add = on_add
        self._on_remove = on_remove
        self.devices: dict[str, SmartThingsConfig] = {}
        self._ensure_config_dir()
        self.load()

    def _ensure_config_dir(self) -> None:
        """Ensure the configuration directory exists."""
        if not os.path.exists(self.config_dir):
            os.makedirs(self.config_dir, exist_ok=True)
            _LOG.info("Created configuration directory: %s", self.config_dir)

    def load(self) -> None:
        """Load device configurations from disk."""
        if not os.path.exists(self.config_file_path):
            _LOG.debug("No configuration file found at %s", self.config_file_path)
            return

        _LOG.info("Loading device configurations from %s", self.config_file_path)
        try:
            with open(self.config_file_path, "r", encoding="utf-8") as f:
                devices_json = json.load(f)
                for identifier, dev_json in devices_json.items():
                    try:
                        self.devices[identifier] = SmartThingsConfig.from_dict(dev_json)
                    except (TypeError, KeyError) as e:
                        _LOG.error("Failed to load device %s: %s", identifier, e)
        except (json.JSONDecodeError, TypeError) as e:
            _LOG.error("Could not decode config.json: %s. Starting fresh.", e)
            try:
                os.remove(self.config_file_path)
            except OSError:
                pass

    def save(self) -> None:
        """Save device configurations to disk with atomic write."""
        _LOG.info("Saving device configurations to %s", self.config_file_path)
        temp_path = self.config_file_path + ".tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(
                    {k: v.to_dict() for k, v in self.devices.items()},
                    f,
                    indent=2,
                )
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, self.config_file_path)
        except Exception as e:
            _LOG.error("Failed to save configuration: %s", e)
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise

    def add(self, device: SmartThingsConfig) -> None:
        """Add or update a device configuration."""
        is_new = device.identifier not in self.devices
        self.devices[device.identifier] = device
        self.save()
        if is_new and self._on_add:
            self._on_add(device)

    def update(self, device: SmartThingsConfig) -> None:
        """Update an existing device configuration."""
        self.devices[device.identifier] = device
        self.save()

    def remove(self, identifier: str) -> bool:
        """Remove a device configuration."""
        if identifier in self.devices:
            del self.devices[identifier]
            self.save()
            if self._on_remove:
                self._on_remove(identifier)
            return True
        return False

    def get(self, identifier: str) -> SmartThingsConfig | None:
        """Get a device configuration by identifier."""
        return self.devices.get(identifier)

    def all(self) -> list[SmartThingsConfig]:
        """Get all device configurations."""
        return list(self.devices.values())

    def is_configured(self) -> bool:
        """Check if any devices are configured."""
        return len(self.devices) > 0

    def clear(self) -> None:
        """Clear all device configurations."""
        identifiers = list(self.devices.keys())
        self.devices.clear()
        self.save()
        if self._on_remove:
            for identifier in identifiers:
                self._on_remove(identifier)
