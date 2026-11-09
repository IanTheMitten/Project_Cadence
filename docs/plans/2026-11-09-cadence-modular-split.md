# Plan - Cadence modular split, step 1 (core over /peer, speaker + Muse adapters, voice schedules)

Spec: `docs/specs/2026-11-09-cadence-modular-split.md` (status "ready for planning", spec-lint exit 0).
Scope: spec step 1 only (split in place into `harness/`, `speaker/`, `muse_adapter/`). Step 2 (new repos,
GitHub rename) is a Deferred open question (`docs/specs/2026-11-09-cadence-modular-split.md:230`) and needs
user confirmation at that time; not in this plan.

Test commands (shared venv, per spec `docs/specs/2026-11-09-cadence-modular-split.md:75`):
- harness: `cd harness && .venv/bin/python -m pytest -q`
- speaker: `cd speaker && ../harness/.venv/bin/python -m pytest -q`
- muse: `cd muse_adapter && ../harness/.venv/bin/python -m pytest -q`

## Assumptions (decided here; spec gaps or `Deferred:` items)

- A1 (Deferred item `:232`): adapters use `websockets` 17.1, `from websockets.asyncio.client import connect`. Already installed; no new deps.
- A2 (Deferred item `:231`): golden schedule items are fixed in Task 17. `schedule.add`/`schedule.cancel` have free args, so Jev always returns `escalation="needs_args"` and the LLM fills args (`harness/cadence/deciders/jev.py:96`). The golden run measures routing only.
- A3 Media hop: a service peer sends a standalone `media {device, action, url?}` message at any time (Cadence forwards it and records the service as that device's media owner). This replaces `result.media` from the spec table, because track advance and pause timeout happen outside any call. `media_event` carries `event` (not `type`, which is the message key), `position_ms`, `url`.
- A4 Muse `state` message body: `{"type": "state", "state": {"now_playing": {<device_id>: {track_name, artist_name, paused} | null}}}`.
- A5 A hello whose `peer_id` is already connected is rejected (`error "peer_id in use"`, close); adapters retry every 2 s. Two peers declaring the same ability name: second rejected (multi-speaker is out of scope, spec `:220`).
- A6 Turn timing: the speaker sends `timing` as `{stage: age_ms}` (ms between the stamp and the send); Cadence marks `at = time.monotonic() - age_ms/1000`, prints the `turn_timing` line and merges durations into `latency_ms`. `first_audio` happens in the speaker, which prints its own `speaker_timing {json}` line.
- A7 Pending question: listen window 8 s, Cadence TTL 12 s (8 s + ASR grace). Answers are logged with decider `"pending"`, route `"schedule_conflict"`.
- A8 Copy-then-delete: Phase 3 copies modules into the adapters; Phase 4 deletes the harness originals, so every phase gate stays green. `turntiming.py` is copied (harness pipeline still uses it). `link.py` is shared by copy.
- A9 `Plugin.call`'s 4th parameter becomes `event: Event` (was `port`); `Executor` loses `ports`. `AudioPort` is deleted.
- A10 A schedule's room defaults to the source device's room. Greeting text by local hour: "Good morning." (<12), "Good afternoon." (<18), "Good evening.".
- A11 Speaker `/session` drops text-frame turns; text clients (`smoke_session.py`) use `/peer` as a `kind "text"` device.
- A12 `harness/scripts/preflight_v1.py` and `preflight_runtime.py` stay as historical one-shot scripts, not ported.
- A13 `harness/acks/` is gitignored (`harness/.gitignore`), so Task 9 copies it on disk only; `speaker/.gitignore` ignores `acks/` too.

## Premises

- Baseline 230 harness tests pass — verified: `cd harness && .venv/bin/python -m pytest -q` (230 passed).
- `websockets` 17.1 client talks to a FastAPI WebSocket served by uvicorn — verified: probe script ran `connect("ws://127.0.0.1:18770/peer")` against `@app.websocket("/peer")`, got `{"type": "welcome", ...}`.
- Live harness is running on this host (`ianshomeserver`) port 8768 — verified: `ss -ltnp | grep 8768` (pid 3328018). Executors must not stop it or bind 8768/8770.
- `TURN_LOCK` lives in `harness/cadence/server.py:31`; only `scheduler.py:12` and `tests/test_scheduler.py:9` import it.
- `Executor` passes a port as the 4th plugin arg — `harness/cadence/executor.py:37`; `ports` ctor param at `executor.py:15`.
- Correction lookup is by source only — `harness/cadence/pipeline.py:79` calls `last_for_source` (`decisionlog.py:126`); `decision_log` already has a `room` column (`decisionlog.py:248`).
- `Catalogue` is fixed at construction and raises on duplicates — `harness/cadence/catalogue.py:12-22`, pinned by `tests/test_core.py:109`.
- `DeviceRegistry.set_online(device_id, online, kind="speaker")` creates unknown devices with room None — `harness/cadence/plugins/registry.py:31-37`.
- `MusicPlugin` drives an `AudioPort` (`play_url(url, on_end)`, `pause`, `resume`, `stop`, `position_ms`, `is_paused`) — `harness/cadence/plugins/music.py:155-175`, `plugins/base.py:35-40`.
- `SpeakerPort.play_url` stops the old stream first, firing `on_end("stopped")` — `harness/cadence/plugins/speaker.py:77-79,126-136`.
- `tts.py` finds Kokoro at `parents[3]/tools` — `harness/cadence/audio/tts.py:11`; same depth under `speaker/cadence_speaker/audio/`.
- Audio modules import config only for `LISTEN_WINDOW_S` (`audio/listener.py:8`), `WAKE_MODEL, WAKE_THRESHOLD` (`audio/wakeword.py:7`); `speaker.py:11` uses `VOLUME_STEP`; `tests/test_benchrec.py:63` reloads `cadence.config` for `BENCH_RECORD_DIR`.
- `golden_replay.py:21-22,41` builds its catalogue from `MusicPlugin`/`SpeakerPlugin`; outputs `docs/preflight/jev-v1-golden.md` and `docs/research/data/jev_v1_golden.json` (both exist).
- `smoke_session.py:19` targets `ws://127.0.0.1:8768/session` with text frames.
- pytest config: `harness/pyproject.toml` has `asyncio_mode = "auto"`, `testpaths = ["tests"]`; `tests/__init__.py` exists so `tests.test_pipeline` fakes are importable.
- Epoch `1799971200` is 2027-01-15 00:00:00 UTC — verified: `time.gmtime(1799971200)` with `TZ=UTC`.

## Phase 1 - Harness primitives

### Task 1: Add the shared device-protocol module to harness
- [x] status
**Objective:** `harness/cadence/protocol.py` defines protocol v1 helpers, tested.
**Write-scope:** `harness/cadence/protocol.py` (new)
`harness/tests/test_protocol.py` (new)
**Read-context:** `docs/specs/2026-11-09-cadence-modular-split.md:179-194`
**Anchors:** none
**Steps:** 1. Create `protocol.py`: module docstring "Cadence device protocol v1 (/peer, JSON text frames). Copied verbatim into each peer package; a hello with another PROTOCOL_VERSION is rejected." `import json`; `PROTOCOL_VERSION = 1`; `ROLES = ("device", "service")`.
2. `encode(msg)` returns `json.dumps(msg)`. `decode(text)` does `json.loads`; raises `ValueError("message must be a JSON object with a string 'type'")` unless result is a dict whose `"type"` is a str.
3. `hello(...)` returns `{"type": "hello", "version": PROTOCOL_VERSION, "peer_id", "role", "kind", "room", "caps": list(caps), "abilities": list(abilities)}`.
4. `check_hello(msg)` returns `msg` or raises `ValueError` in this order: type != "hello" (`f"expected hello, got {msg.get('type')!r}"`); version != PROTOCOL_VERSION (`f"protocol version {msg.get('version')!r} != {PROTOCOL_VERSION}"`); `peer_id` not a non-empty str; `role` not in ROLES; `kind` not a str; `room` not None/str; `caps` (default []) not a list of str; `abilities` (default []) not a list of dicts each containing keys `name`, `description`, `parameters`.
5. Tests: encode/decode round trip; decode rejects `"[1]"`, `'{"a":1}'`, `"not json"` (all ValueError); `hello(...)` output passes `check_hello`; version 2 raises with "protocol version" in message; bad role raises; ability missing `parameters` raises; room None accepted.
**New symbols:** `PROTOCOL_VERSION: int = 1`, `ROLES: tuple[str, str]`, `def encode(msg: dict) -> str`, `def decode(text: str) -> dict`, `def hello(peer_id: str, role: str, kind: str, room: str | None, caps: list[str], abilities: list[dict]) -> dict`, `def check_hello(msg: dict) -> dict`
**Verify:** `cd harness && .venv/bin/python -m pytest -q tests/test_protocol.py` — expected: all pass; full suite still passes.
**Forbidden:** no imports beyond `json`; no other files.
**Depends:** none
**Why:** Three packages must agree on message shapes; this file is copied byte-for-byte into the adapters (Tasks 9, 12).

### Task 2: Pass the event to plugins, make the catalogue dynamic, look back corrections by room
- [x] status
**Objective:** `Plugin.call` gets the `Event`, `Catalogue` supports `add`/`remove`, the registry takes a room, and corrections find the last decision by source or room.
**Write-scope:** `harness/cadence/plugins/base.py`
`harness/cadence/executor.py`
`harness/cadence/plugins/mcp_adapter.py`
`harness/cadence/catalogue.py`
`harness/cadence/plugins/registry.py`
`harness/cadence/decisionlog.py`
`harness/cadence/pipeline.py`
`harness/cadence/wiring.py`
`harness/tests/test_core.py`
`harness/tests/test_pipeline.py`
`harness/tests/test_decisionlog.py`
`harness/tests/test_server.py`
**Read-context:** `harness/cadence/plugins/base.py:35-55`, `harness/cadence/executor.py:13-44`, `harness/cadence/catalogue.py:12-36`, `harness/cadence/plugins/registry.py:31-37`, `harness/cadence/decisionlog.py:126-131`, `harness/cadence/pipeline.py:79`, `harness/tests/test_decisionlog.py:95-102`
**Anchors:** `async def call(self, capability: str, args: dict, target: Device | None,` @ `harness/cadence/plugins/base.py`
`def last_for_source(self, source: str, since: float) -> dict | None:` @ `harness/cadence/decisionlog.py`
`def set_online(self, device_id: str, online: bool, kind: str = "speaker") -> Device:` @ `harness/cadence/plugins/registry.py`
**Steps:** 1. `base.py`: delete `AudioPort` and now-unused typing imports; `from cadence.events import Event`; abstract `call(self, capability: str, args: dict, target: Device | None, event: Event) -> Result`.
2. `executor.py`: ctor `(self, catalogue, registry, *, max_calls=MAX_TOOL_CALLS)`, drop `_ports` and the `AudioPort`/`Callable` imports; call `await plugin.call(cap.name, call.args, t, event)`. `mcp_adapter.py`: rename param `port` to `event`.
3. `catalogue.py`: `add(plugin)` raises `ValueError(f"duplicate capability name: {c.name}")` if any of its names is already registered (builtins included), else appends and registers; `remove(plugin)` removes it (by identity) and its names, no-op if absent.
4. `registry.py`: `set_online(self, device_id, online, kind="speaker", room=None)`; new device uses `room`; existing device gets `dev.room = room` when room is not None.
5. `decisionlog.py`: replace `last_for_source` with `last_for_device_or_room(source, room, since)`: `WHERE (source = ? OR (? IS NOT NULL AND room = ?)) AND at >= ? ORDER BY at DESC, id DESC LIMIT 1`, params `(source, room, room, since)`. Line 33 comment: `server.TURN_LOCK` -> `core.TURN_LOCK`. `pipeline.py:79`: `self._log.last_for_device_or_room(event.source, event.room, self._clock() - self._window)`.
6. `wiring.py`: `Executor(catalogue, registry)`. Tests: drop the `lambda i: None` arg at `test_pipeline.py:74,90` and `test_server.py:34`.
7. `test_decisionlog.py`: rename test to `test_last_for_device_or_room`; cases: source match; other source same room found (`utterance("scheduler", "bedroom", ...)` found by `("speaker-1", "bedroom", ...)`); room None matches only by source; `since` filter. `test_core.py`: add `test_catalogue_add_remove` (add then `get`/`available` include it; duplicate add raises; remove drops names; removing an absent plugin is a no-op) and `test_set_online_sets_room`.
**New symbols:** `Catalogue.add(self, plugin: Plugin) -> None`, `Catalogue.remove(self, plugin: Plugin) -> None`, `DecisionLog.last_for_device_or_room(self, source: str, room: str | None, since: float) -> dict | None`, `DeviceRegistry.set_online(self, device_id: str, online: bool, kind: str = "speaker", room: str | None = None) -> Device`
**Verify:** `cd harness && .venv/bin/python -m pytest -q` — expected: all pass (230 + new).
**Forbidden:** no edits to `plugins/speaker.py`, `plugins/music.py`, `server.py` (they are replaced later; their direct-call tests still pass); no new deps.
**Depends:** none
**Why:** Network peers have no in-process port; local plugins (schedules) need the event's source and room. The live runtime's old speaker/music plugins stop working here and are replaced in Phase 4.

### Task 3: Write schedule tests (red) [test]
- [x] status
**Objective:** `harness/tests/test_schedules.py` pins the schedule store, clash rule, yes/no parser, pending questions and `SchedulePlugin`, failing on import.
**Write-scope:** `harness/tests/test_schedules.py` (new)
**Read-context:** `docs/specs/2026-11-09-cadence-modular-split.md:142-161`, `harness/tests/test_pipeline.py:1-80`
**Anchors:** `def utterance(source: str, room: str | None, text: str, *, asr_conf: float | None = None,` @ `harness/cadence/events.py`
**Steps:** 1. Autouse fixture: `monkeypatch.setenv("TZ", "UTC"); time.tzset()`, after yield `monkeypatch.undo(); time.tzset()`. `D0 = 1799971200.0` (2027-01-15 00:00 UTC); `H = 3600.0`.
2. `parse_hhmm`: "07:00"->"07:00", "7:05"->"07:05", "23:59"->"23:59"; "24:00", "7", None, "ab:cd" -> None.
3. `next_occurrence("07:00", D0+6*H) == D0+7*H`; at exactly `D0+7*H` -> `D0+7*H+86400`; at `D0+8*H` -> `D0+86400+7*H`.
4. `ScheduleStore(str(tmp_path/"s.db"))`: `add("07:00","once",True,"play jazz","bedroom",now=D0+6*H)` returns `Schedule` with `next_at == D0+7*H`; `due(D0+6*H) == []`; `due(D0+7*H)` ids == [id]; `advance` on daily at `D0+7*H+10` sets next_at `D0+86400+7*H`; `advance` on once deletes; `at_time("07:00")`; `delete([id])`.
5. `conflicts`: daily 07:00 vs ("07:10","once") clash, ("07:16","once") none; daily 23:55 vs ("00:05","once") clash; once 07:00 added at `D0+8*H` (next_at tomorrow) vs ("07:05","once") at now `D0+6*H` none.
6. `classify_yes_no`: "yes"->"yes", "Yeah, delete it."->"yes", "no"->"no", "no, don't delete it"->"no", "keep the old one"->"no", "what time is it"->None, ""->None.
7. `PendingQuestions`: `ask(q)`/`peek("speaker-1") is q`; `take` before `expires_at` returns q and clears; `take` after returns None and clears; `drop(q)` True then False.
8. `SchedulePlugin(store, pending, clock=lambda: D0+6*H)`, event `utterance("speaker-1","bedroom","x")`: add `{"time":"07:00","repeat":"daily","greeting":True,"command":"play jazz"}` -> ok, say `"Okay, 07:00 every day."`, row room "bedroom"; `"time":"7"` -> ok False, error "bad_time", say "I didn't catch the time."; greeting False and no command -> error "empty"; greeting `"true"` string accepted; clash -> ok True, `data == {"pending": "schedule_conflict"}`, say `"You already have a schedule at 07:00. Should I delete it and save this one?"`, `pending.peek("speaker-1").clash_ids == [old.id]`, `.new == {"time_":"07:05","repeat":"once","greeting":True,"command":None,"room":"bedroom"}`, store still 1 row; cancel existing -> say "Cancelled the 07:00 schedule."; cancel missing -> ok False, error "not_found", say "There's no schedule at 08:00.".
9. Manifest names `("schedule.add","schedule.cancel")`; `SCHEDULE_ADD.closed_args.keys() == {"repeat","greeting"}`; `SCHEDULE_ADD.free_args == ("time","command","room")`.
**New symbols:** none (tests target Task 4's symbols, copied: `parse_hhmm`, `next_occurrence`, `clashes`, `Schedule`, `ScheduleStore`, `PendingQuestion(kind, device_id, new, clash_ids, expires_at)`, `PendingQuestions`, `classify_yes_no`, `SchedulePlugin`, `SCHEDULE_ADD`, `SCHEDULE_CANCEL` from `cadence.schedules`)
**Verify:** `cd harness && .venv/bin/python -m pytest -q tests/test_schedules.py` — expected: 1 collection error, `ModuleNotFoundError: No module named 'cadence.schedules'`.
**Forbidden:** test file only; no source edits.
**Depends:** none
**Why:** Pins clash window, says and pending shape before implementation (spec `:156-161`).

### Task 4: Implement schedules, pending questions and the schedule plugin
- [x] status
**Objective:** `harness/cadence/schedules.py` makes `tests/test_schedules.py` green.
**Write-scope:** `harness/cadence/schedules.py` (new)
**Read-context:** `harness/tests/test_schedules.py` (from Task 3), `harness/cadence/plugins/base.py:10-55`, `harness/cadence/decisionlog.py:30-45`
**Anchors:** `class Capability:` @ `harness/cadence/plugins/base.py`
`class Catalogue:` @ `harness/cadence/catalogue.py`
`Catalogue.add(self, plugin: Plugin) -> None` @ `harness/cadence/catalogue.py` (from Task 2)
**Steps:** 1. Constants: `LISTEN_S = 8`, `QUESTION_TTL_S = 12.0`, `CLASH_WINDOW_MIN = 15`, `BAD_TIME_SAY = "I didn't catch the time."`, `EMPTY_SAY = "What should I do at that time?"`.
2. `SCHEDULE_ADD = Capability("schedule.add", "Set a wake-up or timed routine: a time, once or every day, an optional greeting, then an optional spoken command (e.g. 'wake me up at 7 and play jazz').", {"type":"object","properties":{"time":{"type":"string","description":"24-hour HH:MM"},"repeat":{"type":"string","enum":["once","daily"]},"greeting":{"type":"boolean"},"command":{"type":"string","description":"what to do then, in the user's words, e.g. 'play jazz'; omit if nothing"},"room":{"type":"string"}},"required":["time","repeat","greeting"]}, closed_args={"repeat":{"once":"just once","daily":"every day"},"greeting":{"true":"wake-up or greeting wanted","false":"no greeting"}}, free_args=("time","command","room"))`. `SCHEDULE_CANCEL = Capability("schedule.cancel", "Cancel or delete a scheduled wake-up or routine at a given time.", {"type":"object","properties":{"time":{"type":"string","description":"24-hour HH:MM"}},"required":["time"]}, free_args=("time",))`.
3. `parse_hhmm`: regex `^(\d{1,2}):(\d{2})$`, hour<24, minute<60, returns `f"{h:02d}:{m:02d}"`; non-str -> None. `next_occurrence`: `time.localtime(now)` fields, `time.mktime((y,mo,d,h,m,0,0,0,-1))`; if `<= now`, same with `d+1`.
4. `clashes(time_, repeat, next_at, other)`: minute-of-day circular diff `min(d, 1440-d) <= CLASH_WINDOW_MIN` and (`repeat == "daily"` or `other.repeat == "daily"` or `abs(next_at - other.next_at) <= CLASH_WINDOW_MIN*60`).
5. `ScheduleStore(path)`: `sqlite3.connect(path, check_same_thread=False)`; `CREATE TABLE IF NOT EXISTS schedules (id INTEGER PRIMARY KEY, time TEXT NOT NULL, repeat TEXT NOT NULL, greeting INTEGER NOT NULL, command TEXT, room TEXT, next_at REAL NOT NULL)`. `add` stores `next_occurrence(time_, now)`; `due(now)` rows with `next_at <= now` ordered by next_at; `advance(id, now)`: daily -> `next_occurrence(time, now)`, once -> delete; `conflicts(time_, repeat, now)` = `[s for s in get_all() if clashes(time_, repeat, next_occurrence(time_, now), s)]`. Commit after each write.
6. `PendingQuestion` dataclass; `PendingQuestions` keyed by `device_id`: `take` pops and returns None if `now >= expires_at`; `drop(q)` removes only if the stored object `is q`.
7. `classify_yes_no`: tokens `re.findall(r"[a-z']+", text.lower())`; any in `{"no","nope","nah","don't","dont","keep","cancel"}` -> "no"; elif any in `{"yes","yeah","yep","yup","sure","ok","okay","delete","replace"}` -> "yes"; else None.
8. `SchedulePlugin.call(capability, args, target, event)`: add -> `t = parse_hhmm(args.get("time"))` (None -> `Result(False, say=BAD_TIME_SAY, error="bad_time")`); repeat defaults "once" unless in ("once","daily"); `greeting = args.get("greeting") in (True, "true")`; command stripped or None; room `args.get("room") or event.room`; no greeting and no command -> `Result(False, say=EMPTY_SAY, error="empty")`; clash -> `pending.ask(PendingQuestion("schedule_conflict", event.source, {"time_":t,"repeat":..,"greeting":..,"command":..,"room":..}, [ids], now + QUESTION_TTL_S))`, say per Task 3 (times `", ".join(sorted({c.time ...}))`); else add, say `f"Okay, {t} {'every day' if repeat == 'daily' else 'once'}."`, `data={"id": s.id}`. cancel -> bad time as above; none at time -> `Result(False, say=f"There's no schedule at {t}.", error="not_found")`; else delete all at time, `Result(True, say=f"Cancelled the {t} schedule.")`.
**New symbols:** constants above; `SCHEDULE_ADD`, `SCHEDULE_CANCEL`; `@dataclass class Schedule(id: int, time: str, repeat: str, greeting: bool, command: str | None, room: str | None, next_at: float)`; `def parse_hhmm(value) -> str | None`; `def next_occurrence(hhmm: str, now: float) -> float`; `def clashes(time_: str, repeat: str, next_at: float, other: Schedule) -> bool`; `class ScheduleStore(path: str)` with `add(time_, repeat, greeting, command, room, now) -> Schedule`, `get_all() -> list[Schedule]`, `at_time(hhmm) -> list[Schedule]`, `due(now) -> list[Schedule]`, `advance(schedule_id: int, now: float) -> None`, `delete(ids: list[int]) -> None`, `conflicts(time_, repeat, now) -> list[Schedule]`; `@dataclass class PendingQuestion(kind: str, device_id: str, new: dict, clash_ids: list[int], expires_at: float)`; `class PendingQuestions` with `ask(q) -> None`, `peek(device_id) -> PendingQuestion | None`, `take(device_id, now) -> PendingQuestion | None`, `drop(q) -> bool`; `def classify_yes_no(text: str) -> str | None`; `class SchedulePlugin(Plugin)` with `manifest = Manifest("schedule", "service", (SCHEDULE_ADD, SCHEDULE_CANCEL))`, `__init__(self, store, pending, *, clock=time.time)`
**Verify:** `cd harness && .venv/bin/python -m pytest -q` — expected: all pass incl. `tests/test_schedules.py`.
**Forbidden:** don't edit `tests/test_schedules.py` (committed test wins; mismatch = report); don't touch `scheduler.py`/`store.py`/`routines.py`; no new deps.
**Depends:** Task 2, Task 3
**Why:** Spec decision "save the words, decide at fire time" (`:149-154`) and the conflict prompt (`:156-161`).

## Phase 2 - Core and /peer hub

### Task 5: Write Core tests (red) [test]
- [x] status
**Objective:** `harness/tests/test_core_submit.py` pins `Core.submit`, `announce`, pending answers and the schedule tick, failing on import.
**Write-scope:** `harness/tests/test_core_submit.py` (new)
**Read-context:** `harness/cadence/schedules.py` (from Task 4), `harness/cadence/turntiming.py:18-43`, `harness/cadence/decisionlog.py:65-98`
**Anchors:** `class TurnTimer:` @ `harness/cadence/turntiming.py`
`class ScheduleStore` @ `harness/cadence/schedules.py` (from Task 4)
**Steps:** 1. TZ=UTC autouse fixture as in Task 3; `D0 = 1799971200.0`, `H = 3600.0`; clock = mutable `now = [D0+7*H]`, `clock=lambda: now[0]`.
2. `FakeHub`: `connected: dict[str, str | None]` (peer_id -> room), `sent: list[tuple[str, dict]]`; `async send(peer_id, msg)` appends and returns True if connected else False; `targets(target)`: `[target]` if target in connected, else ids whose room == target, or all if target is None.
3. `FakePipeline`: records `(event, timer)`; `handle(event, out, timer=None)` does `await out.ack("action")`, `await out.say(self.reply)` (default "done"), then `await self.hook(event)` if set; `raises` option.
4. Build `Core(pipeline, hub, DecisionLog(tmp/"l.db"), ScheduleStore(tmp/"l.db"), PendingQuestions(), clock=clock, question_ttl_s=0.05)`.
5. Cases: (a) submit from "speaker-1" sends in order `turn_start`, `{"type":"ack","category":"action"}`, `{"type":"say","text":"done"}`, `turn_end`; (b) pipeline raises -> `turn_start`, `{"type":"error","message":...}`, `turn_end`; (c) while `TURN_LOCK` held, a submit task has not called the pipeline; after release it has; (d) `timing={"speech_end":500.0,"asr_done":100.0}` -> recorded timer `durations()["asr"]` between 350 and 450, stderr has a `turn_timing ` line; (e) hook calls `pending.ask(...)` -> `{"type":"listen","seconds":8}` sent after the say and before `turn_end`; (f) seeded clash row + pending question, submit "yes" -> pipeline not called, clash row gone, new row added, say `"Done, I replaced it."`, decision log row `decider == "pending"`, `route == "schedule_conflict"`; (g) "no" -> old kept, no new, say `"Okay, I kept your old schedule."`; (h) "what?" -> say `"I'll leave your schedules as they are."`, store unchanged, pending cleared; (i) question asked via hook, await `asyncio.sleep(0.2)` -> LEAVE say sent to speaker-1, `pending.peek` None.
6. `announce`: device id -> that peer only; room "bedroom" -> bedroom peers; None -> all; nobody connected -> returns 0; return value = peers sent.
7. `tick`: daily 07:00 greeting+`"play jazz"` in "bedroom" due at `now=D0+7*H` -> `{"type":"say","text":"Good morning."}` to bedroom peers, pipeline event `kind == "schedule"`, `source == "scheduler"`, `room == "bedroom"`, `payload == {"text":"play jazz","schedule_id":id}`, next_at +86400, returns `[id]`; once -> deleted; due 301 s late -> not fired, stderr contains "missed", once deleted; pipeline raises -> greeting still sent, schedule still advanced; pipeline `say` during a schedule event goes to bedroom peers, no `ack` sent.
**New symbols:** none (tests target Task 6: `from cadence.core import Core, TURN_LOCK, LEAVE_SAY, REPLACED_SAY, KEPT_SAY, greeting_for`)
**Verify:** `cd harness && .venv/bin/python -m pytest -q tests/test_core_submit.py` — expected: 1 collection error, `ModuleNotFoundError: No module named 'cadence.core'`.
**Forbidden:** test file only.
**Depends:** Task 4
**Why:** Core is the single entry point (spec `:51-56`, `:128-140`, `:196-198`).

### Task 6: Implement Core
- [x] status
**Objective:** `harness/cadence/core.py` makes `tests/test_core_submit.py` green.
**Write-scope:** `harness/cadence/core.py` (new)
**Read-context:** `harness/tests/test_core_submit.py` (from Task 5), `harness/cadence/server.py:211-229`, `harness/cadence/pipeline.py:30-52`, `harness/cadence/events.py:1-30`
**Anchors:** `async def handle(self, event: Event, out: TurnOutput, timer: TurnTimer | None = None) -> Decision:` @ `harness/cadence/pipeline.py`
`class PendingQuestions` @ `harness/cadence/schedules.py` (from Task 4)
**Steps:** 1. `TURN_LOCK = asyncio.Lock()`; constants `REPLACED_SAY = "Done, I replaced it."`, `KEPT_SAY = "Okay, I kept your old schedule."`, `LEAVE_SAY = "I'll leave your schedules as they are."`, `MISSED_GRACE_S = 300.0`, `TICK_S = 30.0`, `SCHEDULER_SOURCE = "scheduler"`. `greeting_for(now)`: local hour <12 "Good morning.", <18 "Good afternoon.", else "Good evening.".
2. `Hub(Protocol)`: `async send(peer_id, msg) -> bool`; `targets(target) -> list[str]`. `PeerOutput(hub, peer_id)`: ack sends `{"type":"ack","category":c}`, say sends `{"type":"say","text":t}`. `RoomOutput(core, room)`: ack no-op, say -> `core.announce(room, t)`.
3. `submit(event, timing=None)`: send `turn_start` to `event.source`; `TurnTimer()`; for each `stage, age_ms` in timing with stage in `STAGES`: `mark(stage, at=time.monotonic() - age_ms/1000)`; mark `turn_start`; `async with TURN_LOCK`: `q = pending.take(src, clock())`; if q: `_answer(q, event)`; else `pipeline.handle(event, PeerOutput(hub, src), timer=timer)`, then if `pending.peek(src)` is not None: send `{"type":"listen","seconds":LISTEN_S}` and `asyncio.create_task(self._expire(pending.peek(src)))`. Any `Exception` -> send `{"type":"error","message":str(exc)}`. Then mark `turn_end`, print `timer.log_line(src)` to stderr, send `turn_end`.
4. `_answer(q, event)`: `classify_yes_no(text)`; yes -> `schedules.delete(q.clash_ids)`, `schedules.add(**q.new, now=clock())`, REPLACED_SAY; no -> KEPT_SAY; else LEAVE_SAY; send say to source; `log.record(event, {}, Decision("pending", "schedule_conflict", [], reply=say), None, [], {})`.
5. `_expire(q)`: `await asyncio.sleep(self._question_ttl_s)`; if `pending.drop(q)`: `async with TURN_LOCK: await self.announce(q.device_id, LEAVE_SAY)`.
6. `announce(target, text)`: send `{"type":"say","text":text}` to each `hub.targets(target)`; return count sent True.
7. `tick()`: `now = clock()`; for row in `schedules.due(now)`: if `now - row.next_at > MISSED_GRACE_S`: print `f"schedule {row.id} missed by {int(now - row.next_at)} s, skipped"` to stderr, `advance`, continue. Else under `TURN_LOCK`: greeting -> `announce(row.room, greeting_for(now))`; command -> `Event(uuid4().hex, now, "schedule", SCHEDULER_SOURCE, row.room, DEFAULT_USER, {"text": row.command, "schedule_id": row.id})` through `pipeline.handle(ev, RoomOutput(self, row.room))`, exceptions printed to stderr; then `advance`, append id. Return ids. `run_schedules()`: loop `tick()` then `asyncio.sleep(TICK_S)`.
**New symbols:** `TURN_LOCK: asyncio.Lock`; constants above; `def greeting_for(now: float) -> str`; `class Hub(Protocol)`; `class PeerOutput`; `class RoomOutput`; `class Core` with `__init__(self, pipeline, hub, log, schedules, pending, *, clock=time.time, question_ttl_s=QUESTION_TTL_S)`, `async submit(self, event: Event, timing: dict[str, float] | None = None) -> None`, `async announce(self, target: str | None, text: str) -> int`, `async tick(self) -> list[int]`, `async run_schedules(self) -> None`
**Verify:** `cd harness && .venv/bin/python -m pytest -q` — expected: all pass incl. `tests/test_core_submit.py`.
**Forbidden:** don't edit `server.py`, `scheduler.py` or the Task 5 test; core must not import audio, plugins.speaker, plugins.music or server.
**Depends:** Task 5
**Why:** Moves `TURN_LOCK` and turn dispatch out of the audio server (spec `:128-133`).

### Task 7: Write /peer hub tests (red) [test]
- [x] status
**Objective:** `harness/tests/test_peers.py` pins the `/peer` endpoint and `PeerHub` over a real in-process WebSocket, failing on import.
**Write-scope:** `harness/tests/test_peers.py` (new)
**Read-context:** `harness/tests/test_server.py:1-60`, `harness/tests/test_pipeline.py:20-80`, `harness/cadence/core.py` (from Task 6)
**Anchors:** `class Core` @ `harness/cadence/core.py` (from Task 6)
`def hello(peer_id: str, role: str, kind: str, room: str | None, caps: list[str], abilities: list[dict]) -> dict` @ `harness/cadence/protocol.py` (from Task 1)
**Steps:** 1. Fixture: `hub = PeerHub(Catalogue([]), DeviceRegistry([]), call_timeout_s=0.2)`; real `Pipeline(ScriptedDecider(*[_jev("x.do", [Call("x.do", {})])]*5), ScriptedDecider(), hub.catalogue, Executor(hub.catalogue, hub.registry), log, LiveContext(log, hub.now_playing))`; real `Core(...)` with temp DB; `peers.set_runtime(SimpleNamespace(hub=hub, core=core, log=log))`, reset to None after. `_eventually(pred, 2.0)` polls with `time.sleep(0.01)`.
2. Abilities: `X_DO = {"name":"x.do","description":"do","parameters":{"type":"object","properties":{}},"closed_args":{},"free_args":[],"target":None}`. Speaker hello: `hello("speaker-1","device","speaker","bedroom",["audio_out"],[])`; service hello: `hello("svc","service","test",None,[],[X_DO])`.
3. Cases: (a) non-JSON first frame -> `{"type":"error",...}`; (b) version 2 -> error message contains "protocol version"; (c) good hello -> `{"type":"welcome"}`, `registry.get("speaker-1")` online, room "bedroom", kind "speaker"; offline after close; (d) service hello adds `x.do` to `hub.catalogue`, gone after close; (e) second "speaker-1" while first open -> error "peer_id in use"; first still gets welcome-path turns; (f) round trip: speaker sends `{"type":"event","kind":"utterance","payload":{"text":"do it"}}`; svc receives `{"type":"call","call_id":<str>,"capability":"x.do","args":{},"target":None}`, replies `{"type":"result","call_id":..,"ok":True,"say":"done","data":{}}`; speaker gets `turn_start`, `ack` action, `say` "done", `turn_end`; log row outcome "ok"; (g) svc never replies -> speaker `say` "Sorry, that didn't work.", log results error "timeout"; (h) svc closes after the call -> error "peer_lost"; (i) svc sends `{"type":"media","device":"speaker-1","action":"play_url","url":"http://x/1"}` -> speaker gets `{"type":"media","action":"play_url","url":"http://x/1"}`; speaker sends `{"type":"media_event","event":"track_end","position_ms":5,"url":"http://x/1"}` -> svc gets same plus `"device":"speaker-1"`; (j) svc `{"type":"state","state":{"now_playing":{"speaker-1":{"track_name":"T"}}}}` -> `hub.now_playing("speaker-1") == {"track_name":"T"}`, None after svc closes; (k) text client `hello("cli","device","text",None,["text_out"],[])` event -> turn_start/ack/say/turn_end; `registry.find("speaker")` excludes "cli"; (l) `hub.targets("speaker-1") == ["speaker-1"]`, `targets("bedroom")`, `targets(None)` excludes service peers; (m) monkeypatch `cadence.wiring.build_runtime` to raise, `importlib.reload(peers)` must not call it.
**New symbols:** none (tests target Task 8: `from cadence.peers import PeerHub, app, set_runtime, capability_from_ability`)
**Verify:** `cd harness && .venv/bin/python -m pytest -q tests/test_peers.py` — expected: 1 collection error, `ModuleNotFoundError: No module named 'cadence.peers'`.
**Forbidden:** test file only; no real ports (TestClient only).
**Depends:** Task 1, Task 6
**Why:** Pins spec testing strategy for the core (`:214`).

### Task 8: Implement the /peer hub and endpoint
- [ ] status
**Objective:** `harness/cadence/peers.py` makes `tests/test_peers.py` green.
**Write-scope:** `harness/cadence/peers.py` (new)
**Read-context:** `harness/tests/test_peers.py` (from Task 7), `harness/cadence/server.py:30-48,88-209`, `harness/cadence/catalogue.py`, `harness/cadence/core.py` (from Task 6)
**Anchors:** `def check_hello(msg: dict) -> dict` @ `harness/cadence/protocol.py` (from Task 1)
`async def submit(self, event: Event, timing: dict[str, float] | None = None) -> None` @ `harness/cadence/core.py` (from Task 6)
**Steps:** 1. `CALL_TIMEOUT_S = 5.0`, `FAIL_SAY = "Sorry, that didn't work."`. `capability_from_ability(a)`: `Capability(a["name"], a["description"], a["parameters"], closed_args=a.get("closed_args") or {}, free_args=tuple(a.get("free_args") or ()), target=a.get("target"))`.
2. `@dataclass Peer(peer_id, role, kind, room, caps: frozenset[str], send, state: dict = {}, calls: dict[str, asyncio.Future] = {}, plugin: "PeerPlugin | None" = None)` (field default_factory).
3. `PeerPlugin(Plugin)`: `manifest = Manifest(peer.peer_id, peer.role, tuple(capability_from_ability(a) for a in abilities))`; `call(capability, args, target, event)`: new `uuid4().hex` call_id, future in `peer.calls`, send `{"type":"call","call_id","capability","args","target": target.id if target else None}`, `asyncio.wait_for(fut, timeout)`; TimeoutError -> `Result(False, say=FAIL_SAY, error="timeout")`; always pop; reply -> `Result(bool(m.get("ok")), say=m.get("say"), data=m.get("data") or {}, error=m.get("error"))`.
4. `PeerHub`: `add(peer, abilities)` raises `ValueError("peer_id in use")` if present; plugin (`PeerPlugin(peer, abilities, timeout_s=self._call_timeout_s)`, stored on `peer.plugin`) only when abilities; `catalogue.add` errors propagate; device role -> `registry.set_online(id, True, kind=peer.kind, room=peer.room)`. `remove(peer)`: only if `peers.get(id) is peer`; catalogue remove; device -> `set_online(id, False, kind=peer.kind)`; pending futures get `{"ok":False,"say":FAIL_SAY,"error":"peer_lost"}`; drop media-owner entries for it. `send(peer_id, msg) -> bool` (False if absent or send raises). `targets(target)`: device peers only, with `"audio_out"` or `"text_out"` in caps: `[target]` if it is such a peer id, else room match, or all if None. `now_playing(device_id)`: first service peer `state.get("now_playing", {}).get(device_id)`. `on_message(peer, msg)`: `result` -> set future; `media` from a service -> owner[device] = peer id, forward `{"type":"media","action","url"}`; `media_event` from a device -> forward `{**msg, "device": peer.peer_id}` to owner; `state` -> `peer.state = msg.get("state") or {}`; else ignore.
5. `app = FastAPI()`, `set_runtime`/`get_runtime` lazy exactly like `server.py:35-48`. `@app.websocket("/peer")`: accept; first frame -> `check_hello(decode(...))` (errors incl. disconnect-safe parse -> send `{"type":"error","message":str(exc)}`, close, return); build `Peer`, `hub.add` (ValueError -> error, close); send `{"type":"welcome"}`; loop: `event` with `kind == "utterance"` and text -> spawn `core.submit(utterance(peer_id, peer.room, text, asr_conf=payload.get("asr_conf")), timing=msg.get("timing"))` as a guarded task (copy `_guard`, `server.py:202-208`); other types -> `await hub.on_message(peer, msg)`; undecodable frames skipped. `finally`: cancel turn tasks, `hub.remove(peer)`.
**New symbols:** `CALL_TIMEOUT_S`, `FAIL_SAY`, `def capability_from_ability(a: dict) -> Capability`, `class Peer`, `class PeerPlugin(Plugin)` with `__init__(self, peer: Peer, abilities: list[dict], *, timeout_s: float = CALL_TIMEOUT_S)`, `class PeerHub` with `__init__(self, catalogue: Catalogue, registry: DeviceRegistry, *, call_timeout_s: float = CALL_TIMEOUT_S)`, attrs `catalogue`, `registry`, methods `add(peer, abilities) -> None`, `remove(peer) -> None`, `async send(peer_id, msg) -> bool`, `targets(target) -> list[str]`, `now_playing(device_id) -> dict | None`, `async on_message(peer, msg) -> None`; `app`, `set_runtime(rt)`, `get_runtime()`
**Verify:** `cd harness && .venv/bin/python -m pytest -q` — expected: all pass incl. `tests/test_peers.py`.
**Forbidden:** don't edit `server.py`, `wiring.py` or the Task 7 test; the event loop must keep reading while turns run (turns as tasks); no new deps.
**Depends:** Task 7, Task 6
**Why:** The hub is how lamps, speakers and Muse plug in without Cadence edits (spec `:100-105`).

## Phase 3 - Speaker and Muse adapters

### Task 9: Scaffold the speaker package from harness audio code
- [x] status
**Objective:** `speaker/` is a standalone package `cadence_speaker` holding copies of the audio code, its tests green, nothing importing `cadence`.
**Write-scope:** `speaker/` (new)
**Read-context:** `harness/cadence/plugins/speaker.py:1-30,169-188`, `harness/tests/test_speaker.py:191-232`, `harness/pyproject.toml`, `harness/.gitignore`
**Anchors:** `class SpeakerPort:` @ `harness/cadence/plugins/speaker.py`
`class SpeakerPlugin(Plugin):` @ `harness/cadence/plugins/speaker.py`
**Steps:** 1. From repo root: `mkdir -p speaker/cadence_speaker/audio speaker/tests speaker/scripts`; `cp harness/cadence/audio/*.py speaker/cadence_speaker/audio/`; `cp harness/cadence/{acks,benchrec,wakebench,turntiming,session,protocol}.py speaker/cadence_speaker/`; `cp harness/cadence/plugins/speaker.py speaker/cadence_speaker/speaker.py`; `touch speaker/cadence_speaker/__init__.py`; `cp harness/tests/{__init__,test_acks,test_benchrec,test_listener,test_mixer,test_speaker,test_turntiming,test_wakebench}.py speaker/tests/`; `cp harness/scripts/{asr_bench,wake_bench,wake_guide,preflight_wake_bench,build_ack_pool}.py speaker/scripts/`; `cp harness/cadence/llm.py speaker/scripts/ollama_llm.py`; `cp -r harness/acks speaker/acks` (on-disk only, gitignored).
2. In every `speaker/**/*.py`, in order: `sed -i -e 's/cadence\.plugins\.speaker/cadence_speaker.speaker/g' -e 's/from cadence\.plugins import speaker/from cadence_speaker import speaker/g' -e 's/\bcadence\./cadence_speaker./g' -e 's/from cadence import/from cadence_speaker import/g'`. Then in `speaker/scripts/build_ack_pool.py` replace `from cadence_speaker.llm import OllamaLLM` with `from ollama_llm import OllamaLLM`.
3. Create `speaker/cadence_speaker/config.py` with exactly: `SPEAKER_PORT = 8768`; `PEER_URL = os.environ.get("CADENCE_PEER_URL", "ws://127.0.0.1:8770/peer")`; `ROOM = os.environ.get("CADENCE_SPEAKER_ROOM", "bedroom")`; `RECONNECT_S = 2.0`; `UNREACHABLE_SAY = "I can't reach my brain right now."`; and copied from `harness/cadence/config.py`: `WAKE_ENABLED`, `WAKE_MODEL`, `WAKE_THRESHOLD`, `LISTEN_WINDOW_S`, `BENCH_RECORD_DIR`, `ACK_DIR`, `VOLUME_STEP`, `MAX_VOLUME`.
4. `speaker.py`: drop the `plugins.base` import and `SpeakerPlugin`; `VOLUME` becomes a dict `{"name":"speaker.volume","description":<same>,"parameters":<same>,"closed_args":<same>,"free_args":[],"target":"speaker"}`; add `def set_volume(port, action, step=VOLUME_STEP) -> dict` with the same branch logic as `SpeakerPlugin.call` (`speaker.py:175-188`), returning `{"ok": False, "say": "That speaker isn't connected.", "data": {}, "error": "no_port"}` or `{"ok": True, "say": None, "data": {"gain":..,"muted":..}, "error": None}`.
5. `speaker/tests/test_speaker.py`: the 4 plugin tests call `set_volume(port, "<action>")` and read `res["ok"]`, `res["data"]["muted"]`, `res["say"]`; import `set_volume` instead of `SpeakerPlugin`.
6. `speaker/pyproject.toml`: `[project] name = "cadence_speaker"`, `version = "0.1.0"`, `requires-python = ">=3.14"`; pytest block copied from `harness/pyproject.toml`. `speaker/.gitignore`: `acks/`, `bench_audio/`.
**New symbols:** `cadence_speaker.config` constants above; `VOLUME: dict`; `def set_volume(port: SpeakerPort | None, action: str | None, step: float = VOLUME_STEP) -> dict`
**Verify:** `cd speaker && ../harness/.venv/bin/python -m pytest -q` — expected: 73 passed. `grep -rnE "^\s*(from|import) cadence(\.| |$)" speaker` — expected: no output. `cd harness && .venv/bin/python -m pytest -q` — expected: unchanged pass.
**Forbidden:** don't modify or delete anything under `harness/` (copies only); no new deps; don't start servers.
**Depends:** Task 1
**Why:** Spec moves all audio to the speaker adapter (`:174`, `:216`); copying keeps harness green until Phase 4.

### Task 10: Write speaker /session server tests (red) [test]
- [x] status
**Objective:** `speaker/tests/test_server.py` pins the board-facing `/session` plus its peer link, failing on import.
**Write-scope:** `speaker/tests/test_server.py` (new)
**Read-context:** `harness/tests/test_server.py:1-206`, `speaker/tests/test_listener.py:20-40` (from Task 9), `speaker/cadence_speaker/speaker.py` (from Task 9)
**Anchors:** `def set_volume(port: SpeakerPort | None, action: str | None, step: float = VOLUME_STEP) -> dict` @ `speaker/cadence_speaker/speaker.py` (from Task 9)
**Steps:** 1. `FakeLink(hello)`: `outbox = queue.Queue()`, `inbox = queue.Queue()`, `closed = False`; `async send(msg)` puts to outbox (raises `LinkClosed` if closed); `async recv()` loops `inbox.get_nowait()` / `await asyncio.sleep(0.01)`, raising `LinkClosed` once closed; `async close()` sets closed. `links = queue.Queue()`; `async open_link(url, hello)` makes a FakeLink, puts it on `links`, returns it. Helper `_out(link)` = `json`-free `link.outbox.get(timeout=2)`.
2. Fixture `rt = SpeakerRuntime(acks=AckPool(str(tmp/"acks")), tts=lambda t: b"\x00\x00"*100, asr=lambda pcm: "do it", listener_factory=lambda: Listener(None, vad_factory=lambda: FakeVad([b"\x00\x00"*8000])), open_link=open_link, room="bedroom", reconnect_s=0.05)`; `server.set_runtime(rt)`, None after. Board hello `{"type":"hello","client_id":"speaker-1","caps":["audio_in","audio_out"]}`.
3. Cases: (a) link hello equals `hello("speaker-1","device","speaker","bedroom",["audio_in","audio_out"],[VOLUME])`; (b) bad board hello -> board gets `{"type":"error",...}`; (c) one mic frame -> link outbox `{"type":"event","kind":"utterance","payload":{"text":"do it","asr_conf":None},"timing":{...}}` with `"speech_end"` and `"asr_done"` keys; (d) with `listener_factory=lambda: Listener(None, vad_factory=RepeatVad)` where `RepeatVad.feed` returns `[b"\x00\x00"*8000]` on every call: more mic frames before `turn_end` produce no second event; after inbox `{"type":"turn_end"}` the next frame does; (e) inbox `{"type":"say","text":"Hi."}` -> board receives bytes `b"\x00\x00"*100`; (f) clip `tmp/acks/action/01.pcm` = `b"\x00\x00"*10`, inbox `{"type":"ack","category":"action"}` -> board receives those bytes; (g) inbox `{"type":"call","call_id":"c1","capability":"speaker.volume","args":{"action":"mute"},"target":"speaker-1"}` -> outbox `{"type":"result","call_id":"c1","ok":True,"say":None,"data":{"gain":1.0,"muted":True},"error":None}`; (h) `rt.transport = httpx.MockTransport(lambda r: httpx.Response(200, content=b"\x00"*400))`, inbox `{"type":"media","action":"play_url","url":"http://m/1"}` -> outbox `{"type":"media_event","event":"track_end","position_ms":<int>,"url":"http://m/1"}`; (i) inbox `{"type":"listen","seconds":8}` with a spy listener -> `listen_for(8)` called; (j) `open_link` raising `LinkClosed` -> mic utterance makes board receive tts audio and the fake tts got `"I can't reach my brain right now."`; (k) bench recorder test ported from `harness/tests/test_server.py:132-149`; (l) two board sessions with the same id each get their own link; closing the first closes only its link.
4. Listener test in `speaker/tests/test_server.py`: `Listener(gate, vad_factory=...)` after `listen_for(8)` returns VAD utterances without a wake detection.
**New symbols:** none (tests target Task 11: `cadence_speaker.server.{app,set_runtime}`, `cadence_speaker.wiring.SpeakerRuntime`, `cadence_speaker.link.LinkClosed`, `Listener.listen_for`)
**Verify:** `cd speaker && ../harness/.venv/bin/python -m pytest -q tests/test_server.py` — expected: 1 collection error, `ModuleNotFoundError` naming `cadence_speaker.server` (or `.wiring`/`.link`).
**Forbidden:** test file only; no real sockets.
**Depends:** Task 9
**Why:** Board protocol must stay byte-for-byte (spec `:114-119`); pins `listen`, ducking path and reconnect cleanup.

### Task 11: Implement the speaker server, peer link and entry point
- [ ] status
**Objective:** `python -m cadence_speaker` serves `/session` on 8768 and bridges each board session to Cadence `/peer`; `speaker/tests/test_server.py` green.
**Write-scope:** `speaker/cadence_speaker/server.py` (new)
`speaker/cadence_speaker/link.py` (new)
`speaker/cadence_speaker/wiring.py` (new)
`speaker/cadence_speaker/__main__.py` (new)
`speaker/cadence_speaker/audio/listener.py` (new)
`speaker/cadence_speaker/session.py` (new)
**Read-context:** `speaker/tests/test_server.py` (from Task 10), `harness/cadence/server.py:51-209`, `harness/cadence/wiring.py:66-88`
**Anchors:** `def listening(self) -> bool:` @ `harness/cadence/audio/listener.py`
`class SpeakerPort:` @ `speaker/cadence_speaker/speaker.py` (from Task 9)
**Steps:** 1. `link.py`: `LinkClosed(Exception)`; `WsLink(ws)` with `send` (json.dumps; `ConnectionClosed` -> LinkClosed), `recv` (json.loads), `close`; `open_link(url, hello)`: `connect(url, max_size=None)` (`OSError`/`WebSocketException` -> LinkClosed), send hello, first reply must be `welcome` else close and raise `LinkClosed(reply.get("message") or "no welcome")`.
2. `listener.py` (already copied by Task 9; edit in place): `listen_for(seconds)`: no-op if gate None; else `_listening=True`, `wake_at=now`, `_deadline=now+seconds`, fresh VAD.
3. `session.py` (already copied by Task 9): keep only `SessionCaps` and `_KNOWN_CAPS`.
4. `wiring.py`: `@dataclass SpeakerRuntime(acks, tts, asr, listener_factory, open_link, room=ROOM, peer_url=PEER_URL, reconnect_s=RECONNECT_S, bench_dir=None, transport=None)`; `build_runtime()` like `harness/cadence/wiring.py:66-88` (lazy Tts/Asr, `Listener(WakeGate() if WAKE_ENABLED else None)`, `AckPool(ACK_DIR)`, `open_link=link.open_link`, `bench_dir=BENCH_RECORD_DIR`).
5. `server.py` `/session`: parse board hello as `harness/cadence/server.py:92-104`; `port = SpeakerPort(send_audio, transport=rt.transport, max_gain=MAX_VOLUME)` if audio_out; listener if audio_in; recorder as before. Peer hello `hello(client_id, "device", "speaker", rt.room, <board caps list>, [VOLUME] if port else [])`. Link task: loop { `open_link` -> read `recv()` and `dispatch` each message sequentially } on `LinkClosed`/`OSError`: `link=None`, `in_turn=False`, sleep `reconnect_s`. dispatch: `turn_start` mark; `ack` -> clip via `port.speak`; `say` -> `SentenceChunker`, `asyncio.to_thread(rt.tts, s)`, `port.speak`; `listen` -> `listener.listen_for(seconds)`; `media` -> `play_url(url, on_end)` / `pause` / `resume` / `stop`, where `on_end(reason)` sends `{"type":"media_event","event":reason,"position_ms":port.position_ms(),"url":url}` if linked; `call` with `speaker.volume` -> `set_volume(port, args.get("action"))` sent as `{"type":"result","call_id":..,**res}`; `turn_end` -> `in_turn=False`, mark, print `"speaker_timing " + json` of durations to stderr; `error` -> stderr. Mic frames: recorder write; skip if no listener/asr or `in_turn`; utterances -> guarded task: `in_turn=True`, TurnTimer marks `wake`/`speech_end`/`asr_done`, ASR; empty text -> `in_turn=False`; no link -> speak `tts(UNREACHABLE_SAY)`, `in_turn=False`; else send event with `timing={stage: (time.monotonic()-at)*1000}`. Text frames ignored. `finally`: cancel turn tasks, recorder close, `await port.stop("lost")` while the link is still up, then cancel link task and close the link.
6. `__main__.py`: `uvicorn.run(app, host="0.0.0.0", port=SPEAKER_PORT)`.
**New symbols:** `class LinkClosed(Exception)`, `class WsLink`, `async def open_link(url: str, hello: dict) -> WsLink`, `Listener.listen_for(self, seconds: float) -> None`, `@dataclass class SpeakerRuntime`, `def build_runtime() -> SpeakerRuntime`, `app`, `def set_runtime(rt) -> None`, `def get_runtime() -> SpeakerRuntime`
**Verify:** `cd speaker && ../harness/.venv/bin/python -m pytest -q` — expected: all pass. `grep -rnE "^\s*(from|import) cadence(\.| |$)" speaker` — expected: no output.
**Forbidden:** don't run `python -m cadence_speaker` (port 8768 is the live harness); don't edit tests; no new deps; nothing under `harness/`.
**Depends:** Task 10
**Why:** Board needs no reflash; the speaker becomes one peer per board session (spec `:114-119`, `:204`).

### Task 12: Scaffold the Muse adapter package [mechanical]
- [x] status
**Objective:** `muse_adapter/` is a standalone package `cadence_muse` holding the Muse client and MCP server, their tests green.
**Write-scope:** `muse_adapter/` (new)
**Read-context:** `harness/cadence/config.py:11-34`, `harness/cadence/muse/__main__.py`
**Anchors:** `class MuseClient:` @ `harness/cadence/muse/client.py`
**Steps:** 1. From repo root: `mkdir -p muse_adapter/cadence_muse muse_adapter/tests muse_adapter/scripts`; `cp harness/cadence/muse/client.py harness/cadence/muse/mcp_server.py harness/cadence/protocol.py muse_adapter/cadence_muse/`; `cp harness/cadence/muse/__main__.py muse_adapter/cadence_muse/mcp_main.py`; `touch muse_adapter/cadence_muse/__init__.py`; `cp harness/tests/__init__.py harness/tests/test_muse_client.py harness/tests/test_muse_mcp_server.py muse_adapter/tests/`; `cp -r harness/tests/fixtures muse_adapter/tests/fixtures`; `cp harness/scripts/capture_muse_fixtures.py muse_adapter/scripts/`.
2. In every `muse_adapter/**/*.py`: `sed -i -e 's/cadence\.muse\./cadence_muse./g' -e 's/python -m cadence\.muse/python -m cadence_muse.mcp_main/g'`.
3. Create `muse_adapter/cadence_muse/config.py`: `import os`; `PEER_URL = os.environ.get("CADENCE_PEER_URL", "ws://127.0.0.1:8770/peer")`; `RECONNECT_S = 2.0`; then copy lines for `MUSE_BASE_URL`, `MUSE_PROXY_URL`, `PAUSE_TIMEOUT_S`, `PLAY_SOURCE`, `MUSE_CONTRACT_MAJOR`, `DEFAULT_QUEUE_LEN`, `MAX_QUEUE_LEN` verbatim from `harness/cadence/config.py`.
4. `muse_adapter/pyproject.toml`: `[project] name = "cadence_muse"`, `version = "0.1.0"`, `requires-python = ">=3.14"`, pytest block copied from `harness/pyproject.toml`.
**New symbols:** none
**Verify:** `cd muse_adapter && ../harness/.venv/bin/python -m pytest -q` — expected: 23 passed. `grep -rnE "^\s*(from|import) cadence(\.| |$)" muse_adapter` — expected: no output.
**Forbidden:** don't modify anything under `harness/`; don't copy `plugins/music.py` (Task 14 does); no new deps.
**Depends:** none
**Why:** Spec makes Muse its own service peer (`:121-126`).

### Task 13: Write Muse remote-port and adapter tests (red) [test]
- [x] status
**Objective:** `muse_adapter/tests/test_adapter.py` pins `RemotePort` and `MuseAdapter`, failing on import.
**Write-scope:** `muse_adapter/tests/test_adapter.py` (new)
**Read-context:** `harness/tests/test_music_plugin.py:1-118`, `harness/cadence/plugins/music.py:155-175`, `harness/cadence/plugins/speaker.py:77-145`
**Anchors:** `def compose_queue(text_results: list[dict] | None, vibe_results: list[dict] | None,` @ `harness/cadence/plugins/music.py`
**Steps:** 1. Collect sends in a list via `async def send(msg): sent.append(msg)`. Clock list `t = [10.0]`.
2. RemotePort cases (`RemotePort("speaker-1", send, clock=lambda: t[0])`): (a) `play_url("http://p/1", on_end)` sends `{"type":"media","device":"speaker-1","action":"play_url","url":"http://p/1"}`, `is_paused()` False; (b) `pause`/`resume` send actions `pause`/`resume`, `is_paused` toggles; (c) `stop()` sends `stop` and calls `on_end("stopped")` once; a second `stop()` sends but does not call it; (d) `on_media_event("track_end", 1234, "http://p/1")` -> `on_end("track_end")`, `position_ms() == 1234`; (e) event with another url, or event `"stopped"`, is ignored; (f) position estimate: play at t=10, t=12.5 -> 2500; pause at 13, t=20 -> 3000; resume at 20, t=21 -> 4000.
3. MuseAdapter cases using `FakeMuse` and `_three`/`_vibe` copied from `harness/tests/test_music_plugin.py:12-58,104-110` into this file: `adapter = MuseAdapter(MusicPlugin(muse), send)`; (g) `handle({"type":"call","call_id":"c1","capability":"music.play","args":{"mood":"chill"},"target":"speaker-1"})` sends, in order, a `media` `play_url` for `speaker-1`, `{"type":"result","call_id":"c1","ok":True,"say":<starts "Playing ">,"data":{"queue":[1,2,3]},"error":None}`, then `{"type":"state","state":{"now_playing":{"speaker-1":{...,"paused":False}}}}`; (h) plugin unavailable (`muse.version = "2.0"` then `plugin.check()`) -> result `ok False`, `error "muse_unavailable"`, say "Muse isn't answering."; (i) after play, `handle({"type":"media_event","device":"speaker-1","event":"track_end","position_ms":111,"url":<first url>})` sends `play_url` for track 2 and a `state`; (j) `adapter.hello() == hello("muse","service","music",None,[],ABILITIES)`.
**New symbols:** none (tests target Task 14: `cadence_muse.remote.RemotePort`, `cadence_muse.adapter.MuseAdapter`, `cadence_muse.music.{MusicPlugin,ABILITIES}`, `cadence_muse.protocol.hello`)
**Verify:** `cd muse_adapter && ../harness/.venv/bin/python -m pytest -q tests/test_adapter.py` — expected: 1 collection error, `ModuleNotFoundError` naming `cadence_muse.remote` (or `.adapter`/`.music`).
**Forbidden:** test file only.
**Depends:** Task 12
**Why:** The queue logic stays as-is behind a port that speaks the protocol (assumption A3).

### Task 14: Port the music plugin onto a remote port and connect it as a service peer
- [ ] status
**Objective:** `python -m cadence_muse` connects to `/peer` as service `muse`; music plugin tests and adapter tests green.
**Write-scope:** `muse_adapter/cadence_muse/music.py` (new)
`muse_adapter/cadence_muse/remote.py` (new)
`muse_adapter/cadence_muse/adapter.py` (new)
`muse_adapter/cadence_muse/link.py` (new)
`muse_adapter/cadence_muse/__main__.py` (new)
`muse_adapter/tests/test_music_plugin.py` (new)
**Read-context:** `muse_adapter/tests/test_adapter.py` (from Task 13), `harness/cadence/plugins/music.py:1-30,80-175`, `speaker/cadence_speaker/link.py` (from Task 11)
**Anchors:** `class MusicPlugin(Plugin):` @ `harness/cadence/plugins/music.py`
`async def open_link(url: str, hello: dict) -> WsLink` @ `speaker/cadence_speaker/link.py` (from Task 11)
**Steps:** 1. `cp harness/cadence/plugins/music.py muse_adapter/cadence_muse/music.py`; `cp harness/tests/test_music_plugin.py muse_adapter/tests/`; `cp speaker/cadence_speaker/link.py muse_adapter/cadence_muse/link.py`.
2. `music.py`: imports from `cadence_muse.config` and `cadence_muse.client`; drop `plugins.base`; add local `@dataclass Result(ok, say=None, data=field(default_factory=dict), error=None)` and `def _ability(name, description, parameters, closed_args=None, free_args=(), target=None) -> dict` returning the protocol ability dict (`free_args` as list); replace each `Capability(` with `_ability(`; `ABILITIES = [PLAY, CONTROL, RATE, NOW]`; `class MusicPlugin:` (no base, no `manifest`); in `call`, `target` is a device id str: `dev = target`.
3. `tests/test_music_plugin.py`: imports to `cadence_muse.*`; drop the `Device` import; `DEVICE = "speaker-1"`.
4. `remote.py` `RemotePort(device_id, send, *, clock=time.monotonic)`: `play_url` stores url and on_end, resets position baseline, sends media `play_url`; `pause`/`resume` send and track paused time; `stop(reason="stopped")` sends media `stop`, clears url, calls the stored on_end(reason) once; `position_ms()` = last reported position if set by an event since play, else `(clock()-start-paused_total)*1000` as int; `on_media_event(event, position_ms, url)`: ignore unless `url == current` and `event in ("track_end","lost")`; store position, clear on_end, call it with `event`. Comment: `# shortcut: position is wall-clock estimated between media_events, upgrade when the speaker reports position periodically`.
5. `adapter.py` `MuseAdapter(plugin, send, *, clock=time.monotonic)`: `self.send` is replaceable; ports per device built with `self._emit` (calls `self.send`, swallows `LinkClosed`). `hello()` per Task 13. `state()` = `{"now_playing": {d: plugin.now_playing(d) for d in ports}}`. `handle(msg)`: `call` -> unavailable gives `Result(False, say="Muse isn't answering.", error="muse_unavailable")`, else `plugin.call(capability, args, target, port)`; send `{"type":"result","call_id",**asdict(res)}`; then send state. `media_event` -> port `on_media_event`, then state. `async def run(adapter, url=PEER_URL, *, open_link=open_link, reconnect_s=RECONNECT_S)`: forever open link with `adapter.hello()`, set `adapter.send = link.send`, `handle` each `recv()`; on `LinkClosed`/`OSError` sleep `reconnect_s`.
6. `__main__.py`: `client = MuseClient(MUSE_BASE_URL, MUSE_PROXY_URL)`; `plugin = MusicPlugin(client)`; `plugin.check()`; `asyncio.run(run(MuseAdapter(plugin, None)))`.
**New symbols:** `Result`, `ABILITIES: list[dict]`, `class RemotePort` with `async play_url(url, on_end)`, `async pause()`, `async resume()`, `async stop(reason="stopped")`, `position_ms() -> int`, `is_paused() -> bool`, `async on_media_event(event: str, position_ms: int, url: str)`; `class MuseAdapter` with `hello() -> dict`, `state() -> dict`, `async handle(msg: dict) -> None`; `async def run(adapter, url=PEER_URL, *, open_link=open_link, reconnect_s=RECONNECT_S) -> None`
**Verify:** `cd muse_adapter && ../harness/.venv/bin/python -m pytest -q` — expected: all pass (23 + 21 music + adapter tests). `grep -rnE "^\s*(from|import) cadence(\.| |$)" muse_adapter` — expected: no output.
**Forbidden:** don't change queue/selection logic in `music.py` beyond Step 2; don't edit `test_adapter.py`; don't run `python -m cadence_muse`; nothing under `harness/`.
**Depends:** Task 13, Task 11
**Why:** Muse owns queues and returns URLs; the speaker plays them (spec `:121-126`).

## Phase 4 - Switch harness to /peer

### Task 15: Point golden replay and the smoke script at the new catalogue and /peer
- [ ] status
**Objective:** `golden_replay.py` builds caps from `tests/golden/abilities.json` plus schedule caps; `smoke_session.py` speaks `/peer`; a guard test checks the golden catalogue.
**Write-scope:** `harness/scripts/golden_replay.py`
`harness/scripts/smoke_session.py`
`harness/tests/golden/abilities.json` (new)
`harness/tests/test_golden.py` (new)
**Read-context:** `harness/scripts/golden_replay.py:17-45`, `harness/scripts/smoke_session.py:1-78`
**Anchors:** `def capability_from_ability(a: dict) -> Capability` @ `harness/cadence/peers.py` (from Task 8)
`class SchedulePlugin(Plugin)` @ `harness/cadence/schedules.py` (from Task 4)
**Steps:** 1. From repo root write the JSON: `harness/.venv/bin/python -c "import json,sys; sys.path[:0]=['speaker','muse_adapter']; from cadence_muse.music import ABILITIES; from cadence_speaker.speaker import VOLUME; json.dump(ABILITIES+[VOLUME], open('harness/tests/golden/abilities.json','w'), indent=1)"`.
2. `golden_replay.py`: drop `MusicPlugin`/`SpeakerPlugin`/`Catalogue` imports; `caps = [capability_from_ability(a) for a in json.load(open(os.path.join(ROOT, "tests/golden/abilities.json")))] + list(SchedulePlugin.manifest.capabilities) + list(BUILTINS)` (import `BUILTINS` from `cadence.catalogue`).
3. `smoke_session.py`: `URL = "ws://127.0.0.1:8770/peer"`; docstring says server on `/peer` port 8770; send `hello("smoke", "device", "text", None, ["text_out"], [])` from `cadence.protocol`, require a `welcome` reply; `turn` sends `{"type":"event","kind":"utterance","payload":{"text":text}}`, collects `say` (`frame["text"]`) and `error` texts, stops on `turn_end`; table column header "say/error frames"; drop audio byte counting.
4. `tests/test_golden.py`: names in `abilities.json` == `["music.play","music.control","music.rate","music.now_playing","speaker.volume"]`; every name in `tests/golden/utterances.json` `"catalogue"` is in abilities + schedule + builtins names; each ability passes `capability_from_ability`.
**New symbols:** none
**Verify:** `cd harness && .venv/bin/python -m pytest -q` — expected: all pass incl. `tests/test_golden.py`; `.venv/bin/python -c "import ast;ast.parse(open('scripts/golden_replay.py').read());ast.parse(open('scripts/smoke_session.py').read())"` — expected: no output.
**Forbidden:** don't run `smoke_session.py` or `golden_replay.py` (live services); no new deps.
**Depends:** none
**Why:** Harness can no longer import the plugins once they leave (Task 16).

### Task 16: Wire Cadence onto /peer and delete the moved harness code
- [ ] status
**Objective:** `python -m cadence` runs `/peer` on 8770 plus the schedule loop; audio, speaker, music and Muse code is gone from `harness/`.
**Write-scope:** `harness/cadence/wiring.py`
`harness/cadence/__main__.py`
`harness/cadence/config.py`
`harness/cadence/plugins/registry.py`
`harness/cadence/plugins/base.py`
`harness/cadence/server.py`
`harness/cadence/session.py`
`harness/cadence/scheduler.py`
`harness/cadence/acks.py`
`harness/cadence/benchrec.py`
`harness/cadence/wakebench.py`
`harness/cadence/audio/`
`harness/cadence/plugins/speaker.py`
`harness/cadence/plugins/music.py`
`harness/cadence/muse/`
`harness/devices.json`
`harness/tests/`
`harness/scripts/`
**Read-context:** `harness/cadence/wiring.py:1-88`, `harness/cadence/config.py:1-34`, `harness/cadence/peers.py` (from Task 8), `harness/cadence/core.py` (from Task 6)
**Anchors:** `def build_runtime() -> Runtime:` @ `harness/cadence/wiring.py`
`class PeerHub` @ `harness/cadence/peers.py` (from Task 8)
**Steps:** 1. `git rm` in `harness/`: `cadence/server.py cadence/session.py cadence/scheduler.py cadence/acks.py cadence/benchrec.py cadence/wakebench.py cadence/plugins/speaker.py cadence/plugins/music.py devices.json`, `-r cadence/audio cadence/muse tests/fixtures/muse`, `tests/test_server.py tests/test_scheduler.py tests/test_acks.py tests/test_benchrec.py tests/test_listener.py tests/test_mixer.py tests/test_speaker.py tests/test_wakebench.py tests/test_music_plugin.py tests/test_muse_client.py tests/test_muse_mcp_server.py`, `scripts/asr_bench.py scripts/wake_bench.py scripts/wake_guide.py scripts/preflight_wake_bench.py scripts/build_ack_pool.py scripts/capture_muse_fixtures.py`.
2. `wiring.py`: `@dataclass Runtime(registry, catalogue, hub, core, pipeline, log)`; `build_runtime()`: `registry = DeviceRegistry([])`, `log = DecisionLog(DB_PATH)`, `schedules = ScheduleStore(DB_PATH)`, `pending = PendingQuestions()`, `catalogue = Catalogue([SchedulePlugin(schedules, pending)])`, `hub = PeerHub(catalogue, registry)`, Jev/LLM as today (`wiring.py:55-60`), `executor = Executor(catalogue, registry)`, `context = LiveContext(log, hub.now_playing)`, pipeline, `core = Core(pipeline, hub, log, schedules, pending)`. Docstring: "Builds the Cadence core runtime: hub, catalogue, deciders, pipeline, schedules."
3. `__main__.py`: build `uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=PEER_PORT))` with `app`/`get_runtime` from `cadence.peers`; `asyncio.run(main())` where `main` starts `get_runtime().core.run_schedules()` as a task, awaits `server.serve()`, cancels the task after.
4. `config.py`: replace `WS_PORT = 8768` with `PEER_PORT = 8770`; delete `MCP_SERVERS`, `MUSE_BASE_URL`, `MUSE_PROXY_URL`, `DEVICES_PATH`, `WAKE_ENABLED`, `WAKE_MODEL`, `WAKE_THRESHOLD`, `LISTEN_WINDOW_S`, `BENCH_RECORD_DIR`, `ACK_DIR`, `PAUSE_TIMEOUT_S`, `VOLUME_STEP`, `MAX_VOLUME`, `PLAY_SOURCE`, `MUSE_CONTRACT_MAJOR`, `DEFAULT_QUEUE_LEN`, `MAX_QUEUE_LEN`.
5. `registry.py`: delete `from_file` and unused `json`/`os` imports; `tests/test_core.py`: delete `test_registry_from_file`. `base.py`: Manifest kind comment `# "device" | "service"`.
6. New `tests/test_wiring.py`: `monkeypatch.chdir(tmp_path)`, `monkeypatch.setenv("TYPESAFE_API_KEY", "x")`; `rt = build_runtime()`; `[c.name for c in rt.catalogue.available()] == ["schedule.add","schedule.cancel","chat","correction"]`; `rt.hub.catalogue is rt.catalogue`.
**New symbols:** `PEER_PORT = 8770`; `Runtime(registry, catalogue, hub, core, pipeline, log)`
**Verify:** `cd harness && .venv/bin/python -m pytest -q` — expected: all pass. `grep -rnE "cadence\.(audio|acks|benchrec|wakebench|server|session|scheduler|muse)|plugins\.(speaker|music)|WS_PORT|DEVICES_PATH" cadence scripts tests` — expected: no output. `grep -rn "cadence_speaker\|cadence_muse" cadence` — expected: no output.
**Forbidden:** don't touch `store.py`, `routines.py`, `context.py`, `agent.py`, `mcp_client.py`, `preflight_v1.py`, `preflight_runtime.py`, `bench_*`; don't delete on-disk `harness/acks/` (gitignored); don't run `python -m cadence` (the live server owns this host's ports); no new deps.
**Depends:** Task 15
**Why:** Cadence becomes the audio-free core; this is the cutover point of step 1 (spec `:44-47`).

### Task 17: Add schedule items to the Jev golden set and replay [experiment]
- [ ] status
**Objective:** golden set has schedule utterances; one live replay is recorded with per-route accuracy for `schedule.add`/`schedule.cancel`.
**Write-scope:** `harness/tests/golden/utterances.json`
`docs/preflight/jev-v1-golden.md`
`docs/research/data/jev_v1_golden.json`
**Read-context:** `harness/tests/golden/utterances.json:1-12`, `harness/scripts/golden_replay.py` (from Task 15), `docs/preflight/jev-v1-golden.md:1-25`
**Anchors:** none
**Steps:** 1. Note the current overall route accuracy line from `docs/preflight/jev-v1-golden.md` (before overwrite).
2. Append to `"items"` (`args` `{}` each; Jev never fills args for free-arg caps): `s1` "wake me up at 7 and play jazz" `["schedule.add"]`; `s2` "set an alarm for six thirty tomorrow" `["schedule.add"]`; `s3` "wake me up every day at 7" `["schedule.add"]`; `s4` "every morning at 8 play something upbeat" `["schedule.add"]`; `s5` "at 10 pm turn the volume down" `["schedule.add"]`; `s6` "cancel my 7 o'clock alarm" `["schedule.cancel"]`; `s7` "delete the wake-up at six thirty" `["schedule.cancel"]`; `s8` "never mind the 8am schedule" `["schedule.cancel"]`; `s9` "stop the alarm" `["music.control","schedule.cancel"]`; `s10` "what time is my alarm" `["chat"]`. Add `"schedule.add","schedule.cancel"` to `"catalogue"`; append to `"about"`: " Items s1-s10 cover voice schedules (2026-11-09)."
3. `cd harness && .venv/bin/python -m pytest -q tests/test_golden.py` stays green.
4. `cd harness && .venv/bin/python scripts/golden_replay.py` (live Jev; key from `~/.config/cadence/typesafe.env`). If it stops on `DeciderUnavailable`, keep the outputs it wrote and record the reason.
5. Append to `docs/preflight/jev-v1-golden.md` a section "## Schedule items (2026-11-09)": previous overall accuracy (Step 1), new overall, schedule.add and schedule.cancel accuracy, list of wrong schedule items with their predicted route.
Negative result is a valid outcome.
**New symbols:** none
**Verify:** `grep -n "Schedule items\|schedule.add\|schedule.cancel" docs/preflight/jev-v1-golden.md` — expected: the section exists and records the measured numbers (or the stop reason).
**Forbidden:** never print or write the API key; don't edit `golden_replay.py` or deciders to raise scores.
**Depends:** Task 15
**Why:** Spec defers whether Jev routes schedule requests well; this measures it (`:218`, `:231`).

### Task 18: Update CLAUDE.md and READMEs for the three-program layout [docs]
- [ ] status
**Objective:** CLAUDE.md, `harness/README.md`, `speaker/README.md`, `muse_adapter/README.md` describe the split accurately.
**Write-scope:** `CLAUDE.md`
`harness/README.md`
`speaker/README.md` (new)
`muse_adapter/README.md` (new)
**Read-context:** `CLAUDE.md:1-60`, `harness/README.md:1-40`, `docs/specs/2026-11-09-cadence-modular-split.md:21-47,177-200`, `speaker/cadence_speaker/config.py` (from Task 9), `muse_adapter/cadence_muse/config.py` (from Task 12)
**Anchors:** none
**Steps:** 1. Audience: future Claude sessions and the user on another machine.
2. CLAUDE.md "Repository layout": add `speaker/` (`cadence_speaker`, `/session` on 8768, board-facing, wake/VAD/ASR/TTS/acks/ducking) and `muse_adapter/` (`cadence_muse`, service peer). "Decision harness" section: `/peer` on 8770 in `cadence/peers.py`, `Core` and `TURN_LOCK` in `cadence/core.py`, schedules in `cadence/schedules.py`; remove claims about audio modules, `devices.json`, `CADENCE_DEVICES_PATH`, `SpeakerPort`, plugins `speaker`/`music`; voice_chat section: board talks to the speaker adapter, which talks to Cadence. Run order: `python -m cadence` (harness/), `python -m cadence_muse` (muse_adapter/), `python -m cadence_speaker` (speaker/), each with `harness/.venv/bin/python`. Env vars: `CADENCE_PEER_URL`, `CADENCE_SPEAKER_ROOM`, plus moved ones.
3. Protocol summary table (message, direction, fields) in `harness/README.md`, matching `cadence/protocol.py` and assumption A3/A4 of `docs/plans/2026-11-09-cadence-modular-split.md`.
4. `speaker/README.md` and `muse_adapter/README.md`: what it is, run command, config env vars, test command, Kokoro files in `tools/`, `acks/` regeneration with `scripts/build_ack_pool.py`.
**New symbols:** none
**Verify:** `grep -n "8770\|cadence_speaker\|cadence_muse\|peers.py\|core.py" CLAUDE.md harness/README.md speaker/README.md muse_adapter/README.md` — expected: each file has hits; `grep -n "devices.json\|CADENCE_DEVICES_PATH" CLAUDE.md harness/README.md` — expected: no output.
**Forbidden:** don't change the git/sync rules section of CLAUDE.md; every port, path and command must match the repo.
**Depends:** Task 16
**Why:** Other machines and sessions learn the layout from these files.

## Post-plan (human, not autopilot)

1. Cutover on `ianshomeserver`: stop the old harness on 8768, then start `python -m cadence` (harness/), `python -m cadence_muse` (muse_adapter/), `python -m cadence_speaker` (speaker/).
2. Board smoke test (spec `:219`): wake word, a command, music play/pause, volume, a schedule set one minute ahead firing with a greeting, a conflict prompt answered without the wake word. Record in `docs/hardware/build-log.md`.
3. Step 2 (new repos, GitHub rename) after confirmation.
