"""
SmartThings Integration driver for Unfolded Circle Remote using ucapi-framework.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

import logging
from typing import Any

from ucapi import Entity
from ucapi_framework import BaseIntegrationDriver
from ucapi_framework.device import DeviceEvents

from uc_intg_smartthings.config import SmartThingsConfig
from uc_intg_smartthings.device import SmartThingsDevice
from uc_intg_smartthings.entities import SmartThingsEntityFactory

_LOG = logging.getLogger(__name__)


class SmartThingsDriver(BaseIntegrationDriver[SmartThingsDevice, SmartThingsConfig]):
    """SmartThings integration driver using ucapi-framework."""

    def __init__(self):
        super().__init__(
            device_class=SmartThingsDevice,
            entity_classes=[],
            driver_id="smartthings",
        )
        self._entity_factories: dict[str, SmartThingsEntityFactory] = {}
        self._device_to_config: dict[str, str] = {}

    def device_from_entity_id(self, entity_id: str) -> str | None:
        """Map entity ID to config identifier."""
        if not entity_id:
            return None

        parts = entity_id.split(".")
        if len(parts) < 2:
            return None

        entity_suffix = parts[1]
        if entity_suffix.startswith("st_"):
            device_part = entity_suffix[3:]
            st_device_id = device_part.split("_")[0]
            config_id = self._device_to_config.get(st_device_id)
            _LOG.debug(
                "Mapped entity %s -> device %s -> config %s",
                entity_id, st_device_id, config_id
            )
            return config_id

        return None

    def create_entities(
        self, device_config: SmartThingsConfig, device: SmartThingsDevice
    ) -> list[Entity]:
        """Create entity instances dynamically based on SmartThings devices."""
        _LOG.info("Creating entities for %s", device_config.name)

        for st_device_id in device.devices.keys():
            self._device_to_config[st_device_id] = device_config.identifier
        self._device_to_config[device_config.identifier] = device_config.identifier

        factory = SmartThingsEntityFactory(device)
        entities = factory.create_entities(
            include_lights=device_config.include_lights,
            include_switches=device_config.include_switches,
            include_sensors=device_config.include_sensors,
            include_climate=device_config.include_climate,
            include_covers=device_config.include_covers,
            include_media_players=device_config.include_media_players,
            include_buttons=device_config.include_buttons,
        )

        self._entity_factories[device_config.identifier] = factory

        device.events.on(
            DeviceEvents.UPDATE,
            lambda did, status: self._on_device_update(device_config.identifier, did, status),
        )

        _LOG.info("Created %d entities for %s", len(entities), device_config.name)
        return entities

    def _on_device_update(
        self, config_id: str, device_id: str, status: dict[str, Any]
    ) -> None:
        """Handle device status update events."""
        factory = self._entity_factories.get(config_id)
        if not factory:
            return

        updates = factory.update_entity_states(device_id, status)

        for entity_id, attrs in updates.items():
            if self.api.configured_entities.contains(entity_id):
                self.api.configured_entities.update_attributes(entity_id, attrs)
                _LOG.debug("Updated entity %s: %s", entity_id, attrs)

    def on_device_removed(
        self, device_or_config: SmartThingsDevice | SmartThingsConfig | None
    ) -> None:
        """Handle device removed - clean up entity factory and mappings."""
        if device_or_config is None:
            self._entity_factories.clear()
            self._device_to_config.clear()
            return

        if isinstance(device_or_config, SmartThingsConfig):
            config_id = device_or_config.identifier
        else:
            config_id = device_or_config.identifier

        self._entity_factories.pop(config_id, None)
        keys_to_remove = [k for k, v in self._device_to_config.items() if v == config_id]
        for key in keys_to_remove:
            self._device_to_config.pop(key, None)
        _LOG.info("Cleaned up entity factory for %s", config_id)
