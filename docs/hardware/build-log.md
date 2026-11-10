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

## 2026-11-10: lamp 24 V bench test passed, ready to mount (`lamp/`)
- Board / project dir: ESP32-S3 #2 (`bedroom-ceiling`), `lamp/`, 24 V PSU via buck, USB unplugged.
- What changed or was tried: channel checks from the chat page via Jev `light.preset` (warm, cool, dim, night, on, off, 22:00-22:20 KST), then both channels at 100 % for over 10 min.
- Result: all presets returned `ok`. Heat by touch after 10+ min at 100/100: MOSFETs barely warm, LED strip warm but comfortable, ESP32 module warm (normal for WiFi always on), buck converter not hot. No TC4427 needed. PSU current not measured.
- Next: mount on ceiling (power off; keep MOSFETs, buck and ESP32 ventilated and off the strip; strain-relieve 24 V; fuse on the 24 V line). Reserve 172.30.1.28 in DHCP.
- Links: `harness/cadence/lamp.py`, inventory "Ceiling lamp wiring"

## 2026-11-10: lamp first light on 24 V, 100 % blink fixed (`lamp/`)
- Board / project dir: ESP32-S3 #2 (`bedroom-ceiling`), `lamp/`, powered from 24 V PSU (60-150 W) via buck, USB unplugged.
- What changed or was tried: strip first stayed dark: harness routed `light.set` with empty args (fixed in `99b06c0`). Then it blinked at 100 %. Step test from Cadence: 10 % warm steady, 100 % warm blinking, 99 % warm steady; ESP32 never reset (one steady `/peer` link, ping stable), so not a supply cut-out. Cause: ESP32-S3 LEDC cannot output duty 2^14 at its max 14-bit resolution (IDF `ledc.c` note). Capped duty at 2^14-1 (`9cddd3e`), pushed by OTA (power-cycle of 24 V).
- Result: OTA 10:48:20 full GET, 10:48:41 same-image abort, link up. 100 % warm steady at 12:29. Warm channel works 10-100 %.
- Next: cool-only check, both at 100 % for 10 min with PSU current and MOSFET temperature by touch (still not done), then ceiling mount.
- Links: `lamp/main/lamp.c`, `harness/cadence/peers.py`

## 2026-11-10: lamp first OTA, reconnect-after-close fix (`lamp/`)
- Board / project dir: ESP32-S3 #2 (`bedroom-ceiling`), `lamp/`
- What changed or was tried: lamp had dropped off `/peer` after a 09:50 USB replug and never retried. Cause: `esp_websocket_client` 2.0.0 stops for good after a clean server close (here likely the `peer_id in use` rejection while Cadence still held the stale socket) unless `enable_close_reconnect` is set. Fixed in `lamp.c` and `voice_chat.c` (commit `89bf2cb`). Lamp image built on ianshomeserver, served with `python3 -m http.server 8772 --bind 172.30.1.28` from a directory holding only `lamp.bin`, then lamp replugged.
- Result: 10:15:57 full GET of `lamp.bin` (980384 bytes), flash, restart; 10:16:19 new image re-checked OTA, saw same image, aborted (expected); `/peer` link up and welcomed about 10:16:2x. First OTA on this board works end to end.
- Next: voice_chat board #1 was not on the LAN (no ARP reply); power it and USB-flash `89bf2cb`. voice_chat has no OTA (single-app partition) until it gets the lamp's two-slot table and `ota_check`.
- Links: `lamp/main/lamp.c`, `voice_chat/main/voice_chat.c`

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
