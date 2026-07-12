"""Remote entity for a McIntosh processor."""

import asyncio
import logging
from typing import Any

from const import (
    MCINTOSH_REMOTE_STATE_MAPPING,
    SOURCES,
    SimpleCommands,
    McIntoshConfig,
)
from mcintosh import McIntoshDevice
from media_player import _SIMPLE_COMMANDS
from protocol import McIntoshProtocolError
from ucapi import EntityTypes, StatusCodes, media_player
from ucapi.media_player import States as MediaStates
from ucapi.remote import Attributes, Commands, Features, Remote
from ucapi.remote import States as RemoteStates
from ucapi.ui import Buttons
from ucapi_framework import create_entity_id
from ucapi_framework.entities import RemoteEntity

_LOG = logging.getLogger(__name__)


class McIntoshRemote(RemoteEntity):
    """Remote entity for a McIntosh processor."""

    def __init__(self, config_device: McIntoshConfig, device: McIntoshDevice):
        """Initialize the entity."""
        self._device = device
        entity_id = create_entity_id(EntityTypes.REMOTE, config_device.identifier)

        super().__init__(
            entity_id,
            f"{config_device.name} Remote",
            [Features.SEND_CMD, Features.ON_OFF, Features.TOGGLE],
            attributes={Attributes.STATE: device.state},
            simple_commands=[cmd.value for cmd in SimpleCommands],
            button_mapping=BUTTON_MAPPING,
            ui_pages=UI_PAGES,
            cmd_handler=self.command_handler,
        )

        self.subscribe_to_device(device)

    async def sync_state(self) -> None:
        """Sync entity state from the device."""
        if self._device is None:
            self.set_unavailable()
            return

        self.update({Attributes.STATE: self.map_entity_states(self._device.state)})

    def map_entity_states(self, device_state: MediaStates) -> RemoteStates:
        """Map the device power state onto remote states."""
        return MCINTOSH_REMOTE_STATE_MAPPING.get(device_state, RemoteStates.UNKNOWN)

    async def command_handler(
        self, entity: Remote, cmd_id: str, params: dict[str, Any] | None = None
    ) -> StatusCodes:
        """Handle a command sent to the remote entity."""
        _LOG.info("Got %s command: %s %s", entity.id, cmd_id, params or "")

        if self._device is None:
            _LOG.warning("No McIntosh device for entity: %s", self.id)
            return StatusCodes.SERVICE_UNAVAILABLE

        repeat = max(1, _int_param(params, "repeat", 1))
        delay = _int_param(params, "delay", 0) / 1000

        for iteration in range(repeat):
            if iteration and delay:
                await asyncio.sleep(delay)

            status = await self._run(cmd_id, params)
            if status != StatusCodes.OK:
                return status

        return StatusCodes.OK

    async def _run(
        self, cmd_id: str, params: dict[str, Any] | None
    ) -> StatusCodes:
        """Execute a single command."""
        device = self._device
        command = params.get("command", "") if params else ""

        try:
            match cmd_id:
                case Commands.ON:
                    await device.power_on()
                case Commands.OFF:
                    await device.power_off()
                case Commands.TOGGLE:
                    await device.power_toggle()
                case Commands.SEND_CMD:
                    return await self._send_named(command)
                case _:
                    return StatusCodes.NOT_IMPLEMENTED

        except (McIntoshProtocolError, TimeoutError) as err:
            _LOG.error("Command %s failed: %s", cmd_id, err)
            return StatusCodes.SERVICE_UNAVAILABLE

        return StatusCodes.OK

    async def _send_named(self, command: str) -> StatusCodes:
        """Run a command carried in remote.send params."""
        device = self._device

        try:
            match command:
                case media_player.Commands.ON:
                    await device.power_on()
                case media_player.Commands.OFF:
                    await device.power_off()
                case media_player.Commands.TOGGLE:
                    await device.power_toggle()
                case media_player.Commands.VOLUME_UP:
                    await device.volume_up()
                case media_player.Commands.VOLUME_DOWN:
                    await device.volume_down()
                case media_player.Commands.MUTE_TOGGLE:
                    await device.mute_toggle()
                case _ if command in _SIMPLE_COMMANDS:
                    await device.send_raw(_SIMPLE_COMMANDS[command])
                case _ if command in _SOURCE_COMMANDS:
                    await device.select_source(command)
                case _:
                    _LOG.warning("Unknown remote command: %s", command)
                    return StatusCodes.NOT_IMPLEMENTED

        except ValueError as err:
            _LOG.warning("Bad remote command %s: %s", command, err)
            return StatusCodes.BAD_REQUEST
        except (McIntoshProtocolError, TimeoutError) as err:
            _LOG.error("Remote command %s failed: %s", command, err)
            return StatusCodes.SERVICE_UNAVAILABLE

        return StatusCodes.OK


def _int_param(params: dict[str, Any] | None, key: str, default: int) -> int:
    """Read an int param that the remote may send as a string."""
    if not params:
        return default

    value = params.get(key, default)
    if isinstance(value, str) and value:
        try:
            return int(float(value))
        except ValueError:
            return default
    if isinstance(value, (int, float)):
        return int(value)
    return default


_SOURCE_COMMANDS = set(SOURCES.values())

BUTTON_MAPPING: list[dict[str, Any]] = [
    {
        "button": Buttons.POWER,
        "short_press": {"cmd_id": media_player.Commands.TOGGLE},
    },
    {
        "button": Buttons.VOLUME_UP,
        "short_press": {"cmd_id": media_player.Commands.VOLUME_UP},
    },
    {
        "button": Buttons.VOLUME_DOWN,
        "short_press": {"cmd_id": media_player.Commands.VOLUME_DOWN},
    },
    {
        "button": Buttons.MUTE,
        "short_press": {"cmd_id": media_player.Commands.MUTE_TOGGLE},
    },
]


def _icon(command: str, icon: str, x: int, y: int) -> dict[str, Any]:
    """Build a single icon button for a UI page."""
    return {
        "command": {
            "cmd_id": "remote.send",
            "params": {"command": command, "repeat": 1},
        },
        "icon": icon,
        "location": {"x": x, "y": y},
        "size": {"height": 1, "width": 1},
        "type": "icon",
    }


def _text(command: str, text: str, x: int, y: int, width: int = 1) -> dict[str, Any]:
    """Build a single text button for a UI page."""
    return {
        "command": {
            "cmd_id": "remote.send",
            "params": {"command": command, "repeat": 1},
        },
        "text": text,
        "location": {"x": x, "y": y},
        "size": {"height": 1, "width": width},
        "type": "text",
    }


UI_PAGES: list[dict[str, Any]] = [
    {
        "page_id": "mcintosh_main",
        "name": "McIntosh",
        "grid": {"width": 4, "height": 6},
        "items": [
            _icon(media_player.Commands.TOGGLE, "uc:power-on", 0, 0),
            _icon(media_player.Commands.MUTE_TOGGLE, "uc:mute", 1, 0),
            _icon(media_player.Commands.VOLUME_DOWN, "uc:minus", 2, 0),
            _icon(media_player.Commands.VOLUME_UP, "uc:plus", 3, 0),
            _text(SimpleCommands.BASS_DOWN, "Bass -", 0, 1),
            _text(SimpleCommands.BASS_UP, "Bass +", 1, 1),
            _text(SimpleCommands.TREBLE_DOWN, "Treb -", 2, 1),
            _text(SimpleCommands.TREBLE_UP, "Treb +", 3, 1),
            _text(SimpleCommands.LOUDNESS_ON, "Loud On", 0, 2),
            _text(SimpleCommands.LOUDNESS_OFF, "Loud Off", 1, 2),
            _text(SimpleCommands.LIPSYNC_DOWN, "Sync -", 2, 2),
            _text(SimpleCommands.LIPSYNC_UP, "Sync +", 3, 2),
            _text(SimpleCommands.ZONE2_ON, "Z2 On", 0, 3),
            _text(SimpleCommands.ZONE2_OFF, "Z2 Off", 1, 3),
            _text(SimpleCommands.ZONE2_VOLUME_DOWN, "Z2 Vol -", 2, 3),
            _text(SimpleCommands.ZONE2_VOLUME_UP, "Z2 Vol +", 3, 3),
        ],
    },
    {
        "page_id": "mcintosh_sources",
        "name": "Sources",
        "grid": {"width": 2, "height": 4},
        "items": [
            _text(SOURCES[source_id], SOURCES[source_id], index % 2, index // 2, 1)
            for index, source_id in enumerate(range(8))
        ],
    },
]
