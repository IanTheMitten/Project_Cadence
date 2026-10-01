# Cadence harness

## What this is

v1 of the Cadence decision harness: a WebSocket server (`cadence.server`, `/session`) that turns
speaker utterances into decisions and actions. Pipeline: mic audio, then wake word ("hey
jarvis"), VAD, ASR, then an `Event` goes through Decide (Jev first, a cloud LLM on
escalation), Resolve, Execute. Every decision is written to a SQLite decision log. Plugins:
`speaker` (volume, audio port) and `music` (Muse). Replies are synthesized with Kokoro TTS.

Design: `docs/specs/2026-10-01-cadence-decision-harness-v1.md`. Plan:
`docs/plans/2026-10-01-cadence-decision-harness-v1.md`.

The ESP32-S3 boards talk to this server as WebSocket clients over `/session`
(`harness/cadence/server.py`). Target host is `ianshomeserver`.

## Setup

From the repo root:

```
python3 -m venv harness/.venv
harness/.venv/bin/pip install -r harness/requirements.txt
harness/.venv/bin/pip install --no-deps -r harness/requirements-nodeps.txt
```

The second install is `--no-deps` on purpose. `openwakeword` 0.6.0 hard-requires
`tflite-runtime` on Linux, which has no Python 3.14 wheel, so a normal install fails. The code
runs it with `inference_framework="onnx"` instead; its other needs (`scikit-learn`, `requests`,
`tqdm`) are listed in `requirements.txt`. Never run a plain `pip install openwakeword`.

### Kokoro model files

`cadence.audio.tts` loads them from `tools/` at the repo root:

```
cd tools
wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.onnx
wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin
```

Kokoro and Whisper load lazily on first use, not at import.

### Jev (TypeSafe) key

Jev, the first-stage decider, needs a TypeSafe API key. It is read from the env var
`TYPESAFE_API_KEY`, or else from `~/.config/cadence/typesafe.env`, a file with a line:

```
TYPESAFE_API_KEY=<your key>
```

Keep that file outside the repo and never commit it. If no key is found, Jev is marked
unavailable at startup (a message goes to stderr) and every utterance escalates to the LLM.

### LLM (Ollama)

Escalations go to `gemma4:31b-cloud` at `http://localhost:11434/api/chat` (`cadence/llm.py`).
Run `ollama signin` once on the host; the harness does not do it for you.

## Configuration

Env vars, read in `cadence/config.py`:

| Variable | Default | Meaning |
|---|---|---|
| `CADENCE_MUSE_BASE_URL` | `http://ianshomeserver:8080` | Muse library server |
| `CADENCE_MUSE_PROXY_URL` | `http://ianshomeserver:8765` | `tools/muse_proxy.py`, where speakers fetch PCM |
| `CADENCE_DEVICES_PATH` | `devices.json` | Device registry file |
| `CADENCE_WAKE_ENABLED` | `1` | `1` gates utterances on the wake word; any other value falls back to VAD-only |

Relative paths resolve against `harness/`, the directory the server runs from.

### `devices.json`

Static device list, loaded at startup. The shipped file has one device:

```
{"devices": [{"id": "speaker-1", "kind": "speaker", "room": "bedroom"}]}
```

`id` is the client id the firmware connects with (`speaker-1` is the firmware default). Edit
`room` by hand.

## Acknowledgement clips

Short spoken acknowledgements (categories `action`, `chat`, `correction`) are played from
`harness/acks/<category>/NN.pcm`. Regenerate them from `harness/` with:

```
.venv/bin/python scripts/build_ack_pool.py --out acks --per-category 20
```

It asks the Ollama LLM for phrases and renders them with Kokoro, so both must be available.

## Running it

1. Start the Muse proxy on the host (the harness does not start it):

   ```
   python3 tools/muse_proxy.py
   ```

   It listens on port 8765 and transcodes tracks to raw PCM.

2. Start the harness:

   ```
   cd harness && .venv/bin/python -m cadence
   ```

   Listens on `0.0.0.0:8768` (`WS_PORT`). The runtime is built lazily on first use
   (`build_runtime()` in `cadence/wiring.py`).

Wake phrase: "hey jarvis" (`hey_jarvis_v0.1`, threshold 0.5). After a wake, utterances are
accepted for a listen window of 8 s.

## Decision log

Decisions are stored in `cadence.sqlite3` (`DB_PATH`, relative to `harness/`):

- `decision_log` — one row per decision: event, context, decider, route, calls, and results.
- `decision_labels` — labels on decisions. When an utterance is routed to `correction` within
  60 s of the same source's previous decision, that previous decision is labelled `wrong` with
  source `spoken_correction`.

The log is append-only data for later finetuning of Jev's replacement.
