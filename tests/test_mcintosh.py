"""Device tests: state parsing, source naming, and commands."""

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
    assert fake.source == 0
    assert device.source == "Blu-ray"


async def test_select_unknown_source_is_rejected(device):
    """An unknown source name is a bad request, not a silent no-op."""
    with pytest.raises(ValueError):
        await device.select_source("Betamax")


async def test_commands_reach_the_device_and_refresh_state(device, fake):
    """
    A command updates the entity without waiting for the next poll.

    The processor never announces what a command changed, so the device re-reads
    its state after each one.
    """
    await device.power_off()
    assert fake.power is False
    assert device.state == media_player.States.OFF

    await device.set_volume(42)
    assert fake.volume == 42
    assert device.volume == 42

    await device.set_mute(True)
    assert fake.muted is True
    assert device.muted is True


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
