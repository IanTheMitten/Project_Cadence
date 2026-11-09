# Cadence speaker adapter

## What this is

`cadence_speaker`: the board-facing program. ESP32 boards connect to it as WebSocket clients on `/session` (port 8768, `SPEAKER_PORT`; `cadence_speaker/server.py`). It does the audio work: wake word ("hey jarvis", `hey_jarvis_v0.1`, threshold 0.5), VAD, ASR (Whisper), TTS (Kokoro), acknowledgement clips, and music ducking under speech. Each board session opens one Cadence `/peer` link (`cadence_speaker/link.py`) and turns audio into `utterance` events; Cadence's `say`, `ack`, `listen` and `media` messages become audio. After a wake, utterances are accepted for a listen window of 8 s (`LISTEN_WINDOW_S`). Protocol table: `harness/README.md`.

Setup uses the shared venv at `harness/.venv` (see `harness/README.md`).

## Run

From `speaker/`, with Cadence running (`python -m cadence` in `harness/`):

```
../harness/.venv/bin/python -m cadence_speaker
```

## Config

Read in `cadence_speaker/config.py`:

| Variable | Default | Meaning |
|---|---|---|
| `CADENCE_PEER_URL` | `ws://127.0.0.1:8770/peer` | Cadence `/peer` endpoint |
| `CADENCE_SPEAKER_ROOM` | `bedroom` | Room this speaker reports in its hello |
| `CADENCE_WAKE_ENABLED` | `1` | `1` gates utterances on the wake word; any other value falls back to VAD-only |
| `CADENCE_BENCH_RECORD_DIR` | unset | If set, `BenchRecorder` writes session and utterance recordings there; the directory is never auto-created |

Output volume is capped at `MAX_VOLUME = 0.7` (constant, not an env var).

## Kokoro model files

`cadence_speaker/audio/tts.py` loads them from `tools/` at the repo root:

```
cd tools
wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.onnx
wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin
```

Kokoro and Whisper load lazily on first use.

## Acknowledgement clips

Clips (categories `action`, `chat`, `correction`) are played from `speaker/acks/<category>/NN.pcm` (`ACK_DIR = "acks"`, relative to the directory you run from). `acks/` is gitignored (`speaker/.gitignore`), so a fresh clone must generate it. From `speaker/`:

```
../harness/.venv/bin/python scripts/build_ack_pool.py --out acks --per-category 20
```

It asks the Ollama LLM for phrases and renders them with Kokoro, so both must be available.

## Tests

From `speaker/`:

```
../harness/.venv/bin/python -m pytest
```
