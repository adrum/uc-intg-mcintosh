"""
A fake McIntosh processor, reproducing the real MX160's protocol behaviour.

Every quirk encoded here was observed on real hardware, and each one broke a real
implementation before it was understood:

* The connection starts at verbosity 0, where the device answers **nothing** --
  not even the ``!VERB(2)`` that raises the verbosity. Waiting for a reply to the
  init command deadlocks setup.
* At verbosity 2 the device echoes each command as ``#CMD`` before replying.
  Treating that echo as the reply makes ``!PING?`` return ``#PING?``.
* Only **queries** get a ``!`` reply. A set command is answered with the echo
  alone, so awaiting a reply to one blocks until the timeout.
* Mute is reported as ``!MUTEON`` / ``!MUTEOFF``, never ``!MUTE(0|1)``.
* The device does not push state changes unless explicitly told to here.
"""

import asyncio


class FakeMcIntosh:
    """An asyncio server that speaks the McIntosh control protocol."""

    def __init__(self) -> None:
        """Create a fake processor in a known state."""
        self.power = True
        self.volume = 28
        self.muted = False
        self.source = 7
        self.labels = {7: "Apple TV", 0: "Blu-ray"}

        self._server: asyncio.Server | None = None
        self._writers: list[asyncio.StreamWriter] = []
        self.received: list[str] = []

        # Delay between the echo and the reply. Lets a test slip an unsolicited
        # message into the window where a command is in flight.
        self.reply_delay = 0.0

    @property
    def port(self) -> int:
        """Return the ephemeral port the server bound to."""
        return self._server.sockets[0].getsockname()[1]

    async def start(self) -> None:
        """Start listening on an ephemeral port."""
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)

    async def stop(self) -> None:
        """Stop the server and drop all connections."""
        for writer in self._writers:
            writer.close()
        self._writers.clear()

        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def push(self, message: str) -> None:
        """Volunteer an unsolicited message to every connected client."""
        for writer in self._writers:
            writer.write(f"{message}\r".encode("ascii"))
            await writer.drain()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Serve one connection. Verbosity is per-connection, and starts at 0."""
        self._writers.append(writer)
        verbose = False

        try:
            while True:
                raw = await reader.readuntil(b"\r")
                command = raw.decode("ascii").strip()
                self.received.append(command)

                if command == "!VERB(2)":
                    # The command that enables replies is itself unacknowledged
                    # while the connection is still silent.
                    if verbose:
                        writer.write(b"#VERB(2)\r")
                        await writer.drain()
                    verbose = True
                    continue

                if not verbose:
                    continue  # verbosity 0: total silence

                # Echo first, always.
                writer.write(f"#{command[1:]}\r".encode("ascii"))
                await writer.drain()

                if self.reply_delay:
                    await asyncio.sleep(self.reply_delay)

                if reply := self._reply(command):
                    writer.write(f"{reply}\r".encode("ascii"))
                    await writer.drain()

        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            if writer in self._writers:
                self._writers.remove(writer)

    def _reply(self, command: str) -> str | None:
        """Return the '!' reply for a command, or None -- set commands get none."""
        # Set commands: apply the change, and answer with the echo alone.
        if command == "!PON":
            self.power = True
            return None
        if command == "!POFF":
            self.power = False
            return None
        if command == "!MUTEON":
            self.muted = True
            return None
        if command == "!MUTEOFF":
            self.muted = False
            return None
        if command.startswith("!VOL(") and command.endswith(")"):
            self.volume = int(command[5:-1])
            return None
        if command.startswith("!SRC(") and command.endswith(")"):
            self.source = int(command[5:-1])
            return None

        # Queries: echo plus a reply.
        if command == "!PING?":
            return "!PONG"
        if command == "!DEVICE?":
            return "!DEVICE(MX160)"
        if command == "!POWER?":
            return f"!POWER({1 if self.power else 0})"
        if command == "!VOL?":
            return f"!VOL({self.volume})"
        if command == "!MUTE?":
            return "!MUTEON" if self.muted else "!MUTEOFF"
        if command == "!SRC?":
            return self._src(self.source)
        if command.startswith("!SRC(") and command.endswith(")?"):
            return self._src(int(command[5:-2]))

        return None

    def _src(self, source_id: int) -> str:
        """Format a source reply, with the user's label if the input has one."""
        label = self.labels.get(source_id)
        return f'!SRC({source_id})"{label}"' if label else f"!SRC({source_id})"
