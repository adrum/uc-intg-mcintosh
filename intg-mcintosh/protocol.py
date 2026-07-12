"""
Asyncio protocol for McIntosh A/V processors (MX160/MX170/MX180).

The processor speaks a line-based ASCII protocol over TCP port 84 (and over
RS232, which is typically bridged to TCP by a serial adapter).

Protocol notes, all verified against a real MX160:

* Commands and replies are terminated by CR (``\\r``).
* ``!VERB(2)`` sets the connection's verbosity. Verbosity is **per-connection**,
  so raising it here does not disturb other controllers (e.g. a Control4 driver)
  talking to the same processor.
* A connection starts at verbosity 0, where the device answers nothing at all.
  ``!VERB(2)`` is therefore the command that enables replies, and the device does
  **not** acknowledge it -- it must be sent fire-and-forget.
* At verbosity 2 the device echoes each command back as ``#CMD`` immediately
  before sending the real ``!REPLY``, so a single ``!PING?`` yields
  ``#PING?\\r!PONG\\r``. Echoes are discarded.
* Only **query** commands get a ``!`` reply. A set command such as ``!VOL(15)``
  is answered with the echo alone, so waiting for a reply to one blocks until the
  timeout.
* The device does **not** push state changes. An idle connection at verbosity 2
  hears nothing when the volume is changed on another connection, so callers must
  poll.

Replies do not carry a request id, so a reply is correlated to its command by
matching the command's leading token (see :func:`_expected_reply_prefix`). Any
``!`` line that does not answer the in-flight command is handed to the event
callback rather than mistaken for the reply -- which costs nothing today, and
keeps the protocol correct on any model that does push.
"""

import asyncio
import logging
import time
from collections.abc import Callable

_LOG = logging.getLogger(__name__)

COMMAND_EOL = "\r"
RESPONSE_EOL = "\r"
ECHO_PREFIX = "#"

# Only query commands produce a '!' reply; set commands are answered with the
# echo alone.
QUERY_SUFFIX = "?"

DEFAULT_PORT = 84
DEFAULT_TIMEOUT = 2.0

# Sets verbosity to "maximum": command echo plus unsolicited status pushes.
CONNECTION_INIT = "!VERB(2)"

# Commands whose reply token differs from the command token.
_REPLY_OVERRIDES = {
    "!PING?": "!PONG",
}


def _expected_reply_prefix(command: str) -> str:
    """
    Return the leading token a reply to ``command`` must start with.

    ``!VOL?`` -> ``!VOL``, which matches ``!VOL(28)``.
    ``!MUTE?`` -> ``!MUTE``, which matches both ``!MUTEOFF`` and ``!MUTE(0)``.
    ``!SRC(3)`` -> ``!SRC``, which matches ``!SRC(3)"Apple TV"``.
    """
    if override := _REPLY_OVERRIDES.get(command):
        return override

    token = command
    for delimiter in ("(", "?", "+", "-"):
        token = token.split(delimiter, 1)[0]
    return token


class McIntoshProtocolError(Exception):
    """Raised when the protocol connection fails or is closed."""


class McIntoshProtocol:
    """Line-based async client for a McIntosh processor over TCP."""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        *,
        on_event: Callable[[str], None] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        min_time_between_commands: float = 0.4,
    ) -> None:
        """
        Create a protocol client.

        :param on_event: called with each unsolicited ``!`` message the device
            pushes (e.g. ``!VOL(29)`` when the volume is changed from the front
            panel or another controller).
        """
        self._host = host
        self._port = port
        self._on_event = on_event
        self._timeout = timeout
        self._min_time_between_commands = min_time_between_commands

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._last_send = 0.0

        # In-flight command awaiting a reply, and the token that reply must start
        # with. Commands are serialised by ``_lock``, so at most one is pending.
        self._pending: asyncio.Future[str] | None = None
        self._pending_prefix: str | None = None

    @property
    def is_connected(self) -> bool:
        """Return True while the socket is open."""
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        """Open the socket, start reading, and raise the connection to verbosity 2."""
        _LOG.debug("Connecting to %s:%s", self._host, self._port)
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self._host, self._port), self._timeout
        )

        # Replies are delivered by the reader task, so it must be running before
        # any command is sent -- including the init command below.
        self._reader_task = asyncio.create_task(self._read_loop())

        # The device answers nothing until verbosity is raised, and it does not
        # acknowledge the command that raises it -- so do not wait for a reply.
        await self.send(CONNECTION_INIT, wait_for_reply=False)
        _LOG.debug("Connected to %s:%s", self._host, self._port)

    async def close(self) -> None:
        """Close the socket and stop reading."""
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        self._reader_task = None

        if self._writer is None:
            return

        self._writer.close()
        try:
            await self._writer.wait_closed()
        except (OSError, asyncio.CancelledError):  # already torn down
            pass
        finally:
            self._reader = None
            self._writer = None

    async def wait_closed(self) -> None:
        """
        Block until the connection drops.

        Re-raises whatever ended the reader, so the caller can reconnect.
        """
        if self._reader_task is None:
            raise McIntoshProtocolError("Not connected")
        await self._reader_task

    async def send(
        self, command: str, wait_for_reply: bool | None = None
    ) -> str | None:
        """
        Send a command and return its reply, or None if no reply is expected.

        Only query commands (``!VOL?``) get a ``!`` reply. The device answers a
        set command (``!VOL(15)``) with the echo alone, so waiting on one would
        block until the timeout.

        :raises McIntoshProtocolError: if the connection is not open.
        :raises TimeoutError: if no matching reply arrives within the timeout.
        """
        if wait_for_reply is None:
            wait_for_reply = command.endswith(QUERY_SUFFIX)

        if not self.is_connected:
            raise McIntoshProtocolError(f"Not connected to {self._host}:{self._port}")

        async with self._lock:
            await self._throttle()

            loop = asyncio.get_running_loop()
            if wait_for_reply:
                self._pending = loop.create_future()
                self._pending_prefix = _expected_reply_prefix(command)

            _LOG.debug("Sending: %s", command)
            self._last_send = time.monotonic()
            self._writer.write((command + COMMAND_EOL).encode("ascii"))
            await self._writer.drain()

            if not wait_for_reply:
                return None

            try:
                return await asyncio.wait_for(self._pending, self._timeout)
            except asyncio.TimeoutError:
                _LOG.warning(
                    "Timeout waiting for a %s reply to %s (%ss)",
                    self._pending_prefix,
                    command,
                    self._timeout,
                )
                raise
            finally:
                self._pending = None
                self._pending_prefix = None

    async def _read_loop(self) -> None:
        """Consume the socket until it closes, dispatching every line."""
        if self._reader is None:
            raise McIntoshProtocolError("Not connected")

        eol = RESPONSE_EOL.encode("ascii")

        while True:
            try:
                raw = await self._reader.readuntil(eol)
            except (
                asyncio.IncompleteReadError,
                ConnectionResetError,
                OSError,
            ) as err:
                raise McIntoshProtocolError(f"Connection lost: {err}") from err

            line = raw.decode("ascii", errors="ignore").strip()
            if line:
                self._dispatch(line)

    def _dispatch(self, line: str) -> None:
        """Route one received line to the pending command or the event callback."""
        # The device echoes every command back before replying to it.
        if line.startswith(ECHO_PREFIX):
            _LOG.debug("Ignoring echoed command: %s", line)
            return

        pending = self._pending
        if (
            pending is not None
            and not pending.done()
            and self._pending_prefix
            and line.startswith(self._pending_prefix)
        ):
            _LOG.debug("Received: %s", line)
            pending.set_result(line)
            return

        # No command is in flight, or this line does not answer the one that is:
        # the device volunteered a status change.
        _LOG.debug("Unsolicited event: %s", line)
        if self._on_event:
            self._on_event(line)

    async def _throttle(self) -> None:
        """Space out commands; the processor drops them if pushed too hard."""
        delta = time.monotonic() - self._last_send
        if delta < self._min_time_between_commands:
            await asyncio.sleep(self._min_time_between_commands - delta)
