"""Protocol tests, driven against a fake processor that behaves like real hardware."""

import asyncio

import pytest
from protocol import McIntoshProtocol, _expected_reply_prefix


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("!VOL?", "!VOL"),
        ("!MUTE?", "!MUTE"),  # matches both !MUTEOFF and !MUTE(0)
        ("!SRC?", "!SRC"),
        ("!POWER?", "!POWER"),
        ("!DEVICE?", "!DEVICE"),
        ("!PING?", "!PONG"),  # the one command whose reply token differs
        ("!SRC(3)", "!SRC"),
        ("!VOL+(1)", "!VOL"),
        ("!TRIMTREB?", "!TRIMTREB"),  # matches !TRIMTREBLE( on MX170+
    ],
)
def test_expected_reply_prefix(command, expected):
    """A reply is matched to its command by leading token."""
    assert _expected_reply_prefix(command) == expected


async def test_query_returns_reply_not_echo(protocol):
    """The device echoes '#PING?' before '!PONG'; the echo is not the reply."""
    assert await protocol.send("!PING?") == "!PONG"
    assert await protocol.send("!DEVICE?") == "!DEVICE(MX160)"


async def test_mute_is_reported_as_muteon_muteoff(protocol):
    """Mute comes back as !MUTEON/!MUTEOFF, never !MUTE(0|1)."""
    assert await protocol.send("!MUTE?") == "!MUTEOFF"
    await protocol.send("!MUTEON")
    assert await protocol.send("!MUTE?") == "!MUTEON"


async def test_set_command_does_not_wait_for_a_reply(protocol, fake):
    """
    A set command is answered with the echo alone.

    Awaiting a reply to one would block for the full timeout, so a setter must
    return promptly -- and must still have reached the device.
    """
    protocol._timeout = 1.0

    # Comfortably under the timeout: if the setter is awaiting a reply that never
    # comes, this raises instead of returning.
    result = await asyncio.wait_for(protocol.send("!VOL(15)"), timeout=0.5)

    assert result is None
    await asyncio.sleep(0.05)  # let the server apply it
    assert fake.volume == 15


async def test_init_command_survives_a_silent_device(fake):
    """
    Connecting must not hang.

    The connection starts at verbosity 0, where the device answers nothing at all
    -- including the !VERB(2) that turns replies on. Awaiting a reply to it can
    never succeed.
    """
    protocol = McIntoshProtocol(
        "127.0.0.1", fake.port, timeout=1.0, min_time_between_commands=0
    )

    await asyncio.wait_for(protocol.connect(), timeout=2.0)
    await asyncio.sleep(0.05)  # let the server log the command

    assert "!VERB(2)" in fake.received
    assert await protocol.send("!PING?") == "!PONG"  # replies now flow
    await protocol.close()


async def test_unsolicited_message_is_not_mistaken_for_a_reply(protocol, fake):
    """
    A status push arriving mid-command must not be returned as that command's reply.

    Replies carry no request id, so a naive reader hands back the first line it
    sees -- which here would report the source as the volume.
    """
    events = []
    protocol._on_event = events.append

    # Hold the reply back so the push genuinely lands mid-command.
    fake.reply_delay = 0.2

    async def interrupt():
        await asyncio.sleep(0.05)
        await fake.push('!SRC(3)"Roku"')

    asyncio.create_task(interrupt())
    reply = await protocol.send("!VOL?")

    assert reply == "!VOL(28)", "an unsolicited push was returned as the reply"
    assert events == ['!SRC(3)"Roku"']


async def test_messages_on_an_idle_connection_are_events(protocol, fake):
    """With no command in flight, a message is a status push."""
    events = []
    protocol._on_event = events.append

    await fake.push("!VOL(31)")
    await fake.push("!MUTEON")
    await asyncio.sleep(0.1)

    assert events == ["!VOL(31)", "!MUTEON"]


async def test_send_on_a_closed_connection_raises(fake):
    """A command sent without a connection fails loudly rather than hanging."""
    from protocol import McIntoshProtocolError

    protocol = McIntoshProtocol("127.0.0.1", fake.port)

    with pytest.raises(McIntoshProtocolError):
        await protocol.send("!PING?")
