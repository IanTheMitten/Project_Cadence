# Technical spec - Cadence modular split (core, device protocol, voice schedules)

> Status: ready for planning. Feed to /autopilot-plan once ready - it verifies this line and refuses a spec that isn't "ready for planning".

## Source

No PRD. Goal stated by the user in conversation on 2026-11-09:

- The harness is a decision layer that stands by itself. The speaker is only an input source; lights and music are outputs.
- Split into separate repos: **Cadence** (the core, this repo, renamed), **cadence_speaker** (board firmware plus all audio work: wake word, VAD, ASR, TTS), **cadence_lights** (later), and **cadence_muse** (the Muse adapter).
- Voice schedules: "wake me up at 7 and play jazz", add and cancel, daily or once. On a clash, the AI asks whether to delete the conflicting schedule.
- Long-term vision this must not block (lamps in every room, three or more speakers, CSI posture sensing, RAG, chat, Claude Code session control, light-and-speaker wake-up, synced party mode): `memory: cadence-long-term-vision`.

Current state this changes:

- `harness/cadence/server.py` mixes the WebSocket connection, the speaker's audio path (listener, ASR, TTS, acks, `SpeakerPort`) and turn dispatch.
- `pipeline.py` is already clean. It takes an `Event` and a `TurnOutput` (`ack`/`say`).
- `scheduler.py` imports `TURN_LOCK` from `cadence.server` and uses the old M1 tool registry; it is not wired up.
- `Executor` passes an in-process `AudioPort` to plugins.

## Architecture

Three programs during step 1, each in its own top-level folder of this repo. In step 2 each moves to its own repo.

```
ESP32 board --/session (unchanged, :8768)--> speaker/       (cadence_speaker)
                                              wake, VAD, ASR, TTS, acks, SpeakerPort, ducking
                                                 |
                                                 | Cadence device protocol (WebSocket + JSON, :8770)
                                                 v
                                             harness/      (Cadence core)
                                              Core: submit(event), announce(target, text)
                                              TURN_LOCK, Pipeline (Jev -> LLM), Executor,
                                              catalogue (built from connected peers),
                                              device registry (from hellos), decision log,
                                              schedules, pending questions
                                                 ^
                                                 | same protocol
muse server <--HTTP-- muse_adapter/ (cadence_muse)
                       declares music.play / control / rate / now_playing,
                       owns queues; returns stream URLs; Cadence routes them to a speaker
```

- **Core** (`harness/cadence/core.py`): the only entry point. `submit(event)` takes `TURN_LOCK` and runs the pipeline. `announce(target, text)` sends `say` to matching speakers without a turn. It knows nothing about audio.
- **Peers**: anything that connects over the device protocol. A peer is either a *device* (it has a room and is a target, e.g. the speaker) or a *service* (no room, e.g. Muse). Each peer declares its abilities in `hello`. Cadence adds them to the catalogue and sends `call`s back over the same socket.
- **Speaker adapter** (`speaker/`): takes over port 8768 and the existing `/session` protocol, so the board needs no change and no reflash. It turns audio into `utterance` events and turns Cadence's `say`/`ack`/`play_url` commands into audio.
- **Muse adapter** (`muse_adapter/`): moves the queue logic from `harness/cadence/plugins/music.py` and the client from `harness/cadence/muse/`. It returns a stream URL; Cadence forwards `play_url` to the target speaker. The speaker reports track end and position back; Cadence relays them to Muse.

## Decisions

### Decision: Core shape - one Core object, direct call
- **Status:** Accepted
- **Context:** Inputs mostly need a reply to the same device (speech in, speech out). The pipeline already takes an `Event` plus an output object.
- **Options considered:** (a) Core object with `submit`/`announce`: a direct call that is easy to trace. (b) Event bus: inputs post to a queue, outputs subscribe; easy to add listeners, but replies need routing tags and lost messages fail silently. (c) Every part as its own network service, core included.
- **Decision:** (a) inside Cadence. A queue can later be put in front of `submit` for fire-and-forget sensor traffic (CSI) without changing the core.
- **Consequences:** The pipeline is unchanged. Scheduler and speaker both call `Core`. `TURN_LOCK` moves to `core.py`.

### Decision: Repo split - this repo becomes Cadence
- **Status:** Accepted
- **Context:** The harness is what is being built now. Its git history lives here. Firmware projects are independent ESP-IDF folders that move cleanly.
- **Options considered:** (a) This repo becomes Cadence; firmware, speaker hardware docs and audio code move to a new cadence_speaker repo. (b) This repo becomes cadence_speaker and the harness moves out, losing its history.
- **Decision:** (a).
- **Consequences:** Step 2 moves the root firmware, `voice_chat/`, `mic_test/`, `tools/muse_proxy.py`, `tools/voice_chat_host.py`, speaker parts of `docs/hardware/` and `speaker/` to cadence_speaker, and `muse_adapter/` to cadence_muse. Renaming the GitHub repo and the local folder is outward-facing and gets its own confirmation at that time (see Open questions).

### Decision: Order of work - split in place, then move
- **Status:** Accepted
- **Context:** Changing the architecture and moving code at the same time makes failures hard to trace. The voice path works on real hardware today.
- **Options considered:** (a) Step 1: split inside this repo into sibling folders, with tests and the board working. Step 2: move folders to new repos. (b) New repos first, then split.
- **Decision:** (a).
- **Consequences:** Step 1 ends with a board smoke test. Step 2 is mostly mechanical moves plus updates to CLAUDE.md and READMEs.

### Decision: Step-1 layout - sibling top-level folders
- **Status:** Accepted
- **Context:** Each folder must later move to its own repo unchanged, and nothing should quietly import across the boundary.
- **Options considered:** (a) `harness/` (core), `speaker/`, `muse_adapter/` at top level, each its own Python package and program, sharing `harness/.venv` for now. (b) Packages inside `harness/`, where cross-imports are easy and silent.
- **Decision:** (a). Each package may import only its own code and the shared protocol module (next decision).
- **Consequences:** The protocol types need a home that all three can use (see next decision).

### Decision: Shared protocol definition - copy per repo, pinned by version
- **Status:** Assumed - not confirmed
- **Context:** Three repos need the same message shapes. A shared library adds a fourth package to publish.
- **Options considered:** (a) A small `protocol.py` copied into each package with a `PROTOCOL_VERSION` constant; `hello` carries it and a mismatch is rejected. (b) A separate `cadence_protocol` package installed by all three. (c) A JSON Schema file that each side validates against.
- **Decision:** (a). The protocol is about ten message types. The version check catches drift, and peers can be written in other languages (ESP32 lamp firmware) from the doc alone.
- **Consequences:** The protocol is documented in this spec (Data flow) and copied into each repo. A version bump means updating all peers.

### Decision: Link between programs - network API
- **Status:** Accepted
- **Context:** The user asked whether this adds latency and whether it's practical. A hop costs under 1 ms on the same machine (2-5 ms over WiFi). Jev's p50 is 243 ms (`docs/preflight/jev-v1-golden.md:21`) and TTS is over 1 s (`docs/preflight/runtime-v1.md:21`). Audio never passes through Cadence.
- **Options considered:** (a) Network API: separate programs, so lamps and CSI firmware can connect the same way. (b) Python package imported in-process: no protocol, but the repos stay tied and firmware can't use it.
- **Decision:** (a).
- **Consequences:** A protocol to design and keep stable, reconnect handling, and two or three programs to run.

### Decision: Transport - WebSocket + JSON
- **Status:** Accepted
- **Context:** Cadence must push commands (`say`, `play_url`) to devices without being asked. FastAPI and `esp_websocket_client` are already in use.
- **Options considered:** (a) WebSocket + JSON text frames. (b) MQTT, which needs an always-on broker and a new dependency, and fits request/reply turns less well. (c) HTTP REST, which can't push unless every device also runs a server.
- **Decision:** (a), on a new port 8770, path `/peer`.
- **Consequences:** No new dependencies. ESP32 lamps can later connect directly.

### Decision: Abilities - declared by the peer on connect
- **Status:** Accepted
- **Context:** The goal is that new device types (lamps) need no Cadence change.
- **Options considered:** (a) The peer declares its capabilities (name, description, JSON-schema parameters, `closed_args`, `free_args`, `target` kind) in `hello`, and the catalogue is built from connected peers plus the built-ins `chat` and `correction`. (b) Cadence keeps one plugin per device type that talks over the network.
- **Decision:** (a). Capability fields match the existing `Capability` dataclass (`harness/cadence/plugins/base.py`), so Jev's prompt building is unchanged.
- **Consequences:** `SpeakerPlugin` and `MusicPlugin` leave Cadence. `Executor` sends `call` messages and awaits `result`. The catalogue changes when peers connect or disconnect. Abilities Cadence itself owns (`schedule.add`, `schedule.cancel`) are registered as local capabilities in the same catalogue.

### Decision: Rooms - declared by the device in hello
- **Status:** Accepted
- **Context:** Fits "a new lamp needs no Cadence edit".
- **Options considered:** (a) `hello` carries `room`, from the device's own config; `devices.json` is removed. (b) Cadence keeps `devices.json`.
- **Decision:** (a). The speaker adapter reads its room and client id from its own config.
- **Consequences:** `DeviceRegistry.from_file` and `CADENCE_DEVICES_PATH` are removed. The registry is filled from hellos. Room-based resolution (`resolver.py`) is unchanged.

### Decision: Board connection - unchanged, speaker adapter serves /session on 8768
- **Status:** Accepted
- **Context:** The board works today against `ws://ianshomeserver:8768/session`. ASR and TTS can't run on the ESP32.
- **Options considered:** (a) The speaker adapter keeps 8768 and the `/session` protocol byte for byte. (b) The board talks to Cadence directly, which isn't workable for audio.
- **Decision:** (a).
- **Consequences:** No firmware change or reflash in either step. The speaker adapter is itself a peer of Cadence and holds one peer connection per board session.

### Decision: Muse - its own service over the same protocol
- **Status:** Accepted
- **Context:** The user wants Muse as its own plugin exposing its own functions. Cadence picks among them and talks over the music (ducking). Party mode later needs one place that coordinates all speakers.
- **Options considered:** (a) Muse adapter as a service peer: it declares `music.*`, owns queues, and returns stream URLs; Cadence routes `play_url` to the target speaker; the speaker ducks music under speech. (b) The same, but over Muse's existing MCP server and `mcp_adapter.py`, which means two protocols. (c) Music inside each speaker adapter, so logic is copied per speaker and party mode is harder.
- **Decision:** (a). Final home: new repo cadence_muse.
- **Consequences:** Music needs a *media* hop. A Muse `result` may carry `media: {device, action: play_url|pause|resume|stop, url}`, and Cadence forwards it as a command to that device. Speaker `media_event`s (`track_end`, `lost`, position) go to Cadence, which relays them to the service that started the media. `LiveContext` now-playing comes from Muse's `state` message instead of `music.now_playing` in-process.

### Decision: Turn lock - lives in Core
- **Status:** Accepted
- **Context:** A turn and a schedule must not change music or volume at the same time. The scheduler should not depend on speaker code.
- **Options considered:** (a) Move `TURN_LOCK` into `core.py`, same one-at-a-time behavior. (b) One lock per room (only useful with several speakers). (c) Leave it in `server.py`.
- **Decision:** (a).
- **Consequences:** `Core.submit` and schedule firing both take it. Pending-question answers take it too. Long agent tasks (Claude Code sessions) are out of scope; they will need to release the lock when that work comes.

### Decision: Speaking first - announce to a device or room
- **Status:** Accepted
- **Context:** The wake-up routine must say "good morning" with no turn open. Over the network this uses the same `say` command as a reply.
- **Options considered:** (a) `Core.announce(target, text)`, where the target is a device id, a room, or `None` (all online speakers); it is skipped when nothing is online. (b) Defer, so routines stay silent.
- **Decision:** (a).
- **Consequences:** No new message type is needed. The speaker treats an unprompted `say` like a reply (TTS, ducking over music).

### Decision: Scheduler scope - voice add and cancel, daily or once
- **Status:** Accepted
- **Context:** The user wants voice creation with add and cancel, daily or once. The speaker is the only input, with no app.
- **Options considered:** (a) Add and cancel, daily or once. (b) Add only, once. (c) Add, cancel, list and weekday patterns, which means more time parsing and more for Jev to learn.
- **Decision:** (a). Cadence registers local capabilities `schedule.add {time "HH:MM", repeat "once"|"daily", greeting bool, command string?, room?}` and `schedule.cancel {time "HH:MM"}`. `repeat` and `greeting` are closed args.
- **Consequences:** The old `scheduler.py` (M1 tool registry, imports `cadence.server`) and its test are replaced. `store.py`/`routines.py` stay untouched (v2 diary). Jev's golden set needs schedule items (see Open questions).

### Decision: Schedule storage - save the words, decide at fire time
- **Status:** Accepted
- **Context:** "Wake me up at 7 and play jazz". Jev decides single calls well but is not built to produce an action nested inside an action.
- **Options considered:** (a) Store `{time, repeat, greeting, command text, room}`. At fire time, announce a greeting if set, then submit `command` as an `Event(kind="schedule", payload={"text": command, "schedule_id"})` through the normal decide path. (b) Resolve to exact plugin calls when the schedule is set: predictable at fire time, but it needs the LLM for nested calls.
- **Decision:** (a). The fire-time decision is logged like any other.
- **Consequences:** If Jev or Muse is down at fire time, the greeting still plays and the failure is spoken and logged. Schedules live in a new `schedules` table in `cadence.sqlite3`.

### Decision: Schedule conflicts - ask, then wait for yes/no without the wake word
- **Status:** Accepted
- **Context:** The user wants the AI to ask before deleting a clashing schedule.
- **Options considered:** (a) A clash is another schedule within ±15 min on an overlapping day. Cadence asks and the speaker listens about 8 s without the wake word. (b) Exact same time only. (c) Any clash, with the wake word needed to answer.
- **Decision:** (a). Cadence stores one *pending question* per device (kind `schedule_conflict`, the new schedule, the clashing ids, expiry 8 s). It sends `say` then `listen {seconds: 8}`. The next utterance from that device within the window is matched as yes or no before normal decision. A yes deletes the clashes and saves the new schedule; a no keeps the old ones and drops the new one; anything else or a timeout drops the question and says so.
- **Consequences:** This is the first two-step conversation in the system. The speaker adapter needs a wake-free listen window, and the `listen` command is new.

### Decision: Corrections across inputs - look back by device then room
- **Status:** Assumed - not confirmed
- **Context:** After a 7am schedule plays the wrong thing, "no, not that" comes from the speaker. But the decision was made with source `scheduler`, so `last_for_source(event.source)` would miss it.
- **Options considered:** (a) The correction finds the last decision within the window whose source *or* target room matches the speaker's room. (b) Keep source-only matching, so schedule mistakes can't be corrected by voice. (c) Look for the last decision anywhere in the house, which goes wrong once there are several rooms.
- **Decision:** (a).
- **Consequences:** `DecisionLog` needs the room recorded per decision (check whether it is already in `ctx`). Labels still come only from spoken corrections.

### Decision: Smaller defaults
- **Status:** Assumed - not confirmed
- **Context:** Small calls the user wasn't asked about. Each is cheap to reverse.
- **Options considered:** Stated defaults, or ask each one separately.
- **Decision:** Times use the server's local time zone. A schedule missed by more than 5 min (Cadence was down) is skipped, logged, and not fired late. Text-only clients (`smoke_session.py`) connect to `/peer` as a device with no abilities and `text_out`; `say` arrives as text. Turn timing: the speaker adapter sends its stage stamps (`wake`, `speech_end`, `asr_done`) inside the event, and Cadence merges them into `latency_ms`, so the per-turn timing line is still complete. `BenchRecorder`, acks, mixer and all of `cadence/audio/` move to `speaker/`.
- **Consequences:** Any of these can be changed during planning without touching the architecture.

## Data flow

**Device protocol** (`/peer`, port 8770, JSON text frames, `PROTOCOL_VERSION = 1`):

| Direction | Message | Fields |
|---|---|---|
| peer to Cadence | `hello` | `version`, `peer_id`, `role` (`device`\|`service`), `kind` (e.g. `speaker`), `room?`, `caps` (`audio_out`, `text_out`, ...), `abilities[]` (Capability fields) |
| Cadence to peer | `welcome` / `error` | `error.message` on a version mismatch or bad hello (then close) |
| peer to Cadence | `event` | `kind` (`utterance`), `payload` (`text`, `asr_conf`), `timing` (stage stamps) |
| Cadence to peer | `turn_start` / `turn_end` | for the event that started the turn |
| Cadence to peer | `call` | `call_id`, `capability`, `args`, `target` (device id or null) |
| peer to Cadence | `result` | `call_id`, `ok`, `say?`, `data`, `error?`, `media?` (`device`, `action`, `url?`) |
| Cadence to peer | `ack` | `category` (`action`\|`chat`\|`correction`) |
| Cadence to peer | `say` | `text` |
| Cadence to peer | `listen` | `seconds`: open the mic without the wake word |
| Cadence to peer | `media` | `action` (`play_url`\|`pause`\|`resume`\|`stop`), `url?` |
| peer to Cadence | `media_event` | `type` (`track_end`\|`lost`\|`stopped`), `position_ms` |
| peer to Cadence | `state` | free-form dict (Muse: now playing, paused), fed to `LiveContext` |

**Voice turn:** board mic, then speaker adapter (wake, VAD, ASR), then `event`, then `Core.submit` (takes the lock). Next a pending-question check, then the pipeline: Jev, then the LLM if needed. Then `Executor`, which sends a `call` to the owning peer and waits for its `result`. Any `media` in the result is forwarded to the target speaker. Last come `ack` and `say` back to the source device, then the decision log, then `turn_end`.

**Schedule fire:** the core's schedule loop ticks every 30 s and finds due rows. It takes the lock, sends `announce(greeting)` to the schedule's room, submits `Event(kind="schedule")` with the stored command, and logs the decision. A daily schedule rolls to the next day; a one-time schedule is deleted.

**State:** schedules, the decision log and labels live in `cadence.sqlite3` (Cadence). Queues and now playing live in the Muse adapter. Gain, mute and the music stream live in the speaker adapter. The device registry and catalogue are in memory in Cadence, rebuilt from hellos.

## Error handling

- Speaker can't reach Cadence: it plays the local "I can't reach my brain right now" line on a turn attempt and retries the peer connection every 2 s. Board `/session` stays up.
- A peer disconnects: its abilities leave the catalogue and its device goes offline, so Jev won't pick them. In-flight calls to it resolve as `Result(ok=False, error="peer_lost")`.
- A `call` gets no `result` within 5 s: "Sorry, that didn't work.", logged with `error="timeout"`.
- `hello` version mismatch or malformed hello: an `error` message, then the socket closes.
- Muse down when a schedule fires: the greeting still plays, the music call fails and is spoken and logged.
- A pending question expires or gets an unclear answer: the question is dropped, the new schedule is not saved, and Cadence says "I'll leave your schedules as they are."
- A decision log write fails: the current behavior stays (`log_healthy = False`, stderr line).

## Testing strategy

- **Core (`harness/tests/`):** fake peers over a real in-process WebSocket (FastAPI `TestClient`): hello/catalogue add and remove, call/result round trip, timeout, peer loss, media forwarding, announce, version mismatch. Existing pipeline, decider and decision log tests stay.
- **Schedules:** add, cancel, daily roll, once delete, missed-by-more-than-5-min skip, conflict window ±15 min, pending question yes/no/timeout. All with an injected clock.
- **Speaker adapter (`speaker/tests/`):** the current `test_server.py` cases move here against a fake Cadence peer: hello, mic frames ignored mid-turn, reconnect cleanup, ports, plus `listen` window and `say` while music plays (ducking). Audio unit tests (`test_listener`, `test_mixer`, `test_speaker`, `test_acks`, `test_benchrec`, `test_turntiming`, `test_wakebench`) move with their code.
- **Muse adapter (`muse_adapter/tests/`):** `test_music_plugin.py` and `test_muse_client.py` move and adapt to the call/result/media shape.
- **Jev:** add schedule utterances to the golden set and rerun `golden_replay.py`.
- **Board smoke test** after step 1 and again after step 2: wake word, a command, music play/pause, volume, a schedule set one minute ahead firing with a greeting, a conflict prompt answered without the wake word. Recorded in `docs/hardware/build-log.md`.
- Out of scope: multi-speaker, per-room locks, CSI, party sync.

## Tech stack

- Python >= 3.14, FastAPI WebSockets for `/peer` (Cadence) and `/session` (speaker adapter), `websockets`-style client in the adapters. No new dependencies; the plan verifies which WebSocket client library is already installed before choosing.
- SQLite (`cadence.sqlite3`) for schedules plus the existing decision log.
- Existing: Jev (TypeSafe), Ollama `gemma4:31b-cloud`, Whisper, Kokoro, openwakeword, all now in the speaker adapter except the deciders.

## Open questions

- Deferred: GitHub repo rename (`IanTheMitten/Cadence_Speaker` to Cadence), local folder rename, and creating the cadence_speaker and cadence_muse repos. This is step 2 and outward-facing, so the user confirms at that time.
- Deferred: the exact Jev golden-set schedule items and whether `schedule.add` needs LLM escalation for time parsing. The plan measures this with `golden_replay.py`.
- Deferred: which WebSocket client library the adapters use. The plan checks `harness/requirements.txt` and picks what is already installed.
- Deferred: cadence_lights. It is out of scope here and will connect with the same protocol when built.

## Provenance

- user-picked: repo split (this repo becomes Cadence), Muse as its own service peer, voice add+cancel daily/once, conflict prompt (user asked for it; ±15 min and no wake word were recommended and accepted)
- recommended-and-accepted: Core object, split in place then move, sibling folders, network API (after a latency question), WebSocket + JSON, peer-declared abilities, rooms in hello, board unchanged on 8768, cadence_muse repo, lock in Core, speaking first via announce (accepted once the network design made it cheap), save the words, error handling and testing defaults
- assumed: shared protocol copied per repo, corrections by device then room, smaller defaults (time zone, missed-schedule skip, text clients, turn timing, audio modules move)
- overrides: none
