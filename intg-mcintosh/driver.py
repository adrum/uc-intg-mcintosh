#!/usr/bin/env python3
"""Unfolded Circle integration driver for McIntosh A/V processors."""

import asyncio
import logging
import os

from const import McIntoshConfig
from mcintosh import McIntoshDevice
from media_player import McIntoshMediaPlayer
from remote import McIntoshRemote
from setup import McIntoshSetupFlow
from ucapi_framework import BaseConfigManager, BaseIntegrationDriver, get_config_path


async def main():
    """Start the integration driver."""
    logging.basicConfig()

    level = os.getenv("UC_LOG_LEVEL", "INFO").upper()
    for module in ("driver", "mcintosh", "protocol", "setup", "media_player", "remote"):
        logging.getLogger(module).setLevel(level)

    driver = BaseIntegrationDriver(
        device_class=McIntoshDevice,
        entity_classes=[McIntoshMediaPlayer, McIntoshRemote],
    )

    driver.config_manager = BaseConfigManager(
        get_config_path(driver.api.config_dir_path),
        driver.on_device_added,
        driver.on_device_removed,
        config_class=McIntoshConfig,
    )

    await driver.register_all_device_instances()

    setup_handler = McIntoshSetupFlow.create_handler(driver)
    await driver.api.init("driver.json", setup_handler)

    await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
