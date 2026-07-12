"""Shared test fixtures."""

import pathlib
import sys

import pytest
import pytest_asyncio

# The driver modules import each other flat (`from const import ...`), matching how
# they run under pyinstaller, so the package dir goes on the path directly.
sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parent.parent / "intg-mcintosh")
)

from fake_mcintosh import FakeMcIntosh  # noqa: E402
from protocol import McIntoshProtocol  # noqa: E402


@pytest_asyncio.fixture
async def fake():
    """A fake McIntosh processor listening on an ephemeral port."""
    server = FakeMcIntosh()
    await server.start()
    yield server
    await server.stop()


@pytest_asyncio.fixture
async def protocol(fake):
    """A protocol client connected to the fake processor.

    The real device drops commands sent faster than 0.4s apart; the fake does not,
    so the throttle is disabled to keep the suite fast.
    """
    client = McIntoshProtocol(
        "127.0.0.1", fake.port, timeout=2.0, min_time_between_commands=0
    )
    await client.connect()
    yield client
    await client.close()
