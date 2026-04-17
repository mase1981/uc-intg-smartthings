"""
SmartThings button entity creation and command handling.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ucapi import button, StatusCodes
from ucapi.button import Button

from uc_intg_smartthings.const import detect_entity_type_from_caps

if TYPE_CHECKING:
    from uc_intg_smartthings.config import SmartThingsConfig
    from uc_intg_smartthings.device import SmartThingsDevice

_LOG = logging.getLogger(__name__)


def create_buttons(config: SmartThingsConfig, device: SmartThingsDevice) -> list:
    """Create button entities from config."""
    if not config.include_buttons:
        return []

    entities = []

    for dev_info in config.devices:
        if detect_entity_type_from_caps(dev_info.capabilities) != "button":
            continue

        device_id = dev_info.device_id
        entity_id = f"button.st_{device_id}"

        async def cmd_handler(
            entity: Button, cmd_id: str, params: dict | None, _did=device_id
        ) -> StatusCodes:
            return await _handle_button_command(device, _did, cmd_id, params)

        entities.append(Button(
            entity_id,
            dev_info.name,
            cmd_handler=cmd_handler,
            area=dev_info.room or None,
        ))

    return entities


async def _handle_button_command(
    device: SmartThingsDevice, device_id: str, cmd_id: str, params: dict | None
) -> StatusCodes:
    if cmd_id == button.Commands.PUSH:
        success = await device.execute_command(device_id, "momentary", "push")
        if not success:
            success = await device.execute_command(device_id, "button", "push")
    else:
        return StatusCodes.NOT_IMPLEMENTED

    return StatusCodes.OK if success else StatusCodes.SERVER_ERROR
