"""Setup flow for the McIntosh integration."""

import logging
from typing import Any

from const import DEFAULT_PORT, McIntoshConfig
from protocol import McIntoshProtocol, McIntoshProtocolError
from ucapi import IntegrationSetupError, RequestUserInput, SetupError
from ucapi_framework import BaseSetupFlow

_LOG = logging.getLogger(__name__)


class McIntoshSetupFlow(BaseSetupFlow[McIntoshConfig]):
    """Setup flow for McIntosh processors, by IP address."""

    def get_manual_entry_form(self) -> RequestUserInput:
        """Return the manual entry form."""
        return RequestUserInput(
            {"en": "McIntosh Setup"},
            [
                {
                    "id": "info",
                    "label": {"en": "Setup Information"},
                    "field": {
                        "label": {
                            "value": {
                                "en": (
                                    "Enter the IP address of your McIntosh processor. "
                                    "Control over IP must be enabled on the unit."
                                )
                            }
                        }
                    },
                },
                {
                    "id": "address",
                    "label": {"en": "IP Address"},
                    "field": {"text": {"value": ""}},
                },
                {
                    "id": "port",
                    "label": {"en": "Port"},
                    "field": {"text": {"value": str(DEFAULT_PORT)}},
                },
                {
                    "id": "volume_step",
                    "label": {"en": "Volume Step"},
                    "field": {"text": {"value": "1"}},
                },
            ],
        )

    async def query_device(
        self, input_values: dict[str, Any]
    ) -> McIntoshConfig | SetupError | RequestUserInput:
        """Connect to the processor and build its configuration."""
        address = (input_values.get("address") or "").strip()
        if not address:
            return self.get_manual_entry_form()

        port = _to_int(input_values.get("port"), DEFAULT_PORT)
        volume_step = max(1, _to_int(input_values.get("volume_step"), 1))

        _LOG.debug("Connecting to McIntosh at %s:%s", address, port)

        protocol = McIntoshProtocol(address, port)
        try:
            await protocol.connect()

            # !PING? proves the control protocol is actually answering, not just
            # that something accepted the TCP connection.
            if await protocol.send("!PING?") != "!PONG":
                _LOG.error("No !PONG from %s:%s", address, port)
                return SetupError(IntegrationSetupError.NOT_FOUND)

            model = await protocol.send("!DEVICE?")
        except (TimeoutError, McIntoshProtocolError) as err:
            _LOG.error("Cannot reach McIntosh at %s:%s: %s", address, port, err)
            return SetupError(IntegrationSetupError.CONNECTION_REFUSED)
        except OSError as err:
            _LOG.error("Connection error to %s:%s: %s", address, port, err)
            return SetupError(IntegrationSetupError.CONNECTION_REFUSED)
        except Exception as err:  # pylint: disable=broad-except
            _LOG.exception("Setup error for %s:%s: %s", address, port, err)
            return SetupError(IntegrationSetupError.OTHER)
        finally:
            await protocol.close()

        # e.g. !DEVICE(MX160)
        model_name = "McIntosh"
        if model and "(" in model:
            model_name = model.split("(", 1)[1].split(")", 1)[0]

        identifier = f"mcintosh_{model_name.lower()}_{address.replace('.', '_')}"

        if self._add_mode and self.config.contains(identifier):
            _LOG.warning("Device %s already configured", identifier)
            return SetupError(IntegrationSetupError.OTHER)

        _LOG.info("Found McIntosh %s at %s:%s", model_name, address, port)

        return McIntoshConfig(
            identifier=identifier,
            name=f"McIntosh {model_name}",
            address=address,
            port=port,
            model=model_name,
            volume_step=volume_step,
        )


def _to_int(value: Any, default: int) -> int:
    """Parse an int from a setup form field."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default
