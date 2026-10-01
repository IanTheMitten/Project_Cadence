# Plan — Cadence decision harness v1

Source spec: `docs/specs/2026-10-01-cadence-decision-harness-v1.md` (spec-lint `--handoff` exit 0,
status "ready for planning"). Research: `docs/research/2026-09-30-jev-needle-laya.md`.

## Scope

v1 replaces the M1 LLM-first turn loop with the event pipeline (Event, Decide, Resolve, Execute,
Log): Jev decides first, the cloud LLM escalates on need, plugins act, every decision is logged with
spoken-correction labels. Plugins: speaker (audio port, volume) and music (Muse queues, plays
write-back). Plus server-side wake word, acknowledgement clip pool, MCP adapter, golden-set replay.

**Not in this plan** (named so no executor invents them):
- Board-side wake word (`esp-sr`) and echo cancellation — separate firmware plan, needs the board.
- Any change inside `~/Projects/muse_intelligence` — briefed separately in
  `docs/handoffs/2026-10-01-muse-cadence-contract.md`.
- Lamp, scheduler wiring, rules decider, plugin event streams, diary, routines (v2).
- Saved playlists, `similar to this` requests, numeric volume, repeat, seek.
- Removing M1 modules: `agent.py`, `routines.py`, `scheduler.py`, `store.py`, `mcp_client.py`,
  `muse/mcp_server.py`, `context.py` stay and their tests stay green.

## Manual prerequisites (the user runs these; no task can)

1. TypeSafe key in `~/.config/cadence/typesafe.env` (`TYPESAFE_API_KEY=...`, mode 600) — present,
   verified 2026-10-01 (length only). **Never print, log, or commit it.**
2. `ollama signin` on this server — done: `GET http://localhost:11434/api/tags` returns 200.
3. Muse running (`uv run --all-extras python -m muse` in `~/Projects/muse_intelligence`) — running.

## Premises

- Host is `ianshomeserver`, Python 3.14.4 — verified: `python3 --version`; `uv python list`.
- `harness/.venv` exists with `requirements.txt` installed; baseline suite is 55 passed —
  verified: `cd harness && .venv/bin/python -m pytest -q` printed `55 passed`.
- Test command: `cd harness && .venv/bin/python -m pytest -q` (pyproject `asyncio_mode = "auto"`,
  `testpaths = ["tests"]`) — verified: `harness/pyproject.toml:6-8`.
- The hostname `ianshomeserver` does not resolve on this host; Muse listens on tailnet address
  `100.122.149.75:8080` only; port 8765 (proxy) is not running — verified: `ss -ltnp` and
  urllib probes (8080 at tailnet IP returned 200; hostname gave `Name or service not known`).
- `cadence/config.py` hardcodes `MUSE_BASE_URL = "http://ianshomeserver:8080"` — verified:
  `harness/cadence/config.py:9`. `tools/muse_proxy.py:13` hardcodes `MUSE_BASE` the same way.
- `cadence.server` must keep exporting `TURN_LOCK` and stay cheap to import: `cadence/scheduler.py:12`
  and `tests/test_scheduler.py:9` import it.
- `openwakeword` 0.6.0 requires `tflite-runtime` on Linux, which has no wheel here; installed with
  `--no-deps` plus `scikit-learn`, `requests`, `tqdm`, it loads `hey_jarvis_v0.1` with
  `inference_framework="onnx"` and predicts in 2.65 ms per 1280-sample frame — verified in a scratch
  venv: `pip install tflite-runtime` → `No matching distribution`; ONNX predict run printed scores.
  Resolved versions: `scikit-learn==1.9.1`, `requests==2.34.2`, `tqdm==4.70.1`.
- Kokoro files `tools/kokoro-v1.0.onnx`, `tools/voices-v1.0.bin` are **absent** on this host; URLs in
  `tools/voice_chat_host.py:31-32`; `tools/*.onnx` and `tools/voices-*.bin` are gitignored (`.gitignore`).
- Jev API: `POST https://api.typesafe.ai/v1/systemone`, bearer auth, body
  `{"state","model","questions"}`; a `choice` answer is `{"choice","probabilities","confidence"}`;
  response carries `answers`, `model`, `usage` — verified: `harness/scripts/bench_run.py:231-246`,
  record in `docs/research/data/jev_route.json`. Jev cannot generate text
  (`docs/research/2026-09-30-jev-needle-laya.md:29`).
- Ollama response shape (tool calls under `message.tool_calls[].function.{name,arguments}`) —
  verified: `harness/tests/test_agent.py:24-57`.
- Muse plays API: `POST /api/plays` body `{track_rowid:int, duration_ms:int, source:str|null}` →
  201 `{"id": int}`; `POST /api/plays/{id}/close` body `{ended_reason, position_ms}`; reasons
  `track_end, user_next, user_prev, new_selection, pause_timeout, lost` —
  verified: `~/Projects/muse_intelligence/muse/api.py:138-174,1347-1375`.
- Muse search results: text items are flat track dicts (`track_rowid`, `track_name`, `artist_name`,
  `artist_names: list[str]`, `duration_ms`, `playable: bool`); vibe items are
  `{track_rowid, score, track:{same fields}}` — verified: `harness/tests/fixtures/muse/search_text.json`,
  `search_vibe.json`.
- `MuseClient(base_url, proxy_url, transport=None)`, sync `httpx.Client`, `MuseUnavailable` on any
  HTTP error — verified: `harness/cadence/muse/client.py:18-45`.
- `mix(music, speech, duck)` requires equal lengths — verified: `harness/cadence/audio/mixer.py:9-16`.
- Golden set exists (written at plan time): 60 items, unique ids, all routes inside the v1 catalogue — verified: `python3 -c "import json; d=json.load(open('harness/tests/golden/utterances.json')); print(len(d['items']))"` printed `60`.
- No ESP-IDF and no board on this host — verified: `ls ~/esp/esp-idf`, `ls /dev/ttyACM*` both absent.

## Assumptions (plan-level decisions; none change the spec)

- Volume is a server-side output gain on the speaker port (0.0–1.0, step 0.1, default 1.0); the
  firmware is untouched.
- "Stop the music" is `music.control` `pause` (Muse has no "user stopped" end reason). A pause longer
  than 600 s closes the play span with `pause_timeout`; resuming after that restarts the track.
- `harness/devices.json` ships one device: `speaker-1`, kind `speaker`, room `bedroom` (the
  firmware default client id, `voice_chat/main/Kconfig.projbuild`). The user edits rooms by hand.
- Kokoro and Whisper load lazily on first use; the server never loads a model at import.

## Shared constants (Task 1 writes these into `cadence/config.py`; every brief uses these names)

| Name | Value |
|---|---|
| `WS_PORT` | `8768` |
| `DB_PATH` | `"cadence.sqlite3"` |
| `MUSE_BASE_URL` | env `CADENCE_MUSE_BASE_URL`, default `"http://ianshomeserver:8080"` |
| `MUSE_PROXY_URL` | env `CADENCE_MUSE_PROXY_URL`, default `"http://ianshomeserver:8765"` |
| `DEVICES_PATH` | env `CADENCE_DEVICES_PATH`, default `"devices.json"` |
| `JEV_URL` | `"https://api.typesafe.ai/v1/systemone"` |
| `JEV_MODEL` | `"jev-latest"` |
| `JEV_TIMEOUT_S` | `1.5` |
| `JEV_CLOSED_ARGS` | `True` |
| `TYPESAFE_ENV_PATH` | `os.path.expanduser("~/.config/cadence/typesafe.env")` |
| `CONF_MIN` | `0.5` |
| `SHORTLIST_MIN` | `0.25` |
| `CORRECTION_WINDOW_S` | `60.0` |
| `WAKE_ENABLED` | env `CADENCE_WAKE_ENABLED` == `"1"`, default `"1"` |
| `WAKE_MODEL` | `"hey_jarvis_v0.1"` |
| `WAKE_THRESHOLD` | `0.5` |
| `LISTEN_WINDOW_S` | `8.0` |
| `ACK_DIR` | `"acks"` |
| `PAUSE_TIMEOUT_S` | `600.0` |
| `VOLUME_STEP` | `0.1` |
| `PLAY_SOURCE` | `"cadence"` |
| `MUSE_CONTRACT_MAJOR` | `1` |
| `DEFAULT_QUEUE_LEN` | `10` |
| `MAX_QUEUE_LEN` | `50` |

Relative paths resolve against `harness/`, the working directory the server runs from.

## Interfaces (normative — test tasks and implementation tasks copy these verbatim)

### I1 `cadence/events.py`
```python
DEFAULT_USER = "household"

@dataclass(frozen=True)
class Event:
    id: str
    ts: float
    kind: str
    source: str
    room: str | None
    user_id: str
    payload: dict

def utterance(source: str, room: str | None, text: str, *, asr_conf: float | None = None,
              user_id: str = DEFAULT_USER, ts: float | None = None) -> Event
    # id = uuid.uuid4().hex; kind = "utterance"; ts = time.time() when None;
    # payload = {"text": text, "asr_conf": asr_conf}

@dataclass(frozen=True)
class Call:
    capability: str
    args: dict

@dataclass
class Decision:
    decider: str                  # "jev" | "llm" | "none"
    route: str | None             # capability name, "chat", or "correction"
    calls: list[Call]
    confidence: float | None = None
    candidates: dict[str, float] = field(default_factory=dict)
    reply: str | None = None
    escalation: str | None = None # None|"chat"|"low_confidence"|"needs_args"|"correction"|"correction_no_previous"|"jev_unavailable"
    model: str | None = None
```

### I2 `cadence/plugins/registry.py`
```python
@dataclass
class Device:
    id: str
    kind: str
    room: str | None
    online: bool = False

class DeviceRegistry:
    def __init__(self, devices: list[Device]) -> None
    @classmethod
    def from_file(cls, path: str) -> "DeviceRegistry"   # JSON {"devices":[{"id","kind","room"}]}; missing file -> empty; all offline
    def get(self, device_id: str) -> Device | None
    def set_online(self, device_id: str, online: bool, kind: str = "speaker") -> Device  # unknown id is added, room None
    def find(self, kind: str, room: str | None = None, online_only: bool = True) -> list[Device]  # registration order; room None = any
    def rooms(self) -> list[str]   # sorted unique non-None rooms
```

### I3 `cadence/plugins/base.py`
```python
@dataclass(frozen=True)
class Capability:
    name: str
    description: str
    parameters: dict                                   # JSON-schema object
    closed_args: dict[str, dict[str, str]] = field(default_factory=dict)  # arg -> {value: description}
    free_args: tuple[str, ...] = ()
    target: str | None = None                          # device kind, e.g. "speaker"

@dataclass(frozen=True)
class Manifest:
    id: str
    kind: str                                          # "device" | "service" | "sensor"
    capabilities: tuple[Capability, ...]

@dataclass
class Result:
    ok: bool
    say: str | None = None
    data: dict = field(default_factory=dict)
    error: str | None = None

class AudioPort(Protocol):
    async def play_url(self, url: str, on_end: Callable[[str], Awaitable[None]]) -> None
    async def pause(self) -> None
    async def resume(self) -> None
    async def stop(self, reason: str = "stopped") -> None
    def position_ms(self) -> int
    def is_paused(self) -> bool

class Plugin(abc.ABC):
    manifest: Manifest
    @abc.abstractmethod
    async def call(self, capability: str, args: dict, target: Device | None,
                   port: AudioPort | None) -> Result: ...
    def available(self) -> bool: return True
    def state(self) -> dict: return {}
```

### I4 `cadence/catalogue.py`
```python
CHAT = Capability(name="chat", description="Chit-chat, a question, thanks, or a request no other function can perform.",
                  parameters={"type": "object", "properties": {}})
CORRECTION = Capability(name="correction", description="The user says the previous action was wrong or corrects it ('no, I meant...', 'not that', 'wrong song').",
                        parameters={"type": "object", "properties": {}})
BUILTINS: tuple[Capability, ...] = (CHAT, CORRECTION)

class Catalogue:
    def __init__(self, plugins: list[Plugin]) -> None   # ValueError on a duplicate name, incl. a clash with a builtin
    def get(self, name: str) -> Capability | None       # builtins included
    def plugin_for(self, name: str) -> Plugin | None    # None for builtins and unknown names
    def available(self) -> list[Capability]             # caps of plugins whose available() is True, plugin then manifest order, then CHAT, CORRECTION
```

### I5 `cadence/resolver.py`
```python
def resolve(call: Call, capability: Capability, event: Event, registry: DeviceRegistry) -> list[Device | None]
```
In order: (1) `capability.target is None` → `[None]`. (2) `room = call.args.get("room")`; if set and
`registry.find(target, room)` non-empty → that. (3) if `event.room` and `registry.find(target, event.room)`
non-empty → that. (4) `src = registry.get(event.source)`; if `src` and `src.kind == target` and
`src.online` → `[src]`. (5) `registry.find(target)` (may be `[]`).

### I6 `cadence/deciders/base.py`
```python
class DeciderUnavailable(Exception): ...

class Decider(abc.ABC):
    name: str
    @abc.abstractmethod
    async def decide(self, event: Event, context: dict, capabilities: list[Capability],
                     instruction: str | None = None) -> Decision: ...

class UnavailableDecider(Decider):
    name = "jev"
    def __init__(self, reason: str) -> None
    async def decide(self, event, context, capabilities, instruction=None) -> Decision  # always raises DeciderUnavailable(reason)
```

### I7 `cadence/decisionlog.py`
```python
LABELS = ("wrong",)
LABEL_SOURCES = ("spoken_correction",)

class DecisionLog:
    def __init__(self, path: str) -> None   # creates tables decision_log, decision_labels if missing
    def record(self, event: Event, context: dict, decision: Decision, jev: Decision | None,
               results: list[Result], latency_ms: dict[str, float]) -> int
    def label(self, decision_id: int, label: str, source: str, corrected_by: int | None = None) -> int
        # ValueError: label not in LABELS, source not in LABEL_SOURCES, or unknown decision_id
    def last_for_source(self, source: str, since: float) -> dict | None   # newest row with source and at >= since
    def recent(self, n: int) -> list[dict]   # newest first
    def export(self) -> list[dict]           # oldest first; row dict plus "labels": list[dict]
```
Row dict keys, exactly: `id, at, event_id, source, room, user_id, text, asr_conf, context, decider,
route, calls, reply, escalation, jev_route, jev_confidence, jev_candidates, outcome, results,
latency_ms, models`. `at = event.ts`; `text = event.payload.get("text")`; `calls` = list of
`{"capability","args"}`; `results` = list of `{"ok","say","error"}`; `models` =
`{"decider": decision.model, "jev": jev.model if jev else None}`; `jev_*` are `None` when `jev` is
`None`. JSON columns come back decoded. `outcome`: `"reply"` (no results, reply set), `"none"` (no
results, no reply), `"ok"` (all ok), `"error"` (none ok), `"partial"` (otherwise). Label dict keys:
`id, decision_id, at, label, source, corrected_by` (`at = time.time()`). No method updates or
deletes a `decision_log` row.

### I8 `cadence/deciders/jev.py`
```python
ROUTE_INSTRUCTIONS = "Which single function best serves what the user just said?"
def load_api_key(path: str = TYPESAFE_ENV_PATH) -> str
    # env TYPESAFE_API_KEY wins; else first line starting "TYPESAFE_API_KEY=" in path, value stripped
    # of whitespace and quotes; else raise DeciderUnavailable("no TypeSafe key")
def render_state(event: Event, context: dict) -> str
    # "Home speaker assistant.\n" + one f"{key}: {value}" line per context item in order
    # (value json.dumps'd unless str) + "\nUser said: " + event.payload["text"]
def build_questions(capabilities: list[Capability], closed_args: bool) -> dict
    # {"route": {"type": "choice", "instructions": ROUTE_INSTRUCTIONS,
    #            "criteria": {c.name: c.description for c in capabilities}}}
    # plus, when closed_args, per capability c and arg a in c.closed_args:
    # f"arg:{c.name}:{a}": {"type": "choice", "instructions": f"If the user wants {c.name}, which {a}?",
    #                       "criteria": c.closed_args[a]}

class JevDecider(Decider):
    name = "jev"
    def __init__(self, api_key: str, *, url: str = JEV_URL, model: str = JEV_MODEL,
                 timeout_s: float = JEV_TIMEOUT_S, closed_args: bool = JEV_CLOSED_ARGS,
                 transport: httpx.AsyncBaseTransport | None = None) -> None
    async def decide(self, event, context, capabilities, instruction=None) -> Decision
```
`decide`: POST `{"state", "model", "questions"}` with `Authorization: Bearer <key>`. Transport error,
timeout, or status != 200 → `DeciderUnavailable(f"jev HTTP {status}")` or
`DeciderUnavailable("jev transport error")` — the message never contains the key. `a =
answers["route"]`: `route=a["choice"]`, `confidence=a.get("confidence")`, `candidates=a["probabilities"]`,
`model=j.get("model")`. Route `chat`/`correction` → `calls=[]`. Else the routed capability: if it has
`free_args`, or has `closed_args` while `closed_args=False` → `calls=[]`, `escalation="needs_args"`;
else `calls=[Call(route, {a: answers[f"arg:{route}:{a}"]["choice"] for a in cap.closed_args})]`.
Missing answer keys → `DeciderUnavailable("jev malformed response")`. `instruction` is ignored.

### I9 `cadence/deciders/llm.py`
```python
SYSTEM_PROMPT = ("You are the voice of a home speaker. Use a function when the user wants something done; "
                 "otherwise answer in one or two short sentences, since replies are spoken aloud. Never write code.")
def tool_name(capability_name: str) -> str          # "." -> "__"
def capability_tools(capabilities: list[Capability]) -> list[dict]
    # {"type":"function","function":{"name": tool_name(c.name),"description": c.description,"parameters": c.parameters}}
    # for every capability except names "chat" and "correction"

class LlmDecider(Decider):
    name = "llm"
    def __init__(self, llm, rolling: RollingContext, *, max_calls: int = MAX_TOOL_CALLS) -> None
    async def decide(self, event, context, capabilities, instruction=None) -> Decision
```
Messages: `[system SYSTEM_PROMPT, system "Context: " + json.dumps(context)]` + `[system instruction]`
if given + `rolling.messages()` + `[user text]`. `await llm.chat(messages, capability_tools(caps),
think=False)`; `ConnectionError` → `DeciderUnavailable(str(exc))`. Calls: each tool call whose name
maps (`"__"` → `"."`) to a capability in `capabilities`, in order, first `max_calls`; others dropped.
`reply = content.strip() or None`. `route = calls[0].capability if calls else "chat"`. Then
`rolling.append("user", text)` and, if reply, `rolling.append("assistant", reply)`. Returns
`Decision(decider="llm", route, calls, reply=reply, model=LLM_MODEL)`. `MAX_TOOL_CALLS` from
`cadence.agent`, `LLM_MODEL` from `cadence.llm`, `RollingContext` from `cadence.context`.

### I10 `cadence/executor.py`
```python
class Executor:
    def __init__(self, catalogue: Catalogue, registry: DeviceRegistry,
                 ports: Callable[[str], AudioPort | None], *, max_calls: int = MAX_TOOL_CALLS) -> None
    async def run(self, decision: Decision, event: Event) -> list[Result]
```
Per call in `decision.calls[:max_calls]`: unknown capability or no plugin →
`Result(False, say="I can't do that yet.", error=f"unknown capability {name}")`, stop. `targets =
resolve(...)`; empty → `Result(False, say=f"No {cap.target} is online.", error="no_target")`, stop.
Per target: `port = ports(t.id) if t else None`; `await plugin.call(cap.name, call.args, t, port)`;
an exception becomes `Result(False, say="Sorry, that didn't work.", error=f"{type(exc).__name__}: {exc}")`.
The first `ok=False` result ends the run (no retry, remaining calls skipped).

### I11 `cadence/livecontext.py`
```python
class LiveContext:
    def __init__(self, log: DecisionLog, now_playing: Callable[[str], dict | None], *,
                 clock: Callable[[], float] = time.time) -> None
    def snapshot(self, event: Event) -> dict
```
Returns, in this key order: `time` (`"%H:%M"` of `time.localtime(clock())`), `weekday` (`"%A"`),
`room` (`event.room`), `now_playing` (`now_playing(event.source)`), `recent` (`[{"text","route"}]`
from `log.recent(3)`).

### I12 `cadence/pipeline.py`
```python
UNAVAILABLE_SAY = "I can't reach my brain right now."
NOTHING_SAY = "I'm not sure what to do with that."
CHAT_INSTRUCTION = "Reply conversationally. Only call a function if the user clearly asked for an action."
ARGS_INSTRUCTION = "The user wants this function. Fill in its arguments from what they said."
LOW_CONF_INSTRUCTION = "Pick the function that best matches what the user said, or reply if none fits."
def correction_instruction(previous: dict) -> str
    # f"The user is correcting your previous action. Their previous request: {previous['text']!r}. "
    # f"What you did: {json.dumps(previous['calls'])}, reply {previous['reply']!r}. Work out what they actually want now."

class TurnOutput(Protocol):
    async def ack(self, category: str) -> None   # "action" | "chat" | "correction"
    async def say(self, text: str) -> None

class Pipeline:
    log_healthy: bool                               # True until a log write fails
    def __init__(self, jev: Decider, llm: Decider, catalogue: Catalogue, executor: Executor,
                 log: DecisionLog, context: LiveContext, *, conf_min: float = CONF_MIN,
                 shortlist_min: float = SHORTLIST_MIN, correction_window_s: float = CORRECTION_WINDOW_S,
                 clock: Callable[[], float] = time.time) -> None
    async def handle(self, event: Event, out: TurnOutput) -> Decision
```
`handle`, normative:
1. `ctx = context.snapshot(event)`; `caps = catalogue.available()`; `no_corr = [c for c in caps if c.name != "correction"]`.
2. `jev_d = await jev.decide(event, ctx, caps)`; `DeciderUnavailable` → `jev_d = None`.
3. `jev_d is None` → `final = await llm.decide(event, ctx, caps)`, `final.escalation = "jev_unavailable"`; no ack.
4. Else `await out.ack("chat" if route == "chat" else "correction" if route == "correction" else "action")`, then:
   - `route == "correction"`: `prev = log.last_for_source(event.source, clock() - correction_window_s)`;
     `final = await llm.decide(event, ctx, no_corr, correction_instruction(prev) if prev else None)`;
     escalation `"correction"` if prev else `"correction_no_previous"`.
   - `route == "chat"`: `llm.decide(event, ctx, no_corr, CHAT_INSTRUCTION)`, escalation `"chat"`.
   - `confidence is None or confidence < conf_min`: shortlist = capabilities other than chat/correction
     with `candidates.get(name, 0) >= shortlist_min`, sorted by probability descending, first 2; empty →
     `no_corr`. `llm.decide(event, ctx, shortlist, LOW_CONF_INSTRUCTION)`, escalation `"low_confidence"`.
   - `jev_d.escalation == "needs_args"`: `llm.decide(event, ctx, [catalogue.get(route)], ARGS_INSTRUCTION)`, escalation `"needs_args"`.
   - otherwise `final = jev_d`.
5. Any LLM `DeciderUnavailable` in 3–4 → `await out.say(UNAVAILABLE_SAY)`; `final = Decision("none",
   None, [], escalation=<that branch's escalation>)`; skip step 6, go to step 7.
6. `results = await executor.run(final, event)`; `say` each `r.say` that is set, then `final.reply`;
   no results and no reply → `say(NOTHING_SAY)`.
7. `latency_ms` keys: `jev`, `llm` (only if called), `execute` (only if run), `total`. `new_id =
   log.record(event, ctx, final, jev_d, results, latency_ms)`; for a correction with `prev`, then
   `log.label(prev["id"], "wrong", "spoken_correction", corrected_by=new_id)`. Any exception in
   step 7 → print `decision log write failed: <exc>` to stderr, `log_healthy = False`, never raise.
8. Return `final`.

### I13 `MuseClient` additions (`cadence/muse/client.py`)
```python
ENDED_REASONS = ("track_end", "user_next", "user_prev", "new_selection", "pause_timeout", "lost")
def open_play(self, track_rowid: int, duration_ms: int, source: str | None = None) -> int
    # POST /api/plays {"track_rowid","duration_ms","source"} -> response["id"]
def close_play(self, play_id: int, ended_reason: str, position_ms: int | None = None) -> None
    # ValueError (no request) if reason not in ENDED_REASONS; POST /api/plays/{play_id}/close {"ended_reason","position_ms"}
def contract_version(self) -> str | None
    # GET /api/contract; 404 -> None; 200 -> response["version"] (e.g. "1.0"); transport error or other status -> MuseUnavailable
```

### I14 `cadence/plugins/music.py`
```python
PLAY = Capability("music.play", "Play music: a mood, genre, artist, song, or a playlist built from a vibe.",
    {"type": "object", "properties": {"artist": {"type": "string"}, "title": {"type": "string"},
     "mood": {"type": "string", "description": "mood, vibe, activity, or feeling"}, "genre": {"type": "string"},
     "count": {"type": "integer", "minimum": 1, "maximum": 50}, "room": {"type": "string"}}},
    free_args=("artist", "title", "mood", "genre"), target="speaker")
CONTROL = Capability("music.control", "Pause, stop, resume, skip, go back, or turn shuffle on or off for the music playing now.",
    {"type": "object", "properties": {"action": {"type": "string", "enum": ["pause", "resume", "skip", "previous", "shuffle_on", "shuffle_off"]},
     "room": {"type": "string"}}, "required": ["action"]},
    closed_args={"action": {"pause": "pause or stop the music", "resume": "resume or continue paused music",
     "skip": "skip to the next track", "previous": "go back to the previous track",
     "shuffle_on": "turn shuffle on", "shuffle_off": "turn shuffle off"}}, target="speaker")
RATE = Capability("music.rate", "Like or dislike the track playing now, or clear its rating.",
    {"type": "object", "properties": {"rating": {"type": "string", "enum": ["up", "down", "clear"]},
     "room": {"type": "string"}}, "required": ["rating"]},
    closed_args={"rating": {"up": "likes it, thumbs up", "down": "dislikes it, thumbs down", "clear": "remove the rating"}},
    target="speaker")
NOW = Capability("music.now_playing", "Say what is playing now, or whether the music is paused.",
    {"type": "object", "properties": {}}, target="speaker")

def compose_queue(text_results: list[dict] | None, vibe_results: list[dict] | None,
                  artist: str | None, count: int) -> list[dict]

class MusicPlugin(Plugin):
    manifest = Manifest("music", "service", (PLAY, CONTROL, RATE, NOW))
    def __init__(self, client, *, pause_timeout_s: float = PAUSE_TIMEOUT_S, rng: random.Random | None = None,
                 source: str = PLAY_SOURCE, contract_major: int = MUSE_CONTRACT_MAJOR,
                 clock: Callable[[], float] = time.monotonic) -> None
    def check(self) -> bool         # stores and returns availability, stamps clock()
    def available(self) -> bool     # True before any check; else last result, re-running check() first
                                    # when the last result was False and >= 30 s have passed
    def now_playing(self, device_id: str) -> dict | None   # {"track_name","artist_name","paused"} or None
    async def call(self, capability, args, target, port) -> Result
```
`compose_queue`: vibe items normalise to `item["track"]` (keeping `track_rowid`); drop tracks whose
`playable` is falsy; if `artist`, keep text tracks whose `artist_name` or any `artist_names` entry
contains `artist` case-insensitively. Both lists → text tracks present in vibe ordered by vibe score
descending, then the remaining text tracks in original order. Only text → text order. Only vibe →
vibe order. Dedupe by `track_rowid`; first `count`.

`check`: `contract_version()` `None` → True; `"M.m"` with `int(M) == contract_major` → True; other
version or `MuseUnavailable` → False.

`call` (Muse calls run through `asyncio.to_thread`): `target is None` → `Result(False, say="No speaker
is online.", error="no_target")`; `port is None` → `Result(False, say="That speaker isn't connected.",
error="no_port")`.
- `music.play`: no artist/title/mood/genre → `Result(False, say="What should I play?", error="no_slots")`.
  `count = min(max(args.get("count") or DEFAULT_QUEUE_LEN, 1), MAX_QUEUE_LEN)`. Text search
  `" ".join` of title then artist (non-empty), `limit=MAX_QUEUE_LEN`, only when title or artist; vibe
  search `" ".join` of mood then genre, `n=200`, only when mood or genre. `MuseUnavailable` →
  `Result(False, say="Muse isn't answering.", error="muse_unavailable")`. Empty queue →
  `Result(False, say="I couldn't find anything like that.", error="empty")`. If the device has an
  active track: `pos = port.position_ms()`, `await port.stop()`, close span `new_selection`. Start
  index 0. `Result(True, say=f"Playing {track_name} by {artist_name}.", data={"queue": [rowids]})`.
- Starting a track: `play_id = open_play(rowid, duration_ms, source)` (`MuseUnavailable` → `None`,
  stderr warning); `await port.play_url(f"{client.proxy_url}/play/{rowid}", on_end)`. `on_end("track_end")`
  closes `track_end` with `port.position_ms()` and starts the next index, or clears the device state at
  the end; `on_end("lost")` closes `lost` and clears state; `on_end("stopped")` does nothing.
- Closing a span: `play_id is None` → skip; `MuseUnavailable` or `ValueError` → stderr warning only.
- `music.control` with no active track → `Result(False, say="Nothing is playing right now.", error="idle")`.
  `pause`: `port.pause()`, start a timer task; after `pause_timeout_s`, if `port.is_paused()`: close
  `pause_timeout`, `await port.stop()`, mark timed out. `resume`: timed out → restart the same index;
  else `port.resume()`; cancel the timer. `skip`: `pos`, stop, close `user_next`; next index exists →
  start it, else clear and `say="That's the end of the queue."`. `previous`: `pos`, stop, close
  `user_prev`, start `max(index - 1, 0)`. `shuffle_on`: shuffle tracks after the current index with
  `rng`; `shuffle_off`: flag only. Results `ok=True`, `say=None` unless stated.
- `music.rate`: no active track → as control. `client.rate(rowid, {"up": 1, "down": -1, "clear": None}[rating])`;
  say `"Noted, you like this one."` / `"Noted, you don't like this one."` / `"Rating cleared."`.
- `music.now_playing`: active → `f"This is {track_name} by {artist_name}."` plus `" It's paused."` when
  paused; none → `"Nothing is playing right now."`; both `ok=True`.

### I15 `cadence/plugins/speaker.py`
```python
BYTES_PER_MS = 176.4                         # 44100 Hz * 2 ch * 2 bytes / 1000
VOLUME = Capability("speaker.volume", "Make the speaker louder or quieter, or mute or unmute it.",
    {"type": "object", "properties": {"action": {"type": "string", "enum": ["up", "down", "mute", "unmute"]},
     "room": {"type": "string"}}, "required": ["action"]},
    closed_args={"action": {"up": "louder, turn it up", "down": "quieter, turn it down", "mute": "mute", "unmute": "unmute"}},
    target="speaker")

class SpeakerPort:                           # implements AudioPort for one connected session
    def __init__(self, send_audio: Callable[[bytes], Awaitable[None]], *,
                 transport: httpx.AsyncBaseTransport | None = None, gain: float = 1.0) -> None
    gain: float                              # read-only property
    muted: bool                              # read-only property
    def set_gain(self, gain: float) -> None  # clamps to [0.0, 1.0]
    def mute(self) -> None
    def unmute(self) -> None
    async def play_url(self, url: str, on_end: Callable[[str], Awaitable[None]]) -> None
    async def pause(self) -> None
    async def resume(self) -> None
    async def stop(self, reason: str = "stopped") -> None
    def position_ms(self) -> int             # int(music bytes forwarded / BYTES_PER_MS)
    def is_paused(self) -> bool
    def is_playing(self) -> bool
    async def speak(self, pcm: bytes) -> None
    async def drain(self) -> None            # awaits the current pump task, if any (tests)

class SpeakerPlugin(Plugin):
    manifest = Manifest("speaker", "device", (VOLUME,))
    def __init__(self, *, step: float = VOLUME_STEP) -> None
    async def call(self, capability, args, target, port) -> Result
```
Port: `play_url` first `await self.stop()` (old `on_end("stopped")`), then starts a background pump:
`httpx.AsyncClient(transport=..., timeout=None)` streams GET `url`; per chunk it waits while paused, buffers
into `tail` while speaking, else sends the gain-applied chunk; natural end → `on_end("track_end")`;
`httpx.HTTPError` → `on_end("lost")`. `stop(reason)` cancels the pump and calls the current `on_end(reason)`
exactly once; no stream → no-op. Output gain: effective gain `0` when muted; gain `1.0` and unmuted sends
bytes unchanged; otherwise scale int16 samples, carrying an odd trailing byte to the next chunk.
`speak(pcm)`: stream active and not paused → set speaking, take `len(pcm)` bytes of `tail` (zero-padded),
`mix(music, pcm, DUCK_GAIN)`, send gain-applied, clear speaking, then send any remaining `tail`
gain-applied; otherwise send `pcm` gain-applied. Plugin: `port is None` → `Result(False, say="That
speaker isn't connected.", error="no_port")`; `up` → unmute, `set_gain(min(1.0, gain + step))`; `down`
→ `set_gain(max(0.0, gain - step))`; `mute`/`unmute`; `Result(True, data={"gain": port.gain, "muted": port.muted})`.

### I16 `cadence/acks.py`, `cadence/audio/wakeword.py`, `cadence/audio/listener.py`, `cadence/plugins/mcp_adapter.py`
```python
# acks.py
ACK_CATEGORIES = ("action", "chat", "correction")
class AckPool:
    def __init__(self, root: str, *, rng: random.Random | None = None) -> None  # loads root/<category>/*.pcm (sorted) at construction; missing dirs -> empty
    def count(self, category: str) -> int
    def pick(self, category: str) -> bytes | None   # None if empty/unknown; with 2+ clips never the same clip twice in a row

# audio/wakeword.py
WAKE_FRAME_SAMPLES = 1280
WAKE_FRAME_BYTES = 2560
class WakeGate:
    def __init__(self, model_name: str = WAKE_MODEL, threshold: float = WAKE_THRESHOLD, *,
                 model_factory: Callable[[str], object] | None = None) -> None   # model built lazily on first feed
    def feed(self, pcm: bytes) -> bool
# default factory: openwakeword.model.Model(wakeword_models=[name], inference_framework="onnx"), imported inside the factory.
# feed buffers bytes; per full 2560-byte frame: scores = model.predict(np.frombuffer(frame, np.int16));
# scores.get(model_name, 0) >= threshold -> model.reset(), clear buffer, return True. Else False.

# audio/listener.py
class Listener:
    def __init__(self, gate: WakeGate | None, *, vad_factory: Callable[[], object] = VadSegmenter,
                 window_s: float = LISTEN_WINDOW_S, clock: Callable[[], float] = time.monotonic) -> None
    listening: bool                          # read-only property
    def feed(self, pcm: bytes) -> list[bytes]
# gate None: one VAD built at init, feed returns vad.feed(pcm). With gate, idle: gate.feed(pcm) True ->
# listening, deadline = clock() + window_s, fresh vad_factory(); return []. Listening: clock() > deadline
# -> idle, return []; utts = vad.feed(pcm); non-empty -> idle, return utts[:1]; else [].

# plugins/mcp_adapter.py
class McpPlugin(Plugin):
    def __init__(self, plugin_id: str, registry) -> None   # registry: ToolRegistry-like; manifest has no capabilities until start()
    async def start(self) -> None
# start: await registry.start(); one Capability per registry.list_tools() entry fn = entry["function"]:
# name f"{plugin_id}.{fn['name']}", description fn["description"], parameters fn["parameters"],
# free_args = tuple(fn["parameters"].get("properties", {})); manifest = Manifest(plugin_id, "service", caps).
# call: data = await registry.call(capability[len(plugin_id) + 1:], args);
# Result(True, data=data if isinstance(data, dict) else {"result": data}); exceptions propagate.
```

### I17 `cadence/wiring.py` and `cadence/server.py`
```python
# wiring.py
@dataclass
class Runtime:
    registry: DeviceRegistry
    ports: dict[str, SpeakerPort]
    music: MusicPlugin | None
    pipeline: Pipeline
    acks: AckPool
    tts: Callable[[str], bytes] | None       # sentence -> speaker PCM
    asr: Callable[[bytes], str] | None       # mic PCM -> text
    listener_factory: Callable[[], Listener]
def build_runtime() -> Runtime

# server.py (keeps app, TURN_LOCK, REGISTRY)
def set_runtime(runtime: Runtime | None) -> None
def get_runtime() -> Runtime                 # build_runtime() on first call when unset
class SessionOutput:                          # TurnOutput
    def __init__(self, session: Session, port: SpeakerPort | None, runtime: Runtime) -> None
async def handle_text(session: Session, port: SpeakerPort | None, text: str) -> None
```

## WebSocket session protocol (unchanged from M1, normative)

- `ws://<host>:8768/session`; first client text frame `{"type":"hello","client_id":"<id>","caps":[...]}`,
  caps from `audio_in, audio_out, text_in, text_out`; bad hello → `{"type":"error","message":...}` then close.
- Client binary frames: mic PCM 16000 Hz mono s16le. Server binary frames: PCM 44100 Hz stereo s16le.
- Client text frame `{"type":"text","content":"..."}` is an utterance.
- Server text frames: `{"type":"turn_start"}`, `{"type":"turn_end"}`, `{"type":"error","message":...}`,
  and `{"type":"text","content":...}` for spoken text when the session lacks `audio_out` or no TTS is configured.

---

## Phase 1 — Foundation and preflight

### Task 1: Pin dependencies, add config constants, and make Muse URLs configurable [mechanical]
- [ ] status
**Objective:** `openwakeword` installs and imports in `harness/.venv`, `cadence/config.py` holds every shared constant, and Muse/proxy URLs read environment overrides.
**Write-scope:**
- `harness/requirements.txt`
- `harness/requirements-nodeps.txt` (new)
- `harness/cadence/config.py`
- `harness/devices.json` (new)
- `harness/.gitignore`
- `tools/muse_proxy.py`
**Read-context:** `docs/plans/2026-10-01-cadence-decision-harness-v1.md:81-110` (shared constants table); `harness/cadence/config.py:1-11`; `tools/muse_proxy.py:8-14`.
**Anchors:**
- `MUSE_BASE_URL = "http://ianshomeserver:8080"` @ `harness/cadence/config.py`
- `MUSE_BASE = "http://ianshomeserver:8080"` @ `tools/muse_proxy.py`.
**Steps:**
1. Append to `harness/requirements.txt`: `scikit-learn==1.9.1`, `requests==2.34.2`, `tqdm==4.70.1`.
2. Create `harness/requirements-nodeps.txt` containing exactly `openwakeword==0.6.0`.
3. In `harness/cadence/config.py`, add `import os` and every constant in the shared constants table with the exact names and values; replace the `MUSE_BASE_URL`/`MUSE_PROXY_URL` lines with the env-override forms (`os.environ.get(...)`). `WAKE_ENABLED = os.environ.get("CADENCE_WAKE_ENABLED", "1") == "1"`. Keep `WS_PORT`, `DB_PATH`, `MCP_SERVERS` and the module docstring.
4. In `tools/muse_proxy.py`, add `import os` and change `MUSE_BASE` to `os.environ.get("CADENCE_MUSE_BASE_URL", "http://ianshomeserver:8080")`.
5. Create `harness/devices.json`: `{"devices": [{"id": "speaker-1", "kind": "speaker", "room": "bedroom"}]}`.
6. Append the line `acks/` to `harness/.gitignore`.
7. Run `cd harness && .venv/bin/pip install -r requirements.txt && .venv/bin/pip install --no-deps -r requirements-nodeps.txt`.
**New symbols:** constants listed in the shared constants table.
**Verify:** `cd harness && .venv/bin/python -c "import openwakeword, sklearn; from cadence import config as c; print(c.JEV_TIMEOUT_S, c.MAX_QUEUE_LEN, c.WAKE_MODEL)" && .venv/bin/python -m pytest -q` — expected: prints `1.5 50 hey_jarvis_v0.1`, then `55 passed`.
**Forbidden:** no packages beyond the four named; never `pip install openwakeword` without `--no-deps` (it pulls `tflite-runtime`, which fails); no other edits to `muse_proxy.py`.
**Depends:** none
**Why:** Every later brief imports these constants and forbids new deps. Muse is reachable only by tailnet address on this host, so URLs must be overridable.

### Task 2: Prove the live runtime on ianshomeserver [experiment]
- [ ] status
**Objective:** A recorded table showing whether Kokoro, Whisper, openwakeword, Jev (multi-question), Ollama, and Muse each load or answer on this host, with latencies.
**Write-scope:**
- `harness/scripts/preflight_v1.py` (new)
- `docs/preflight/runtime-v1.md` (new)
**Read-context:** `harness/scripts/preflight_runtime.py` — the M1 preflight style; `harness/scripts/bench_run.py:210-246` — Jev request code and key handling; `tools/voice_chat_host.py:28-34` — Kokoro download URLs; `harness/cadence/audio/tts.py:57-63`; `harness/cadence/audio/asr.py:11-15`.
**Anchors:**
- `class Tts:` @ `harness/cadence/audio/tts.py`
- `class Asr:` @ `harness/cadence/audio/asr.py`
- `def _typesafe_key() -> str:` @ `harness/scripts/bench_run.py`.
**Steps:**
1. Download `kokoro-v1.0.onnx` and `voices-v1.0.bin` from the URLs at `tools/voice_chat_host.py:31-32` into `tools/` (skip a file that already exists).
2. Write `harness/scripts/preflight_v1.py` that runs each check, catches every exception, and prints one markdown table row per check (`check | ok | detail | ms`): (a) `Asr()` load ms plus `transcribe(bytes(32000))` ms; (b) `Tts()` load ms plus `speak("Playing Weightless by Marconi Union.")` ms and output bytes; (c) `openwakeword.utils.download_models(model_names=["hey_jarvis_v0.1"])`, `Model(wakeword_models=["hey_jarvis_v0.1"], inference_framework="onnx")`, predict ms on 50 zero frames of 1280 int16 samples; (d) one Jev POST with four questions (a `route` choice over 3 options and three `arg:` choices of 2 options each), recording latency, `model`, and whether all four answer keys came back; (e) Ollama `gemma4:31b-cloud` one-message chat latency; (f) `GET {CADENCE_MUSE_BASE_URL}/api/health` status.
3. Read the key exactly as `bench_run.py:211-216` does; never print it, never write it to the doc.
4. Run `cd harness && CADENCE_MUSE_BASE_URL=http://100.122.149.75:8080 .venv/bin/python scripts/preflight_v1.py`, and write the table plus host facts (CPU count, RAM) into `docs/preflight/runtime-v1.md`.
**New symbols:** none
**Verify:** `test -s docs/preflight/runtime-v1.md && grep -c "^|" docs/preflight/runtime-v1.md` — expected: the table exists; record each check's ok/ms. Negative result is a valid outcome.
**Forbidden:** no edits under `harness/cadence/`; no key in any output or file; no retry loops against Jev.
**Depends:** Task 1
**Why:** Kokoro is missing here and Jev multi-question fan-out was never exercised; Tasks 21–23 need all of these live. A failure is recorded, not worked around.

## Phase 2 — Core model

### Task 3: Write core-type tests [test]
- [ ] status
**Objective:** Red tests pin events, registry, plugin base, catalogue, resolver, and the decider base exactly as I1–I6.
**Write-scope:**
- `harness/tests/test_core.py` (new)
**Read-context:** `docs/plans/2026-10-01-cadence-decision-harness-v1.md:114-248` (I1–I6).
**Anchors:** none
**Steps:**
1. Import `utterance, Event, Call, Decision, DEFAULT_USER` from `cadence.events`; `Device, DeviceRegistry` from `cadence.plugins.registry`; `Capability, Manifest, Result, Plugin` from `cadence.plugins.base`; `Catalogue, CHAT, CORRECTION, BUILTINS` from `cadence.catalogue`; `resolve` from `cadence.resolver`; `Decider, DeciderUnavailable, UnavailableDecider` from `cadence.deciders.base`.
2. Cases: (1) `utterance("speaker-1", "bedroom", "hi")` → kind `utterance`, `user_id == "household"`, payload `{"text": "hi", "asr_conf": None}`, 32-char hex id, two calls give different ids; (2) `Event` is frozen (assigning raises `FrozenInstanceError`); (3) `Decision` defaults: `candidates == {}`, `escalation is None`; (4) `DeviceRegistry.from_file` on a tmp JSON loads devices offline, on a missing path returns empty; (5) `set_online` on unknown id adds it with room `None`; (6) `find("speaker", "bedroom")` respects room and `online_only`; (7) `rooms()` sorted unique; (8) `Catalogue` with two fake plugins: `available()` order is plugin caps then `chat`, `correction`; a plugin whose `available()` is False is excluded; (9) duplicate capability name raises `ValueError`, including a plugin capability named `chat`; (10) `plugin_for("chat")` is `None`, `get("chat") is CHAT`; (11) resolver: untargeted → `[None]`; `args["room"]` wins; then `event.room`; then online source device; then all online; none online → `[]`; (12) `UnavailableDecider("x").decide(...)` raises `DeciderUnavailable`.
3. Fake plugin: subclass `Plugin` with a `Manifest` and an async `call` returning `Result(True)`.
**New symbols:** none
**Verify:** `cd harness && .venv/bin/python -m pytest -q tests/test_core.py` — expected: collection error `ModuleNotFoundError: No module named 'cadence.events'`.
**Forbidden:** no files outside Write-scope; no network.
**Depends:** none
**Why:** Pins the core seam before code exists so the implementer cannot drift from I1–I6.

### Task 4: Implement core types
- [ ] status
**Objective:** `cadence.events`, `cadence.plugins.{base,registry}`, `cadence.catalogue`, `cadence.resolver`, `cadence.deciders.base` exist exactly as I1–I6 and Task 3's tests pass.
**Write-scope:**
- `harness/cadence/events.py` (new)
- `harness/cadence/plugins/__init__.py` (new)
- `harness/cadence/plugins/base.py` (new)
- `harness/cadence/plugins/registry.py` (new)
- `harness/cadence/catalogue.py` (new)
- `harness/cadence/resolver.py` (new)
- `harness/cadence/deciders/__init__.py` (new)
- `harness/cadence/deciders/base.py` (new)
**Read-context:** `docs/plans/2026-10-01-cadence-decision-harness-v1.md:114-248` (I1–I6); `harness/tests/test_core.py` (from Task 3).
**Anchors:** none
**Steps:**
1. Implement each module with the exact signatures, defaults, and rules in I1–I6. `plugins/base.py` imports `Device` from `cadence.plugins.registry`.
2. Empty `__init__.py` files.
**New symbols:** every symbol in I1–I6.
**Verify:** `cd harness && .venv/bin/python -m pytest -q` — expected: all pass (55 baseline + Task 3's).
**Forbidden:** no new deps; do not edit tests; no imports of `cadence.server`.
**Depends:** Task 3
**Why:** Every later module builds on these types.

## Phase 3 — Log, deciders, pipeline

### Task 5: Write decision-log tests [test]
- [ ] status
**Objective:** Red tests pin `DecisionLog` per I7.
**Write-scope:**
- `harness/tests/test_decisionlog.py` (new)
**Read-context:** `docs/plans/2026-10-01-cadence-decision-harness-v1.md:250-273` (I7).
**Anchors:** `def utterance(source: str, room: str | None, text: str, *, asr_conf: float | None = None,` @ `harness/cadence/events.py` (from Task 4).
**Steps:**
1. Use `DecisionLog(str(tmp_path / "log.sqlite3"))`.
2. Cases: (1) `record` returns an int id; `export()[0]` has exactly the 21 keys in I7 plus `labels == []`; (2) `calls` round-trips as `[{"capability": "music.control", "args": {"action": "pause"}}]`; (3) `jev=None` → `jev_route`, `jev_confidence`, `jev_candidates` are `None`, `models == {"decider": "gemma4:31b-cloud", "jev": None}`; (4) outcome for `[Result(True)]` `ok`, `[Result(False)]` `error`, mixed `partial`, `[]` with reply `reply`, `[]` without reply `none`; (5) `label(id, "wrong", "spoken_correction", corrected_by=id2)` appears in export with those values; (6) `label` with label `"right"`, source `"ui"`, or unknown id raises `ValueError`; (7) `last_for_source("speaker-1", since)` returns the newest matching row and `None` when all rows are older than `since` or from another source; (8) `recent(2)` newest first; (9) `DecisionLog` exposes no attribute containing `update` or `delete`; (10) reopening the same path keeps rows.
**New symbols:** none
**Verify:** `cd harness && .venv/bin/python -m pytest -q tests/test_decisionlog.py` — expected: collection error `No module named 'cadence.decisionlog'`.
**Forbidden:** no files outside Write-scope.
**Depends:** Task 4
**Why:** The log is the training data; its shape and append-only rule must be pinned before code.

### Task 6: Implement the decision log
- [ ] status
**Objective:** `cadence/decisionlog.py` per I7; Task 5's tests pass.
**Write-scope:**
- `harness/cadence/decisionlog.py` (new)
**Read-context:** `docs/plans/2026-10-01-cadence-decision-harness-v1.md:250-273` (I7); `harness/cadence/store.py:8-45` — sqlite style; `harness/tests/test_decisionlog.py` (from Task 5).
**Anchors:** `class Store:` @ `harness/cadence/store.py`
**Steps:**
1. Two tables `decision_log` (one column per I7 key, JSON columns as TEXT) and `decision_labels`; `CREATE TABLE IF NOT EXISTS`; commit after every insert.
2. Implement each method per I7. Rows come back as dicts with JSON decoded.
**New symbols:** `LABELS`, `LABEL_SOURCES`, `DecisionLog` per I7.
**Verify:** `cd harness && .venv/bin/python -m pytest -q` — expected: all pass.
**Forbidden:** no edits to `store.py` or its `decisions` table; no UPDATE/DELETE SQL against `decision_log`; no new deps.
**Depends:** Task 5
**Why:** Separate from M1's diary table by spec decision.

### Task 7: Write decider tests [test]
- [ ] status
**Objective:** Red tests pin `JevDecider` (I8) and `LlmDecider` (I9).
**Write-scope:**
- `harness/tests/test_deciders.py` (new)
**Read-context:** `docs/plans/2026-10-01-cadence-decision-harness-v1.md:275-328` (I8–I9); `harness/tests/test_agent.py:24-71` — Ollama response shape and `FakeLLM`; `docs/research/data/jev_route.json` — the first record's info.jev field is a real Jev answer.
**Anchors:**
- `class FakeLLM:` @ `harness/tests/test_agent.py`
- `class RollingContext:` @ `harness/cadence/context.py`
**Steps:**
1. Jev fakes: `httpx.MockTransport` handler capturing the request and returning `{"answers": {...}, "model": "jev-1.13.0", "usage": {}}`. Capabilities: a closed one (`music.control` with `closed_args={"action": {"pause": "p", "skip": "s"}}`), a free one (`music.play`, `free_args=("mood",)`), plus `CHAT`, `CORRECTION`.
2. Jev cases: (1) request JSON has `state`, `model == "jev-latest"`, `questions["route"]["criteria"]` keys equal the capability names, and `arg:music.control:action` present; (2) `closed_args=False` → no `arg:` questions; (3) `Authorization` header is `Bearer k`; (4) route `music.control` with arg answer `pause` → `calls == [Call("music.control", {"action": "pause"})]`, confidence and candidates copied, `model == "jev-1.13.0"`; (5) route `music.play` → `calls == []`, `escalation == "needs_args"`; (6) route `chat` → no calls; (7) status 500 → `DeciderUnavailable` whose message does not contain `k`; (8) `httpx.ConnectError` raised by the handler → `DeciderUnavailable`; (9) missing `arg:` answer → `DeciderUnavailable`; (10) `render_state` ends with `"\nUser said: pause"`; (11) `load_api_key` reads a tmp file line `TYPESAFE_API_KEY='abc'` → `abc`; env `TYPESAFE_API_KEY` wins (monkeypatch); missing → `DeciderUnavailable`.
3. LLM cases with `FakeLLM`: (12) tool call `music__control` `{"action": "skip"}` → `Call("music.control", {"action": "skip"})`, route `music.control`, `think` False; (13) tools list excludes `chat`/`correction`, names use `__`; (14) text-only response → `calls == []`, `reply` set, route `chat`; (15) a tool name not in the given capabilities is dropped; (16) 4 tool calls with `max_calls=3` → 3 kept; (17) `instruction` appears as a system message before the user message; (18) `ConnectionError` → `DeciderUnavailable`; (19) rolling context gains the user text and the reply.
**New symbols:** none
**Verify:** `cd harness && .venv/bin/python -m pytest -q tests/test_deciders.py` — expected: collection error `No module named 'cadence.deciders.jev'`.
**Forbidden:** no real network; never put a real key in tests.
**Depends:** Task 4
**Why:** Deciders talk to two external APIs; recorded shapes pin them without network.

### Task 8: Implement the Jev and LLM deciders
- [ ] status
**Objective:** `cadence/deciders/jev.py` and `cadence/deciders/llm.py` per I8–I9; Task 7's tests pass.
**Write-scope:**
- `harness/cadence/deciders/jev.py` (new)
- `harness/cadence/deciders/llm.py` (new)
**Read-context:** `docs/plans/2026-10-01-cadence-decision-harness-v1.md:275-328` (I8–I9); `harness/scripts/bench_run.py:211-246`; `harness/cadence/llm.py:1-34`; `harness/tests/test_deciders.py` (from Task 7).
**Anchors:**
- `class OllamaLLM:` @ `harness/cadence/llm.py`
- `MAX_TOOL_CALLS = 3` @ `harness/cadence/agent.py`
- `class DeciderUnavailable(Exception)` @ `harness/cadence/deciders/base.py` (from Task 4)
**Steps:**
1. Implement per I8: one `httpx.AsyncClient(transport=..., timeout=timeout_s)` per `decide` call; no retries.
2. Implement per I9.
**New symbols:** I8 and I9 symbols.
**Verify:** `cd harness && .venv/bin/python -m pytest -q` — expected: all pass.
**Forbidden:** no logging of headers or the key; no retry; no new deps; do not edit `llm.py` or `agent.py`.
**Depends:** Task 7
**Why:** Jev is the first-stage decider; the LLM fills free-text args and handles chat.

### Task 9: Write pipeline, executor, and live-context tests [test]
- [ ] status
**Objective:** Red tests pin `Executor` (I10), `LiveContext` (I11), and `Pipeline.handle` (I12).
**Write-scope:**
- `harness/tests/test_pipeline.py` (new)
**Read-context:** `docs/plans/2026-10-01-cadence-decision-harness-v1.md:330-400` (I10–I12).
**Anchors:**
- `class DecisionLog:` @ `harness/cadence/decisionlog.py` (from Task 6)
- `class Catalogue:` @ `harness/cadence/catalogue.py` (from Task 4)
**Steps:**
1. Fakes: `ScriptedDecider(Decider)` returning queued `Decision`s or raising `DeciderUnavailable`, recording `(capabilities, instruction)`; `FakePlugin` with capabilities `x.do` (target `speaker`, closed arg) and `x.ask` (free arg), returning a configured `Result` or raising; `FakeOut` recording `("ack", c)`/`("say", t)`; real `DecisionLog` on `tmp_path`; registry with online `speaker-1` in `bedroom`; `ports=lambda i: None`.
2. Executor cases: (1) success returns plugin result; (2) unknown capability → `"I can't do that yet."`; (3) no online target → `"No speaker is online."`; (4) plugin raises → `"Sorry, that didn't work."`, later calls skipped; (5) only `max_calls` calls run.
3. LiveContext: (6) keys in order `time, weekday, room, now_playing, recent` with a fixed `clock`.
4. Pipeline cases: (7) Jev confident `x.do` → executed, ack `action`, LLM never called, log row decider `jev`; (8) Jev route `chat` → ack `chat`, LLM called with `CHAT_INSTRUCTION`, reply said, escalation `chat`; (9) confidence 0.3 → LLM gets shortlist of capabilities with probability ≥ 0.25 (max 2, highest first), escalation `low_confidence`; (10) `needs_args` → LLM gets exactly `[x.ask]` with `ARGS_INSTRUCTION`; (11) Jev unavailable → no ack, LLM gets all available capabilities, escalation `jev_unavailable`; (12) Jev and LLM unavailable → `say(UNAVAILABLE_SAY)`, row decider `none`; (13) correction with an earlier row from the same source within 60 s → LLM instruction starts `"The user is correcting"`, previous row gets a `wrong` label with `corrected_by` = new row id; (14) correction with no recent row → escalation `correction_no_previous`, no label; (15) no results and no reply → `NOTHING_SAY`; (16) a log whose `record` raises → `handle` returns, `log_healthy is False`; (17) row `latency_ms` has `jev` and `total`.
**New symbols:** none
**Verify:** `cd harness && .venv/bin/python -m pytest -q tests/test_pipeline.py` — expected: collection error `No module named 'cadence.pipeline'`.
**Forbidden:** no network; no real deciders.
**Depends:** Task 6
**Why:** The escalation rules are the heart of v1 and must be pinned exactly.

### Task 10: Implement executor, live context, and pipeline
- [ ] status
**Objective:** `cadence/executor.py`, `cadence/livecontext.py`, `cadence/pipeline.py` per I10–I12; Task 9's tests pass.
**Write-scope:**
- `harness/cadence/executor.py` (new)
- `harness/cadence/livecontext.py` (new)
- `harness/cadence/pipeline.py` (new)
**Read-context:** `docs/plans/2026-10-01-cadence-decision-harness-v1.md:330-400` (I10–I12); `harness/tests/test_pipeline.py` (from Task 9).
**Anchors:** `def resolve(call: Call, capability: Capability, event: Event, registry: DeviceRegistry) -> list[Device | None]` @ `harness/cadence/resolver.py` (from Task 4)
**Steps:**
1. Implement exactly the numbered `handle` algorithm in I12, including latency keys and the stderr message text.
2. Implement I10 and I11.
**New symbols:** I10–I12 symbols.
**Verify:** `cd harness && .venv/bin/python -m pytest -q` — expected: all pass.
**Forbidden:** no imports of `cadence.deciders.jev` or `cadence.deciders.llm` (pipeline depends only on `Decider`); no new deps.
**Depends:** Task 9
**Why:** Single seam every input passes through; deciders stay swappable.

## Phase 4 — Plugins and audio

### Task 11: Write Muse client tests for plays and contract version [test]
- [ ] status
**Objective:** Red tests pin I13 additions to `MuseClient`.
**Write-scope:**
- `harness/tests/test_muse_client.py`
**Read-context:** `docs/plans/2026-10-01-cadence-decision-harness-v1.md:402-411` (I13); `harness/tests/test_muse_client.py:1-30,113-135`.
**Anchors:** `def make_client(handler):` @ `harness/tests/test_muse_client.py`
**Steps:**
1. Append tests (keep every existing test unchanged): (1) `open_play(5, 1000, "cadence")` POSTs `/api/plays` with body `{"track_rowid": 5, "duration_ms": 1000, "source": "cadence"}` and returns the `id` from a 201 `{"id": 9}`; (2) `close_play(9, "track_end", 1200)` POSTs `/api/plays/9/close` with `{"ended_reason": "track_end", "position_ms": 1200}`; (3) `close_play(9, "stopped")` raises `ValueError` and sends no request; (4) `ENDED_REASONS` equals the six reasons in I13; (5) `contract_version()` → `"1.0"` on 200 `{"version": "1.0"}`, `None` on 404, `MuseUnavailable` on 500; (6) transport error on `open_play` → `MuseUnavailable`.
**New symbols:** none
**Verify:** `cd harness && .venv/bin/python -m pytest -q tests/test_muse_client.py` — expected: the 9 existing tests pass; the new ones fail with `AttributeError` or `ImportError` naming `open_play`, `close_play`, `contract_version`, or `ENDED_REASONS`.
**Forbidden:** do not modify existing tests or fixtures.
**Depends:** none
**Why:** Plays write into Muse's one non-regenerable table; the request shape must match Muse's API exactly.

### Task 12: Add plays and contract-version methods to MuseClient
- [ ] status
**Objective:** `MuseClient` gains I13 methods; Task 11's tests pass.
**Write-scope:**
- `harness/cadence/muse/client.py`
**Read-context:** `docs/plans/2026-10-01-cadence-decision-harness-v1.md:402-411` (I13); `harness/cadence/muse/client.py:18-92`.
**Anchors:** `def _send(self, method: str, path: str, json: dict | None = None) -> dict:` @ `harness/cadence/muse/client.py`
**Steps:**
1. Add module constant `ENDED_REASONS` and the three methods per I13. `open_play`/`close_play` use `_send`. `contract_version` calls `self._client.get("/api/contract")` directly so a 404 returns `None`.
**New symbols:** `ENDED_REASONS`, `MuseClient.open_play`, `MuseClient.close_play`, `MuseClient.contract_version`.
**Verify:** `cd harness && .venv/bin/python -m pytest -q` — expected: all pass.
**Forbidden:** do not change existing methods; no new deps.
**Depends:** Task 11
**Why:** Shared-facts sync with Muse.

### Task 13: Write music plugin tests [test]
- [ ] status
**Objective:** Red tests pin `compose_queue` and `MusicPlugin` behaviour per I14.
**Write-scope:**
- `harness/tests/test_music_plugin.py` (new)
**Read-context:** `docs/plans/2026-10-01-cadence-decision-harness-v1.md:413-483` (I14); `harness/tests/fixtures/muse/search_text.json`; `harness/tests/fixtures/muse/search_vibe.json` (shapes).
**Anchors:** `class Plugin(abc.ABC):` @ `harness/cadence/plugins/base.py` (from Task 4)
**Steps:**
1. Fakes: `FakeMuse` (sync `search_text`, `search_vibe`, `open_play` returning increasing ids, `close_play` recording `(play_id, reason, position)`, `rate`, `contract_version`, attribute `proxy_url = "http://proxy"`, can raise `MuseUnavailable`); `FakePort` implementing I3 `AudioPort`, recording `play_url` urls, storing `on_end`, with settable `position_ms`; target `Device("speaker-1", "speaker", "bedroom", True)`.
2. `compose_queue` cases: (1) artist filter keeps tracks matching `artist_names` case-insensitively; (2) text+vibe ordering by vibe score then leftovers; (3) unplayable dropped; (4) dedupe and `count` cap.
3. Plugin cases: (5) no slots → `"What should I play?"`; (6) play mood → vibe called with `n=200`, port gets `http://proxy/play/<rowid>`, `open_play(rowid, duration, "cadence")`, say `"Playing <track> by <artist>."`; (7) `MuseUnavailable` → `"Muse isn't answering."`; (8) empty → `"I couldn't find anything like that."`; (9) new play while playing closes `new_selection`; (10) `on_end("track_end")` closes `track_end` and starts next; at queue end state clears; (11) `on_end("lost")` closes `lost`; (12) skip closes `user_next` and starts next; skip at last track says `"That's the end of the queue."`; (13) previous closes `user_prev`; (14) pause with `pause_timeout_s=0.01`, sleep 0.05 → closes `pause_timeout`, port stopped; resume restarts same track; (15) control with nothing playing → `"Nothing is playing right now."`; (16) rate up calls `rate(rowid, 1)` and says `"Noted, you like this one."`; (17) now_playing text with and without `" It's paused."`; (18) `check()` True for `None` and `"1.0"`, False for `"2.0"` and `MuseUnavailable`; (19) `open_play` raising `MuseUnavailable` still plays; (20) `port=None` → `"That speaker isn't connected."`; (21) with a fake clock: after a failed `check()`, `available()` is False and makes no new call before 30 s, and re-checks (now True) at 30 s.
**New symbols:** none
**Verify:** `cd harness && .venv/bin/python -m pytest -q tests/test_music_plugin.py` — expected: collection error `No module named 'cadence.plugins.music'`.
**Forbidden:** no network.
**Depends:** none
**Why:** Queue composition and play-span reasons are deterministic and must match Muse's semantics.

### Task 14: Implement the music plugin
- [ ] status
**Objective:** `cadence/plugins/music.py` per I14; Task 13's tests pass.
**Write-scope:**
- `harness/cadence/plugins/music.py` (new)
**Read-context:** `docs/plans/2026-10-01-cadence-decision-harness-v1.md:413-483` (I14); `harness/tests/test_music_plugin.py` (from Task 13).
**Anchors:** `def open_play(self, track_rowid: int, duration_ms: int, source: str | None = None) -> int` @ `harness/cadence/muse/client.py` (from Task 12)
**Steps:**
1. Implement per I14. Per-device state: tracks, index, play_id, timed_out, timer task. Muse calls via `asyncio.to_thread`.
**New symbols:** I14 symbols.
**Verify:** `cd harness && .venv/bin/python -m pytest -q` — expected: all pass.
**Forbidden:** no direct calls to the speaker plugin; no new deps; do not edit `muse/client.py`.
**Depends:** Task 13, Task 12
**Why:** Turns structured slots into a queue and keeps Muse's plays honest.

### Task 15: Write speaker port and plugin tests [test]
- [ ] status
**Objective:** Red tests pin `SpeakerPort` and `SpeakerPlugin` per I15.
**Write-scope:**
- `harness/tests/test_speaker.py` (new)
**Read-context:** `docs/plans/2026-10-01-cadence-decision-harness-v1.md:485-527` (I15); `harness/cadence/audio/mixer.py:1-24`.
**Anchors:** `def mix(music: bytes, speech: bytes, duck: float) -> bytes:` @ `harness/cadence/audio/mixer.py`
**Steps:**
1. Stream fake: `httpx.MockTransport` returning `httpx.Response(200, stream=<async byte iterator>)` yielding fixed int16 chunks; `sent` list for `send_audio`.
2. Cases: (1) play_url forwards all bytes unchanged at gain 1.0, then `on_end("track_end")`; (2) `position_ms()` equals `int(len(bytes)/176.4)`; (3) `set_gain(0.5)` halves sample values; `set_gain(2.0)` clamps to 1.0; (4) mute sends zeros; (5) odd-length chunk at gain 0.5 loses no bytes overall; (6) `stop()` calls `on_end("stopped")` once; `stop("lost")` passes `lost`; stop with nothing playing is a no-op; (7) a second `play_url` stops the first with `stopped`; (8) pause stops forwarding until resume (`is_paused` toggles); (9) `speak` with no stream sends the speech bytes unchanged at gain 1.0; (10) handler raising `httpx.ReadError` → `on_end("lost")`; (11) plugin `up` from 0.5 → 0.6 and unmutes, `down` floors at 0.0, `mute`/`unmute`, `port=None` → `"That speaker isn't connected."`.
**New symbols:** none
**Verify:** `cd harness && .venv/bin/python -m pytest -q tests/test_speaker.py` — expected: collection error `No module named 'cadence.plugins.speaker'`.
**Forbidden:** no real network or audio devices.
**Depends:** none
**Why:** The port carries music and speech to the board; gain and end reasons feed Muse plays.

### Task 16: Implement the speaker port and plugin
- [ ] status
**Objective:** `cadence/plugins/speaker.py` per I15; Task 15's tests pass.
**Write-scope:**
- `harness/cadence/plugins/speaker.py` (new)
**Read-context:** `docs/plans/2026-10-01-cadence-decision-harness-v1.md:485-527` (I15); `harness/cadence/server.py:95-145` — the M1 `MusicStream`/`_pump_music` this replaces; `harness/tests/test_speaker.py` (from Task 15).
**Anchors:**
- `DUCK_GAIN = 0.25` @ `harness/cadence/audio/mixer.py`
- `class MusicStream:` @ `harness/cadence/server.py`
**Steps:**
1. Implement per I15. Port gain via numpy int16 scaling with `np.clip`.
**New symbols:** I15 symbols.
**Verify:** `cd harness && .venv/bin/python -m pytest -q` — expected: all pass.
**Forbidden:** do not edit `server.py` (Task 20 removes `MusicStream`); no new deps.
**Depends:** Task 15
**Why:** Moves playback out of the server into a device plugin with a reusable port.

### Task 17: Write ack pool, wake gate, listener, and MCP adapter tests [test]
- [ ] status
**Objective:** Red tests pin I16.
**Write-scope:**
- `harness/tests/test_acks.py` (new)
- `harness/tests/test_listener.py` (new)
- `harness/tests/test_mcp_adapter.py` (new)
**Read-context:** `docs/plans/2026-10-01-cadence-decision-harness-v1.md:529-568` (I16); `harness/cadence/audio/vad.py:1-30`.
**Anchors:** `class VadSegmenter:` @ `harness/cadence/audio/vad.py`
**Steps:**
1. `test_acks.py`: (1) tmp `action/00.pcm`, `action/01.pcm` → `count("action") == 2`; (2) 20 picks never repeat back-to-back; (3) single clip returns it each time; (4) empty or unknown category → `None`; missing root → counts 0.
2. `test_listener.py` with `FakeModel` (`predict` returns `{"hey_jarvis_v0.1": score}` from a queue, counts `reset` calls) via `model_factory`, and `FakeVad`: (5) gate fires only on a full 2560-byte frame scoring ≥ 0.5 and calls `reset`; partial frames are buffered; (6) the model factory is not called until the first `feed`; (7) `Listener(None)` returns VAD utterances directly; (8) with a gate: idle returns `[]`, fire → `listening`, next VAD utterance returned once then idle; (9) fake clock past `window_s` → idle with `[]`.
3. `test_mcp_adapter.py` with `FakeRegistry` (`start`, `list_tools` returning Ollama-format entries, `call`): (10) before `start` the manifest has no capabilities; after, names are `"ext.search"`, `free_args` from properties; (11) `call("ext.search", {"q": 1}, None, None)` forwards `("search", {"q": 1})`, dict data kept, non-dict wrapped as `{"result": ...}`; (12) registry exception propagates.
**New symbols:** none
**Verify:** `cd harness && .venv/bin/python -m pytest -q tests/test_acks.py tests/test_listener.py tests/test_mcp_adapter.py` — expected: 3 collection errors naming `cadence.acks`, `cadence.audio.wakeword` or `cadence.audio.listener`, and `cadence.plugins.mcp_adapter`.
**Forbidden:** never load the real openwakeword model in tests.
**Depends:** Task 4
**Why:** Small units with sharp edges (repeat avoidance, frame buffering, listening window).

### Task 18: Implement ack pool, wake gate, listener, and MCP adapter
- [ ] status
**Objective:** I16 modules exist; Task 17's tests pass.
**Write-scope:**
- `harness/cadence/acks.py` (new)
- `harness/cadence/audio/wakeword.py` (new)
- `harness/cadence/audio/listener.py` (new)
- `harness/cadence/plugins/mcp_adapter.py` (new)
**Read-context:** `docs/plans/2026-10-01-cadence-decision-harness-v1.md:529-568` (I16); `harness/cadence/mcp_client.py:16-73`; tests from Task 17.
**Anchors:**
- `class ToolRegistry:` @ `harness/cadence/mcp_client.py`
- `def feed(self, data: bytes) -> list[bytes]:` @ `harness/cadence/audio/vad.py`
**Steps:**
1. Implement per I16. `openwakeword` is imported only inside the default model factory.
**New symbols:** I16 symbols.
**Verify:** `cd harness && .venv/bin/python -m pytest -q` — expected: all pass.
**Forbidden:** no top-level `import openwakeword`; no edits to `mcp_client.py` or `vad.py`; no new deps.
**Depends:** Task 17
**Why:** Wake word gates the mic; acks mask latency; MCP keeps the harness extensible.

## Phase 5 — Wiring and server

### Task 19: Write server tests [test]
- [ ] status
**Objective:** Red tests pin the rewritten `/session` endpoint against a fake runtime per I17 and the protocol section.
**Write-scope:**
- `harness/tests/test_server.py` (new)
**Read-context:** `docs/plans/2026-10-01-cadence-decision-harness-v1.md:570-600` (I17 and protocol); `harness/cadence/server.py:148-213`.
**Anchors:**
- `TURN_LOCK = asyncio.Lock()` @ `harness/cadence/server.py`
- `class Pipeline:` @ `harness/cadence/pipeline.py` (from Task 10)
**Steps:**
1. Build a `Runtime` (from `cadence.wiring`) with: a real `Pipeline` over a `ScriptedDecider` Jev returning a confident `x.do` decision, an LLM decider that is never called, a `Catalogue` with a fake plugin whose `x.do` returns `Result(True, say="done")`, a `DecisionLog` on `tmp_path`, `DeviceRegistry([Device("speaker-1", "speaker", "bedroom")])`, `ports={}`, `music=None`, `AckPool(str(tmp_path / "acks"))`, `tts=None`, `asr=None`, `listener_factory=lambda: Listener(None)`. Call `server.set_runtime(rt)`; reset with `set_runtime(None)` after.
2. Use `fastapi.testclient.TestClient(server.app).websocket_connect("/session")`.
3. Cases: (1) text hello (`client_id "speaker-1"`, caps `text_in, text_out`) then `{"type":"text","content":"do it"}` → frames `turn_start`, `{"type":"text","content":"done"}`, `turn_end`; the log has one row with `source == "speaker-1"` and `room == "bedroom"`; (2) bad hello → error frame; (3) during the session `registry.get("speaker-1").online` is True, after disconnect False; (4) a pipeline raising `RuntimeError` → error frame then `turn_end`; (5) `server.TURN_LOCK` is an `asyncio.Lock`; (6) importing `cadence.server` does not call `build_runtime` (monkeypatch `cadence.wiring.build_runtime` to raise, then `importlib.reload(cadence.server)`).
**New symbols:** none
**Verify:** `cd harness && .venv/bin/python -m pytest -q tests/test_server.py` — expected: collection error `No module named 'cadence.wiring'`.
**Forbidden:** no network; no real models.
**Depends:** Task 10, Task 18
**Why:** Proves the server is only a transport around the pipeline.

### Task 20: Wire the runtime and rewrite the server around the pipeline
- [ ] status
**Objective:** `cadence/wiring.py` builds the v1 runtime and `cadence/server.py` routes every utterance through `Pipeline.handle`; all tests pass.
**Write-scope:**
- `harness/cadence/wiring.py` (new)
- `harness/cadence/server.py`
**Read-context:** `docs/plans/2026-10-01-cadence-decision-harness-v1.md:570-600` (I17 and protocol); `harness/cadence/server.py:1-283`; `harness/tests/test_server.py` (from Task 19).
**Anchors:**
- `async def session_endpoint(ws) -> None:` @ `harness/cadence/server.py`
- `class MusicPlugin(Plugin):` @ `harness/cadence/plugins/music.py` (from Task 14)
- `class SpeakerPort:` @ `harness/cadence/plugins/speaker.py` (from Task 16)
**Steps:**
1. `build_runtime()`: `DeviceRegistry.from_file(DEVICES_PATH)`; `ports = {}`; `MuseClient(MUSE_BASE_URL, MUSE_PROXY_URL)`; `MusicPlugin(client)` then `check()`; `SpeakerPlugin()`; `Catalogue([music, speaker])`; `DecisionLog(DB_PATH)`; Jev from `load_api_key()`, on `DeciderUnavailable` print `jev unavailable: <reason>` to stderr and use `UnavailableDecider`; `LlmDecider(OllamaLLM(), RollingContext())`; `Executor(catalogue, registry, ports.get)`; `LiveContext(log, music.now_playing)`; `AckPool(ACK_DIR)`; `tts` and `asr` as closures creating `Tts()`/`Asr()` on first call (`tts` returns `Tts.speak(text)`); `listener_factory` returns `Listener(WakeGate() if WAKE_ENABLED else None)`.
2. Rewrite `server.py` per I17: keep `app`, `TURN_LOCK`, `REGISTRY`, the hello parsing and error frame; on connect `registry.set_online(client_id, True)` and create `SpeakerPort(send_audio)` into `runtime.ports` when caps include `audio_out`; binary frames → `listener.feed` → `runtime.asr` → `handle_text`; text frames → `handle_text`; on disconnect remove the session and port, `set_online(False)`, `await port.stop("lost")`. `handle_text` builds `utterance(client_id, device.room, text)` and runs the pipeline under `TURN_LOCK` between `turn_start` and `turn_end`, sending an error frame on exception. `SessionOutput.say` speaks per sentence via `SentenceChunker` when the session has `audio_out` and `runtime.tts`, else sends text frames; `ack` plays `runtime.acks.pick(category)` on the port when available.
3. Delete `MusicStream`, `_pump_music`, `_maybe_start_music`, and the routine/agent turn code from `server.py`.
**New symbols:** I17 symbols.
**Verify:** `cd harness && .venv/bin/python -m pytest -q` — expected: all pass, including `test_scheduler.py` and `test_server.py`.
**Forbidden:** no model loading or network at import of `cadence.server` or `cadence.wiring`; do not edit `scheduler.py`, `routines.py`, `agent.py`, `store.py`; no new deps.
**Depends:** Task 19, Task 14, Task 16
**Why:** The v1 entry point; `python -m cadence` now runs the pipeline.

### Task 21: Build the acknowledgement clip pool
- [ ] status
**Objective:** `harness/scripts/build_ack_pool.py` writes pre-rendered clips per category into `harness/acks/`.
**Write-scope:**
- `harness/scripts/build_ack_pool.py` (new)
**Read-context:** `docs/plans/2026-10-01-cadence-decision-harness-v1.md:529-537` (I16 acks); `harness/cadence/llm.py:1-34`; `harness/cadence/audio/tts.py:57-63`.
**Anchors:**
- `async def chat(self, messages: list[dict], tools: list[dict], think: bool) -> dict:` @ `harness/cadence/llm.py`
- `def speak(self, text: str) -> bytes:` @ `harness/cadence/audio/tts.py`
- `ACK_CATEGORIES = ("action", "chat", "correction")` @ `harness/cadence/acks.py` (from Task 18)
**Steps:**
1. CLI: `--out` (default `acks`), `--per-category` (default 20).
2. Per category, one `OllamaLLM().chat([...], tools=[], think=True)` with user prompt: `f"Write {n} different short spoken acknowledgements a home speaker says {situation}. 1 to 4 words each, casual, no emojis. Answer with a JSON array of strings only."` Situations: action `"right after being asked to do something like play music or pause"`; chat `"right before answering a question or chatting"`; correction `"right after the user says it got something wrong"`.
3. Parse the text between the first `[` and the last `]` as JSON; dedupe case-insensitively; keep the first `n`.
4. `Tts().speak(phrase)` → write `<out>/<category>/<NN>.pcm` (two-digit index); write `<out>/phrases.json` `{category: [phrases]}`.
5. Run `cd harness && .venv/bin/python scripts/build_ack_pool.py --per-category 3`.
**New symbols:** none
**Verify:** `cd harness && .venv/bin/python -c "from cadence.acks import AckPool; p = AckPool('acks'); print([p.count(c) for c in ('action','chat','correction')])"` — expected: three counts, each between 1 and 3.
**Forbidden:** no edits under `harness/cadence/`; no new deps; do not commit `harness/acks/` (gitignored).
**Depends:** Task 2, Task 18
**Why:** Clips play the instant Jev routes, masking LLM and Muse latency.

## Phase 6 — Live validation and docs

### Task 22: Replay the golden set against live Jev and calibrate [experiment]
- [ ] status
**Objective:** A recorded table of Jev route accuracy, closed-arg accuracy, confidence distribution, and latency on the v1 catalogue, with a recommended `CONF_MIN` and `JEV_CLOSED_ARGS`.
**Write-scope:**
- `harness/scripts/golden_replay.py` (new)
- `docs/preflight/jev-v1-golden.md` (new)
- `docs/research/data/jev_v1_golden.json` (new)
**Read-context:** `harness/tests/golden/utterances.json` (schema in its `about` field); `docs/plans/2026-10-01-cadence-decision-harness-v1.md:275-305` (I8).
**Anchors:**
- `class JevDecider(Decider):` @ `harness/cadence/deciders/jev.py` (from Task 8)
- `class MusicPlugin(Plugin):` @ `harness/cadence/plugins/music.py` (from Task 14)
- `class SpeakerPlugin(Plugin):` @ `harness/cadence/plugins/speaker.py` (from Task 16)
**Steps:**
1. Build `Catalogue([MusicPlugin(<any client>), SpeakerPlugin()]).available()` and `JevDecider(load_api_key())`; context `{"time": "22:30", "weekday": "Tuesday", "room": "bedroom", "now_playing": {"track_name": "Weightless", "artist_name": "Marconi Union", "paused": False}, "recent": []}`.
2. One pass over all 60 items, sequential; per item record route, confidence, probabilities, closed args, latency ms. Stop on the first `DeciderUnavailable` and record how far it got.
3. Score: route correct if in `routes`; args scored only when the predicted route equals `routes[0]` and `args` is non-empty. Report overall route accuracy, per-route accuracy, arg accuracy, p50/p95 latency, and route accuracy of items with confidence ≥ each of 0.3/0.5/0.7/0.9 plus the share escalated at each.
4. Write raw records to `docs/research/data/jev_v1_golden.json` and the tables plus a one-paragraph recommendation for `CONF_MIN` and `JEV_CLOSED_ARGS` to `docs/preflight/jev-v1-golden.md`.
**New symbols:** none
**Verify:** `test -s docs/preflight/jev-v1-golden.md && python3 -c "import json; d=json.load(open('docs/research/data/jev_v1_golden.json')); print(len(d['records']))"` — expected: records the count reached (60 if no stop). Negative result is a valid outcome.
**Forbidden:** do not change `config.py` (the user decides from the recommendation); no key in outputs; no retries.
**Depends:** Task 2, Task 8, Task 14, Task 16
**Why:** Sets the escalation threshold and the closed-arg switch from evidence, as the spec requires.

### Task 23: Smoke the full turn path against live services [experiment]
- [ ] status
**Objective:** A recorded transcript of five live turns through the running harness with Jev, the LLM, Muse, and the proxy, plus the resulting decision-log rows.
**Write-scope:**
- `harness/scripts/smoke_session.py` (new)
- `docs/preflight/e2e-v1.md` (new)
**Read-context:** `docs/plans/2026-10-01-cadence-decision-harness-v1.md:593-600` (protocol); `harness/cadence/decisionlog.py` (from Task 6).
**Anchors:**
- `def build_runtime() -> Runtime` @ `harness/cadence/wiring.py` (from Task 20)
- `def export(self) -> list[dict]` @ `harness/cadence/decisionlog.py` (from Task 6)
**Steps:**
1. Start the proxy: `CADENCE_MUSE_BASE_URL=http://100.122.149.75:8080 python3 tools/muse_proxy.py &`.
2. Start the harness from `harness/`: `CADENCE_MUSE_BASE_URL=http://100.122.149.75:8080 CADENCE_MUSE_PROXY_URL=http://127.0.0.1:8765 CADENCE_WAKE_ENABLED=0 .venv/bin/python -m cadence &`.
3. `smoke_session.py` connects to `ws://127.0.0.1:8768/session` with hello `{"client_id": "speaker-1", "caps": ["text_in", "audio_out"]}` and sends, waiting for `turn_end` each time: `"play something chill"`, `"what's playing"`, `"pause the music"`, `"tell me a joke"`, `"no, I meant something upbeat"`. Per turn record wall time and audio bytes received.
4. Read `DecisionLog("cadence.sqlite3").export()[-5:]` and record route, decider, escalation, calls, outcome, latency, labels.
5. Write both tables to `docs/preflight/e2e-v1.md`; stop both background processes.
**New symbols:** none
**Verify:** `test -s docs/preflight/e2e-v1.md` — expected: the doc exists; record each turn's outcome. Negative result is a valid outcome.
**Forbidden:** no edits under `harness/cadence/`; no key in outputs; leave no background process running.
**Depends:** Task 20, Task 21
**Why:** The only check that every piece works together with real services.

### Task 24: Document v1 setup and architecture [docs]
- [ ] status
**Objective:** `harness/README.md` and the repo `CLAUDE.md` describe the v1 harness accurately.
**Write-scope:**
- `harness/README.md`
- `CLAUDE.md`
**Read-context:** `docs/specs/2026-10-01-cadence-decision-harness-v1.md:24-72`; `docs/plans/2026-10-01-cadence-decision-harness-v1.md:81-110` (constants and env vars); `harness/README.md`; `CLAUDE.md:1-40`.
**Anchors:** `def build_runtime() -> Runtime` @ `harness/cadence/wiring.py` (from Task 20)
**Steps:**
1. README audience: the user setting up the harness on `ianshomeserver`. Cover: venv install including `pip install --no-deps -r requirements-nodeps.txt` and why; Kokoro download; the TypeSafe key file location (never commit it); env vars `CADENCE_MUSE_BASE_URL`, `CADENCE_MUSE_PROXY_URL`, `CADENCE_DEVICES_PATH`, `CADENCE_WAKE_ENABLED`; `devices.json`; `scripts/build_ack_pool.py`; running `muse_proxy.py` and `python -m cadence`; the wake phrase "hey jarvis"; where decisions are logged (`decision_log`, `decision_labels` in `cadence.sqlite3`).
2. CLAUDE.md: replace the stale three-project framing with a `harness/` section describing the event pipeline, deciders, plugins, decision log, and pointers to the v1 spec and plan; keep the ESP-IDF sections.
**New symbols:** none
**Verify:** `grep -c "requirements-nodeps" harness/README.md && grep -c "decision_log" CLAUDE.md` — expected: each prints at least 1.
**Forbidden:** no claims not backed by the code or the spec; never include the key or the WiFi password.
**Depends:** Task 20
**Why:** CLAUDE.md is stale since M1; the next session should not rediscover the architecture.
