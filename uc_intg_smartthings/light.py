"""
SmartThings light entity creation and command handling.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ucapi import light, StatusCodes
from ucapi.light import Light, Features, Attributes, States

from uc_intg_smartthings.const import detect_entity_type_from_caps, has_capability

if TYPE_CHECKING:
    from uc_intg_smartthings.config import SmartThingsConfig
    from uc_intg_smartthings.device import SmartThingsDevice

_LOG = logging.getLogger(__name__)


def create_lights(config: SmartThingsConfig, device: SmartThingsDevice) -> list:
    """Create light entities from config."""
    if not config.include_lights:
        return []

    entities = []

    for dev_info in config.devices:
        if detect_entity_type_from_caps(dev_info.capabilities) != "light":
            continue

        device_id = dev_info.device_id
        dev_dict = {
            "components": [{"capabilities": [{"id": c} for c in dev_info.capabilities]}],
        }

        features = [Features.ON_OFF, Features.TOGGLE]
        if has_capability(dev_dict, "switchLevel"):
            features.append(Features.DIM)
        if has_capability(dev_dict, "colorControl"):
            features.append(Features.COLOR)
        if has_capability(dev_dict, "colorTemperature"):
            features.append(Features.COLOR_TEMPERATURE)

        entity_id = f"light.st_{device_id}"

        async def cmd_handler(
            entity: Light, cmd_id: str, params: dict | None, _did=device_id
        ) -> StatusCodes:
            return await _handle_light_command(device, _did, cmd_id, params)

        entities.append(Light(
            entity_id,
            dev_info.name,
            features,
            {Attributes.STATE: States.UNKNOWN, Attributes.BRIGHTNESS: 0},
            area=dev_info.room or None,
            cmd_handler=cmd_handler,
        ))

    return entities


async def _handle_light_command(
    device: SmartThingsDevice, device_id: str, cmd_id: str, params: dict | None
) -> StatusCodes:
    if cmd_id == light.Commands.ON:
        success = await device.execute_command(device_id, "switch", "on")
    elif cmd_id == light.Commands.OFF:
        success = await device.execute_command(device_id, "switch", "off")
    elif cmd_id == light.Commands.TOGGLE:
        current = device.get_device_capability_status(device_id, "switch", "switch")
        cmd = "off" if current == "on" else "on"
        success = await device.execute_command(device_id, "switch", cmd)
    elif cmd_id == light.Commands.BRIGHTNESS:
        level = params.get("brightness", 100) if params else 100
        success = await device.execute_command(device_id, "switchLevel", "setLevel", [level])
    elif cmd_id == light.Commands.COLOR_TEMPERATURE:
        temp = params.get("color_temperature", 4000) if params else 4000
        success = await device.execute_command(device_id, "colorTemperature", "setColorTemperature", [temp])
    elif cmd_id == light.Commands.COLOR:
        hue = params.get("hue", 0) if params else 0
        sat = params.get("saturation", 100) if params else 100
        success = await device.execute_command(device_id, "colorControl", "setHue", [hue])
        if success:
            success = await device.execute_command(device_id, "colorControl", "setSaturation", [sat])
    else:
        return StatusCodes.NOT_IMPLEMENTED

    return StatusCodes.OK if success else StatusCodes.SERVER_ERROR
