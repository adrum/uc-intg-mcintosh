"""Media-player entity for a McIntosh processor."""

import logging
from typing import Any

import ucapi
from const import SimpleCommands, McIntoshConfig
from mcintosh import McIntoshDevice
from protocol import McIntoshProtocolError
from ucapi import EntityTypes, media_player
from ucapi.media_player import Attributes, DeviceClasses
from ucapi_framework import create_entity_id
from ucapi_framework.entities import MediaPlayerEntity

_LOG = logging.getLogger(__name__)

FEATURES = [
    media_player.Features.ON_OFF,
    media_player.Features.TOGGLE,
    media_player.Features.VOLUME,
    media_player.Features.VOLUME_UP_DOWN,
    media_player.Features.MUTE,
    media_player.Features.UNMUTE,
    media_player.Features.MUTE_TOGGLE,
    media_player.Features.SELECT_SOURCE,
]

# Simple commands that map to a single protocol command with no arguments.
_SIMPLE_COMMANDS: dict[str, str] = {
    SimpleCommands.ZONE2_ON: "!POWERONZONE2",
    SimpleCommands.ZONE2_OFF: "!POWEROFFZONE2",
    SimpleCommands.ZONE2_VOLUME_UP: "!ZVOL+",
    SimpleCommands.ZONE2_VOLUME_DOWN: "!ZVOL-",
    SimpleCommands.ZONE2_MUTE_TOGGLE: "!ZMUTE",
    SimpleCommands.LOUDNESS_ON: "!LOUDNESS(1)",
    SimpleCommands.LOUDNESS_OFF: "!LOUDNESS(0)",
    SimpleCommands.BASS_UP: "!TRIMBASS+",
    SimpleCommands.BASS_DOWN: "!TRIMBASS-",
    SimpleCommands.TREBLE_UP: "!TRIMTREB+",
    SimpleCommands.TREBLE_DOWN: "!TRIMTREB-",
    SimpleCommands.LIPSYNC_UP: "!LIPSYNC+",
    SimpleCommands.LIPSYNC_DOWN: "!LIPSYNC-",
}


class McIntoshMediaPlayer(MediaPlayerEntity):
    """Media-player entity for a McIntosh processor."""

    def __init__(self, config_device: McIntoshConfig, device: McIntoshDevice):
        """Initialize the entity."""
        self._device = device
        self.config = config_device

        entity_id = create_entity_id(
            EntityTypes.MEDIA_PLAYER, config_device.identifier
        )

        super().__init__(
            entity_id,
            config_device.name,
            FEATURES,
            attributes={
                Attributes.STATE: device.state,
                Attributes.VOLUME: device.volume,
                Attributes.MUTED: device.muted,
                Attributes.SOURCE: device.source,
                Attributes.SOURCE_LIST: device.source_list,
            },
            device_class=DeviceClasses.RECEIVER,
            options={
                media_player.Options.SIMPLE_COMMANDS: [
                    cmd.value for cmd in SimpleCommands
                ]
            },
            cmd_handler=self.command_handler,
        )

        self.subscribe_to_device(device)

    async def sync_state(self) -> None:
        """Sync entity state from the device."""
        if self._device is None:
            self.set_unavailable()
            return

        attrs = self._device.get_media_player_attributes(self._device.identifier)
        if attrs is not None:
            self.update(attrs)

    async def command_handler(
        self,
        entity: MediaPlayerEntity,
        cmd_id: str,
        params: dict[str, Any] | None,
    ) -> ucapi.StatusCodes:
        """Handle a command sent to the media-player entity."""
        _LOG.info("Got %s command: %s %s", entity.id, cmd_id, params or "")

        if self._device is None:
            _LOG.warning("No McIntosh device for entity: %s", self.id)
            return ucapi.StatusCodes.SERVICE_UNAVAILABLE

        device = self._device

        try:
            match cmd_id:
                case media_player.Commands.ON:
                    await device.power_on()
                case media_player.Commands.OFF:
                    await device.power_off()
                case media_player.Commands.TOGGLE:
                    await device.power_toggle()
                case media_player.Commands.VOLUME:
                    await device.set_volume(int(params.get("volume", 0)))
                case media_player.Commands.VOLUME_UP:
                    await device.volume_up()
                case media_player.Commands.VOLUME_DOWN:
                    await device.volume_down()
                case media_player.Commands.MUTE:
                    await device.set_mute(True)
                case media_player.Commands.UNMUTE:
                    await device.set_mute(False)
                case media_player.Commands.MUTE_TOGGLE:
                    await device.mute_toggle()
                case media_player.Commands.SELECT_SOURCE:
                    await device.select_source(params.get("source", ""))
                case _ if cmd_id in _SIMPLE_COMMANDS:
                    await device.send_raw(_SIMPLE_COMMANDS[cmd_id])
                case _:
                    return ucapi.StatusCodes.NOT_IMPLEMENTED

        except ValueError as err:  # unknown source name
            _LOG.warning("Bad parameter for %s: %s", cmd_id, err)
            return ucapi.StatusCodes.BAD_REQUEST
        except (McIntoshProtocolError, TimeoutError) as err:
            _LOG.error("Command %s failed: %s", cmd_id, err)
            return ucapi.StatusCodes.SERVICE_UNAVAILABLE

        return ucapi.StatusCodes.OK
