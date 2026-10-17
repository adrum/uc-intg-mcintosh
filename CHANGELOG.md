# Changelog

## v0.1.1

- Commands are now fire-and-forget: the entity updates optimistically and the device state is no longer re-read after every command. Pressing volume up/down repeatedly is no longer slow (it previously stalled 1.7-5.7s per press while a state re-read held the connection). An occasional poll still corrects the state.

## v0.1.0

- Initial release: media player and remote entities for McIntosh MX-series A/V processors (MX160, MX170, MX180) over IP.
