# Cadence harness

## What this is

M1 of the Cadence voice/music agent harness: a WebSocket server (`cadence.server`) that runs
the turn loop — VAD/ASR on incoming mic audio, an LLM tool-calling agent, TTS on the reply, and
a mixer that ducks any in-progress music playback under the reply. A companion stdio MCP server
(`cadence.muse`) exposes eight Muse library tools to the agent. State (diary entries, routines)
lives in SQLite.

Measured on this Mac (Python 3.14.7, `docs/preflight/runtime.md`): Whisper `small.en` (CPU,
int8) loads in 1.146 s cold / 0.627 s warm; Kokoro TTS synthesizes a short test sentence in a
mean 0.631 s against 1.643 s of output audio (RTF 0.384, faster than real time here).

This is a desktop test harness, not the firmware. The ESP32-S3 boards talk to it as WebSocket
clients over the `/session` endpoint (`harness/cadence/server.py`).

## Prerequisites

- Python 3.14.7, with `harness/.venv` created and `harness/requirements.txt` installed into it
  (see runtime notes in `docs/preflight/runtime.md` — all imports in that dep set succeed on
  3.14.7).
- `ollama signin` run once on this Mac. The agent calls `gemma4:31b-cloud` at
  `http://localhost:11434/api/chat`. Measured post-signin (`docs/preflight/ollama.md`): a
  tool-call round trip took 719.7 ms with `think: false` and 1739.4 ms with `think: true`. The
  harness does not run `ollama signin` for you.
- `tools/muse_proxy.py` running and reachable on port 8765. It transcodes tracks to raw PCM for
  playback; the harness does not start it. Without it, `play` tool calls will resolve to a URL
  that nothing serves.

## Running it

From the repo root:

```
python3 -m venv harness/.venv
harness/.venv/bin/pip install -r harness/requirements.txt
cd harness && .venv/bin/python -m cadence
```

This starts the WebSocket server listening on the port read from `cadence/config.py`
(`WS_PORT`, currently `8768`). A client connects, sends a `hello` frame, and the server runs
one turn per utterance/text message it receives.

## The eight Muse tools

Exposed by `cadence.muse.mcp_server` (`TOOL_NAMES`), each a thin pass-through to one
`MuseClient` call:

- `search_vibe` — ranked candidate tracks matching a vibe/mood query; returns candidates, does
  not pick one.
- `search_text` — ranked candidate tracks matching a text search; returns candidates, does not
  pick one.
- `recommend_next` — ranked candidate tracks recommended to follow a given track; returns
  candidates, does not pick one.
- `play` — the playback URL for a track; returns the URL, does not decide which track to play.
- `get_player_state` — the current player state; read-only.
- `set_player_state` — applies exactly the queue/playback state you provide; does not decide
  what to play next.
- `get_dashboard` — the library dashboard summary; read-only.
- `rate` — records exactly the rating you provide for a track; does not decide how to rate it.

## What M1 does not do yet

Deferred, on purpose, to a later plan:

- **Wake word** — no on-board or server-side wake word detection. Until it lands, VAD is the
  only utterance gate.
- **Echo subtraction** — no acoustic echo cancellation on the mic path.
- **Acknowledgement clip pool** — no pre-generated filler-phrase audio for turn latency.
- **Server deployment** — nothing here is packaged or running on `ianshomeserver`; this runs on
  a dev Mac only.
- **Telegram and iMessage adapters** — the only client protocol is the WebSocket session
  protocol above; no chat-platform bridges exist.
