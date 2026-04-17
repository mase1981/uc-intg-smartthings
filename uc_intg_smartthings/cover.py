"""
SmartThings cover entity creation and command handling.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ucapi import cover, StatusCodes
from ucapi.cover import Cover, Features, Attributes, States

from uc_intg_smartthings.const import detect_entity_type_from_caps, has_capability

if TYPE_CHECKING:
    from uc_intg_smartthings.config import SmartThingsConfig
    from uc_intg_smartthings.device import SmartThingsDevice

_LOG = logging.getLogger(__name__)


def create_covers(config: SmartThingsConfig, device: SmartThingsDevice) -> list:
    """Create cover entities from config."""
    if not config.include_covers:
        return []

    entities = []

    for dev_info in config.devices:
        if detect_entity_type_from_caps(dev_info.capabilities) != "cover":
            continue

        device_id = dev_info.device_id
        dev_dict = {
            "components": [{"capabilities": [{"id": c} for c in dev_info.capabilities]}],
        }

        features = [Features.OPEN, Features.CLOSE]
        if has_capability(dev_dict, "windowShadeLevel"):
            features.append(Features.POSITION)
        if has_capability(dev_dict, "windowShade"):
            features.append(Features.STOP)

        entity_id = f"cover.st_{device_id}"

        async def cmd_handler(
            entity: Cover, cmd_id: str, params: dict | None, _did=device_id
        ) -> StatusCodes:
            return await _handle_cover_command(device, _did, cmd_id, params)

        entities.append(Cover(
            entity_id,
            dev_info.name,
            features,
            {Attributes.STATE: States.UNKNOWN, Attributes.POSITION: 0},
            area=dev_info.room or None,
            cmd_handler=cmd_handler,
        ))

    return entities


async def _handle_cover_command(
    device: SmartThingsDevice, device_id: str, cmd_id: str, params: dict | None
) -> StatusCodes:
    if cmd_id == cover.Commands.OPEN:
        success = await device.execute_command(device_id, "windowShade", "open")
    elif cmd_id == cover.Commands.CLOSE:
        success = await device.execute_command(device_id, "windowShade", "close")
    elif cmd_id == cover.Commands.STOP:
        success = await device.execute_command(device_id, "windowShade", "pause")
    elif cmd_id == cover.Commands.POSITION:
        position = params.get("position", 50) if params else 50
        success = await device.execute_command(device_id, "windowShadeLevel", "setShadeLevel", [position])
    else:
        return StatusCodes.NOT_IMPLEMENTED

    return StatusCodes.OK if success else StatusCodes.SERVER_ERROR
