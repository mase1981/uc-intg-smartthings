"""
:copyright: (c) 2025 by Meir Miyara
:license: MPL-2.0, see LICENSE for more details
"""

import json
import logging
import os
import re
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, validator

_LOG = logging.getLogger(__name__)


class SmartThingsConfig(BaseModel):
    access_token: Optional[str] = None
    
    location_id: Optional[str] = None
    location_name: Optional[str] = None
    
    include_lights: bool = True
    include_switches: bool = True
    include_sensors: bool = False
    include_climate: bool = True
    include_covers: bool = True
    include_media_players: bool = True
    
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

    @validator('access_token')
    def validate_access_token(cls, v):
        if v is None:
            return v
        
        pat_pattern = r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
        if not re.match(pat_pattern, v.lower()):
            raise ValueError('Invalid SmartThings Personal Access Token format')
        
        return v.lower()

    @validator('location_id')
    def validate_location_id(cls, v):
        if v is None:
            return v
            
        uuid_pattern = r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
        if not re.match(uuid_pattern, v.lower()):
            raise ValueError('Invalid SmartThings location ID format')
        
        return v.lower()


class ConfigManager:
    CONFIG_VERSION = "1.0"
    
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
        config = self.load_config()
        access_token = config.get("access_token")
        location_id = config.get("location_id")
        
        return bool(access_token and location_id)
    
    def get_config_summary(self) -> Dict[str, Any]:
        config = self.load_config()
        
        return {
            "configured": self.is_configured(),
            "has_access_token": bool(config.get("access_token")),
            "location_configured": bool(config.get("location_id")),
            "location_name": config.get("location_name", "Unknown"),
            "entity_types_enabled": {
                "lights": config.get("include_lights", True),
                "switches": config.get("include_switches", True),
                "sensors": config.get("include_sensors", False),
                "climate": config.get("include_climate", True),
                "covers": config.get("include_covers", True),
                "media_players": config.get("include_media_players", True),
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
    
    def update_partial_config(self, updates: Dict[str, Any]) -> bool:
        current_config = self.load_config()
        current_config.update(updates)
        return self.save_config(current_config)
    
    def reset_to_defaults(self) -> bool:
        current_config = self.load_config()
        default_config = self._get_default_config()
        
        if current_config.get("access_token"):
            default_config["access_token"] = current_config["access_token"]
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


def validate_smartthings_token(token: str) -> bool:
    if not token or not isinstance(token, str):
        return False
    
    pat_pattern = r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
    return bool(re.match(pat_pattern, token.lower()))


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