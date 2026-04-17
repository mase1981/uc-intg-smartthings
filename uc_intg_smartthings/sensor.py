"""
SmartThings sensor entity creation.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ucapi.sensor import (
    Sensor,
    Attributes,
    States,
    DeviceClasses,
    Options,
)

from uc_intg_smartthings.const import get_sensor_types

if TYPE_CHECKING:
    from uc_intg_smartthings.config import SmartThingsConfig
    from uc_intg_smartthings.device import SmartThingsDevice

_LOG = logging.getLogger(__name__)

_SENSOR_TYPE_MAP: dict[str, tuple[DeviceClasses, dict | None]] = {
    "temperature": (DeviceClasses.TEMPERATURE, {Options.NATIVE_UNIT: "C"}),
    "humidity": (DeviceClasses.HUMIDITY, None),
    "battery": (DeviceClasses.BATTERY, None),
    "power": (DeviceClasses.POWER, None),
    "energy": (DeviceClasses.ENERGY, None),
    "illuminance": (DeviceClasses.CUSTOM, {Options.CUSTOM_UNIT: "lux"}),
    "motion": (DeviceClasses.CUSTOM, {Options.CUSTOM_UNIT: "motion"}),
    "contact": (DeviceClasses.CUSTOM, {Options.CUSTOM_UNIT: "contact"}),
    "presence": (DeviceClasses.CUSTOM, {Options.CUSTOM_UNIT: "presence"}),
}


def create_sensors(config: SmartThingsConfig, device: SmartThingsDevice) -> list:
    """Create sensor entities from config."""
    if not config.include_sensors:
        return []

    entities = []

    for dev_info in config.devices:
        sensor_types = get_sensor_types(dev_info.capabilities)
        for sensor_type in sensor_types:
            entity_id = f"sensor.st_{dev_info.device_id}_{sensor_type}"
            sensor_name = f"{dev_info.name} {sensor_type.title()}"

            device_class, options = _SENSOR_TYPE_MAP.get(
                sensor_type, (DeviceClasses.CUSTOM, {Options.CUSTOM_UNIT: sensor_type})
            )

            kwargs: dict = {
                "area": dev_info.room or None,
                "device_class": device_class,
            }
            if options:
                kwargs["options"] = options

            entities.append(Sensor(
                entity_id,
                sensor_name,
                features=[],
                attributes={Attributes.STATE: States.UNKNOWN, Attributes.VALUE: None},
                **kwargs,
            ))

    return entities
