"""
:copyright: (c) 2025 by Meir Miyara
:license: MPL-2.0, see LICENSE for more details
"""

import json
import logging
import os
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, validator

_LOG = logging.getLogger(__name__)


class SmartThingsConfig(BaseModel):
    # OAuth2 credentials and tokens
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    redirect_uri: Optional[str] = None
    oauth2_tokens: Optional[Dict[str, Any]] = None
    
    location_id: Optional[str] = None
    location_name: Optional[str] = None
    
    include_lights: bool = True
    include_switches: bool = True
    include_sensors: bool = False
    include_climate: bool = True
    include_covers: bool = True
    include_media_players: bool = True
    include_buttons: bool = True
    
    polling_interval: int = Field(default=8, ge=3, le=60)
    high_priority_interval: int = Field(default=3, ge=1, le=10)
    low_priority_interval: int = Field(default=30, ge=10, le=300)
    
    max_concurrent_requests: int = Field(default=5, ge=1, le=20)
    cache_ttl_seconds: int = Field(default=30, ge=10, le=300)
    
    enable_optimistic_updates: bool = True
    command_verification_delay: float = Field(default=1.5, ge=0.5, le=5.0)
    
    class Config:
        extra = "allow"
        validate_assignment = True

    @validator('location_id')
    def validate_location_id(cls, v):
        if v is None:
            return v
            
        import re
        uuid_pattern = r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
        if not re.match(uuid_pattern, v.lower()):
            raise ValueError('Invalid SmartThings location ID format')
        
        return v.lower()

    @validator('client_id')
    def validate_client_id(cls, v):
        if v is not None and len(v.strip()) == 0:
            raise ValueError('Client ID cannot be empty')
        return v

    @validator('client_secret')
    def validate_client_secret(cls, v):
        if v is not None and len(v.strip()) == 0:
            raise ValueError('Client secret cannot be empty')
        return v

    @validator('redirect_uri')
    def validate_redirect_uri(cls, v):
        if v is not None and len(v.strip()) == 0:
            raise ValueError('Redirect URI cannot be empty')
        return v

    @validator('oauth2_tokens')
    def validate_oauth2_tokens(cls, v):
        if v is None:
            return v
        
        # Validate OAuth2 token structure
        required_fields = ["access_token", "refresh_token", "expires_at"]
        for field in required_fields:
            if field not in v:
                raise ValueError(f'OAuth2 tokens missing required field: {field}')
        
        return v


class ConfigManager:
    CONFIG_VERSION = "2.1"  # OAuth2 with client credentials version
    
    def __init__(self, config_dir: str):
        self.config_dir = config_dir
        self.config_file = os.path.join(config_dir, "smartthings_config.json")
        self.backup_file = os.path.join(config_dir, "smartthings_config_backup.json")
        
        os.makedirs(config_dir, exist_ok=True)
    
    def load_config(self) -> Dict[str, Any]:
        if not os.path.exists(self.config_file):
            _LOG.info("No configuration file found, using defaults")
            return self._get_default_config()
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                raw_config = json.load(f)
            
            # Migrate from legacy configurations
            raw_config = self._migrate_legacy_config(raw_config)
            
            config_model = SmartThingsConfig(**raw_config)
            validated_config = config_model.dict()
            
            _LOG.info("Configuration loaded and validated successfully")
            return validated_config
            
        except json.JSONDecodeError as e:
            _LOG.error(f"Invalid JSON in config file: {e}")
            return self._load_backup_or_default()
        except ValueError as e:
            _LOG.error(f"Configuration validation failed: {e}")
            return self._load_backup_or_default()
        except Exception as e:
            _LOG.error(f"Failed to load configuration: {e}")
            return self._load_backup_or_default()

    def _migrate_legacy_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Migrate legacy configurations to OAuth2 with client credentials format."""
        config_version = config.get("_config_version", "1.0")
        
        if config_version == "1.0" or config_version < "2.1":
            _LOG.info("Migrating legacy configuration to OAuth2 with client credentials format")
            
            # Remove any legacy PAT tokens
            if "access_token" in config:
                _LOG.warning("Removing legacy PAT token - OAuth2 with client credentials required")
                del config["access_token"]
            
            if "auth_method" in config:
                del config["auth_method"]
            
            config["_config_version"] = "2.1"
        
        return config

    def save_config(self, config_data: Dict[str, Any]) -> bool:
        try:
            config_model = SmartThingsConfig(**config_data)
            validated_config = config_model.dict()
            
            validated_config['_config_version'] = self.CONFIG_VERSION
            validated_config['_last_updated'] = self._get_timestamp()
            
            if os.path.exists(self.config_file):
                try:
                    os.rename(self.config_file, self.backup_file)
                except OSError as e:
                    _LOG.warning(f"Failed to create config backup: {e}")
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(validated_config, f, indent=2, sort_keys=True)
            
            _LOG.info("Configuration saved and validated successfully")
            return True
            
        except ValueError as e:
            _LOG.error(f"Configuration validation failed: {e}")
            return False
        except Exception as e:
            _LOG.error(f"Failed to save configuration: {e}")
            if os.path.exists(self.backup_file):
                try:
                    os.rename(self.backup_file, self.config_file)
                    _LOG.info("Configuration restored from backup")
                except OSError:
                    pass
            return False
    
    def is_configured(self) -> bool:
        """Check if integration is properly configured with OAuth2."""
        config = self.load_config()
        client_id = config.get("client_id")
        client_secret = config.get("client_secret")
        redirect_uri = config.get("redirect_uri")
        oauth2_tokens = config.get("oauth2_tokens")
        location_id = config.get("location_id")
        
        return bool(client_id and client_secret and redirect_uri and oauth2_tokens and location_id)
    
    def get_config_summary(self) -> Dict[str, Any]:
        config = self.load_config()
        
        summary = {
            "configured": self.is_configured(),
            "auth_method": "oauth2",
            "has_client_credentials": bool(config.get("client_id") and config.get("client_secret")),
            "has_redirect_uri": bool(config.get("redirect_uri")),
            "location_configured": bool(config.get("location_id")),
            "location_name": config.get("location_name", "Unknown"),
            "entity_types_enabled": {
                "lights": config.get("include_lights", True),
                "switches": config.get("include_switches", True),
                "sensors": config.get("include_sensors", False),
                "climate": config.get("include_climate", True),
                "covers": config.get("include_covers", True),
                "media_players": config.get("include_media_players", True),
                "buttons": config.get("include_buttons", True),
            },
            "polling_settings": {
                "base_interval": config.get("polling_interval", 8),
                "high_priority": config.get("high_priority_interval", 3),
                "low_priority": config.get("low_priority_interval", 30),
            },
            "performance_settings": {
                "optimistic_updates": config.get("enable_optimistic_updates", True),
                "max_concurrent": config.get("max_concurrent_requests", 5),
                "cache_ttl": config.get("cache_ttl_seconds", 30),
            },
            "config_version": config.get("_config_version"),
            "last_updated": config.get("_last_updated"),
        }
        
        # OAuth2 token status
        oauth2_tokens = config.get("oauth2_tokens")
        summary["has_oauth2_tokens"] = bool(oauth2_tokens)
        if oauth2_tokens:
            import time
            expires_at = oauth2_tokens.get("expires_at", 0)
            is_expired = time.time() >= expires_at
            remaining_hours = max(0, (expires_at - time.time()) / 3600)
            summary["oauth2_status"] = {
                "is_expired": is_expired,
                "remaining_hours": remaining_hours
            }
        
        return summary
    
    def update_partial_config(self, updates: Dict[str, Any]) -> bool:
        current_config = self.load_config()
        current_config.update(updates)
        return self.save_config(current_config)
    
    def reset_to_defaults(self) -> bool:
        current_config = self.load_config()
        default_config = self._get_default_config()
        
        # Preserve OAuth2 credentials and tokens and location
        if current_config.get("client_id"):
            default_config["client_id"] = current_config["client_id"]
        if current_config.get("client_secret"):
            default_config["client_secret"] = current_config["client_secret"]
        if current_config.get("redirect_uri"):
            default_config["redirect_uri"] = current_config["redirect_uri"]
        if current_config.get("oauth2_tokens"):
            default_config["oauth2_tokens"] = current_config["oauth2_tokens"]
        if current_config.get("location_id"):
            default_config["location_id"] = current_config["location_id"]
        if current_config.get("location_name"):
            default_config["location_name"] = current_config["location_name"]
        
        return self.save_config(default_config)
    
    def _load_backup_or_default(self) -> Dict[str, Any]:
        if os.path.exists(self.backup_file):
            try:
                with open(self.backup_file, 'r', encoding='utf-8') as f:
                    backup_config = json.load(f)
                
                backup_config = self._migrate_legacy_config(backup_config)
                config_model = SmartThingsConfig(**backup_config)
                _LOG.info("Loaded configuration from backup")
                return config_model.dict()
                
            except Exception as e:
                _LOG.error(f"Backup configuration also invalid: {e}")
        
        _LOG.warning("Using default configuration")
        return self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        return SmartThingsConfig().dict()
    
    def _get_timestamp(self) -> str:
        import datetime
        return datetime.datetime.now().isoformat()
    
    def cleanup_old_configs(self) -> None:
        try:
            if os.path.exists(self.backup_file):
                backup_age_days = (
                    self._get_file_age_days(self.backup_file)
                )
                
                if backup_age_days > 30:
                    os.remove(self.backup_file)
                    _LOG.info("Removed old configuration backup")
        except Exception as e:
            _LOG.warning(f"Failed to cleanup old configs: {e}")
    
    def _get_file_age_days(self, file_path: str) -> float:
        import time
        file_stat = os.stat(file_path)
        file_age_seconds = time.time() - file_stat.st_mtime
        return file_age_seconds / (24 * 3600)


def get_recommended_polling_settings(device_count: int) -> Dict[str, int]:
    if device_count <= 10:
        return {
            "polling_interval": 5,
            "high_priority_interval": 2,
            "low_priority_interval": 20,
        }
    elif device_count <= 50:
        return {
            "polling_interval": 8,
            "high_priority_interval": 3,
            "low_priority_interval": 30,
        }
    else:
        return {
            "polling_interval": 12,
            "high_priority_interval": 4,
            "low_priority_interval": 60,
        }