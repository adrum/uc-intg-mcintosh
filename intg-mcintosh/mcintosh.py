"""
McIntosh A/V processor device, backed by a persistent TCP control connection.

State is kept up to date from two sources that share one parser:

* unsolicited messages the processor pushes when anything changes (front panel,
  IR remote, another controller), giving near-instant updates, and
* a slow poll that re-reads everything, as a safety net for any missed push.
"""

import asyncio
import logging
from asyncio import AbstractEventLoop

from const import (
    DEFAULT_POLL_INTERVAL,
    MAX_VOLUME,
    SOURCES,
    McIntoshConfig,
)
from protocol import McIntoshProtocol, McIntoshProtocolError
from ucapi import media_player
from ucapi_framework import BaseIntegrationDriver, PersistentConnectionDevice
from ucapi_framework.helpers import MediaPlayerAttributes, RemoteAttributes

_LOG = logging.getLogger(__name__)


def _in_parens(message: str) -> str:
    """Return the argument of a message like ``!VOL(28)`` -> ``28``."""
    return message.split("(", 1)[1].split(")", 1)[0]


# Queried on every poll. Each reply is fed through the same parser as the
# unsolicited pushes, so there is exactly one place that interprets device state.
_POLL_COMMANDS = ("!POWER?", "!VOL?", "!MUTE?", "!SRC?")


class McIntoshDevice(PersistentConnectionDevice):
    """A McIntosh MX-series processor."""

    def __init__(
        self,
        device_config: McIntoshConfig,
        loop: AbstractEventLoop | None = None,
        config_manager=None,
        driver: BaseIntegrationDriver | None = None,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
    ) -> None:
        """Create instance."""
        super().__init__(
            device_config, loop, config_manager=config_manager, driver=driver
        )
        self._device_config: McIntoshConfig = device_config
        self._poll_interval = poll_interval
        self._protocol: McIntoshProtocol | None = None

        self._state: media_player.States = media_player.States.UNKNOWN
        self._volume: int = 0
        self._muted: bool = False
        self._source: str = ""

    # -- Identity ------------------------------------------------------------

    @property
    def identifier(self) -> str:
        """Return the device identifier."""
        if not self._device_config.identifier:
            raise ValueError("Instance not initialized, no identifier available")
        return self._device_config.identifier

    @property
    def name(self) -> str:
        """Return the device name."""
        return self._device_config.name

    @property
    def address(self) -> str | None:
        """Return the device address."""
        return self._device_config.address

    @property
    def log_id(self) -> str:
        """Return a log identifier."""
        return self._device_config.name or self._device_config.identifier

    # -- Shared state --------------------------------------------------------

    @property
    def state(self) -> media_player.States:
        """Return the current power state."""
        return self._state

    @property
    def volume(self) -> int:
        """Return the current volume (0-99)."""
        return self._volume

    @property
    def muted(self) -> bool:
        """Return whether the processor is muted."""
        return self._muted

    @property
    def source(self) -> str:
        """Return the current source name."""
        return self._source

    @property
    def source_list(self) -> list[str]:
        """Return the selectable source names, with any custom names applied."""
        return [self._source_name(source_id) for source_id in sorted(SOURCES)]

    def _source_name(self, source_id: int) -> str:
        """Return the configured name for a source id, else the factory name."""
        custom = self._device_config.sources.get(source_id)
        return custom or SOURCES.get(source_id, f"Source {source_id}")

    def _source_id(self, name: str) -> int | None:
        """Return the source id for a source name, or None if unknown."""
        for source_id in SOURCES:
            if self._source_name(source_id) == name:
                return source_id
        return None

    # -- Entity attribute accessors ------------------------------------------

    def get_media_player_attributes(
        self, device_id: str
    ) -> MediaPlayerAttributes | None:
        """Return current MediaPlayer attributes."""
        if device_id != self.identifier:
            return None
        return MediaPlayerAttributes(
            STATE=self._state,
            VOLUME=self._volume,
            MUTED=self._muted,
            SOURCE=self._source,
            SOURCE_LIST=self.source_list,
        )

    def get_remote_attributes(self, device_id: str) -> RemoteAttributes | None:
        """Return current Remote attributes.

        The Remote entity maps device.state to remote.States itself, so no state
        is carried here.
        """
        if device_id != self.identifier:
            return None
        return RemoteAttributes(STATE=None)

    # -- Connection lifecycle ------------------------------------------------

    async def establish_connection(self) -> McIntoshProtocol:
        """Open the control connection and read the processor's current state."""
        protocol = McIntoshProtocol(
            self._device_config.address,
            self._device_config.port,
            on_event=self._handle_message,
        )
        await protocol.connect()
        self._protocol = protocol

        await self._refresh()
        return protocol

    async def close_connection(self) -> None:
        """Close the control connection."""
        if self._protocol:
            await self._protocol.close()
            self._protocol = None

        self._state = media_player.States.UNAVAILABLE
        self.push_update()

    async def maintain_connection(self) -> None:
        """
        Block for the life of the connection.

        Runs the socket reader alongside the safety-net poll; whichever finishes
        first (always the reader, on disconnect) tears the other down and returns,
        handing control back to the framework's reconnect/backoff loop.
        """
        if self._protocol is None:
            raise McIntoshProtocolError("Not connected")

        connection = asyncio.create_task(self._protocol.wait_closed())
        poller = asyncio.create_task(self._poll_loop())

        done, pending = await asyncio.wait(
            (connection, poller), return_when=asyncio.FIRST_COMPLETED
        )

        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Surface whatever ended the connection so the framework backs off and
        # reconnects rather than treating this as a clean shutdown.
        for task in done:
            task.result()

    async def _poll_loop(self) -> None:
        """Re-read device state periodically, in case a push was missed."""
        while True:
            await asyncio.sleep(self._poll_interval)
            try:
                await self._refresh()
            except (McIntoshProtocolError, TimeoutError) as err:
                _LOG.warning("[%s] Poll failed: %s", self.log_id, err)

    async def _refresh(self) -> None:
        """Query every piece of state we track and push the result."""
        for command in _POLL_COMMANDS:
            reply = await self._protocol.send(command)
            if reply:
                self._handle_message(reply, push=False)

        self.push_update()

    # -- Message handling ----------------------------------------------------

    def _handle_message(self, message: str, push: bool = True) -> None:
        """
        Apply one device message to the local state.

        Handles both replies to our own queries and the unsolicited messages the
        processor pushes when its state is changed by someone else, since the two
        are the same messages.
        """
        try:
            changed = self._apply(message)
        except (ValueError, IndexError):
            _LOG.debug("[%s] Unparsable message: %s", self.log_id, message)
            return

        if changed and push:
            self.push_update()

    def _apply(self, message: str) -> bool:
        """Update state from one message. Return True if anything changed."""
        if message.startswith("!POWER("):
            state = (
                media_player.States.ON
                if _in_parens(message) == "1"
                else media_player.States.OFF
            )
            return self._set("_state", state)

        if message.startswith("!VOL("):
            return self._set("_volume", int(_in_parens(message)))

        # Mute is reported as !MUTEON / !MUTEOFF, not !MUTE(0|1).
        if message.startswith("!MUTEON"):
            return self._set("_muted", True)
        if message.startswith("!MUTEOFF"):
            return self._set("_muted", False)
        if message.startswith("!MUTE("):
            return self._set("_muted", _in_parens(message) == "1")

        # e.g. !SRC(7)"Apple TV" -- prefer the processor's own label, which the
        # user may have renamed on the unit itself.
        if message.startswith("!SRC("):
            source_id = int(_in_parens(message))
            label = message.split(")", 1)[1].strip().strip('"')
            return self._set("_source", label or self._source_name(source_id))

        _LOG.debug("[%s] Ignoring message: %s", self.log_id, message)
        return False

    def _set(self, attr: str, value) -> bool:
        """Assign an attribute, returning True if the value actually changed."""
        if getattr(self, attr) == value:
            return False
        setattr(self, attr, value)
        return True

    # -- Commands ------------------------------------------------------------

    async def _send(self, command: str, wait_for_reply: bool = True) -> str | None:
        """Send a command, tolerating a dropped connection."""
        if self._protocol is None:
            raise McIntoshProtocolError(f"[{self.log_id}] Not connected")
        return await self._protocol.send(command, wait_for_reply=wait_for_reply)

    async def power_on(self) -> None:
        """Turn the processor on."""
        await self._send("!PON")

    async def power_off(self) -> None:
        """Turn the processor off."""
        await self._send("!POFF")

    async def power_toggle(self) -> None:
        """Toggle power."""
        await self._send("!PTOGGLE")

    async def set_volume(self, level: int) -> None:
        """Set the volume (0-99)."""
        await self._send(f"!VOL({max(0, min(MAX_VOLUME, int(level)))})")

    async def volume_up(self) -> None:
        """Raise the volume by the configured step."""
        await self._send(f"!VOL+({self._device_config.volume_step})")

    async def volume_down(self) -> None:
        """Lower the volume by the configured step."""
        await self._send(f"!VOL-({self._device_config.volume_step})")

    async def mute_toggle(self) -> None:
        """Toggle mute."""
        await self._send("!MUTE")

    async def set_mute(self, muted: bool) -> None:
        """Set mute on or off."""
        await self._send("!MUTEON" if muted else "!MUTEOFF")

    async def select_source(self, name: str) -> None:
        """Select an input by name."""
        source_id = self._source_id(name)
        if source_id is None:
            raise ValueError(f"Unknown source: {name}")
        await self._send(f"!SRC({source_id})")

    async def send_raw(self, command: str) -> str | None:
        """Send a raw protocol command (used by the remote entity)."""
        return await self._send(command)
