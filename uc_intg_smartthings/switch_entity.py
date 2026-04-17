"""
SmartThings switch entity creation and command handling.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ucapi import switch, StatusCodes
from ucapi.switch import Switch, Features, Attributes, States

from uc_intg_smartthings.const import detect_entity_type_from_caps

if TYPE_CHECKING:
    from uc_intg_smartthings.config import SmartThingsConfig
    from uc_intg_smartthings.device import SmartThingsDevice

_LOG = logging.getLogger(__name__)


def create_switches(config: SmartThingsConfig, device: SmartThingsDevice) -> list:
    """Create switch entities from config."""
    if not config.include_switches:
        return []

    entities = []

    for dev_info in config.devices:
        if detect_entity_type_from_caps(dev_info.capabilities) != "switch":
            continue

        device_id = dev_info.device_id
        entity_id = f"switch.st_{device_id}"

        async def cmd_handler(
            entity: Switch, cmd_id: str, params: dict | None, _did=device_id
        ) -> StatusCodes:
            return await _handle_switch_command(device, _did, cmd_id, params)

        entities.append(Switch(
            entity_id,
            dev_info.name,
            [Features.ON_OFF, Features.TOGGLE],
            {Attributes.STATE: States.UNKNOWN},
            area=dev_info.room or None,
            cmd_handler=cmd_handler,
        ))

    return entities


async def _handle_switch_command(
    device: SmartThingsDevice, device_id: str, cmd_id: str, params: dict | None
) -> StatusCodes:
    if cmd_id == switch.Commands.ON:
        success = await device.execute_command(device_id, "switch", "on")
    elif cmd_id == switch.Commands.OFF:
        success = await device.execute_command(device_id, "switch", "off")
    elif cmd_id == switch.Commands.TOGGLE:
        current = device.get_device_capability_status(device_id, "switch", "switch")
        cmd = "off" if current == "on" else "on"
        success = await device.execute_command(device_id, "switch", cmd)
    else:
        return StatusCodes.NOT_IMPLEMENTED

    return StatusCodes.OK if success else StatusCodes.SERVER_ERROR
