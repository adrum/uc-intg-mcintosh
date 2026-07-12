# McIntosh integration for Unfolded Circle Remote Two/3

Control a McIntosh MX-series A/V processor from an Unfolded Circle remote, over the
processor's RS232/IP control protocol.

## Requirements

- A McIntosh **MX160**, **MX170**, or **MX180** processor. All three share the same
  control protocol; only the MX160 has been tested against real hardware.
- The processor reachable over IP, listening on **TCP port 84** (the default).
- The processor on a **static IP address** (or a DHCP reservation). McIntosh processors
  have no discovery mechanism, so the integration is configured with a fixed address.

An RS232-only unit can be used through a serial-to-IP bridge, since the integration
talks to a TCP socket either way.

## Installation

1. Download the integration package (`.tar.gz`) from the [Releases page][releases].
2. Upload it via the Remote's web configurator: **Integrations → Install custom**.
3. Configure your processor through the setup wizard.

## Updating

1. Download the new integration package (`.tar.gz`) from the [Releases page][releases].
2. Remove the existing integration from the Remote (twice). Your configured activity
   settings are preserved.
3. Upload the new archive via the web configurator: **Integrations → Install custom**.
4. Configure your processor through the setup wizard.

[releases]: https://github.com/adrum/uc-intg-mcintosh/releases

## Setup

The wizard first asks whether to **restore from backup** — decline this on a first
install. Then enter:

1. The processor's **IP address**.
2. The **port**, if you have changed it from 84.
3. A **volume step**, the amount a single volume-up or volume-down press moves the
   volume. The processor's volume scale runs 0–99.

Setup verifies the connection by sending `!PING?` and reads the model from `!DEVICE?`,
so a wrong address or a unit with IP control disabled fails immediately rather than
producing a broken integration.

## Entities

| Entity | Provides |
| --- | --- |
| Media player | Power, volume (0–99), mute, and source selection across all 26 inputs |
| Remote | Physical button mappings, two UI pages, and simple commands for Zone 2, loudness, bass, treble and lipsync |

Source names are read from the processor itself, so an input you renamed on the unit
appears under that name — input 7 shows as *Apple TV* rather than *HDMI 8*.

## Behaviour worth knowing

**It will not disturb another control system.** The integration raises its connection's
verbosity so the processor will answer it, and that verbosity is **per-connection** —
verified by watching a second, independent connection stay unaffected. A Control4 or
Crestron driver talking to the same processor sees no change.

**State is polled, not pushed.** The processor does not volunteer state changes: an idle
connection hears nothing when the volume is changed from the front panel or another
controller. The integration polls every 10 seconds to notice such a change, and re-reads
state immediately after each of its own commands so the UI never lags behind its own
actions. `DEFAULT_POLL_INTERVAL` in `intg-mcintosh/const.py` controls the interval.

**Commands are paced.** The processor drops commands that arrive faster than ~0.4s
apart, so a burst of rapid key presses is spaced out rather than fired at once.
`MIN_TIME_BETWEEN_COMMANDS` in `intg-mcintosh/const.py` controls the spacing if you want
to trade responsiveness against reliability.

**Source names take a few seconds to appear.** Reading all 26 input names costs about
ten seconds at that command rate, so it happens in the background after connecting. The
source list shows factory names until it finishes.

## Protocol notes

Documented because none of it is obvious, and each point broke an implementation before
it was understood. All verified against a real MX160.

- A connection begins at **verbosity 0, where the processor answers nothing at all**.
  `!VERB(2)` is the command that enables replies — and the processor does not
  acknowledge it. It must be sent without waiting for a response, or setup deadlocks.
- At verbosity 2 the processor **echoes each command back** as `#CMD` before sending the
  real `!REPLY`, so `!PING?` yields `#PING?\r!PONG\r`. The echo is not the reply.
- **Only queries get a reply.** A set command such as `!VOL(15)` is answered with the
  echo alone, so waiting for a reply to one blocks until the timeout.
- **Mute is reported as `!MUTEON` / `!MUTEOFF`**, never `!MUTE(0|1)`.

Replies carry no request id, so each is matched to its command by leading token. Any
message that does not answer the command in flight is treated as an unsolicited status
push rather than mistaken for the reply.

## Not supported

- **No discovery.** The processor announces itself on no protocol, so the IP address is
  entered by hand.
- **Zone 2 has no entities of its own.** It is driven through simple commands on the
  remote entity, not a second media player.
- **Bass, treble, loudness, lipsync and channel trims are commands, not entities.** They
  can be sent, but their current values are not exposed as sensors or number entities.
- **No sound-mode selection.** The processor's audio modes are not read or set.

## Development

The driver can run on any machine on the same network instead of being uploaded to the
Remote, which discovers it over mDNS. This is the easier way to develop against a real
processor, since you get logs and a fast reload loop:

```bash
pip install -r requirements.txt
UC_LOG_LEVEL=DEBUG python intg-mcintosh/driver.py
```

Docker images are published to `ghcr.io/adrum/uc-intg-mcintosh`.

## Tests

```bash
pip install -r requirements.txt -r test-requirements.txt
pytest
```

The suite runs against `tests/fake_mcintosh.py`, a server that reproduces the protocol
behaviour above — including starting each connection silent, answering set commands with
the echo alone, and reporting mute as `!MUTEON`/`!MUTEOFF`. Re-introducing any of those
bugs fails the suite, which is the point: they are hardware facts that cannot be
rediscovered without an MX160 on the bench.

## Releasing

Pushing a `v*` tag runs the tests, builds the aarch64 driver binary, packages it, and
publishes a GitHub release with the `.tar.gz` attached:

```bash
git tag v0.1.0
git push origin main --tags
```

Keep `driver.json`, `pyproject.toml`, and the `CHANGELOG.md` heading on the same version
— the release notes are extracted by matching `## v<version>` in the changelog.

## Credits

Protocol behaviour was derived from [hass-mcintosh][hass] and the McIntosh model
definitions in [rsnodgrass/pyavcontrol][pyav], then corrected against a real MX160.
Project structure follows [JackJPowell/uc-intg-yamaha-avr][yamaha] and the
[`ucapi-framework`][fw] base classes.

[hass]: https://github.com/homeassistant-projects/hass-mcintosh
[pyav]: https://github.com/rsnodgrass/pyavcontrol
[yamaha]: https://github.com/JackJPowell/uc-intg-yamaha-avr
[fw]: https://pypi.org/project/ucapi-framework/

## License

Mozilla Public License 2.0 — see [LICENSE](LICENSE).
