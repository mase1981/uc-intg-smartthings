"""
SmartThings select entity creation for scenes and modes.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ucapi import StatusCodes
from ucapi.select import Select, Attributes, States, Commands

if TYPE_CHECKING:
    from uc_intg_smartthings.config import SmartThingsConfig
    from uc_intg_smartthings.device import SmartThingsDevice

_LOG = logging.getLogger(__name__)

_SELECT_ENTITIES: dict[str, Select] = {}


def create_selects(config: SmartThingsConfig, device: SmartThingsDevice) -> list:
    """Create scene and mode select entities from config."""
    entities = []

    scene_select = _create_scene_select(config, device)
    if scene_select:
        entities.append(scene_select)

    mode_select = _create_mode_select(config, device)
    if mode_select:
        entities.append(mode_select)

    return entities


def _create_scene_select(config: SmartThingsConfig, device: SmartThingsDevice) -> Select | None:
    if not config.scenes:
        return None

    scene_names = [s.get("sceneName", "Unknown") for s in config.scenes]
    if not scene_names:
        return None

    entity_id = f"select.st_{config.identifier}_scenes"

    async def cmd_handler(entity: Select, cmd_id: str, params: dict | None) -> StatusCodes:
        return await _handle_scene_select_command(config, device, entity, cmd_id, params)

    sel = Select(
        entity_id,
        f"{config.name} Scenes",
        {
            Attributes.STATE: States.ON,
            Attributes.OPTIONS: scene_names,
            Attributes.CURRENT_OPTION: scene_names[0] if scene_names else None,
        },
        cmd_handler=cmd_handler,
    )
    _SELECT_ENTITIES[entity_id] = sel
    return sel


def _create_mode_select(config: SmartThingsConfig, device: SmartThingsDevice) -> Select | None:
    if not config.modes:
        return None

    mode_names = [m.get("name", "Unknown") for m in config.modes]
    if not mode_names:
        return None

    entity_id = f"select.st_{config.identifier}_modes"

    async def cmd_handler(entity: Select, cmd_id: str, params: dict | None) -> StatusCodes:
        return await _handle_mode_select_command(config, device, entity, cmd_id, params)

    sel = Select(
        entity_id,
        f"{config.name} Mode",
        {
            Attributes.STATE: States.ON,
            Attributes.OPTIONS: mode_names,
            Attributes.CURRENT_OPTION: mode_names[0] if mode_names else None,
        },
        cmd_handler=cmd_handler,
    )
    _SELECT_ENTITIES[entity_id] = sel
    return sel


def _resolve_select_option(
    options: list[str], entity: Select, cmd_id: str, params: dict | None
) -> str | None:
    current = entity.attributes.get(Attributes.CURRENT_OPTION)
    current_idx = options.index(current) if current in options else 0

    if cmd_id == Commands.SELECT_OPTION:
        return params.get("option") if params else None
    if cmd_id == Commands.SELECT_FIRST:
        return options[0]
    if cmd_id == Commands.SELECT_LAST:
        return options[-1]
    if cmd_id == Commands.SELECT_NEXT:
        return options[(current_idx + 1) % len(options)]
    if cmd_id == Commands.SELECT_PREVIOUS:
        return options[(current_idx - 1) % len(options)]
    return None


async def _handle_scene_select_command(
    config: SmartThingsConfig,
    device: SmartThingsDevice,
    entity: Select,
    cmd_id: str,
    params: dict | None,
) -> StatusCodes:
    scene_names = [s.get("sceneName", "Unknown") for s in config.scenes]
    if not scene_names:
        return StatusCodes.NOT_FOUND

    selected = _resolve_select_option(scene_names, entity, cmd_id, params)
    if selected is None:
        if cmd_id not in (
            Commands.SELECT_OPTION, Commands.SELECT_FIRST, Commands.SELECT_LAST,
            Commands.SELECT_NEXT, Commands.SELECT_PREVIOUS,
        ):
            return StatusCodes.NOT_IMPLEMENTED
        return StatusCodes.BAD_REQUEST

    for scene in config.scenes:
        if scene.get("sceneName") == selected:
            scene_id = scene.get("sceneId")
            if scene_id:
                success = await device.execute_scene(scene_id)
                if success:
                    entity.attributes[Attributes.CURRENT_OPTION] = selected
                return StatusCodes.OK if success else StatusCodes.SERVER_ERROR

    return StatusCodes.NOT_FOUND


async def _handle_mode_select_command(
    config: SmartThingsConfig,
    device: SmartThingsDevice,
    entity: Select,
    cmd_id: str,
    params: dict | None,
) -> StatusCodes:
    mode_names = [m.get("name", "Unknown") for m in config.modes]
    if not mode_names:
        return StatusCodes.NOT_FOUND

    selected = _resolve_select_option(mode_names, entity, cmd_id, params)
    if selected is None:
        if cmd_id not in (
            Commands.SELECT_OPTION, Commands.SELECT_FIRST, Commands.SELECT_LAST,
            Commands.SELECT_NEXT, Commands.SELECT_PREVIOUS,
        ):
            return StatusCodes.NOT_IMPLEMENTED
        return StatusCodes.BAD_REQUEST

    for mode in config.modes:
        if mode.get("name") == selected:
            mode_id = mode.get("id")
            if mode_id:
                success = await device.set_mode(mode_id)
                if success:
                    entity.attributes[Attributes.CURRENT_OPTION] = selected
                return StatusCodes.OK if success else StatusCodes.SERVER_ERROR

    return StatusCodes.NOT_FOUND
