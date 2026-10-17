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
