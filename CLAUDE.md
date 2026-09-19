# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

This repo contains **three independent ESP-IDF projects** targeting the same ESP32-S3 board, not one project:

- **Root project** (`CMakeLists.txt`, `main/Cadence_Speaker.c`) — the real firmware. Joins WiFi, pulls a raw PCM stream over HTTP from `tools/muse_proxy.py`, and plays it out an I2S DAC/amp.
- **`mic_test/`** — a standalone scratch project (its own `CMakeLists.txt`, `main/`, `sdkconfig.defaults`) that reads an INMP441 I2S mic and prints an amplitude meter over serial. Not wired into the main app; it's a separate firmware image for bench-testing the mic in isolation.
- **`voice_chat/`** — a standalone scratch project that runs the speaker TX path and the mic RX path at once (the board is wired for both simultaneously), streaming mic audio to `tools/voice_chat_host.py` and playing back its TTS replies, for a realtime spoken-conversation test. See "Voice conversation test" below.

Each has its own `build/` directory. `idf.py` commands act on whichever project directory you're `cd`'d into — always check which one before building/flashing.

## Commands

Environment must be sourced once per shell (ESP-IDF lives at `~/esp/esp-idf`, v5.3):

```
source ~/esp/esp-idf/export.sh
```

From inside any project directory (root, `mic_test/`, or `voice_chat/`):

```
idf.py set-target esp32s3   # only needed once per project / after a clean
idf.py build
idf.py -p /dev/cu.usbmodem101 flash
idf.py -p /dev/cu.usbmodem101 monitor
idf.py -p /dev/cu.usbmodem101 flash monitor   # combined
```

Port may enumerate differently across replugs/reboots — check with `ls /dev/cu.usbmodem*` if flashing fails to connect. Flashing either project overwrites whatever firmware is currently on the chip; there's no way to run both at once. Reflash the other project's directory to switch back.

## Architecture (root project — speaker/playback path)

`main/Cadence_Speaker.c` is a single-file app with three concurrent pieces tied together by a FreeRTOS `StreamBuffer` (`s_audio_ring`, 64 KB):

1. **WiFi STA connect** (`wifi_init_sta`) — blocks in `app_main` until an IP is obtained, using credentials from Kconfig (`CONFIG_MUSE_WIFI_SSID` / `CONFIG_MUSE_WIFI_PASSWORD`, set in `sdkconfig.defaults`).
2. **`http_stream_task`** — issues one long-lived GET to `CONFIG_MUSE_PROXY_URL` (default `http://172.30.1.67:8765/play/3112`). The HTTP event handler (`http_event_handler`) pushes each received chunk into `s_audio_ring` as it arrives.
3. **`i2s_drain_task`** — pulls fixed-size chunks out of the ring buffer and writes them straight to the I2S TX channel. No decoding on-device: the proxy sends raw `s16le`, 44100 Hz, stereo PCM and it goes straight to the DAC.

The HTTP task and I2S task run independently so a slow/bursty network doesn't stall audio output directly — the ring buffer is the only coupling between them.

### `tools/muse_proxy.py` (companion server, runs on a host machine, not the ESP32)

Transcodes tracks from a Muse library server (`MUSE_BASE = http://ianshomeserver:8080`) to the raw PCM format the firmware expects, using `ffmpeg` piped to `stdout`. `GET /play/<track_rowid>` streams the result back chunked. Bass/treble EQ (`bass=g=6:f=110,treble=g=-4:f=8000` by default) is applied in the same ffmpeg pass and can be overridden per-request via `?bass=<dB>&treble=<dB>`. The firmware's `CONFIG_MUSE_PROXY_URL` must point at wherever this script is actually running (port 8765) — it is **not** started by the firmware or by ESP-IDF; run it separately on the host before expecting playback to work.

## Voice conversation test (`voice_chat/`)

`voice_chat/main/voice_chat.c` runs the root project's speaker TX path and `mic_test`'s mic
RX path in the same firmware image (different I2S peripherals/pins, no conflict — see the pin
map below), plus two network tasks: `speak_stream_task` (a `while(1)` version of the root
project's `http_stream_task`, GETting `CONFIG_VOICE_SPEAK_URL` in a loop — one GET per
assistant turn) and `mic_upload_task` (a raw TCP socket streaming 16-bit mic PCM to
`CONFIG_VOICE_HOST_IP:CONFIG_VOICE_MIC_PORT`, reconnecting on failure).

`tools/voice_chat_host.py` is the companion server (like `tools/muse_proxy.py`, but not
related to it — run separately, not started by the firmware): VAD (`webrtcvad`) segments the
mic stream into utterances, `faster-whisper` transcribes them, `mlx_lm` streams a reply from a
small local model, a sentence chunker (ported from
`~/Documents/Projects/lumi`'s `crates/cadence-gateway/src/voice/chunker.rs`) cuts the stream
into sentences as they complete, and Kokoro (`kokoro-onnx`) synthesizes and streams each one
back over `GET /speak_stream` as soon as it's ready — so the board can start talking before
the full reply has finished generating. Setup and model-file download steps are in the
docstring at the top of `tools/voice_chat_host.py`.

No real echo cancellation: instead `tools/voice_chat_host.py` gates the mic off (VAD skipped,
frames dropped) for the estimated duration of the board's own playback after each turn, so it
can't transcribe itself. This surfaced as a real problem during testing — the assistant kept
replying to its own speech — before the mute was added; it's a blunt mitigation, not real AEC,
so a loud enough echo bleeding past the mute window is still possible.

## I2S pin map

The two playback/mic-facing projects use different I2S peripherals and pins, so they don't conflict even though all three target the same chip (`voice_chat/` uses both sets at once):

| Signal | Root project (speaker, TX) | `mic_test` (INMP441, RX) |
|---|---|---|
| I2S peripheral | `I2S_NUM_0` | `I2S_NUM_1` |
| BCLK / SCK | GPIO15 | GPIO5 |
| WS (LRCLK) | GPIO16 | GPIO6 |
| Data pin | GPIO17 (`dout`) | GPIO4 (`din`) |
| Format | 16-bit, stereo, 44100 Hz | 32-bit, mono (left slot), 16000 Hz |
| Role | master, TX only | master, RX only |

INMP441 `L/R` pin is tied to GND (selects left channel — matches `I2S_STD_SLOT_LEFT` in `mic_test.c`). INMP441 `VDD` must be 3.3V, not 5V.

## Config

WiFi SSID/password and the proxy URL are ESP-IDF Kconfig options (`main/Kconfig.projbuild`, under menu "Muse Speaker") with defaults baked into `sdkconfig.defaults`. `sdkconfig` and `sdkconfig.old` are the generated, machine-specific full configs — `sdkconfig.defaults` is the one meant to be hand-edited/committed. Note the WiFi password currently sits in plaintext in `sdkconfig.defaults`. `voice_chat/` has its own equivalent menu ("Voice Chat", in `voice_chat/main/Kconfig.projbuild`) with `VOICE_WIFI_SSID`/`VOICE_WIFI_PASSWORD`/`VOICE_HOST_IP`/`VOICE_MIC_PORT`/`VOICE_SPEAK_URL`.
