"""Device tests: state parsing, source naming, and commands."""

import asyncio

import pytest
import pytest_asyncio
from const import McIntoshConfig
from mcintosh import McIntoshDevice
from ucapi import media_player


@pytest_asyncio.fixture
async def device(fake):
    """A McIntoshDevice connected to the fake processor, fully initialised."""
    dev = McIntoshDevice(
        McIntoshConfig(
            identifier="test",
            name="McIntosh MX160",
            address="127.0.0.1",
            port=fake.port,
        ),
        command_interval=0,
    )
    await dev.establish_connection()

    # Source labels are learned in the background so they never delay startup;
    # wait for that to finish so tests see a fully initialised device.
    if dev._label_task:
        await dev._label_task

    yield dev
    await dev.close_connection()


async def test_reads_state_on_connect(device):
    """Connecting populates power, volume, mute and source."""
    assert device.state == media_player.States.ON
    assert device.volume == 28
    assert device.muted is False


async def test_source_uses_the_label_set_on_the_processor(device):
    """
    The current source must appear in source_list, by the name the user sees.

    The device reports !SRC(7)"Apple TV" -- its own label -- while the factory name
    for input 7 is "HDMI 8". If the list carries the factory name, the current
    source is absent from its own list and cannot be selected.
    """
    assert device.source == "Apple TV"
    assert device.source in device.source_list
    assert "Blu-ray" in device.source_list  # learned label for input 0
    assert "HDMI 2" in device.source_list  # unlabelled inputs keep factory names
    assert len(device.source_list) == 26


async def test_select_source_by_visible_name(device, fake):
    """Selecting the name shown in the list reaches the right input."""
    await device.select_source("Blu-ray")

    assert device.source == "Blu-ray"  # shown immediately, before the wire settles

    await asyncio.sleep(0.05)
    assert fake.source == 0


async def test_select_unknown_source_is_rejected(device):
    """An unknown source name is a bad request, not a silent no-op."""
    with pytest.raises(ValueError):
        await device.select_source("Betamax")


async def test_commands_reach_the_device(device, fake):
    """Commands are actually written to the processor."""
    await device.power_off()
    await asyncio.sleep(0.05)
    assert fake.power is False

    await device.set_volume(42)
    await asyncio.sleep(0.05)
    assert fake.volume == 42

    await device.set_mute(True)
    await asyncio.sleep(0.05)
    assert fake.muted is True


async def test_entity_updates_before_the_command_is_sent(device):
    """
    A button press moves the entity immediately, without waiting on the wire.

    The processor acknowledges a set command with nothing but an echo, so it never
    reports what changed. If the entity waited for a re-read, every press would
    cost five commands at the protocol's spacing -- about two seconds before the
    remote showed anything.
    """
    pushes = []
    original = device.push_update
    device.push_update = lambda: (pushes.append(device.volume), original())[1]

    start = device.volume
    step = device._device_config.volume_step

    await device.volume_down()

    assert pushes and pushes[0] == start - step, "volume did not update optimistically"
    assert device.volume == start - step


async def test_optimistic_volume_is_clamped(device):
    """An optimistic guess never leaves the processor's 0-99 scale."""
    device._volume = 0
    await device.volume_down()
    assert device.volume == 0

    device._volume = 99
    await device.volume_up()
    assert device.volume == 99


async def test_poll_corrects_a_wrong_guess(device, fake):
    """
    The guess is only a guess; the device gets the last word.

    If the processor ignored or clamped the command, the next periodic poll
    pulls the entity back to the truth.
    """
    device._volume = 28

    # The processor disagrees: it is really at 11.
    fake.volume = 11
    device._expect(_volume=99)
    assert device.volume == 99

    await device._refresh()

    assert device.volume == 11, "poll did not correct the optimistic guess"


async def test_a_burst_of_presses_does_not_re_read(device, fake):
    """
    Fire and forget: each press sends only its set command, with no per-press
    state re-read for the next press to stall behind.
    """
    step = device._device_config.volume_step
    fake.received.clear()

    for _ in range(4):
        await device.volume_down()

    await asyncio.sleep(0.05)
    assert fake.received == [f"!VOL-({step})"] * 4


async def test_mute_parses_muteon_muteoff(device, fake):
    """Mute is read from !MUTEON/!MUTEOFF, not !MUTE(0|1)."""
    fake.muted = True
    await device._refresh()
    assert device.muted is True

    fake.muted = False
    await device._refresh()
    assert device.muted is False


async def test_media_player_attributes(device):
    """The entity accessor reflects the device state."""
    attrs = device.get_media_player_attributes("test")

    assert attrs.STATE == media_player.States.ON
    assert attrs.VOLUME == 28
    assert attrs.MUTED is False
    assert attrs.SOURCE == "Apple TV"


async def test_attributes_for_another_device_are_none(device):
    """Attribute accessors ignore ids belonging to other devices."""
    assert device.get_media_player_attributes("someone-else") is None
