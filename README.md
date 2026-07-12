# McIntosh integration for Unfolded Circle Remote Two/3

Control a McIntosh MX-series A/V processor (MX160, MX170, MX180) from an
Unfolded Circle remote over IP.

## Entities

- **Media player** — power, volume, mute, source selection across all 26 inputs.
- **Remote** — button mappings plus simple commands for Zone 2, loudness, bass,
  treble and lipsync.

## Setup

Enter the processor's IP address. Control over IP must be enabled on the unit,
which listens on TCP port 84 by default. Setup verifies the connection with
`!PING?` and reads the model from `!DEVICE?`.

## Protocol notes

The processor speaks a line-based ASCII protocol terminated by CR. A few
behaviours are worth knowing, all verified against an MX160:

- A connection begins at verbosity 0, where the device answers nothing.
  `!VERB(2)` is what enables replies, and the device does **not** acknowledge it,
  so it is sent fire-and-forget on connect.
- Verbosity is **per-connection**. Raising it does not affect other controllers
  (e.g. a Control4 driver) talking to the same processor.
- At verbosity 2 the device echoes each command back as `#CMD` before sending the
  real `!REPLY`, so `!PING?` yields `#PING?\r!PONG\r`. Echoes are discarded.
- Mute is reported as `!MUTEON` / `!MUTEOFF`, not `!MUTE(0|1)`.

Replies carry no request id, so each reply is matched to its command by leading
token. Any `!` message that does not answer the command in flight is treated as
an unsolicited status push and applied to the device state, which is what makes
state updates realtime rather than poll-driven. A slow poll runs behind that as a
safety net.

## Development

```bash
pip install -r requirements.txt
UC_LOG_LEVEL=DEBUG python intg-mcintosh/driver.py
```

## Tests

```bash
pip install -r requirements.txt -r test-requirements.txt
pytest
```

The suite runs against `tests/fake_mcintosh.py`, a server that reproduces the
protocol quirks listed above — including starting each connection at verbosity 0,
answering set commands with the echo alone, and reporting mute as
`!MUTEON`/`!MUTEOFF`. Each of those behaviours broke a real implementation before
it was understood, so the fake exists to keep them from breaking one again.

## Docker

```bash
docker build -t uc-intg-mcintosh .
docker run -v $(pwd)/config:/config -p 9090:9090 uc-intg-mcintosh
```
