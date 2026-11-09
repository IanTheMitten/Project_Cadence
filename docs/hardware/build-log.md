# Hardware build log

Newest first. Entry template:

```
## YYYY-MM-DD: short title
- Board / project dir:
- What changed or was tried:
- Result (numbers with units, conditions):
- Next:
- Links: commit, spec section, measurement file
```

## 2026-11-09: ceiling lamp board first flash (`lamp/`)
- Board / project dir: ESP32-S3 #2 (QFN56 rev v0.2, MAC `20:6e:f1:d6:e8:bc`, 8 MB flash, CH34x USB-serial), `lamp/`
- What changed or was tried: first USB flash of `lamp/` (commit `accc125`: 2 kHz 14-bit PWM). 24 V off, USB power only. Peer and OTA URLs overridden to LAN IP `172.30.1.28` in `lamp/sdkconfig.defaults.local`, because the board's DNS cannot resolve the MagicDNS name `ianshomeserver`.
- Result: flash hash verified; boot restores cool=50.0 warm=50.0 at about 0.5 s, before WiFi; IP 172.30.1.72 at about 4.6 s; `peer link up` then `welcomed by Cadence` at about 4.9 s. OTA check fails fast (no server on 8772; expected). Strip not yet lit: 24 V was off.
- Next: bench test on 24 V (warm only / cool only / off from the chat page; both channels at 100 % for 10 min, MOSFET temperature by touch), then mount on the ceiling. Reserve 172.30.1.28 in the router's DHCP (speaker and lamp both depend on it).
- Links: `lamp/main/lamp.c`, inventory "Ceiling lamp wiring"

## 2026-10-17: log created, state backfilled from repo
- Board / project dir: speaker + mic board, `voice_chat/`
- What changed or was tried: no bench work. Backfilled from git history and docs.
- Known state (from commits and specs, not re-measured today):
  - Speaker TX path and INMP441 mic RX path run together in one image (`voice_chat/`), as a `/session` WebSocket client of the harness.
  - Latest firmware fixes: WiFi disconnect reason logging (`3863e94`); session socket kept serviced during turns, music paced, playback prebuffered on board (`ddedcb5`).
  - Design values in firmware (derived from code): 64 KB ring = about 371 ms; prebuffer 200 ms; mic frame 16 ms. See `docs/specs/2026-10-07-speaker-hardware-improvements.md`.
  - Not yet done: acoustic characterization, enclosure, echo baseline, firmware instrumentation (all `planned`).
  - CSI ground tests on the 3 spare boards: `planned` (`docs/specs/2026-10-13-csi-ground-tests.md`).
- Next: add real bench entries from here on; fill gaps in `inventory.md` (amp part, speaker, power).
