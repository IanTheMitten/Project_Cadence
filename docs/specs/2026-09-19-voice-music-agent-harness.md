# Technical spec — voice music agent harness

> Status: ready for planning. Feed to /autopilot-plan.

## Source

`docs/prd/2026-09-19-voice-music-agent-harness.md`. Decisions below trace to that PRD's Must features, acceptance criteria, and Refusals.

Scope is two passes in one effort: **the harness** (this spec), then **Muse** (integration changes, then the recommender overhaul). The harness is specified first because Muse's changes serve it.

## Architecture

The harness is the system. Everything else is an edge.

```
audio clients                    harness (ianshomeserver)                 tools
─────────────                    ────────────────────────                 ─────
ESP32-S3 speaker  ──WebSocket──▶  wake gate ▶ VAD ▶ ASR                    Muse MCP server
  (1..n)          ◀──WebSocket──  ▶ routine store ──hit──▶ execute    ───▶  (8 thin tools,
                                  └─miss─▶ LLM ⇄ MCP tools ────────┘        see tool surface)
text clients                      ▶ TTS ▶ mixer ▶ session out
─────────────
Telegram  ──adapter──▶            scheduler ──due──▶ execute ───┘
iMessage  ──adapter──▶              (ticks; the only originator of a session)

                                  SQLite: diary · routines
                                  (harness-owned, separate from Muse)
```

Three seams, all the same principle — **adapters at the edge, stable core**:

1. **Tools** plug in over MCP. Adding one never edits the core loop.
2. **Clients** plug in over a session abstraction. WebSocket is the audio-client protocol; text platforms arrive as adapters because they structurally cannot speak WebSocket.
3. **Context/memory** plugs in behind a provider interface (prefetch pre-turn, sync post-turn, system-prompt contribution), so the v1 SQLite provider can be replaced without touching the loop.

The core never imports anything ESP32-specific, Telegram-specific, or Muse-specific.

**Turn path:** client audio → wake gate → VAD segments utterance → ASR → acknowledgement fires → routine lookup → hit executes directly with zero model calls; miss goes to the LLM → MCP tool → LLM reads result → TTS streams back sentence-by-sentence → mixer combines with any music already playing → one PCM stream to the session.

## Decisions

### Decision: Deployment host
- **Status:** Accepted
- **Context:** PRD Must *"Starts unasked"* needs a process awake when the user isn't. User stated their Mac "might be off so I cannot reliably use this machine."
- **Options considered:** (a) `ianshomeserver` — always-on, up 16 days, load 0.19, 15GB RAM, no GPU; (b) the Mac — mlx-native and fast, but unreliable by the user's own statement; (c) split across both.
- **Decision:** (a). The reliability constraint eliminates (b); (c) buys nothing for one user with one board.
- **Consequences:** **mlx is permanently out** — it is Apple-only, so the existing `tools/voice_chat_host.py` LLM path cannot be ported and must be replaced. ASR and TTS run CPU-only. Measured on that CPU: 295 GFLOPS FP32 matmul, 8ms to encode a short sentence through MiniLM-L6, 50ms for a batch of 64 — transformer inference is fine. Token *generation* is memory-bandwidth bound on DDR3L (~25 GB/s), which is why the main model stays in the cloud.

### Decision: Agent loop shape
- **Status:** Accepted
- **Context:** PRD Must — *"Tools declared, not hardcoded — adding a tool never touches the core loop."* User's words: *"mcp style of thing... it's an assistant not a worker."* PRD Refusal — never codes, prompts Claude Code instead.
- **Options considered:** (a) extend `tools/voice_chat_host.py` with an in-process tool registry — smallest delta, but adding a tool edits the core, failing the Must on its face; (b) real MCP — the user's stated shape, tools as separate servers; (c) HTTP tool registry in a config file — simple, but reinvents a subset of MCP and needs custom glue for the Claude Code path.
- **Decision:** (b). Expandability is the most distinguishing Must in the PRD, the user named MCP directly, and Claude Code already speaks MCP — so the delegation Refusal becomes a config entry rather than a project. Verified: `mcp` 2.2.0 on PyPI, requires Python >=3.10.
- **Consequences:** core loop is protocol-bound and stable; a tool crash cannot take the audio path down; debugging spans process boundaries; one new SDK dependency.

### Decision: Client interface
- **Status:** Accepted
- **Context:** User correction — *"the speaker (esp32-s3) is just a pipeline (like a chat interface) to reach the harness not the system itself."* Planned clients: multiple speakers, Telegram, iMessage.
- **Options considered:** (a) transport-agnostic core with the board's existing TCP+HTTP as one adapter — zero firmware work, but bakes in a two-channel audio contract; (b) WebSocket standard for audio clients plus adapters for text platforms; (c) board protocol as *the* protocol for everything.
- **Decision:** (b). Multiple speakers justify the firmware cost. Telegram is a Bot API (webhook or `getUpdates` long-poll) and iMessage has no official API at all — neither can ever dial a WebSocket, so an adapter layer is forced regardless of what the speakers use.
- **Consequences:** real ESP-IDF work lands in this project — `mic_upload_task` and `speak_stream_task` in `voice_chat/main/voice_chat.c` collapse into one bidirectional WebSocket client. Text sessions have no audio stage, so **ASR and TTS must be optional per session**, not fixed pipeline stages. iMessage depends on an always-on Mac, which the user does not have; Telegram has no such constraint.

### Decision: Agent loop depth
- **Status:** Accepted
- **Context:** User bound — *"not a heavy agentic system but a decision layer for tools and light assistant"*, then *"not too thin... not a software engineer but a personal assistant."* Against: free-tier concurrency 1, measured TTFT 343–561ms per hop.
- **Options considered:** (a) fat tools, one call per turn — tool auto-picks the track, so the model never exercises taste, losing the *"reads the room"* Heart; (b) bounded chain where the model sees results between calls; (c) open ReAct loop with retry and recovery — the software-engineer behavior explicitly ruled out.
- **Decision:** (b), capped at **3 tool calls per turn**. The model sees tool results between calls. **A failed tool ends the turn with a spoken report — never a retry, never a workaround.** The cap plus no-recovery is the precise line between personal assistant and software engineer.
- **Consequences:** typical music turn is two hops, roughly 1s of model latency, masked by the sentence chunker at `tools/voice_chat_host.py:127` which starts speech on the first completed sentence. A failed tool sounds like *"Muse isn't answering, want me to try again?"* — the user's call, not the system's.

### Decision: Routines are a cache, not an automation engine
- **Status:** Accepted
- **Context:** User — *"the purpose of the routine or skill or whatever is to reduce time and tokens not an automatic doing it."*
- **Options considered:** (a) LLM composes the workflow live each time it fires — re-decides the same alarm every morning, differently; (b) user declares routines, LLM only fills choices — no *new* workflows; (c) lookup in front of the LLM, crystallized after a miss.
- **Decision:** (c). Turn arrives → routine store consulted → hit executes directly with **zero model calls** → miss goes to the LLM, and the resolved path may be crystallized into a new routine. Routines are readable, editable, deletable.
- **Consequences:** repeat turns become fast *and* consistent. Staleness is a real failure mode — a cached pick the user has tired of — so corrections must bust the cache. Matching stays deliberately dumb; fuzzy intent matching is its own project and contradicts *light assistant*.

### Decision: Scheduled routines — the "starts unasked" mechanism
- **Status:** Accepted
- **Context:** PRD Must — *"Starts unasked: reads the hour and what you played at this hour before, and just goes. No prompt."* Every other path in this spec begins with client audio, so this Must has no component without one stated here. Noted during specification that a routine store and a scheduler are both new and neither exists today.
- **Options considered:** (a) a separate proactive subsystem with its own trigger logic and its own store — two mechanisms for one behaviour; (b) routines gain a second trigger type, evaluated by one scheduler process against the same store; (c) an external cron invoking the harness — simplest, but puts the trigger rules outside the object the user is supposed to be able to read and edit.
- **Decision:** (b). A routine carries one of two trigger types — **utterance-match** (consulted on a turn, as already specified) or **schedule** (time and recurrence). One evaluator process ticks, finds due scheduled routines, and executes them through the same execution path a cache hit uses. Same object, same store, same read-edit-delete affordances.
- **Consequences:** one new long-running component, and the only component that originates a session rather than receiving one — so it must resolve which client to push to, defaulting to the most recently active audio session. A scheduled routine executing with zero model calls is the common case, matching the routines-as-cache decision. In v1 a scheduled routine may start **music** but must not **speak**, per the proactive-speech deferral. Scheduler ticks are background work and are bound by the concurrency rule: a due routine yields to an in-flight user turn.

### Decision: Tool scope in v1
- **Status:** Accepted
- **Context:** PRD Won't — *"Ship non-music tools. Harness supports them; none ship."* User confirmed: *"the music is the only tool for now but I want the architecture to be able to support multiple tools."*
- **Options considered:** (a) music only, with the harness generic underneath; (b) ship a second tool in v1 to prove the seam works; (c) music-only *and* a music-shaped core, deferring genericity until a second tool actually exists.
- **Decision:** One MCP server in v1, wrapping Muse. Lamp, calendar, and anything else are later MCP servers requiring no core change.
- **Consequences:** no PRD amendment needed — the Refusal about surface width already anticipated this.

### Decision: Wake word placement
- **Status:** Accepted
- **Context:** Carries a hardware verification gate, recorded under blocking unknowns below. PRD Must keeps a wake word. User reason: *"I don't want the agent to be talking dumb without any inputs or another conversation I have with my friend."* User preference: on the board.
- **Options considered:** (a) board-side via Espressif `esp-sr` — keeps audio local until the wake word fires, best privacy, needs PSRAM; (b) server-side via `openwakeword` (0.6.0 on PyPI) — no hardware constraint, but every conversation in the room crosses the network; (c) board-side energy/VAD gate only — no model, no PSRAM, but a friend talking still streams.
- **Decision:** (a) as the target, (b) as the fallback if hardware forbids it. **First build task verifies the board's real PSRAM and flash.**
- **Blocking unknowns:** `voice_chat/sdkconfig` has only SoC capability flags — `CONFIG_SPIRAM` is **not set**, so PSRAM is disabled and the module's physical capability is unconfirmed. `CONFIG_ESPTOOLPY_FLASHSIZE="2MB"`, which is tight for esp-sr plus a model plus the app, and may be an uncorrected default. Board was not connected during specification.
- **Consequences:** custom wake phrases are **not self-serve** — Espressif trains WakeNet models from a corpus of 500+ speakers, so off-the-shelf means their stock wake word list, or MultiNet with pinyin phrases. A custom "Hey Cadence" requires going through Espressif's customization process.

### Decision: Music and speech share one output
- **Status:** Accepted
- **Context:** The board has a single I2S TX channel — it can play music or speak, never both. PRD Heart — *"never breaks the mood."*
- **Options considered:** (a) duck — music drops in gain, speech goes over the top; (b) pause, speak, resume; (c) queue speech until the song ends.
- **Decision:** (a), mixed server-side. Both streams are **already the same format** — `tools/muse_proxy.py` emits s16le/44100/stereo and Kokoro output is converted to exactly that at `tools/voice_chat_host.py:161` — so mixing is arithmetic, not a project.
- **Consequences:** the board stays dumb and receives one stream exactly as it does today. The server now mixes continuously for any session playing music. Pausing on every utterance would have broken the Heart.

### Decision: Echo handling
- **Status:** Accepted
- **Context:** Ducking means music keeps playing while the user talks, so the mic hears the speaker's own output for the entire song. PRD Must — *"Correction is the main input"* — requires saying "skip" mid-song, so the mic cannot be muted during playback. **This supersedes the PRD Non-goal** *"Real echo cancellation — mic mute stays the blunt mitigation,"* which was written when speech was the only output and does not survive music.
- **Options considered:** (a) live with it, no cancellation — wake word over loud music will miss; (b) reference-based echo subtraction — the sender knows exactly what PCM it emitted, making this far more tractable than blind AEC; (c) duck harder once listening — helps everything after the wake word, not the wake word itself.
- **Decision:** (b). If the board runs the wake word, this is **the same component**, not a second one: `esp-sr`'s audio front end includes AEC with a dedicated playback reference channel (channel format `"MMNR"` — `R` is the reference), and the board already holds the reference because it is the thing playing the audio. If the wake word falls back to the server, subtraction happens server-side against the stream it sent.
- **Consequences:** PRD Non-goal list needs updating. Echo subtraction requires real tuning and is a named risk.

### Decision: Acknowledgement layer
- **Status:** Accepted
- **Context:** User wants immediate feedback — *"a feedback like 'got it' right after I tell something"* — but also *"I don't want it to get too robotic."* User proposed a small local LLM on CPU.
- **Options considered:** (a) live generation by a small local model; (b) a small fixed set of pre-rendered clips; (c) a large rotating pool, generated by the cloud model in the background and pre-rendered to audio.
- **Decision:** (c). (a) was **measured and rejected on quality, not speed** — with a system prompt and three-shot examples on the server: `llama3.2:1b` at 715ms mean returned `relax vibes`, `mellow up`, `okay`; `qwen3:0.6b` at 541ms returned `check the playlist.`, `no thanks` (an acknowledgement that refuses), `check the check.`. Add Kokoro on top and a live ack costs ~1s to say "got it" — worse than silence. (b) wears out audibly. (c) gets cloud-model phrasing quality, a pool large enough never to loop recognizably, and **0ms playback** because nothing is generated at speech time.
- **Consequences:** pool regeneration is background work and must never hold the single concurrency slot while a user is mid-turn. Contextual acknowledgements ("got it, finding something chill") are foreclosed — **not** because they wait on ASR, which the chosen timing does too, but because generating them costs the ~700ms model call plus Kokoro synthesis measured above. That is roughly a second spent saying "got it," which is longer than the work it is meant to mask.

### Decision: Acknowledgement timing
- **Status:** Assumed - not confirmed
- **Context:** User raised coverage — *"make sure that you consider all the things that a user might ask."* A flat pool answers a correction with "on it," which sounds broken. Category matching requires knowing what was said, which requires ASR.
- **Options considered:** (a) fire before ASR — truly 0ms, but one generic pool for every request, so a correction gets answered with "on it"; (b) fire after ASR, category-matched — right flavour, but waits for transcription; (c) fire twice, a neutral sound immediately and words after ASR — covers both, at the cost of sounding busy.
- **Decision:** fire **after ASR**, category-matched — action, question, correction, ambiguous. If measured ASR latency proves too slow, fall back to (a). Status is Assumed because the user declined the measurement that would settle it.
- **Consequences:** depends on an unmeasured number. `faster-whisper` is not installed on the server; its latency there must be measured before this assumption holds.

### Decision: Diary storage
- **Status:** Accepted
- **Context:** PRD Refusal — *"Never keeps a memory you can't read or burn."* PRD open question — what the box remembers versus what Muse remembers.
- **Options considered:** (a) harness-owned SQLite file; (b) inside Muse's `library.sqlite3`; (c) plain JSONL.
- **Decision:** (a). (b) trips the coupling risk and makes "burn it" dangerous — deleting a diary must never risk the music library. (c) cannot answer *"what was I into last month"* without a full scan.
- **Resolves the PRD's open question:** Muse already owns plays, ratings, and feedback through its API, so the diary stores **decisions and context** — what was asked, what was chosen, why, what was rejected — referencing Muse track IDs rather than copying track data. **Muse owns taste; the harness owns context.** Burn is deleting one file, and Muse is untouched.
- **Consequences:** routines live in the same file in a separate table. No second store.

### Decision: Context provider seam
- **Status:** Accepted
- **Context:** User asked for *"hermes agent style evolving and limiting context or maybe like a searchable data source like OpenViking."*
- **Options considered:** (a) adopt OpenViking as the context store — its three context types (memories, skills, resources) map almost exactly onto diary, routines, and searchable source, but it requires an embedding model **and a VLM**, runs its own server, and is **AGPLv3**; (b) plain SQLite tables with no search; (c) a provider seam shipping a SQLite-plus-local-embedding provider, with OpenViking pluggable later as an MCP server.
- **Decision:** (c), modelled on the provider interface at `~/.hermes/hermes-agent/agent/memory_manager.py` — `build_system_prompt()`, `prefetch_all()` pre-turn, `sync_all()` post-turn, one external provider at a time. Local embeddings cost nothing new: the server already runs `sentence-transformers 5.7.0` and `torch 2.13.0`, and MiniLM-L6 encodes a short sentence in **8ms** there.
- **Consequences:** OpenViking's VLM requirement would mean either painful local inference on GPU-less hardware or cloud calls competing for the same rationed free-tier budget. Deferring it behind a seam keeps that option open at no cost. AGPLv3 obligations are avoided for now.

### Decision: Context shared across clients
- **Status:** Accepted
- **Context:** One user, several clients — speakers plus Telegram. User: *"um I guess memory might be good."*
- **Options considered:** (a) per-session history — simplest, but the speaker forgets what was said in Telegram minutes earlier; (b) one shared rolling context across all clients; (c) shared context with per-client scoping rules deciding what carries over.
- **Decision:** a single rolling conversation context (~10 turns, in-memory, not persisted across restarts) shared across all clients, plus the shared persistent diary. Long-term recall is a diary query, not a growing context window.
- **Consequences:** simpler than N isolated histories, and saying something in Telegram then walking to the speaker works. Building a real memory architecture is the *heavy agentic system* the user ruled out.

### Decision: Cloud model unreachable
- **Status:** Accepted
- **Context:** Free tier is a monthly GPU-time credit pool; measured free-tier `gpt-oss:20b` reliability was **96% over 24h** against 100% paid — roughly an hour a day unavailable. Plus network, auth expiry, and catalog churn.
- **Options considered:** (a) say so and stop; (b) fall back to a local model — measured above as producing `no thanks` and `check the check.`; (c) degrade to routine-cache-only.
- **Decision:** (a), per user. No dumb fallback, no silent degradation.
- **Consequences:** voice control is unavailable during an outage. **Concurrency 1 means background work must never hold the only slot while a user is mid-turn** — this is the self-inflicted version of the same failure and is the one worth designing around.

### Decision: Muse unreachable
- **Status:** Accepted
- **Context:** Muse is the only source of music — library, search, and streaming all come from it. User: *"muse is always reachable but if not say it and stop."* It runs on the same host, so this is rare, but Part-two work will restart it.
- **Options considered:** (a) say so and stop; (b) stay conversational — still answer from the diary while unable to play anything; (c) queue the intent and fulfil it when Muse returns.
- **Decision:** say so and stop. No intent queueing — a request fulfilled minutes later would be surprising.
- **Consequences:** Muse runs on the same host so this is rare, but Part-two work will restart it.

### Decision: ASR uncertainty
- **Status:** Accepted
- **Context:** Misheard input does not error — the vibe endpoint returns something plausible for "less bad" just as it does for "less sad."
- **Options considered:** (a) always act; (b) ask when confidence is low; (c) act while stating what was heard.
- **Decision:** (a), per user. Correction is already the PRD's primary input, so a confirmation turn adds friction to exactly the requests already going wrong. (c) is recorded as a cheap **Should** — announcing the interpretation surfaces mistakes a beat earlier at no latency cost.
- **Consequences:** existing confidence filtering at `tools/voice_chat_host.py:213` is retained as a floor against transcribing noise.

### Decision: LLM model
- **Status:** Accepted
- **Context:** User chose one model over two. Concurrency 1 means two models would serialize anyway.
- **Options considered:** verified tool-calling support on all candidates. `gemma4:31b` — 343ms TTFT, 253 tok/s, intelligence index 15.4; `nemotron-3-nano:30b` — 472ms, 198 tok/s, index 6.8; `gpt-oss:20b` — 561ms, 90 tok/s, index 9.
- **Decision:** **`gemma4:31b`**, with the thinking toggle doing the work a second model would have. `think: false` for live voice turns — lowest measured latency, tools intact, no reasoning nobody is waiting to read. `think: true` for background work — routine composition, ack pool regeneration — where quality is free and nothing is waiting.
- **Correction of record:** an earlier claim in conversation that gemma4 was "non-reasoning with no think param" was wrong. Ollama lists `thinking` among its capabilities, and by the benchmark's own methodology an unlabeled model is measured *with* reasoning on — so 343ms was gemma4 thinking, and `think: false` should be faster still.
- **Consequences:** `ollama signin` on the server is an interactive prerequisite the user must run. Benchmark figures are third-party (ollamatps.com), not Ollama's own published numbers.

### Decision: Proactive speech deferred to v2
- **Status:** Accepted
- **Context:** User asked about *"it's time for you to wake up, boss"* and *"two minutes until it's time for you to leave"*, then scoped it: *"lets put the voice notification for v2 for now."*
- **Options considered:** (a) ship proactive speech in v1 alongside proactive music; (b) defer spoken notifications to v2, keeping proactive music; (c) defer all proactive behaviour including music, which would gut a PRD Must.
- **Decision:** v1 starts music unasked — that is the PRD Must — but never **speaks** unprompted. Proactive spoken lines are v2.
- **Consequences:** no new architecture needed when it arrives; a spoken line is a step in an existing routine, and proactive speech has an effectively infinite latency budget because the trigger time is known in advance. The "two minutes to leave" case additionally needs a calendar tool, which is a v2 MCP server by the v1 scope decision.

### Decision: Muse split into two workstreams
- **Status:** Accepted
- **Context:** User — *"we gotta fix Muse too so that it integrates well... maybe after we decide everything for the harness."*
- **Options considered:** (a) one Muse workstream covering integration and the recommender together — couples a small change to a large one; (b) integration changes first as a blocker, recommender after; (c) no Muse changes required for v1 at all, recommender as pure follow-on.
- **Decision:** (c). **Verified against the live API: Muse needs no new endpoints for v1.** The thin-tool surface maps entirely onto endpoints that already exist and already return what the model needs to choose. **Muse is therefore off the harness critical path** — the harness is built against Muse exactly as it stands today. The recommender overhaul (sequence-aware, mood-conditioned, audio plus lyrics) is a pure follow-on blocking nothing.
- **Verification performed:** `/api/library/search/vibe` returns ranked candidates carrying full track metadata (name, artist, album, duration, rating, playable); `/api/library/search` covers text; `/api/recommend/{track_rowid}` returns `{seed, results}`; `/api/player/state` GET/PUT exposes `queue`, `queue_index`, `position_ms`, `shuffle`, `repeat_mode`; `/api/dashboard` exposes `resume`, `mixes`, `recent_albums`, `never_played`, `forgotten`, `stats`; `tools/muse_proxy.py` streams `/play/<id>` as PCM already matching the speaker's format.
- **Consequences:** an earlier framing of "composite search-and-play" as a required integration change is **withdrawn** — it was unnecessary and it contradicted the thin-tool shape in *Agent loop depth*, since a composite endpoint would pick the track itself and deny the model the judgment that decision exists to preserve. Muse already carries embedding infrastructure — `muse/embed.py` (831 lines), `muse/reco.py`, `muse/taste_retrain.py` — over a 1087-track, 9.9MB library; that scale argues against heavy vector infrastructure in the overhaul.

### Decision: Muse MCP server tool surface
- **Status:** Accepted
- **Context:** *Agent loop depth* requires thin tools returning candidates the model chooses between, never tools that choose for it. The surface must be enumerable so a planner can build it.
- **Options considered:** (a) one composite `play_by_vibe` tool — rejected, it picks the track itself; (b) a thin verb-per-endpoint surface mirroring Muse's API; (c) a generic `muse_api_call` passthrough — maximum flexibility, but hands the model raw HTTP and no schema to reason against.
- **Decision:** (b). v1 tool surface, each a thin wrapper over an endpoint verified to exist:

  | tool | returns | backed by |
  |---|---|---|
  | `search_vibe(query, n)` | ranked candidates with full track metadata | `/api/library/search/vibe` |
  | `search_text(query, limit)` | matching tracks | `/api/library/search` |
  | `recommend_next(track_rowid, n)` | `{seed, results}` | `/api/recommend/{track_rowid}` |
  | `play(track_rowid)` | starts playback on the session | `muse_proxy.py /play/<id>` |
  | `get_player_state()` | queue, index, position, shuffle, repeat | `GET /api/player/state` |
  | `set_player_state(...)` | updated state | `PUT /api/player/state` |
  | `get_dashboard()` | resume, mixes, recent, never-played, forgotten | `/api/dashboard` |
  | `rate(track_rowid, rating)` | acknowledgement | `POST /api/ratings` |

- **Consequences:** every tool returns data for the model to judge; none of them decide. Adding a ninth tool is a change inside this MCP server, not to the harness core.

## Data flow

**Reactive turn.** Client audio arrives over its session. Wake gate fires (board-side if hardware permits). VAD segments the utterance. ASR transcribes. An acknowledgement clip plays from cache. The routine store is consulted: a hit executes directly with zero model calls; a miss goes to `gemma4:31b` with `think: false` and the MCP tool schemas attached. Up to 3 tool calls, model reading results between them. TTS renders sentence-by-sentence as the reply streams. The mixer combines TTS with any music already playing, ducking the music, and emits one PCM stream to the session.

**Proactive turn.** The scheduler ticks, finds a scheduled routine due, resolves a target client (most recently active audio session), and executes it through the same path a cache hit uses — normally zero model calls. In v1 this may start music but may not speak.

**State.** Rolling conversation context lives in memory, shared across clients, ~10 turns, lost on restart. The diary and routine store live in one harness-owned SQLite file. Listening history, ratings, and taste live in Muse and are queried through its API, never copied.

**Synchronous vs async.** The turn path is synchronous end to end. Background work — ack pool regeneration, routine crystallization, diary embedding, scheduler ticks — is async and **must yield the single concurrency slot to any in-flight user turn.**

## Error handling

| Failure | Response |
|---|---|
| Cloud model unreachable | Say so, stop. No local fallback. |
| Muse unreachable | Say so, stop. No intent queueing. |
| MCP tool fails | Report it spoken, end the turn. Never retry, never work around. |
| 3-call cap reached | End the turn with what it has. |
| ASR low confidence | Act anyway; existing `no_speech_prob` floor still drops noise. |
| Client disconnects mid-song | Session ends; on reconnect, playback resumes from the server's known position. |
| Background job holds the concurrency slot | Must not happen by design — user turns preempt. |

## Testing strategy

Middle depth, per user choice.

- **Unit:** routine matching and invalidation, tool dispatch and the 3-call cap, audio mixing and ducking math, PCM format conversion, diary queries.
- **Fixtures:** recorded audio replayed through the wake word and ASR, so regressions are catchable without speaking to it.
- **Mocked:** Muse responses for tool-loop tests.
- **By hand:** the cloud model, live audio end to end, echo subtraction tuning.
- **Out of scope for v1:** a full scripted end-to-end harness with mock cloud and mock Muse.

## Tech stack

| Layer | Choice | Traces to |
|---|---|---|
| Host | `ianshomeserver`, Ubuntu, Python 3.14.4 | Deployment host |
| LLM | Ollama Cloud `gemma4:31b`, think toggled per path | LLM model |
| Tool protocol | `mcp` 2.2.0 | Agent loop shape |
| Client transport | WebSocket via FastAPI/uvicorn (already installed) | Client interface |
| ASR | `faster-whisper`, retained from current host | — |
| TTS | Kokoro via `kokoro-onnx`, retained, including the `PatchedKokoro` float32 fix at `tools/voice_chat_host.py:88` | — |
| Wake word | `esp-sr` on board (target) / `openwakeword` 0.6.0 on server (fallback) | Wake word placement |
| Echo cancellation | `esp-sr` AFE with playback reference, or server-side subtraction | Echo handling |
| Scheduler | in-process evaluator over the routine store, ticking for due schedule-triggered routines | Scheduled routines |
| Storage | SQLite, harness-owned, single file — diary and routines in separate tables | Diary storage |
| Embeddings | `sentence-transformers` MiniLM-L6, already installed, 8ms/sentence | Context provider seam |
| Firmware | ESP-IDF v5.3, `voice_chat/` rewritten to a WebSocket client | Client interface |

## Open questions

- Deferred: exact context signals the harness passes to Muse (hour, spoken mood words, session scene) — depends on the Part-two integration endpoints, which do not exist yet and are specified after this harness.
- Deferred: Muse recommender architecture — explicitly sequenced after the harness by user decision; specifying it now would be guessing at an interface the harness has not yet exercised.
- Deferred: board PSRAM and flash verification — the board was not connected during specification, and the wake-word placement decision carries a documented fallback, so this resolves in the first build task rather than blocking the plan.
- Deferred: `faster-whisper` and Kokoro latency on the server — neither is installed there yet; measuring them is a plan-time task and only the acknowledgement-timing assumption depends on the result.
- Deferred: Python 3.14 wheel availability for `onnxruntime`, `ctranslate2`, and `webrtcvad` — the server has only Python 3.14.4, which is new enough that binary wheels may not exist. Muse's own venv proves `torch` and `transformers` work there. If a wheel is missing, the fallback is a second venv on an older Python, which is a plan-time packaging decision, not an architectural one.

## Provenance

- **user-picked:** agent loop shape (MCP); client interface (WebSocket, chosen over the initial recommendation); music ducking; echo subtraction; one model over two; cloud-unreachable behaviour; Muse-unreachable behaviour; ASR uncertainty (act, don't ask); testing depth; v1 tool scope; proactive speech deferred to v2; wake word on the board.
- **recommended-and-accepted:** deployment host; agent loop depth and the 3-call cap; routines as a cache; scheduled routines; Muse MCP tool surface; diary storage; context provider seam; shared cross-client context; acknowledgement layer; `gemma4:31b`; Muse workstream sequencing.
- **assumed:** acknowledgement timing (after ASR, category-matched) — flagged, depends on an unmeasured number.
- **overrides:** user requested one decision per message rather than one area per message; honoured from Area 3 onward. User declined a proposed measurement of `faster-whisper` latency, which is why the acknowledgement-timing decision carries Assumed status rather than Accepted.
- **corrections of record:** an in-conversation claim that gemma4 was non-reasoning was wrong and is corrected in the LLM decision. An in-conversation characterisation of the server CPU as too slow was wrong and is corrected with measurements in the deployment host decision. An in-conversation framing of "composite search-and-play" as a required Muse integration change was wrong on two counts — it was unnecessary against the live API and it contradicted the thin-tool shape — and is withdrawn in the Muse workstreams decision, which moves Muse off the harness critical path entirely.
