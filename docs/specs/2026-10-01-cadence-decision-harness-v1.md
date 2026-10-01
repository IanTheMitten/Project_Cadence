# Technical spec — Cadence decision harness v1

> Status: ready for planning. Feed to /autopilot-plan.

## Source

Brainstorming session of 2026-10-01 (no PRD for this milestone), building on:

- `docs/specs/2026-09-19-voice-music-agent-harness.md` (the M1 spec, referred to below as "M1")
- `docs/research/2026-09-30-jev-needle-laya.md` (benchmarks of Jev, Needle, Laya, and the cloud LLM)

Cadence is a home system: an ESP32-S3 speaker with a microphone, a circadian-warmth lamp that also acts as an alarm (not built yet), and an emotion-aware music player (Muse, not fully working yet). The harness is the decision layer between inputs (voice now; schedules and sensors later) and the things it can act on (devices and services).

## Scope and roadmap

| Version | Content |
|---|---|
| **v1 (this spec)** | A modular, extensible harness plus the speaker (server-side wake word, audio in/out, volume) and Muse music (search, mood and artist requests, mood-built queues, pause/skip/rate, what's playing). Jev as the decider, a cloud LLM on escalation, a decision log with spoken-correction labels, the acknowledgement clip pool. |
| **Firmware plan (separate)** | Board-side wake word (`esp-sr`) with its audio front end doing echo cancellation, replacing the server-side wake word. Needs ESP-IDF and the board attached. |
| **v2** | The lamp (including the alarm and gradual wake-up ramp), the scheduler, rules as a decider, plugin event streams, diary and routines. |
| **v2.1** | WiFi presence and posture/breathing/heart-rate sensing, built into the lamp hardware. |
| **Later** | Voice ID, finetuning Needle or Laya on the decision log, going fully local. |

## Relation to M1

**Built in M1 and reused:** the audio stages (VAD, faster-whisper, Kokoro TTS, mixer with ducking), the session abstraction and WebSocket protocol, the WebSocket firmware client in `voice_chat/`, the Muse client, the Ollama client, the shared rolling conversation context.

**Decided in M1, not built, and now settled here:** the wake word (server-side `openwakeword` in v1, board-side later), the acknowledgement pool (built in v1, timing changed), echo subtraction (moved to the firmware plan).

**Superseded:** the LLM-first agent loop (`agent.run_turn`) and the routine-hit fast path (Jev now decides first). M1's thin-tool principle for music — the model picks each track — is superseded for v1: the music plugin composes queues deterministically from structured slots.

**Kept as-is from M1:** deployment host `ianshomeserver`; ASR uncertainty means act anyway (the `no_speech_prob` floor still drops noise); a failed action is reported aloud and never retried; Muse unreachable means say so and stop; the turn path holds one concurrency slot (`TURN_LOCK`).

**Deferred to v2 with the diary:** `SqliteContextProvider` (reads the diary's `decisions` table in `store.py`), routines, the scheduler. Their code stays in the repo, unwired.

## Architecture

```
 endpoints / sources                 harness                              plugins
 ───────────────────        ─────────────────────────────         ──────────────────
 speaker session       ──▶   Event ▶ Decide ▶ Resolve ▶ Execute ──▶  speaker (device, audio port)
 (mic ▶ wake word ▶ VAD        │     (Jev → LLM)  (registry)  │      music (Muse client)
  ▶ ASR; WebSocket)            │                              │      [MCP adapter → any MCP server]
 text session (testing)        └────────── Decision log ◀─────┘
 [v2] scheduler, sensors          (SQLite, append-only)
```

**Event.** The only input to the pipeline: `{id, ts, kind, source, room, user_id, payload}`. v1 kind: `utterance`; v2 adds `schedule` and `sensor`. `user_id` defaults to `household`. A correction is not an event kind: it is an utterance the decider routes to the `correction` capability.

**Plugin.** A small in-process interface: a manifest (id, kind device/sensor/service, capabilities) and `call(capability, args, target, port)`, plus `available()` and `state()`. Event streams from plugins arrive in v2 with sensors. Native plugins in v1: speaker and music. An MCP adapter wraps any external MCP server as a plugin; no MCP plugin is wired by default in v1.

**Speaker is two things.** An *endpoint* (WebSocket session producing utterances) and a *device* with an audio port (play a stream, pause, resume, stop, speak with ducking, volume).

**Device registry.** Devices with room, kind, and online state, loaded from a static config file. A speaker is marked online when its WebSocket session connects.

**Output path.** The music plugin is a service, not an output. The executor resolves `music.*` capabilities to a target speaker and hands the plugin that speaker's audio port. Plugins never call each other.

**Capability catalogue.** A flat, fixed-size list of generic capabilities generated from plugin manifests, plus two built-ins (`chat`, `correction`). Each capability declares which args are **closed-set** (Jev can choose them) and which are **free text** (only an LLM can fill them). v1 catalogue: `music.play`, `music.control`, `music.rate`, `music.now_playing`, `speaker.volume`, `chat`, `correction`.

**Deciders.** One interface: `decide(event, context, capabilities, instruction) -> Decision`. v1 implementations: `JevDecider`, `LlmDecider`.

**Resolver, executor, decision log.** The resolver picks target devices, the executor calls plugins (at most 3 calls per turn, stopping at the first failure), the decision log records every decision.

**Context.** A live-state snapshot per event: time, weekday, room, what the source speaker is playing, the last three decisions. The rolling conversation context (M1, 10 turns) feeds the LLM.

### Module layout (`harness/cadence/`)

- `events.py`, `catalogue.py`, `resolver.py`, `executor.py`, `pipeline.py`, `livecontext.py`, `decisionlog.py`, `acks.py`, `wiring.py`
- `deciders/`: `base.py`, `jev.py`, `llm.py`
- `plugins/`: `base.py`, `registry.py`, `speaker.py`, `music.py`, `mcp_adapter.py`
- `audio/`: existing stages plus `wakeword.py` and `listener.py`
- `server.py` keeps the `/session` protocol and `TURN_LOCK`, and hands utterances to the pipeline

## Decisions

### Decision: Jev is the only first-stage decider for now
- **Status:** Accepted
- **Context:** The benchmark measured, on 48 hand-written utterances: Jev routing at 0.979 decision and 0.917 tool-name accuracy, 207 ms median including network; Laya at 0.979 / 0.646, about 1.07 s on this CPU; Needle alone at 0.44 / 0.38 / 0.33; the cloud LLM at 1.00 / 0.92 / 0.83, 612 ms. Zero-shot, small self-labelled set, different tool list from v1 — the numbers indicate, not predict, v1 accuracy.
- **Options considered:** (a) Jev; (b) Laya, open and finetunable; (c) Needle after a Jev gate; (d) one cloud LLM for everything.
- **Decision:** (a). Needle or Laya replace it once the decision log holds enough labelled data.
- **Consequences:** Jev is hosted-only and its docs say it is not fine-tuned on customer data, so it is a stopgap and teacher, not the destination. Transcripts go to TypeSafe (accepted). Jev sits behind the `Decider` interface so it can be swapped.

### Decision: Event-driven core with deciders behind one interface
- **Status:** Accepted
- **Context:** Voice is the only v1 trigger, but v2 adds schedules and sensor events, and the v2 wake-up ramp needs a model decision inside a schedule.
- **Options considered:** (a) one pipeline for every input; (b) separate pipelines per input sharing registry and log; (c) Home Assistant underneath, harness as decision layer only.
- **Decision:** (a).
- **Consequences:** More upfront structure than the M1 turn loop. (b) would duplicate decision logic once schedules need decisions; (c) would cost control over the event and decision-log schema, which is the point of the project.

### Decision: Plugins are hybrid, native plus MCP
- **Status:** Accepted
- **Context:** The lamp and speakers are stateful, can exist several times, and push events; Muse and future services are stateless request/response.
- **Options considered:** (a) one MCP server per plugin; (b) in-process Python plugins only; (c) in-process interface with an MCP adapter.
- **Decision:** (c). Native plugins for speaker, music, and later the lamp; the MCP adapter for third-party and stateless services.
- **Consequences:** Native plugins share the harness process, so a plugin crash can take it down; MCP plugins stay process-isolated.

### Decision: Capability tools plus a deterministic target resolver
- **Status:** Accepted
- **Context:** Jev routes over a closed list, and its accuracy should not fall as devices are added.
- **Options considered:** (a) generic capabilities plus a resolver; (b) one tool per device; (c) an LLM resolves targets.
- **Decision:** (a). Target order: a room named in the args; else the room of the source device; else the source device itself; else every online device of the needed kind.
- **Consequences:** The catalogue stays the same size as devices are added. Rooms live in the device registry config.

### Decision: Jev handles closed-set choices; free-text args always go to the LLM
- **Status:** Accepted
- **Context:** Jev's docs say it does not generate text; it answers `choice`, `score`, and `noul` questions. Its function-calling cookbook covers only closed-set arguments. Argument accuracy for Jev was not measured in the benchmark.
- **Options considered:** (a) Jev fills closed-set args in the same request (speculative fan-out, documented by TypeSafe), the LLM fills free-text args; (b) the LLM fills every arg; (c) Jev only, no free-text capabilities.
- **Decision:** (a). `music.control`, `music.rate`, `music.now_playing`, and `speaker.volume` are closed-set and can run on Jev alone. `music.play` has free-text slots (artist, title, mood, genre) and always escalates to the LLM for args. A config switch turns Jev's closed-set args off, sending those to the LLM too.
- **Consequences:** Music requests pay one LLM round trip (612 ms median in the benchmark), masked by the acknowledgement clip. Control commands stay at Jev latency. A golden-set replay measures closed-set accuracy and sets the switch.

### Decision: LLM escalation on need
- **Status:** Accepted
- **Context:** The user wants an LLM called only when needed.
- **Options considered:** (a) escalate on need; (b) LLM always fills args; (c) Jev only, no LLM.
- **Decision:** (a). Escalation reasons: `chat` (Jev routed to chat), `low_confidence` (route confidence below a threshold, initially 0.5 per TypeSafe's intent-routing pattern; the LLM sees the top two candidates with probability at least 0.25), `needs_args` (free-text args), `correction`, `jev_unavailable` (the LLM decides over the full catalogue). The LLM returns at most 3 calls (M1 cap) or a spoken reply.
- **Consequences:** The threshold is tuned by the golden-set replay. If the LLM is also unreachable, the harness says so and stops (M1).

### Decision: Labels come from spoken correction only
- **Status:** Accepted
- **Context:** The speaker is the only input channel in v1. There is no app, UI, button, or manual-override signal.
- **Options considered:** (a) spoken correction; (b) quick manual override; (c) repeated command; (d) a periodic review UI.
- **Decision:** (a) only. An uncorrected decision is unlabeled, not right.
- **Consequences:** Labels are sparse and skew toward errors. Training export treats unlabeled rows as unknown.

### Decision: Correction flow
- **Status:** Accepted
- **Context:** "No, the other one" means nothing without what came before.
- **Options considered:** (a) re-decide on the correction text alone; (b) re-decide with the previous request and action plus the correction; (c) ask what they meant.
- **Decision:** (b). The `correction` route finds the most recent decision from the same source within 60 seconds, re-decides through the LLM with that decision's text and action plus the correction, then labels the previous decision `wrong` with `corrected_by` pointing at the new one. With no recent decision, the correction is decided as a fresh request.
- **Consequences:** A correction can itself be corrected. The 60-second window is a config value.

### Decision: Decision log is separate, append-only, text only
- **Status:** Accepted
- **Context:** The log is training data; it must not be silently rewritten, and M1's diary already owns a `decisions` table.
- **Options considered:** (a) new append-only tables with labels in their own table; (b) add columns to M1's `decisions` table; (c) JSONL files.
- **Decision:** (a). Tables `decision_log` (immutable rows) and `decision_labels`, in the harness SQLite file. No raw audio. ASR confidence is stored as null until the ASR stage exposes it.
- **Consequences:** The diary can read the log in v2. A log write failure never blocks an action; it prints to stderr and sets a health flag.

### Decision: Identity is a seam in v1
- **Status:** Accepted
- **Context:** The user wants per-user behaviour eventually, via voice ID.
- **Options considered:** (a) `user_id` field defaulting to `household`; (b) voice ID now; (c) room-based identity.
- **Decision:** (a).
- **Consequences:** Voice ID later sets `user_id` without a schema change.

### Decision: Music requests are composed by the music plugin
- **Status:** Accepted
- **Context:** Muse has text search, vibe search, recommend, plays, and ratings, but no combined artist-plus-mood search and no saved playlists.
- **Options considered:** (a) compose in the plugin now, Muse adds filtered search later behind the same capability; (b) extend Muse first; (c) let the LLM chain search primitives.
- **Decision:** (a). `music.play {artist?, title?, mood?, genre?, count?}`: text search for artist/title (filtered to the named artist), vibe search for mood/genre, intersect and order by vibe score, keep playable tracks, queue the first `count` (default 10). "Make me a chill playlist" is a mood queue. Saved, named playlists wait for Muse and arrive as a `music.playlist` capability.
- **Consequences:** Composition is deterministic and unit-testable. Fixing the Muse recommendation algorithm is a separate Muse workstream.

### Decision: Speaker and Muse sync through shared facts, not shared state
- **Status:** Accepted
- **Context:** Muse's own player has a single global player state; the phone and the speaker should not hijack each other.
- **Options considered:** (a) the harness holds the speaker's queue and reports plays and ratings; (b) one shared player state; (c) fully independent, nothing written back.
- **Decision:** (a). The music plugin opens a play span (`POST /api/plays`, source `cadence`) when a track starts and closes it (`POST /api/plays/{id}/close`) with a reason from Muse's fixed set: `track_end`, `user_next`, `user_prev`, `new_selection`, `pause_timeout` (paused longer than 600 s), `lost` (session dropped or stream failed).
- **Consequences:** Muse's recommender learns from speaker listening. A play-span write failure is logged and never stops playback.

### Decision: Muse–Cadence contract, owned by Muse
- **Status:** Accepted
- **Context:** Changes to Muse must not silently break Cadence, and the reverse; the user wants the rules documented in Muse too.
- **Options considered:** (a) Muse owns a versioned contract with a snapshot test, Cadence pins it; (b) Cadence owns the contract; (c) no formal contract, fixtures only.
- **Decision:** (a). Rules: Muse documents the Cadence surface in `docs/contracts/cadence.md` with a committed OpenAPI snapshot and a test diffing it; Muse serves `GET /api/contract` returning `MAJOR.MINOR` (additive change = minor, anything else = major with a deprecation window); Cadence checks the version at startup, treats a missing endpoint as the pre-contract baseline (today's API, as captured in `harness/tests/fixtures/muse/`), and marks music unavailable on a major mismatch; Cadence ignores unknown response fields; a surface change lands in Muse first, then a Cadence sync. Consumers on the Cadence side: the music plugin and `tools/muse_proxy.py`.
- **Consequences:** The Muse-side work is a separate plan in `~/Projects/muse_intelligence`, briefed by `docs/handoffs/2026-10-01-muse-cadence-contract.md`. Muse binds tailnet addresses only, so Cadence reaches it by tailnet address, configurable by environment variable.

### Decision: Wake word is server-side in v1
- **Status:** Accepted
- **Context:** The user wants a board-side wake word, but ESP-IDF and the board are not available on the server where this plan runs. The current firmware already streams the mic continuously, so a server-side wake word adds no privacy cost over today.
- **Options considered:** (a) `openwakeword` on the server now, `esp-sr` on the board later; (b) board-side only, no wake word until firmware lands; (c) server-side permanently.
- **Decision:** (a). Stock model `hey_jarvis_v0.1` with the ONNX runtime until a custom phrase is trained. After the wake word fires, the next VAD utterance within 8 seconds is the request.
- **Consequences:** `openwakeword` 0.6.0 hard-requires `tflite-runtime` on Linux, which has no Python 3.14 wheel; it is installed with `--no-deps` and run with `inference_framework="onnx"` (verified on this server). A config switch disables the gate, falling back to VAD-only.

### Decision: Acknowledgement clips fire on Jev's route
- **Status:** Accepted
- **Context:** M1 planned a pre-rendered clip pool fired after ASR. Jev's route arrives about 200 ms after ASR and gives the category directly.
- **Options considered:** (a) after ASR, uncategorised; (b) after Jev's route, category-matched; (c) no acknowledgement.
- **Decision:** (b). Categories `action`, `chat`, `correction`. The cloud LLM writes the phrases offline and Kokoro pre-renders them; nothing is generated at speech time. When Jev is unavailable no clip plays.
- **Consequences:** Supersedes M1's acknowledgement-timing assumption.

### Decision: Echo handling moves to the firmware plan
- **Status:** Accepted
- **Context:** Server-side echo subtraction needs tuning against the board's real playback delay, which cannot be done without the board.
- **Options considered:** (a) build server-side subtraction now as an untunable experiment; (b) leave it to the board-side `esp-sr` audio front end; (c) never.
- **Decision:** (b).
- **Consequences:** In v1 music ducks while the assistant speaks, and the wake word may miss over loud music.

## Data flow

1. **Endpoint.** The speaker streams mic audio. The wake gate fires, the next VAD utterance (within 8 s) goes to faster-whisper, and the text becomes an `utterance` event with the speaker's id as source and its room. Text sessions send text directly (used for testing).
2. **Decide.** `TURN_LOCK` held. Live context snapshot, then `JevDecider` over the available catalogue: one request carrying the route question and every closed-set arg question.
3. **Acknowledge.** A clip for the routed category plays immediately.
4. **Escalate** per the escalation decision, or execute Jev's call directly.
5. **Execute.** Resolver picks targets, executor calls plugins, each result's spoken text is synthesised and mixed over any music (ducked).
6. **Record.** One `decision_log` row: event, context snapshot, Jev's route/confidence/probabilities, final decider, calls, reply, escalation reason, results, outcome, per-stage latency, model versions. A correction adds a `decision_labels` row for the decision it corrects.

## Error handling

| Failure | Response |
|---|---|
| Jev unreachable, HTTP error, or over 1.5 s | LLM decides over the full catalogue; escalation `jev_unavailable`. |
| No TypeSafe key at startup | Harness runs with Jev permanently unavailable (every turn escalates); logged at startup. |
| LLM unreachable | Say "I can't reach my brain right now." and stop; the turn is logged. |
| Muse unreachable or major contract mismatch | Music capabilities drop out of the catalogue; a music request says "Muse isn't answering." |
| Plugin call raises | Spoken failure, remaining calls skipped, never retried. |
| Play-span write fails | Logged, playback continues. |
| Low ASR confidence | Act anyway (M1). |
| Log write fails | Stderr plus health flag; the action already happened. |

## Testing strategy

Red tests first, as in M1. Unit tests use fakes for Jev (`httpx.MockTransport`), the LLM (scripted responses in the recorded Ollama shape), Muse (`httpx.MockTransport` plus captured fixtures), audio ports, and the wake-word model, so no hardware or network is needed. A FastAPI WebSocket test drives a text session end to end through the real pipeline with fake deciders. Live checks are experiments with recorded results: a runtime preflight on the server, a golden-set replay of 48 utterances relabelled for the v1 catalogue against real Jev (sets the confidence threshold and the closed-arg switch), and an end-to-end text-session smoke against live Jev, the LLM, Muse, and the proxy.

## Tech stack

| Layer | Choice | Traces to |
|---|---|---|
| Host | `ianshomeserver`, Python 3.14.4, venv at `harness/.venv` | M1 deployment host |
| Decider | TypeSafe Jev `jev-latest` over HTTPS (`httpx`) | Jev decision |
| LLM | Ollama `gemma4:31b-cloud`, `think: false` live, `think: true` for the ack pool | M1 LLM model |
| Wake word | `openwakeword` 0.6.0, `--no-deps`, ONNX runtime | Wake word decision |
| ASR / TTS / VAD | `faster-whisper` small.en, Kokoro via `kokoro-onnx`, `webrtcvad` (M1) | M1 |
| Transport | FastAPI WebSocket `/session` on port 8768 (M1 protocol) | M1 client interface |
| Storage | SQLite `harness/cadence.sqlite3`, new tables `decision_log`, `decision_labels` | Decision log decision |
| Muse | HTTP to the tailnet address, plays and ratings write-back | Sync and contract decisions |
| Plugins | in-process ABC; MCP adapter over the existing `mcp` 2.2.0 `ToolRegistry` | Hybrid plugins decision |

## Open questions

- Deferred: Jev rate limits beyond the documented 40 requests per second — one household produces a request every few seconds at most, so this cannot bind in v1.
- Deferred: a custom wake phrase — `hey_jarvis_v0.1` serves until a model is trained; training is not v1 work.
- Deferred: Muse recommendation algorithm problems — a separate Muse workstream; the user has not described them yet.
- Deferred: board PSRAM and flash — they only gate the separate firmware plan.

## Provenance

- **user-picked:** Jev only for now; event-driven core; hybrid plugins; capability tools plus resolver; escalation on need; spoken-correction labels; `user_id` seam; Muse changes in parallel with a contract owned by Muse; shared facts not shared state; server-side wake word now; acknowledgement pool in v1; echo handling with the firmware plan; v1/v2/v2.1 roadmap.
- **recommended-and-accepted:** correction flow and 60-second window; acknowledgement fired on Jev's route; saved playlists out of v1; append-only log with separate labels table; text-only log.
- **assumed:** none.
- **corrections of record:** an earlier draft said low ASR confidence asks the user to repeat; M1 decided "act anyway" and that stands. An earlier draft listed the deployment host as open; M1 already settled it as `ianshomeserver`. An earlier draft implied Jev might extract every arg; its docs say it cannot generate text, so free-text args always go to the LLM.
