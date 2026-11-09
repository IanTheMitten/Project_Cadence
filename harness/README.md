# Cadence harness

## What this is

The Cadence core (`cadence/core.py`): a WebSocket server (`cadence.peers`, `/peer`, port 8770, `PEER_PORT`) that turns events from connected peers into decisions and actions. An `Event` goes through Decide (Jev first, a cloud LLM on escalation), Resolve, Execute. Every decision is written to a SQLite decision log. The core knows nothing about audio.

Audio lives in the speaker adapter (`speaker/`, package `cadence_speaker`: wake word, VAD, ASR, TTS, acks, `/session` on 8768 for the ESP32 boards). Music lives in the Muse adapter (`muse_adapter/`, package `cadence_muse`). Both connect to this server as peers.

Designs: `docs/specs/2026-10-01-cadence-decision-harness-v1.md` (v1), `docs/specs/2026-11-09-cadence-modular-split.md` (split). Plan: `docs/plans/2026-11-09-cadence-modular-split.md`. Target host is `ianshomeserver`.

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

## Running it

Three programs, started in this order, each from its own directory with this venv:

```
cd harness && .venv/bin/python -m cadence
cd muse_adapter && ../harness/.venv/bin/python -m cadence_muse
cd speaker && ../harness/.venv/bin/python -m cadence_speaker
```

`python -m cadence` listens on `0.0.0.0:8770` (`PEER_PORT` in `cadence/config.py`) and runs the schedule loop. The runtime is built lazily on first use (`build_runtime()` in `cadence/wiring.py`). The adapters find it at `CADENCE_PEER_URL` (default `ws://127.0.0.1:8770/peer`); see `speaker/README.md` and `muse_adapter/README.md` for their env vars. Kokoro files and acks are the speaker adapter's (`speaker/README.md`). The Muse proxy (`tools/muse_proxy.py`, port 8765) is started separately on the host.

## Device protocol (`/peer`)

JSON text frames, `PROTOCOL_VERSION = 1` (`cadence/protocol.py`; each peer package carries a verbatim copy). A `hello` with another version is rejected.

| Message | Direction | Fields |
|---|---|---|
| `hello` | peer to Cadence | `version`, `peer_id`, `role` (`device`\|`service`), `kind`, `room` (string or null), `caps` (list of strings, e.g. `audio_out`, `text_out`), `abilities` (list of `{name, description, parameters}`) |
| `welcome` | Cadence to peer | none; sent after an accepted `hello` |
| `error` | Cadence to peer | `message`; sent on a bad or mismatched `hello`, then the socket closes |
| `event` | peer to Cadence | `kind` (`utterance`), `payload` (`text`, `asr_conf`), `timing` (stage stamps, ms; merged into `latency_ms`) |
| `turn_start`, `turn_end` | Cadence to peer | none; bracket the turn for the event's source |
| `ack` | Cadence to peer | `category` (`action`\|`chat`\|`correction`) |
| `say` | Cadence to peer | `text` |
| `listen` | Cadence to peer | `seconds`: open the mic without the wake word |
| `call` | Cadence to peer | `call_id`, `capability`, `args`, `target` (device id or null) |
| `result` | peer to Cadence | `call_id`, `ok`, `say`, `data`, `error` |
| `media` | service to Cadence, then Cadence to device | `device`, `action` (`play_url`\|`pause`\|`resume`\|`stop`), `url` (for `play_url`). Cadence forwards it to the device and records the service as that device's media owner. The forwarded frame carries `action` and `url` only. |
| `media_event` | device to Cadence, then Cadence to the owning service | `event` (`track_end`\|`lost`\|`stopped`), `position_ms`, `url`. Cadence adds `device`. |
| `state` | peer to Cadence | `state`: free-form dict. Muse sends `{"now_playing": {<device_id>: {track_name, artist_name, paused} \| null}}`, fed to `LiveContext`. |

## Decision log

Decisions are stored in `cadence.sqlite3` (`DB_PATH`, relative to `harness/`):

- `decision_log` — one row per decision: event, context, decider, route, calls, and results.
- `decision_labels` — labels on decisions. When an utterance is routed to `correction` within
  60 s of the same source's previous decision, that previous decision is labelled `wrong` with
  source `spoken_correction`.

The log is append-only data for later finetuning of Jev's replacement.
