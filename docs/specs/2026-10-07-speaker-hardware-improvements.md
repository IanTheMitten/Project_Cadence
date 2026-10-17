# Speaker hardware improvements

Status: proposed. Nothing here is built or measured yet.

Baseline: ESP32-S3 -> I2S -> amp -> speaker (TX, `I2S_NUM_0`), INMP441 mic on `I2S_NUM_1` (RX), no enclosure design, no echo cancellation. Firmware: `voice_chat/main/voice_chat.c`.

Principle: each item is a hypothesis, a measurement, a change, and a re-measurement. Report before/after numbers, and keep failures.

## Design values already in firmware (derived from code, not measured)

| Item | Value |
|---|---|
| Playback stream | 44.1 kHz stereo s16 = 176.4 KB/s |
| Ring buffer | 64 KB = about 371 ms |
| Prebuffer | 35,280 B = 200 ms |
| DMA headroom | 8 desc x 480 frames = about 87 ms |
| Worst-case added playback latency | about 290 ms |
| Mic frame | 256 samples at 16 kHz = 16 ms; uplink 32 KB/s |
| Mic sample shift | `>> 14` of a 32-bit slot (about +12 dB vs `>> 16`) |
| Task priorities | i2s_drain 6; ws_client 5; mic_ws 5 |

`PREBUFFER_IDLE_MS` (60 ms) exists because short ack clips never reach the 200 ms prebuffer threshold. This is a found-and-fixed failure mode.

## Known gaps to close first

1. `pcm16[i] = (int16_t)(raw[i] >> 14)` has no saturation, so loud input may wrap. Verify, then clamp.
2. No instrumentation. Add: underrun counter, ring low-water mark, reconnect count with WiFi disconnect reason, RSSI beside underruns, mic noise floor (dBFS), clipping counter.
3. No end-to-end latency figure. Server stages exist (`turn_timing`, `BenchRecorder`); add firmware stages.

## Improvements, ranked by value per effort

### 1. Acoustic characterization and enclosure
- Build a sealed enclosure. Place the mic away from the driver and isolate it from vibration with foam.
- Measure frequency response with a log sweep (20 Hz to 20 kHz), recorded with a phone mic or the INMP441.
- Tune the proxy EQ (`bass=6, treble=-4` in `tools/muse_proxy.py`) against the measured curve instead of by ear.
- Deliverable: before/after response graph.

### 2. Echo: baseline, then fix
- Baseline: play a tone, measure speaker-to-mic coupling in dB.
- Option A, half-duplex gating: mute mic upload during playback. Simple, but blocks barge-in.
- Option B, AEC: firmware holds the playback stream, so the reference signal is free. ESP-SR AFE provides AEC on the S3.
- Report attenuation (dB) for each. The trade-off (simplicity vs. barge-in) is the engineering judgment to show.

### 3. Power integrity
- WiFi TX bursts plus amp peaks can sag the rail: clicks, resets, noise at high volume.
- Check the rail with a scope or log brownout resets.
- Add a bulk capacitor (about 470 uF) and 0.1 uF decoupling at the amp; compare.
- Check mic noise floor for hum or clock noise; fix grounding if needed.

### 4. Smaller options
- Amp hardware gain instead of only software scaling (see Volume below).
- Two-mic beamforming: large effort, skip unless time allows.
- On-device wake word: already tracked as phase 4 in `docs/specs/2026-10-06-speaker-firmware-wake.md`.

## Volume

Current: software only. `SpeakerPort` in `harness/cadence/plugins/speaker.py` scales the 16-bit samples by a gain (`VOLUME_STEP` in `cadence/config.py`) before sending them to the board. It is controlled by voice ("louder", "mute") through the `speaker.volume` capability.

Limitation: digital attenuation of 16-bit samples loses resolution at low volume (SNR drops about 6 dB per halving of gain).

Optional: a rotary encoder. If added, the firmware should send a text frame (for example `{"type":"volume","delta":1}`) so the harness stays the single source of gain. Use the S3 PCNT peripheral for quadrature decoding with its glitch filter instead of polling GPIOs. This adds a physical input, which departs from the current "speaker voice is the only input" design; it would be a volume control only, not a label source.

## Essay notes
- Lead with the measured before/after pairs (sections 1 and 2), not a feature list.
- Keep one failure: the prebuffer vs. short-clip bug.
- Open questions: amp and speaker part numbers (they decide enclosure and power work).
