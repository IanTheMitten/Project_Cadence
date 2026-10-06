# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

This repo holds a Python decision harness plus **three independent ESP-IDF projects** targeting the same ESP32-S3 board:

- **`harness/`** — the server-side Cadence decision harness (Python, v1). See "Decision harness (`harness/`)" below.
- **Root project** (`CMakeLists.txt`, `main/Cadence_Speaker.c`) — the real firmware. Joins WiFi, pulls a raw PCM stream over HTTP from `tools/muse_proxy.py`, and plays it out an I2S DAC/amp.
- **`mic_test/`** — a standalone scratch project (its own `CMakeLists.txt`, `main/`, `sdkconfig.defaults`) that reads an INMP441 I2S mic and prints an amplitude meter over serial. Not wired into the main app; it's a separate firmware image for bench-testing the mic in isolation.
- **`voice_chat/`** — a standalone scratch project that runs the speaker TX path and the mic RX path at once (the board is wired for both simultaneously). It is the firmware client of the harness's `/session` WebSocket; `tools/voice_chat_host.py` is the older, pre-harness companion server for it. See "Voice conversation test" below.

Each ESP-IDF project has its own `build/` directory. `idf.py` commands act on whichever project directory you're `cd`'d into — always check which one before building/flashing.

## Decision harness (`harness/`)

Setup and run steps are in `harness/README.md`. Design: `docs/specs/2026-10-01-cadence-decision-harness-v1.md`; task plan: `docs/plans/2026-10-01-cadence-decision-harness-v1.md`. Run from `harness/` with `python -m cadence` (WebSocket server on port 8768; `/session` protocol and `TURN_LOCK` live in `cadence/server.py`). `build_runtime()` in `cadence/wiring.py` assembles everything lazily.

**Event pipeline** (`cadence/pipeline.py`): speaker session (mic, wake word "hey jarvis" via `openwakeword`, VAD, ASR) produces an `Event` (`cadence/events.py`; v1 kind `utterance`), then Decide, Resolve (`resolver.py`: target devices), Execute (`executor.py`: plugin calls), and every decision is written to the decision log. Acknowledgement clips (`acks.py`, `harness/acks/`) play after Jev routes.

**Deciders** (`cadence/deciders/`): one interface, `decide(event, context, capabilities, instruction)`. `JevDecider` (TypeSafe, key from `TYPESAFE_API_KEY` or `~/.config/cadence/typesafe.env`, never committed) decides first. `LlmDecider` (Ollama) is the escalation: low confidence, missing args, `chat`, `correction`, or Jev unavailable.

**Plugins** (`cadence/plugins/`): `speaker` (volume, audio port) and `music` (Muse client in `cadence/muse/`); `mcp_adapter.py` wraps an external MCP server, none wired by default. `registry.py` holds the device registry loaded from `devices.json`. The capability catalogue (`catalogue.py`) is generated from plugin manifests plus built-ins `chat` and `correction`.

**Decision log** (`cadence/decisionlog.py`, `cadence.sqlite3`): table `decision_log` records every decision; `decision_labels` holds labels. A spoken correction labels the previous decision `wrong` (source `spoken_correction`). The only input is the speaker; labels come from spoken corrections only.

**Other modules**: `cadence/audio/` (`vad.py`, `wakeword.py`, `listener.py` wake-gated utterance capture, `asr.py` Whisper, `tts.py` Kokoro, `mixer.py` music ducking under speech, `chunker.py`); `session.py` (`SessionCaps`, `SessionRegistry` for connected clients); `livecontext.py` (now-playing and recent decisions fed to deciders); `context.py` (`RollingContext`); `llm.py` (Ollama client, model `gemma4:31b-cloud`); `agent.py` (`MAX_TOOL_CALLS` cap, bounded tool loop); `mcp_client.py` (stdio MCP tool registry).

**Setup and tests**: venv lives at `harness/.venv` (Python >= 3.14). Install `requirements.txt`, then `requirements-nodeps.txt` with `--no-deps`. Kokoro model files (`kokoro-v1.0.onnx`, `voices-v1.0.bin`) go in `tools/`; `harness/README.md` has the download commands. Run tests from `harness/`: `.venv/bin/python -m pytest` (`asyncio_mode = auto`, `testpaths = tests`).

**Scripts** (`harness/scripts/`, run from `harness/`): `build_ack_pool.py` (regenerate `acks/`, needs Ollama + Kokoro), `golden_replay.py` (replay golden set against live Jev), `smoke_session.py` (end-to-end turn smoke), `preflight_*.py` (live-service checks), `capture_muse_fixtures.py`, `bench_*.py`. Preflight and smoke results are recorded in `docs/preflight/`; Muse/Cadence contract is `docs/handoffs/2026-10-01-muse-cadence-contract.md`.

Config constants and env vars (`CADENCE_MUSE_BASE_URL`, `CADENCE_MUSE_PROXY_URL`, `CADENCE_DEVICES_PATH`, `CADENCE_WAKE_ENABLED`) are in `cadence/config.py`. `openwakeword` must be installed with `--no-deps` (`requirements-nodeps.txt`). Scheduler, routines, and diary code (`scheduler.py`, `routines.py`, `store.py`) remain in the repo, unwired until v2.

## Commands

Environment must be sourced once per shell (ESP-IDF lives at `~/esp/esp-idf`, v5.3):

```
source ~/esp/esp-idf/export.sh
```

On Linux, cmake and ninja come from `python ~/esp/esp-idf/tools/idf_tools.py install cmake ninja` (run after sourcing `export.sh`).

From inside any project directory (root, `mic_test/`, or `voice_chat/`):

```
idf.py set-target esp32s3   # only needed once per project / after a clean
idf.py build
idf.py -p /dev/cu.usbmodem101 flash
idf.py -p /dev/cu.usbmodem101 monitor
idf.py -p /dev/cu.usbmodem101 flash monitor   # combined
```

Port may enumerate differently across replugs/reboots — check with `ls /dev/cu.usbmodem*` (macOS) or `ls /dev/ttyACM*` (Linux; `-p /dev/ttyACM0`) if flashing fails to connect. Flashing either project overwrites whatever firmware is currently on the chip; there's no way to run both at once. Reflash the other project's directory to switch back.

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
map below). It is the firmware client of the harness's `/session` WebSocket. `app_main` joins
WiFi as a station (blocks until an IP is obtained), then starts three tasks: `i2s_drain_task`
(pulls from the 64 KB `s_audio_ring` and writes to the I2S TX channel), `ws_client_task` (opens
the `esp_websocket_client` to `CONFIG_VOICE_WS_URL`; the client reconnects on its own), and
`mic_ws_task` (reads the mic and uploads it).

On connect the board sends a text hello frame:
`{"type":"hello","client_id":<CONFIG_VOICE_CLIENT_ID>,"caps":["audio_in","audio_out"]}`.
While connected, `mic_ws_task` sends binary frames continuously: 16 kHz s16le mono, 256
samples per frame (32-bit I2S samples shifted `>> 14`). Binary frames from the server are
44.1 kHz s16le stereo PCM and go into `s_audio_ring`. Text frames from the server
(`turn_start`, `turn_end`, `text`, `error`) are only logged (`ws text: ...`); the firmware
takes no other action on them.

The server is the harness: run `python -m cadence` from `harness/` (`/session` on port 8768).
It does the wake word ("hey jarvis") server-side, then VAD and ASR. There is no echo
cancellation; the harness ducks music under speech. `tools/voice_chat_host.py` is the
pre-harness server and is not used by this firmware.

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

WiFi SSID/password and the proxy URL are ESP-IDF Kconfig options (`main/Kconfig.projbuild`, under menu "Muse Speaker") with defaults baked into `sdkconfig.defaults`. `sdkconfig` and `sdkconfig.old` are the generated, machine-specific full configs — `sdkconfig.defaults` is the one meant to be hand-edited/committed. Note the WiFi password currently sits in plaintext in `sdkconfig.defaults`. `voice_chat/` has its own menu ("Voice Chat", in `voice_chat/main/Kconfig.projbuild`) with options `VOICE_WIFI_SSID`, `VOICE_WIFI_PASSWORD`, `VOICE_WS_URL`, `VOICE_CLIENT_ID`. The committed `voice_chat/sdkconfig.defaults` sets 8 MB flash, quad PSRAM, and the WS URL `ws://ianshomeserver:8768/session`. WiFi credentials live in the gitignored `voice_chat/sdkconfig.defaults.local`, which a fresh clone must create by hand:

```
CONFIG_VOICE_WIFI_SSID="your-ssid"
CONFIG_VOICE_WIFI_PASSWORD="your-password"
```

`sdkconfig.defaults.local` may also override `CONFIG_VOICE_WS_URL`. Defaults apply only when `sdkconfig` is generated, so run `rm voice_chat/sdkconfig` after editing either file.