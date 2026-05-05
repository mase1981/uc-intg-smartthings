"""
SmartThings climate entity creation and command handling.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ucapi import climate, StatusCodes
from ucapi.climate import Climate, Features, Attributes, States

from uc_intg_smartthings.const import detect_entity_type_from_caps, has_capability

if TYPE_CHECKING:
    from uc_intg_smartthings.config import SmartThingsConfig
    from uc_intg_smartthings.device import SmartThingsDevice

_LOG = logging.getLogger(__name__)


def create_climate_entities(config: SmartThingsConfig, device: SmartThingsDevice) -> list:
    """Create climate entities from config."""
    if not config.include_climate:
        return []

    entities = []

    for dev_info in config.devices:
        if detect_entity_type_from_caps(dev_info.capabilities) != "climate":
            continue

        device_id = dev_info.device_id
        dev_dict = {
            "components": [{"capabilities": [{"id": c} for c in dev_info.capabilities]}],
        }

        features = [Features.ON_OFF]
        if has_capability(dev_dict, "thermostatHeatingSetpoint"):
            features.append(Features.TARGET_TEMPERATURE)
            features.append(Features.HEAT)
        if has_capability(dev_dict, "thermostatCoolingSetpoint"):
            features.append(Features.TARGET_TEMPERATURE)
            features.append(Features.COOL)
        if has_capability(dev_dict, "thermostatMode"):
            if Features.HEAT not in features:
                features.append(Features.HEAT)
            if Features.COOL not in features:
                features.append(Features.COOL)
        if has_capability(dev_dict, "thermostatFanMode"):
            features.append(Features.FAN)

        entity_id = f"climate.st_{device_id}"

        async def cmd_handler(
            entity: Climate, cmd_id: str, params: dict | None, _did=device_id
        ) -> StatusCodes:
            return await _handle_climate_command(device, _did, cmd_id, params)

        entities.append(Climate(
            entity_id,
            dev_info.name,
            features,
            {
                Attributes.STATE: States.UNKNOWN,
                Attributes.CURRENT_TEMPERATURE: None,
                Attributes.TARGET_TEMPERATURE: None,
            },
            area=dev_info.room or None,
            cmd_handler=cmd_handler,
        ))

    return entities


async def _handle_climate_command(
    device: SmartThingsDevice, device_id: str, cmd_id: str, params: dict | None
) -> StatusCodes:
    if cmd_id == climate.Commands.ON:
        success = await device.execute_command(device_id, "thermostatMode", "auto")
    elif cmd_id == climate.Commands.OFF:
        success = await device.execute_command(device_id, "thermostatMode", "off")
    elif cmd_id == climate.Commands.HVAC_MODE:
        mode = params.get("hvac_mode", "auto") if params else "auto"
        success = await device.execute_command(device_id, "thermostatMode", "setThermostatMode", [mode])
    elif cmd_id == climate.Commands.TARGET_TEMPERATURE:
        temp = params.get("temperature", 21) if params else 21
        success = await device.execute_command(device_id, "thermostatHeatingSetpoint", "setHeatingSetpoint", [temp])
    else:
        return StatusCodes.NOT_IMPLEMENTED

    return StatusCodes.OK if success else StatusCodes.SERVER_ERROR
