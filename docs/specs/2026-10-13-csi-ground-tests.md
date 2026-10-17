# CSI ground tests (before ordering more hardware)

Status: proposed. Nothing here is built or measured yet.

Purpose: use only the 3 spare ESP32-S3 boards to decide whether WiFi CSI is worth building the lamp sensing around, before buying the camera or vitals radar. Background and citations: `docs/research/2026-10-11-esp32-csi-sensing-survey.md`.

## Project context (decisions so far)

- **Product:** 3 voice-controlled lamps in the bedroom: desk lamp, ceiling light, bed lamp (circadian). Each has tunable white plus an RGB strip (party mode synced to music, "parabellum" green scene). No mic or speaker on the lamps; voice goes through the existing speaker and harness.
- **Core goal:** a reliable lamp. CSI must match a cheap mmWave radar before it drives lights-off decisions. A paper is optional, later.
- **Sensing topology:** one ESP32-S3 is the fixed transmitter (ESP-NOW broadcast); the other two are receivers, giving 2 links. All nodes stay connected to the home router (WebSocket to the harness for light commands; receivers upload CSI over UDP). More receivers (a 4th board, or the speaker as a receive-only node) add links later.
- **References (to order later):** HLK-LD2410 radar per lamp (presence reference and teacher), HLK-LD6002 on the bed lamp (breathing reference), Pi 4 (confirmed) + Camera Module 3 NoIR Wide (15-pin cable) + IR light for pose ground truth; the Pi streams, the server runs pose.
- **Compute:** `ianshomeserver` (always on) records and runs inference. MacBook M5 Pro 24 GB for training and analysis only.
- **Sites, later:** bedroom first; parents' room (no camera, scripted labels); school (written consent, including guardian if under 18).
- **Multi-person target:** zone occupancy. People counting and per-person posture are stretch goals.

## Hardware for the ground tests

| Item | Have |
|---|---|
| 3x ESP32-S3 dev boards | yes |
| USB power (wall adapters preferred; many power banks shut off at ~150-250 mA) | yes |
| Stands or tape to hold boards at lamp heights: desk ~75 cm, bed ~60 cm, ceiling ~2.2 m | improvise |
| Phone on a shelf for optional self-labelling video | yes |

Ordering decision: order the 3x LD2410 now (about $12, needed for the lamps regardless, 1-3 weeks shipping). Hold the LD6002 and the camera until these tests pass.

## Node firmware rules (`csi_node/`, new scratch ESP-IDF project)

From the survey's Espressif sources:

1. `WIFI_PS_NONE` on every node; power save is on by default after STA connect.
2. Transmitter: ESP-NOW broadcast on the router channel with `esp_now_set_peer_rate_config` set to HT20 MCS0, so every packet carries HT-LTF. Target 100 Hz per transmitter.
3. Payload: `{tx_node_id, seq, tx_esp_timer_us, role_epoch}`. Receivers align on `(tx_node_id, seq)`; no clock sync needed for packets from the same transmitter.
4. CSI config: fixed `manu_scale`/`shift`, `channel_filter_en` off. Drop the first 4 bytes when `first_word_invalid` is set.
5. Do not force RX gain (packet-loss risk on STA-connected nodes). Log AGC and FFT gain per packet (`esp_csi_gain_ctrl`) and compensate offline.
6. The CSI callback runs in the WiFi task: only enqueue there; a separate task batches frames to UDP.
7. Per-packet log fields: receiver id, tx id, seq, rx timestamp, rssi, noise floor, AGC/FFT gain, rate, sig_mode, cwb, stbc, channel, CSI bytes. Also free heap per batch.
8. Modes: `tx` (fixed transmitter) and `rx`, selected by Kconfig per board.

## Recorder and analysis

- **Recorder:** UDP receiver in `harness/cadence/sensing/` that writes one session directory per run: raw frames plus a `session.json` (node positions, test id, protocol, start time, notes). Off unless enabled, like `BenchRecorder`.
- **Labels:** timed protocol steps written into the session; discard about 5 s around each transition.
- **Analysis scripts** (run on the MacBook): per-link rate and loss report, gain and amplitude drift plots, OpenCSI-style per-link z-score baseline, breathing spectrum.

## Tests

Pass thresholds are provisional; adjust after test 1 shows what the hardware delivers.

| # | Test | Setup and protocol | Measures | Pass (provisional) |
|---|---|---|---|---|
| 1 | Plumbing | 1 tx (STA-connected), 2 rx, 1 h, room in normal use | Per-link packet rate and loss; seq alignment across receivers; effect on home WiFi and on speaker playback (listen for dropouts during the run) | >= 90 Hz per link sustained; loss < 5%; no audible speaker dropouts |
| 2 | Empty-room baseline | Room empty overnight (>= 6 h) | Per-link noise floor, AGC changes, amplitude drift vs time of day | Characterize only; produces the baseline every later test needs |
| 3 | Walk in / out | Timed script: 2 min empty, 1 min walk around, 2 min empty; repeat 5x | Motion detection with per-link z-score | Every walk period detected; no false detections in empty periods |
| 4 | **Still person vs empty** (key test) | Timed script: 5 min empty, 5 min sitting still at desk, 5 min empty, 5 min lying still on bed; repeat 3x | Can CSI tell a still person from an empty room, per link and fused | 1-min windows separate still-person from empty with AUC >= 0.9 on at least one link |
| 5 | Breathing | Sit still near one link 3x 5 min; count your own breaths per 60 s window | Breathing peak in 0.1-0.5 Hz spectrum vs manual count | Error <= 2 breaths/min in >= 70% of windows |
| 6 | Endurance | 1 tx, 2 rx, 24 h unattended | Rate, loss, reconnects, heap over a full day | No node crashes or stalls; rate stays within test 1 pass |

## Decision after the tests

- **Tests 1, 2 and 4 pass:** order the camera (and LD6002 if test 5 is promising), then design the lamps and the `lamp` plugin.
- **Test 4 fails:** the radar becomes the primary presence sensor for lighting. CSI stays an experiment. Hold the camera purchase until it is clear what CSI is good for.
- **Test 1 fails:** fix the firmware or channel setup before any sensing conclusions.

Record results in `docs/preflight/csi-ground-tests.md`: numbers, plots, and failures kept, like the other preflight notes.

## Open questions

- Board placement in the bedroom: with only 2 links, both should cross the areas that matter (bed and desk). Suggested start: transmitter at ceiling height, one receiver at the desk, one at the bed. Record positions in each `session.json`.
- Which router channel is in use, and does it change on its own (auto channel)? A channel change mid-session breaks the baseline; consider pinning it.
