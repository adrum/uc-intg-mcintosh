"""McIntosh integration constants."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Final

from ucapi.media_player import States as MediaStates
from ucapi.remote import States as RemoteStates

DEFAULT_PORT: Final = 84

# The processor drops commands that arrive faster than this.
MIN_TIME_BETWEEN_COMMANDS: Final = 0.4

# How long to wait after the last command in a burst before re-reading state.
# Long enough that holding a volume button does not trigger a refresh per press.
RECONCILE_DELAY: Final = 1.0

# The processor does not push state changes, so polling is the only way to notice
# one made from the front panel, the IR remote, or another controller. State after
# our own commands is refreshed immediately, so this only governs how quickly an
# outside change is picked up.
DEFAULT_POLL_INTERVAL: Final = 10


@dataclass
class McIntoshConfig:
    """McIntosh processor configuration."""

    identifier: str
    """Unique identifier of the device (model + address)."""
    name: str
    """Friendly name of the device."""
    address: str
    """IP address of the processor, or of the RS232-to-IP bridge."""
    port: int = DEFAULT_PORT
    """TCP control port."""
    model: str = "MX160"
    """Model name as reported by !DEVICE?."""
    sources: dict[int, str] = field(default_factory=dict)
    """Custom source names, keyed by source id. Overrides SOURCES."""
    volume_step: int = 1
    """Volume increment for a single volume-up/down press."""


class SimpleCommands(str, Enum):
    """Commands exposed to the remote beyond the media-player features."""

    ZONE2_ON = "Zone 2 On"
    ZONE2_OFF = "Zone 2 Off"
    ZONE2_VOLUME_UP = "Zone 2 Volume Up"
    ZONE2_VOLUME_DOWN = "Zone 2 Volume Down"
    ZONE2_MUTE_TOGGLE = "Zone 2 Mute Toggle"
    LOUDNESS_ON = "Loudness On"
    LOUDNESS_OFF = "Loudness Off"
    BASS_UP = "Bass Up"
    BASS_DOWN = "Bass Down"
    TREBLE_UP = "Treble Up"
    TREBLE_DOWN = "Treble Down"
    LIPSYNC_UP = "Lipsync Up"
    LIPSYNC_DOWN = "Lipsync Down"


# Source inputs. Identical across MX160/MX170/MX180.
SOURCES: Final[dict[int, str]] = {
    0: "HDMI 1",
    1: "HDMI 2",
    2: "HDMI 3",
    3: "HDMI 4",
    4: "HDMI 5",
    5: "HDMI 6",
    6: "HDMI 7",
    7: "HDMI 8",
    8: "Audio Return",
    9: "SPDIF 1 (Optical)",
    10: "SPDIF 2 (Optical)",
    11: "SPDIF 3 (Optical)",
    12: "SPDIF 4 (Optical)",
    13: "SPDIF 5 (AES/EBU)",
    14: "SPDIF 6 (Coaxial)",
    15: "SPDIF 7 (Coaxial)",
    16: "SPDIF 8 (Coaxial)",
    17: "USB Audio",
    18: "Analog 1",
    19: "Analog 2",
    20: "Analog 3",
    21: "Analog 4",
    22: "Balanced 1",
    23: "Balanced 2",
    24: "Phono",
    25: "8 Channel Analog",
}

# Volume is reported and set on a 0-99 scale.
MAX_VOLUME: Final = 99

MCINTOSH_REMOTE_STATE_MAPPING: Final[dict[MediaStates, RemoteStates]] = {
    MediaStates.UNKNOWN: RemoteStates.UNKNOWN,
    MediaStates.UNAVAILABLE: RemoteStates.UNAVAILABLE,
    MediaStates.OFF: RemoteStates.OFF,
    MediaStates.ON: RemoteStates.ON,
    MediaStates.STANDBY: RemoteStates.OFF,
}
