# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

This repo holds three Python programs (`harness/`, `speaker/`, `muse_adapter/`) plus **three independent ESP-IDF projects** targeting the same ESP32-S3 board:

- **`harness/`** — the Cadence core (Python): decisions, schedules, decision log. Knows nothing about audio. See "Decision harness (`harness/`)" below.
- **`speaker/`** (package `cadence_speaker`) — the board-facing speaker adapter. Serves `/session` on 8768 to the ESP32 boards and does wake word, VAD, ASR, TTS, acks, and music ducking. Connects to Cadence over `/peer`. See `speaker/README.md`.
- **`muse_adapter/`** (package `cadence_muse`) — a service peer for Muse (music queues, stream URLs). Connects to Cadence over `/peer`. See `muse_adapter/README.md`.
- **Root project** (`CMakeLists.txt`, `main/Cadence_Speaker.c`) — the real firmware. Joins WiFi, pulls a raw PCM stream over HTTP from `tools/muse_proxy.py`, and plays it out an I2S DAC/amp.
- **`mic_test/`** — a standalone scratch project (its own `CMakeLists.txt`, `main/`, `sdkconfig.defaults`) that reads an INMP441 I2S mic and prints an amplitude meter over serial. Not wired into the main app; it's a separate firmware image for bench-testing the mic in isolation.
- **`voice_chat/`** — a standalone scratch project that runs the speaker TX path and the mic RX path at once (the board is wired for both simultaneously). It is the firmware client of the speaker adapter's `/session` WebSocket; `tools/voice_chat_host.py` is the older, pre-harness companion server for it. See "Voice conversation test" below.

Each ESP-IDF project has its own `build/` directory. `idf.py` commands act on whichever project directory you're `cd`'d into — always check which one before building/flashing.

## Decision harness (`harness/`)

Setup and run steps are in `harness/README.md`. Original v1 design: `docs/specs/2026-10-01-cadence-decision-harness-v1.md`; split design: `docs/specs/2026-11-09-cadence-modular-split.md`, plan `docs/plans/2026-11-09-cadence-modular-split.md`. Run from `harness/` with `python -m cadence` (WebSocket `/peer` on port 8770, `PEER_PORT` in `cadence/config.py`). `build_runtime()` in `cadence/wiring.py` assembles everything lazily.

**Three programs, run order** (each from its own directory, each with `harness/.venv/bin/python`):

```
cd harness     && ../harness/.venv/bin/python -m cadence          # core, /peer on 8770
cd muse_adapter && ../harness/.venv/bin/python -m cadence_muse    # Muse service peer
cd speaker     && ../harness/.venv/bin/python -m cadence_speaker  # board-facing, /session on 8768
```

The adapters reach Cadence at `CADENCE_PEER_URL` (default `ws://127.0.0.1:8770/peer`). The speaker adapter's room is `CADENCE_SPEAKER_ROOM` (default `bedroom`). Moved env vars: `CADENCE_MUSE_BASE_URL`, `CADENCE_MUSE_PROXY_URL` now belong to `cadence_muse`; `CADENCE_WAKE_ENABLED`, `CADENCE_BENCH_RECORD_DIR` to `cadence_speaker`.

**Peers** (`cadence/peers.py`, protocol in `cadence/protocol.py`, table in `harness/README.md`): a peer joins `/peer` with a `hello` as a `device` (has a room, e.g. the speaker) or a `service` (e.g. Muse) and declares its abilities; Cadence builds the capability catalogue and device registry from connected peers' hellos and sends `call`s back over the same socket.

**Core** (`cadence/core.py`): `Core` is the only entry point; `submit(event)` takes `TURN_LOCK` (also in `core.py`) and runs the pipeline. `schedules.py` holds schedules and pending questions; `Core.run_schedules()` is the schedule loop started by `python -m cadence`.

**Event pipeline** (`cadence/pipeline.py`): the speaker adapter (wake word "hey jarvis", VAD, ASR) sends an `event` (`cadence/events.py`; kind `utterance`), then Decide, Resolve (`resolver.py`: target devices), Execute (`executor.py`: `call` to the owning peer), and every decision is written to the decision log. Acknowledgement clips (`speaker/cadence_speaker/acks.py`, `speaker/acks/`, gitignored) play after Jev routes.

**Deciders** (`cadence/deciders/`): one interface, `decide(event, context, capabilities, instruction)`. `JevDecider` (TypeSafe, key from `TYPESAFE_API_KEY` or `~/.config/cadence/typesafe.env`, never committed) decides first. `LlmDecider` (Ollama) is the escalation: low confidence, missing args, `chat`, `correction`, or Jev unavailable.

**Plugins and peers' abilities**: `mcp_adapter.py` (in `cadence/plugins/`) wraps an external MCP server, none wired by default. The music and speaker abilities now live in the adapters (`cadence_muse`, `cadence_speaker`). The Muse MCP server entry point is `python -m cadence_muse.mcp_main`. The capability catalogue (`catalogue.py`) is generated from connected peers' abilities plus built-ins `chat` and `correction`.

**Decision log** (`cadence/decisionlog.py`, `cadence.sqlite3`): table `decision_log` records every decision; `decision_labels` holds labels. A spoken correction labels the previous decision `wrong` (source `spoken_correction`). The only input is the speaker; labels come from spoken corrections only.

**Other harness modules**: `context.py` (`RollingContext`); `livecontext.py` (now-playing and recent decisions fed to deciders); `llm.py` (Ollama client, model `gemma4:31b-cloud`); `agent.py` (`MAX_TOOL_CALLS` cap, bounded tool loop); `mcp_client.py` (stdio MCP tool registry); `turntiming.py` (per-turn stage stamps).

**Speaker adapter modules** (`speaker/cadence_speaker/`): `server.py` (`/session`), `audio/` (`vad.py`, `wakeword.py`, `listener.py`, `asr.py` Whisper, `tts.py` Kokoro, `mixer.py` music ducking, `chunker.py`), `session.py` (`SessionCaps`), `speaker.py`, `acks.py`, `link.py` (the `/peer` client), `turntiming.py`, `benchrec.py` (`BenchRecorder`, off unless `CADENCE_BENCH_RECORD_DIR` is set; the directory is never auto-created), `wakebench.py`. Config in `speaker/cadence_speaker/config.py`. `muse_adapter/cadence_muse/`: `adapter.py`, `music.py`, `client.py` (Muse HTTP client), `link.py`, `mcp_server.py`; config in `config.py`.

**Setup and tests**: one venv at `harness/.venv` (Python >= 3.14) serves all three programs. Install `harness/requirements.txt`, then `harness/requirements-nodeps.txt` with `--no-deps`. Kokoro model files (`kokoro-v1.0.onnx`, `voices-v1.0.bin`) go in `tools/` at the repo root; `harness/README.md` has the download commands. Run tests from each program's directory: `.venv/bin/python -m pytest` in `harness/`, `../harness/.venv/bin/python -m pytest` in `speaker/` and `muse_adapter/` (`asyncio_mode = auto`, `testpaths = tests`).

**Scripts**: `harness/scripts/` (`golden_replay.py`, `smoke_session.py`, `preflight_*.py`, `bench_*.py`; `preflight_v1.py` is historical and still imports the removed `cadence.audio`). `speaker/scripts/` (`build_ack_pool.py` regenerates `acks/`, needs Ollama + Kokoro; `wake_guide.py`, `wake_bench.py`, `asr_bench.py`, `preflight_wake_bench.py`). `muse_adapter/scripts/capture_muse_fixtures.py`. Preflight and smoke results are recorded in `docs/preflight/`; Muse/Cadence contract is `docs/handoffs/2026-10-01-muse-cadence-contract.md`.

`routines.py` and `store.py` (diary) remain in `harness/cadence/`, unwired until v2. Schedules are in `cadence/schedules.py`.

## Version control and multi-machine sync

This repo is worked on from several machines and Claude sessions. GitHub (`origin/master`, `IanTheMitten/Cadence_Speaker`) is the single source of truth; another machine knows what is done only from what is pushed.

- **Session start:** run `git fetch && git status -sb` and `git log --oneline -15`. If behind, `git pull --rebase`. Read the newest `docs/plans/*.md` for task status before starting work.
- **Session end (or before switching machines):** commit everything worth keeping, then `git push`. Do not end a session with unpushed commits or untracked docs/specs/research unless the user says to keep them local. Report `git status -sb` at the end; it must show no `ahead` and no `??` files unless the user said to keep them local.
- **Commit small and often**, one logical change per commit. Conventional prefixes: `feat:`, `fix:`, `test:`, `docs:`, `build:`, `style:`, `refactor:`. Subject says what and where, in the imperative, under about 72 chars. Body only when the why is not obvious.
- **Plan progress lives in git:** when a task from a `docs/plans/*.md` finishes, mark it done in the plan file and say so in the commit message (for example `feat: BenchRecorder (plan task 3 done)`). Another machine reads the plan plus `git log` to see what remains.
- **Specs, research, and plans are committed** (`docs/specs/`, `docs/research/`, `docs/plans/`, `docs/preflight/`, `docs/handoffs/`). Do not leave them untracked.
- **Name the project in commits** when a change touches only one of the independent projects: scope with the directory, e.g. `fix(voice_chat): ...`, `feat(harness): ...`, `fix(mic_test): ...`. Root firmware changes use no scope or `firmware`.
- **Never commit** secrets or machine-local files: `sdkconfig`, `sdkconfig.old`, `build/`, `voice_chat/sdkconfig.defaults.local` (WiFi creds), `harness/.venv`, `typesafe.env`, `cadence.sqlite3`, bench recordings. Check `git status` before `git add`; add files by name, not `git add -A`.
- **Work on `master`** unless the user asks for a branch. Pull with `--rebase` to keep history linear. No force-push, no history rewrites, no amending pushed commits.
- **Hardware state is not in git, so it is documented in `docs/hardware/`.** After any flash, wiring change, bench run, or measurement, add a dated entry to `docs/hardware/build-log.md` (board, project dir, what changed, result with units), update `docs/hardware/inventory.md` if parts, wiring, or flashed firmware changed, and put raw data or photos in `docs/hardware/measurements/`. Commit and push it the same day. Another machine reads that folder to know how far the hardware has progressed.
- Claude still commits and pushes only when the user asks. At session end, if anything is unpushed or untracked, say so and offer to commit and push.

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
map below). It is the firmware client of the speaker adapter's `/session` WebSocket. `app_main` joins
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

The board talks only to the speaker adapter: run `python -m cadence_speaker` from `speaker/` (`/session` on port 8768). The adapter talks to Cadence (`python -m cadence` from `harness/`, `/peer` on 8770).
The adapter does the wake word ("hey jarvis") server-side, then VAD and ASR. There is no echo
cancellation; the speaker adapter ducks music under speech. `tools/voice_chat_host.py` is the
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
