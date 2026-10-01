# Technical spec — Cadence decision harness v1

> Status: draft for review. Not yet planned.

## Source

Brainstorming session of 2026-10-01, building on:

- `docs/specs/2026-09-19-voice-music-agent-harness.md` (the M1 spec, referred to below as "M1")
- `docs/research/2026-09-30-jev-needle-laya.md` (benchmarks of Jev, Needle, Laya, and the cloud LLM)

Cadence is a home system: an ESP32-S3 speaker with a microphone, a circadian-warmth lamp that also acts as an alarm (not built yet), and an emotion-aware music player (Muse, not fully working yet). The harness is the decision layer that sits between inputs (voice now; schedules and sensors later) and the things it can act on (devices and services).

## Scope and roadmap

| Version | Content |
|---|---|
| **v1 (this spec)** | A modular, extensible harness plus the speaker (wake word, audio in/out, volume) and Muse music (play a track, search, mood and artist requests, mood-built queues; saved playlists wait for Muse). Jev as the decider, a cloud LLM on escalation, a decision log with spoken-correction labels. |
| **v2** | The lamp (including the alarm and gradual wake-up ramp), the scheduler, rules as a decider, diary and routines. |
| **v2.1** | WiFi presence and posture/breathing/heart-rate sensing, built into the lamp hardware. |
| **Later** | Voice ID, finetuning Needle or Laya on the decision log, going fully local. |

Diary, routines, and the scheduler from M1 are **deferred to v2**. Their code stays in the repository but is not wired into the v1 pipeline.

## Relation to M1

**Built in M1 and reused:** the audio stages (VAD, faster-whisper, Kokoro TTS, mixer with ducking), the session abstraction, the WebSocket firmware client, the Muse client, and the Ollama client.

**Decided in M1 but not built, and still v1 work:** the board-side wake word (`esp-sr`) with `openwakeword` on the server as fallback, reference-based echo subtraction, and the pre-rendered acknowledgement pool. None of these exist in the code yet. `main/` has no wake word, and `harness/cadence/` has no echo subtraction or acknowledgement pool.

**Superseded:** the LLM-first agent loop (`agent.run_turn` choosing among MCP tools) and the routine-hit fast path. Jev now makes the first decision, and the LLM is called only on escalation.

**Deferred to v2 with the diary:** `SqliteContextProvider`, which reads the diary's `decisions` table in `store.py`. v1 uses a live-state provider instead (see Context below).

## Architecture

The event-driven core: every input becomes an `Event`, and one pipeline handles all of them.

```
 endpoints / sources                 harness                              plugins
 ───────────────────        ─────────────────────────────         ──────────────────
 speaker (wake word,   ──▶   Event ▶ Decide ▶ Resolve ▶ Execute ──▶  speaker (device)
  mic stream, WebSocket)       │     (Jev → LLM)  (registry)  │      music (Muse client)
 [v2] scheduler, sensors       │                              │      [MCP adapter → any MCP server]
                               └────────── Decision log ◀─────┘
                                  (SQLite, append-only)
```

**Event.** The only input to the pipeline: `{id, ts, kind, source, room, user_id, payload}`. Kinds: `utterance` (v1); `schedule`, `sensor` (v2). `user_id` defaults to `household`. A correction is not an event kind: it is an `utterance` that the decider routes to the `correction` capability, because nothing knows it is a correction until it has been decided.

**Plugin.** A small in-process interface: a manifest (id, kind device/sensor/service, capabilities), `tools()`, `call(tool, args)`, optional `state()` and an async `events()` stream. Native plugins in v1: speaker and music. An MCP adapter wraps any external MCP server as a plugin. The existing Muse MCP server stays available but is not on the main path.

**Speaker is two things.** An *endpoint* (mic in, audio out, over WebSocket) that produces `utterance` events carrying a room, and a *device plugin* with tools such as volume.

**Device registry.** Devices with room, group, capabilities, and online state. Targeting looks things up here. In v1 the devices and their rooms come from a static config file. A speaker is marked online when its WebSocket session connects.

**Output path.** The music plugin is a service, not an output. `music.play` resolves to a target speaker. The music plugin builds the queue and a stream source, and the executor hands that source to the target speaker's session, where the mixer combines it with any speech. Plugins never call each other directly. Cross-plugin work goes through the executor.

**Capability catalogue.** A flat, fixed-size list of generic tools generated from plugin manifests, with descriptions written for the model. It is what Jev routes over and it does not grow when a second lamp or speaker is added. v1 catalogue: `music.play`, `music.control`, `music.rate`, `speaker.volume`, `chat`, `correction`.

**Deciders.** One interface, `decide(event, context) -> Decision`. v1 implementations: `JevDecider` and `LlmDecider`. `RuleDecider` arrives in v2 behind the same interface; v1 does not stub it. A `Decision` holds the capability, partial args, confidence, and candidates.

**Resolver.** Fills the concrete target from the registry and the event's room. **Executor.** Calls the plugin. **Decision log.** Records everything.

**Context.** v1 adds a live-state implementation of the existing `ContextProvider` interface: time, the event's room, what each speaker is playing, and the last few decisions from the decision log. The diary-backed `SqliteContextProvider` returns in v2.

### Module layout (`harness/cadence/`)

- `events.py`, `pipeline.py`
- `deciders/`: `base.py`, `jev.py`, `llm.py` (reuses the Ollama client and the `agent.py` core)
- `plugins/`: `base.py`, `registry.py`, `mcp_adapter.py`, `speaker.py`, `music.py`
- `catalogue.py`, `resolver.py`, `executor.py`, `decisionlog.py`
- Kept: `audio/`, `context.py`, `llm.py`. `server.py` shrinks to the speaker endpoint that emits `utterance` events.

## Decisions

### Decision: Jev is the only first-stage decider for now
- **Status:** Accepted (user)
- **Context:** The benchmark (`docs/research/2026-09-30-jev-needle-laya.md`) measured, on 48 hand-written utterances: Jev routing at 0.979 decision accuracy and 0.917 tool-name accuracy with a 207 ms median latency including network; Laya at 0.979 / 0.646 and about 1.07 s on this CPU; Needle alone at 0.44 / 0.38 / 0.33. The cloud LLM scored 1.00 / 0.92 / 0.83 at 612 ms. These are zero-shot results on a small self-labelled set, so gaps under about 10 points are noise.
- **Options considered:** Jev; Laya (open, finetunable); Needle after a Jev gate; a single cloud LLM.
- **Decision:** Jev only. Needle and Laya come after the decision log holds enough data to finetune them.
- **Consequences:** Jev is hosted-only, keyed, and its docs say it is not fine-tuned on customer data, so it is a stopgap and a teacher, not the destination. Transcripts go to a third party (accepted). Jev sits behind the `Decider` interface so it can be swapped.

### Decision: Event-driven core with deciders behind one interface
- **Status:** Accepted (user)
- **Options considered:** (A) one pipeline for all inputs; (B) separate pipelines for voice, scheduler, and sensors; (C) build on Home Assistant.
- **Decision:** (A). The v2 wake-up ramp needs voice-style decisions inside a schedule, which (B) would duplicate. (C) would cost control over the event and decision-log schema, which is the main goal.
- **Consequences:** More upfront structure than the M1 turn loop.

### Decision: Plugins are hybrid, native plus MCP
- **Status:** Accepted (user)
- **Options considered:** MCP server per plugin; in-process Python plugins; hybrid.
- **Decision:** Hybrid. Devices are stateful, may appear several times, and push events, which fits MCP poorly. MCP stays for stateless services and third-party integrations.

### Decision: Capability tools plus a deterministic target resolver
- **Status:** Accepted (user)
- **Decision:** Jev picks a generic capability. A resolver fills the target: room named in the utterance, else the room of the speaker that heard it, else all. The tool list stays constant as devices are added.

### Decision: LLM escalation on need
- **Status:** Accepted (user), with a spike
- **Decision:** A Jev result with all required args and high confidence executes directly. The LLM is called when Jev routes to `chat` or none, confidence is low, or required args are missing or unparseable. The LLM sees only the shortlisted capability.
- **Blocking unknown:** whether Jev's function-calling mode extracts args well enough. Argument accuracy for Jev alone was not measured. **The first task of the plan is a spike** on this. If it fails, the LLM fills args for every capability that has required args (`music.play`, `speaker.volume`, `music.rate`), and those commands gain about one LLM round trip (612 ms median in the benchmark). Argument-free commands such as pause still execute on Jev alone.
- **Benchmark caveat:** the measured numbers came from a different tool list (the 8 Muse tools plus `set_warmth`). The v1 catalogue is smaller and more generic, so the numbers indicate, but do not predict, v1 accuracy.

### Decision: Labels come from spoken correction only
- **Status:** Accepted (user)
- **Context:** The speaker is the only input channel in v1. There is no app, UI, button, or manual-override signal.
- **Decision:** A decision is labelled wrong only when the user speaks a correction. An uncorrected decision is **unlabeled**, not right.
- **Consequences:** Labels are sparse and skewed toward errors. Training export must treat unlabeled rows as unknown, not as positives.

### Decision: Decision log is separate, append-only, text only
- **Status:** Accepted
- **Decision:** Two new tables, `decision_log` (immutable rows) and `decision_labels` (one row per label). The names avoid M1's existing `decisions` table in `store.py`, which belongs to the deferred diary and is left untouched. No raw audio is stored; voice ID, when added, revisits this.
- **Consequences:** The diary can read from this log in v2.

### Decision: Identity is a seam in v1
- **Status:** Accepted (user)
- **Decision:** Every event and decision carries `user_id`, default `household`. Voice ID is a later plug-in with no schema change.

### Decision: Music requests are composed by the music plugin now and by Muse later
- **Status:** Accepted (user)
- **Context:** Muse's API has text search, vibe search, recommend, a queue, plays, and ratings. It has no combined artist-plus-mood search and no named playlists.
- **Decision:** Define the music capability now: `music.play {artist?, title?, mood?, genre?, count?}`. The v1 music plugin composes it client-side from today's endpoints (text search for the artist, vibe re-rank by mood, fill a queue). "Make me a chill playlist" is `music.play` with a mood and a count, and the result is the speaker's queue. Muse gains filtered search as its own workstream in its own repo, and the plugin switches over without the capability changing.
- **Saved playlists are not in v1.** Saving and recalling a named playlist needs storage, and the decision is that Muse owns it. A `music.playlist` capability is added when Muse ships saved playlists, as a minor contract bump.
- **Out of scope here:** fixing the Muse recommendation algorithm. That is a separate Muse workstream.

### Decision: Speaker and Muse sync through shared facts, not shared state
- **Status:** Accepted (user)
- **Decision:** The harness holds the speaker's own queue. It reports plays (`POST /api/plays`, `/api/plays/{id}/close`) and ratings to Muse, so Muse's recommender learns from the speaker and the phone. Neither can hijack the other's playback.

### Decision: Muse–Cadence contract, owned by Muse
- **Status:** Accepted (user)
- **Rules:**
  1. Muse owns the contract: `docs/contracts/cadence.md` plus a committed OpenAPI snapshot of the **Cadence surface** (search, vibe search, recommend, tracks, stream, ratings, plays, and v1 additions), and a Muse ADR recording the rule.
  2. A Muse test diffs the live OpenAPI for that surface against the snapshot, so a change fails until the snapshot, the doc, and the version are updated deliberately.
  3. Muse exposes a contract version (`MAJOR.MINOR`) at `GET /api/contract`. Additive changes are minor. Rename, removal, type change, or changed meaning is major, with the old behaviour kept for a deprecation window.
  4. `MuseClient` checks the version at startup. A major mismatch marks the music plugin unavailable and removes its capabilities from the catalogue. Unknown response fields are ignored. Until Muse ships `GET /api/contract`, a missing endpoint means the **pre-contract baseline**: today's API as captured in the vendored fixtures. That is how v1 works while the Muse workstream runs in parallel.
  5. Cadence vendors the pinned contract and examples in the existing `harness/tests/fixtures/muse/` directory, which already holds `openapi.json` and captured responses from `scripts/capture_muse_fixtures.py`. It adds the contract doc, a sync script, client tests against the fixtures, and a drift warning when Muse is reachable.
  6. A surface change lands in Muse first (code, snapshot, doc, version), then a Cadence sync PR. Both repos' `CLAUDE.md` say so.
- **Consumers on the Cadence side:** the music plugin (through `MuseClient`) and `tools/muse_proxy.py`, which reads `/api/tracks/{id}/stream`. Muse binds tailnet addresses only (`muse/net.py`), so the harness host and the proxy must be on the tailnet.
- **Consequences:** Writing the contract into the Muse repo is a deliverable of the Muse workstream and needs separate approval before anything is changed there.

## Data flow (utterance)

1. The speaker's wake word fires on the board and audio streams to the server. VAD and faster-whisper produce an `utterance` event with text, ASR confidence, room, and `user_id`.
2. `JevDecider` routes over the catalogue.
3. The acknowledgement fires as soon as the route is known, before args and execution, so it masks the remaining latency. It comes from the pre-rendered pool, picked by the routed category (action, chat, correction). This replaces M1's "after ASR" timing, because Jev's route (about 200 ms) gives the category directly.
4. Args come from Jev's function-calling mode if the spike passes, otherwise from the LLM for the one chosen capability.
5. Escalation to `LlmDecider` per the escalation decision above.
6. **Correction:** the `correction` capability links to the most recent decision from the same speaker within 60 seconds (a tunable default). It labels that decision wrong and re-decides using the original utterance and the correction text together, since "no, the other one" means nothing alone. The re-decision is a normal logged decision and can itself be corrected. With no recent decision, the correction is treated as a fresh request.
7. Resolver, then executor.
8. The decision log records the event, a context snapshot, the decider, Jev's raw probabilities for all candidates, the chosen capability and args, confidence, escalation reason, resolved calls, outcome, per-stage latency, and model versions.

## Error handling

- **Jev down or timing out** (budget about 1.5 s): fall back to the LLM over the full catalogue. If the LLM is also down, say "can't process that right now" and log the event with an error outcome.
- **Muse unreachable or major contract mismatch:** remove the music capabilities from the catalogue so Jev cannot pick them, and say so out loud.
- **Low ASR confidence:** ask to repeat (M1 behaviour).
- **Plugin call fails:** log the error, speak the failure, and do not retry silently.
- **Log write fails:** never block the action. Write to stderr and raise a health flag.

## Testing strategy

Red tests first, as in M1.

- **Contract tests** against the pinned Muse fixtures.
- **Pipeline tests** with fake plugins and a fake Jev, so no hardware or network is needed.
- **Golden utterance set:** the 48 benchmark utterances, relabelled for the v1 catalogue and grown over time, replayed through the pipeline as a regression check when the catalogue changes. It doubles as the evaluation set when Laya or Needle replace Jev.
- **Correction-flow and log tests:** the log stays append-only, labels are separate rows, and unlabeled stays unknown.
- **Jev function-calling spike:** the first task, whose result sets the escalation shape.

## Open questions

- **Jev argument extraction** (blocking, see the escalation decision).
- **Where the server runs permanently** and its latency budget. The benchmark ran on an 8-CPU, 15 GB, no-GPU machine; M1 recorded a Mac and `ianshomeserver`. Laya costs about 1 s per decision on CPU, so this matters for the local path.
- **Wake word hardware.** The wake word is in v1 scope but not built. M1's gate still stands: verify the board's PSRAM and flash first. M1 found PSRAM disabled and 2 MB flash in `voice_chat/sdkconfig`. If board-side `esp-sr` doesn't fit, v1 ships server-side `openwakeword`, which streams all room audio to the server.
- **Jev rate limits and quota** beyond the documented 40 requests per second were not probed.
- **Muse algorithm problems** the user wants fixed, in a separate workstream; the specifics have not been gathered.
- **Confidence thresholds** for escalation are untuned. The benchmark showed Jev's gate probabilities separated well (mean 0.82 on tool items, 0.08 on chat) but a 0.5 cutoff missed 64% of tool items.

## Provenance

Decisions marked "(user)" were chosen by the user in the 2026-10-01 brainstorming session. Benchmark numbers come from `docs/research/2026-09-30-jev-needle-laya.md` and its data in `docs/research/data/`; they are zero-shot, on 48 hand-labelled items, and vendor latency claims were not reproduced.
