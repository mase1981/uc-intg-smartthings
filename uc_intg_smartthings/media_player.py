"""
SmartThings media player entity creation and command handling.

Bug Fix #1: SELECT_SOURCE uses a single detected capability per device instead
of cascading 3 sequential API calls (which caused 500 errors on Q990f).

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ucapi import media_player, StatusCodes
from ucapi.media_player import MediaPlayer, Features, Attributes, States

from uc_intg_smartthings.const import (
    SAMSUNG_EXECUTE_SOURCE_MAP,
    SAMSUNG_SOUNDBAR_SOURCES,
    detect_entity_type_from_caps,
    detect_input_source_capability,
    is_samsung_soundbar,
)

if TYPE_CHECKING:
    from uc_intg_smartthings.config import SmartThingsConfig
    from uc_intg_smartthings.device import SmartThingsDevice

_LOG = logging.getLogger(__name__)

_INPUT_SOURCE_CAP_MAP: dict[str, str] = {}


def create_media_players(config: SmartThingsConfig, device: SmartThingsDevice) -> list:
    """Create media player entities from config."""
    if not config.include_media_players:
        return []

    entities = []

    for dev_info in config.devices:
        if detect_entity_type_from_caps(dev_info.capabilities) != "media_player":
            continue

        device_id = dev_info.device_id
        caps = dev_info.capabilities

        features = [Features.ON_OFF]
        if "audioVolume" in caps:
            features.extend([Features.VOLUME, Features.VOLUME_UP_DOWN, Features.MUTE])
        if "mediaPlayback" in caps:
            features.extend([Features.PLAY_PAUSE, Features.STOP])

        input_cap = detect_input_source_capability(dev_info.name, caps)

        initial_attrs: dict = {
            Attributes.STATE: States.UNKNOWN,
            Attributes.VOLUME: 0,
            Attributes.MUTED: False,
        }

        if input_cap:
            _INPUT_SOURCE_CAP_MAP[device_id] = input_cap
            features.append(Features.SELECT_SOURCE)
            _LOG.info("Device %s uses %s for input source", dev_info.name, input_cap)

            if input_cap == "execute":
                initial_attrs[Attributes.SOURCE_LIST] = list(SAMSUNG_EXECUTE_SOURCE_MAP.keys())
            elif is_samsung_soundbar(dev_info.name, caps):
                initial_attrs[Attributes.SOURCE_LIST] = SAMSUNG_SOUNDBAR_SOURCES
        else:
            _LOG.info("No direct input source for %s (cycling-only or unsupported)", dev_info.name)

        entity_id = f"media_player.st_{device_id}"

        async def cmd_handler(
            entity: MediaPlayer, cmd_id: str, params: dict | None, _did=device_id
        ) -> StatusCodes:
            return await _handle_media_player_command(device, _did, cmd_id, params)

        entities.append(MediaPlayer(
            entity_id,
            dev_info.name,
            features,
            initial_attrs,
            area=dev_info.room or None,
            cmd_handler=cmd_handler,
        ))

    return entities


async def _handle_media_player_command(
    device: SmartThingsDevice, device_id: str, cmd_id: str, params: dict | None
) -> StatusCodes:
    if cmd_id == media_player.Commands.ON:
        success = await device.execute_command(device_id, "switch", "on")
    elif cmd_id == media_player.Commands.OFF:
        success = await device.execute_command(device_id, "switch", "off")
    elif cmd_id == media_player.Commands.TOGGLE:
        current = device.get_device_capability_status(device_id, "switch", "switch")
        cmd = "off" if current == "on" else "on"
        success = await device.execute_command(device_id, "switch", cmd)
    elif cmd_id == media_player.Commands.VOLUME:
        volume = params.get("volume", 50) if params else 50
        success = await device.execute_command(device_id, "audioVolume", "setVolume", [volume])
    elif cmd_id == media_player.Commands.VOLUME_UP:
        success = await device.execute_command(device_id, "audioVolume", "volumeUp")
    elif cmd_id == media_player.Commands.VOLUME_DOWN:
        success = await device.execute_command(device_id, "audioVolume", "volumeDown")
    elif cmd_id == media_player.Commands.MUTE_TOGGLE:
        current = device.get_device_capability_status(device_id, "audioMute", "mute")
        if current is not None:
            cmd = "unmute" if current == "muted" else "mute"
            success = await device.execute_command(device_id, "audioMute", cmd)
        else:
            current = device.get_device_capability_status(device_id, "audioVolume", "mute")
            cmd = "unmute" if current == "muted" else "mute"
            success = await device.execute_command(device_id, "audioVolume", cmd)
    elif cmd_id == media_player.Commands.PLAY_PAUSE:
        current = device.get_device_capability_status(device_id, "mediaPlayback", "playbackStatus")
        cmd = "pause" if current == "playing" else "play"
        success = await device.execute_command(device_id, "mediaPlayback", cmd)
    elif cmd_id == media_player.Commands.STOP:
        success = await device.execute_command(device_id, "mediaPlayback", "stop")
    elif cmd_id == media_player.Commands.SELECT_SOURCE:
        cap = _INPUT_SOURCE_CAP_MAP.get(device_id)
        if not cap:
            return StatusCodes.NOT_IMPLEMENTED
        source = params.get("source", "") if params else ""
        if cap == "execute":
            source_entry = SAMSUNG_EXECUTE_SOURCE_MAP.get(source)
            if not source_entry:
                _LOG.warning("Unknown source '%s' for execute soundbar %s", source, device_id)
                return StatusCodes.BAD_REQUEST
            connection_type, sb_mode = source_entry
            payload = {
                "x.com.samsung.networkaudio.soundFrom": {
                    "groupName": "",
                    "duid": "",
                    "deviceType": 4,
                    "sbMode": sb_mode,
                    "di": "",
                    "ip": "",
                    "name": "External Device",
                    "connectionType": connection_type,
                    "mac": "",
                    "status": 0,
                }
            }
            success = await device.execute_command(
                device_id, "execute", "execute",
                ["/sec/networkaudio/soundFrom", payload],
            )
        else:
            if source.lower() == "wifi":
                source = "network"
            success = await device.execute_command(device_id, cap, "setInputSource", [source])
    else:
        return StatusCodes.NOT_IMPLEMENTED

    return StatusCodes.OK if success else StatusCodes.SERVER_ERROR
