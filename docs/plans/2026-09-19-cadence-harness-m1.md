# Plan — Cadence harness M1: turn path + Muse MCP

Source spec: `docs/specs/2026-09-19-voice-music-agent-harness.md` (spec-lint `--handoff` exit 0,
status "ready for planning"). Source PRD: `docs/prd/2026-09-19-voice-music-agent-harness.md`.

## Scope

M1 is the slice an executor can verify on this Mac: the harness core (session + WebSocket,
VAD/ASR/TTS stages, agent loop with the 3-call cap, mixer/ducking), the Muse MCP server, the
SQLite diary + routine store, the scheduler, and the firmware rewrite to a WebSocket client
proven by `idf.py build`.

**Deferred to a later plan** (each named here so no executor invents it):
- Wake word (`esp-sr` on-board / `openwakeword` server fallback) and echo subtraction — both
  gated on board PSRAM/flash verification, which needs hardware the plan cannot assume.
- Acknowledgement clip pool generation — needs the cloud model for background phrasing runs and
  depends on the Assumed acknowledgement-timing decision.
- Deployment packaging onto `ianshomeserver` (Python 3.14 wheel resolution, systemd units).
- Telegram / iMessage adapters. Muse recommender overhaul (spec: pure follow-on, blocks nothing).

Until wake word lands, the VAD gate is the only utterance gate — this is a known M1 limitation,
not an executor's licence to build a wake word.

## Manual prerequisites (the user runs these; no task can)

1. `ollama signin` on this Mac. Verified 2026-09-19: `POST http://localhost:11434/api/chat` with
   `{"model":"gemma4:31b-cloud"}` returns `{"error":"Unauthorized"}`. **Task 3 cannot pass until
   this is done.**
2. ESP32-S3 plugged in — **optional**. No `/dev/cu.usbmodem*` device exists as of planning. Task 23
   verifies by `idf.py build` only; flash + monitor is a manual step recorded in its Why.
3. `ssh ianshomeserver` currently fails `Host key verification failed`. **M1 needs no server
   access** — Muse is reached over HTTP, which works. Accepting the host key is only needed for
   the deferred deployment plan.

## Premises

- Muse API is live and all 8 spec'd tool endpoints answer — verified: `curl -s -m 10 -o /dev/null -w '%{http_code}'` against
  `/api/dashboard` (200), `/api/player/state` GET (200), `/api/library/search?q=bieber&limit=2` (200),
  `/api/library/search/vibe?q=chill&n=2` (200), `/api/recommend/123458861?n=2` (200), and
  `POST /api/ratings` with `{}` (422 = route exists, body rejected).
- Muse publishes OpenAPI at `http://ianshomeserver:8080/openapi.json`, 35 paths — verified: `curl -s -m 10 http://ianshomeserver:8080/openapi.json` returned 200.
- `RatingWrite` is `{track_rowid: int (required), rating: -1 | 1 | null (required)}` — verified: `components.schemas.RatingWrite` in `/tmp/muse_openapi.json`.
- `StateWrite` requires `queue: int[]` and `client_state: str` ('playing' | 'paused' | 'idle');
  optional `queue_index`, `position_ms`, `shuffle`, `repeat_mode`, `radio_seed`, `updated_by` — verified: `components.schemas.StateWrite` in the same document.
- `GET /api/recommend/{track_rowid}` takes `n`, `exclude`, `recent`, `w_audio`, `w_feat`, `w_lyr`,
  `w_emo`, `w_taste`; returns `{seed, results:[{track_rowid, score, reasons}]}` — verified: `curl -s "http://ianshomeserver:8080/api/recommend/123458861?n=1"`.
- `GET /api/library/search/vibe` takes `q`, `n`; returns `{q, results:[{track_rowid, score, track:{...}}]}` — verified: `curl -s "http://ianshomeserver:8080/api/library/search/vibe?q=chill&n=2"`.
- `voice_chat/` builds green today on ESP-IDF v5.3 — verified: `cd voice_chat && source ~/esp/esp-idf/export.sh && idf.py build` exit 0.
- Board flash is 2MB and PSRAM is off — verified: `voice_chat/sdkconfig:504` `CONFIG_ESPTOOLPY_FLASHSIZE="2MB"`, `voice_chat/sdkconfig:1010` `# CONFIG_SPIRAM is not set`.
- `tools/.venv` is Python 3.14.7 and already has `faster-whisper 1.2.1`, `kokoro-onnx 0.4.7`,
  `webrtcvad 2.0.10`, `onnxruntime 1.30.0`, `numpy 2.5.3`, `scipy 1.18.1` — verified: `tools/.venv/bin/pip list`.
- `mcp`, `pytest`, `pytest-asyncio`, `fastapi`, `uvicorn`, `websockets`, `httpx` are **not** in
  `tools/.venv` but all publish current releases (mcp 2.2.0, pytest 9.1.1, pytest-asyncio 1.4.0,
  fastapi 0.141.1, uvicorn 0.53.0, websockets 17.1, httpx 0.28.1) — verified: `tools/.venv/bin/pip index versions <pkg>`.
- `gemma4:31b-cloud` is a real published tag — verified: `curl -s https://ollama.com/library/gemma4/tags | grep -oE "gemma4:[a-z0-9.-]+"` lists both `gemma4:31b` and `gemma4:31b-cloud`.
- Kokoro model files are present next to the legacy host: `tools/kokoro-v1.0.onnx`, `tools/voices-v1.0.bin` — verified: `find . -type f` listing.
- No Python tests exist anywhere in the repo, so no frozen assertion can be broken by new symbols — verified: `find . -name "test_*.py" -not -path "./*/.venv/*"` returned nothing.

## Assumptions (Deferred items from the spec decided here)

- **Python 3.14 wheel availability** (spec Open questions): decided as *one* venv at
  `harness/.venv` on the system Python 3.14.7. Task 2 is an `[experiment]` that proves every
  import; if a wheel is missing, its negative result is the trigger for the second-venv fallback
  the spec names — not something an executor improvises mid-plan.
- **`faster-whisper` / Kokoro latency** (spec Open questions): measured on *this Mac* in Task 2,
  not on `ianshomeserver`. The acknowledgement-timing decision depends on the server number, which
  M1 does not produce — the ack layer is deferred, so nothing in M1 rests on it.
- **Board PSRAM/flash verification** (spec Open questions): not resolved here. M1 ships no wake
  word, so the gate it blocks is out of scope.

## Shared constants (every brief uses these exact values)

| Name | Value |
|---|---|
| WebSocket listen port | `8768` |
| Mic audio | 16000 Hz, mono, s16le |
| Speaker audio | 44100 Hz, stereo, s16le |
| `MAX_TOOL_CALLS` | `3` |
| `DUCK_GAIN` | `0.25` |
| `DUCK_RAMP_MS` | `150` |
| `CONTEXT_TURNS` | `10` |
| LLM model tag | `gemma4:31b-cloud` |
| Ollama endpoint | `http://localhost:11434/api/chat` |
| Muse base | `http://ianshomeserver:8080` |
| Muse PCM proxy base | `http://ianshomeserver:8765` |
| SQLite path (default) | `harness/cadence.sqlite3` |

## WebSocket session protocol (normative — Tasks 20 and 23 both implement this)

- URL: `ws://<host>:8768/session`
- Client to server, **text** frame, first message:
  `{"type":"hello","client_id":"<string>","caps":["audio_in","audio_out"]}`
- Client to server, **binary** frames: mic PCM, 16000 Hz mono s16le, any frame length.
- Server to client, **binary** frames: playback PCM, 44100 Hz stereo s16le.
- Server to client, **text** frames: `{"type":"turn_start"}`, `{"type":"turn_end"}`,
  `{"type":"error","message":"<string>"}`.
- A text client sends `{"type":"hello","client_id":"...","caps":["text_in","text_out"]}` and then
  `{"type":"text","content":"..."}`; the server replies `{"type":"text","content":"..."}` and runs
  no ASR and no TTS for that session.

---

## Phase 1 — Foundation and preflight

### Task 1: Scaffold the harness package and venv [mechanical]
- [x] status
**Objective:** `harness/` exists with a venv, pinned dependencies, and a `pytest` run that collects zero tests and exits 0.
**Write-scope:**
- `harness/pyproject.toml` (new)
- `harness/requirements.txt` (new)
- `harness/cadence/__init__.py` (new)
- `harness/cadence/audio/__init__.py` (new)
- `harness/cadence/muse/__init__.py` (new)
- `harness/tests/__init__.py` (new)
- `harness/.gitignore` (new)
**Read-context:** `tools/requirements-voice.txt` — the legacy pin set; `setuptools<81` is required because `webrtcvad` imports `pkg_resources` at runtime.
**Anchors:** none.
**Steps:**
1. Create `harness/requirements.txt` with exactly these pinned lines and no others:
   `setuptools<81`, `faster-whisper==1.2.1`, `kokoro-onnx==0.4.7`, `webrtcvad==2.0.10`,
   `onnxruntime==1.30.0`, `numpy==2.5.3`, `scipy==1.18.1`, `mcp==2.2.0`, `fastapi==0.141.1`,
   `uvicorn==0.53.0`, `websockets==17.1`, `httpx==0.28.1`, `pytest==9.1.1`,
   `pytest-asyncio==1.4.0`.
2. Create `harness/pyproject.toml`: `[project]` name `cadence`, version `0.1.0`,
   `requires-python = ">=3.14"`; `[tool.pytest.ini_options]` with `asyncio_mode = "auto"` and
   `testpaths = ["tests"]`.
3. Create the four empty `__init__.py` files listed in Write-scope.
4. Create `harness/.gitignore` containing `.venv/`, `__pycache__/`, `*.sqlite3`.
5. Run `python3 -m venv harness/.venv` then `harness/.venv/bin/pip install -r harness/requirements.txt`.
**New symbols:** none
**Verify:** `cd harness && .venv/bin/python -c "import mcp, faster_whisper, kokoro_onnx, webrtcvad, fastapi, uvicorn, websockets, httpx, pytest, numpy, scipy; print('ok')"` — expected: prints `ok`.
**Note:** do not verify with bare `pytest` here — with no test files it exits 5 (`no tests ran`), which reads as a failure.
**Forbidden:** no dependency outside the 14 pinned lines above; do not touch `tools/`; do not create any module beyond the `__init__.py` files listed.
**Depends:** none.
**Why:** Every later task installs nothing — the whole dependency set is decided here so each brief can forbid new deps outright.

### Task 2: Prove the audio stack imports and measure its latency [experiment]
- [ ] status
**Objective:** A written record showing whether `mcp`, `faster-whisper`, `kokoro-onnx`, and `webrtcvad` import and run on Python 3.14.7, with measured ASR and TTS latency.
**Write-scope:**
- `docs/preflight/runtime.md` (new)
- `harness/scripts/preflight_runtime.py` (new)
**Read-context:**
- `tools/voice_chat_host.py:88-112` — `PatchedKokoro`, the float32 speed cast the kokoro-v1.0.onnx model needs.
- `tools/voice_chat_host.py:157-167` — the PCM helpers.
- `harness/requirements.txt` (from Task 1) — the installed pin set.
**Anchors:**
- `class PatchedKokoro(Kokoro)` @ `tools/voice_chat_host.py`
- `def kokoro_audio_to_i2s_pcm(samples: np.ndarray, src_rate: int) -> bytes` @ `tools/voice_chat_host.py`
**Steps:**
1. Write `harness/scripts/preflight_runtime.py`. For each of `mcp`, `faster_whisper`,
   `kokoro_onnx`, `webrtcvad`, `fastapi`, `websockets`, `httpx`: import it inside a `try`, and
   print one line `IMPORT <name> OK <version>` or `IMPORT <name> FAIL <exception repr>`. Never let
   a failed import abort the script.
2. Load `WhisperModel("small.en", device="cpu", compute_type="int8")`, timing the load.
3. Synthesize a 3-second 16000 Hz mono float32 test signal in numpy (a 440 Hz sine plus uniform
   noise at amplitude 0.01 — no audio file is needed; this measures decode cost, not accuracy).
   Transcribe it with `beam_size=5, vad_filter=True`, timing three runs; print the mean.
4. Copy `PatchedKokoro` verbatim into the script, load it against `tools/kokoro-v1.0.onnx` and
   `tools/voices-v1.0.bin`, and synthesize `"Sure, putting something on now."` with voice
   `af_sarah` three times; print the mean synthesis time and the mean audio duration.
5. Write `docs/preflight/runtime.md` recording: each import line verbatim, Whisper load time,
   mean ASR time for 3 seconds of audio, mean Kokoro synthesis time, and the real-time factor for
   each. State plainly whether every import succeeded.
**New symbols:** none.
**Verify:** `cd harness && .venv/bin/python scripts/preflight_runtime.py` — expected: prints seven `IMPORT ... OK|FAIL` lines and the four timing figures, exits 0. Record the numbers; do not assert a threshold.
**Forbidden:** no new deps; do not edit `tools/voice_chat_host.py`; do not download any model file.
**Depends:** Task 1.
**Why:** Eleven downstream tasks assume this stack runs on 3.14. Negative result is a valid outcome — a failed import is the trigger for the spec's second-venv fallback, and reporting it is success.

### Task 3: Prove `gemma4:31b-cloud` tool calling with `think: false` [experiment]
- [x] status
**Objective:** A written record of the exact `tool_calls` JSON shape Ollama returns for `gemma4:31b-cloud`, plus measured latency.
**Write-scope:**
- `docs/preflight/ollama.md` (new)
- `harness/scripts/preflight_ollama.py` (new)
**Read-context:** `docs/specs/2026-09-19-voice-music-agent-harness.md:170-176` — the LLM decision and the `think` toggle rationale.
**Anchors:** none.
**Steps:**
1. Write `harness/scripts/preflight_ollama.py` using `httpx` against `http://localhost:11434/api/chat`.
2. Build one request: `model` `gemma4:31b-cloud`, `stream` false, `think` false, messages
   `[{"role":"user","content":"Find me something chill to play."}]`, and one tool —
   `search_vibe` with parameters `{"type":"object","properties":{"query":{"type":"string"},"n":{"type":"integer"}},"required":["query"]}`.
3. Send it, timing the round trip. Print the HTTP status, the elapsed milliseconds, and the full
   response JSON pretty-printed.
4. Send the same request with `think` true and print the same three things.
5. If either response is `{"error":"Unauthorized"}`, print
   `BLOCKED: run 'ollama signin' on this machine, then re-run` and exit 0 — do not attempt to sign
   in and do not use any other model.
6. Write `docs/preflight/ollama.md` recording, for both `think` settings: the elapsed
   milliseconds, whether `message.tool_calls` was present, and the exact JSON path and field names
   of the tool call (function name, arguments shape) copied from the real response.
**New symbols:** none.
**Verify:** `cd harness && .venv/bin/python scripts/preflight_ollama.py` — expected: exits 0, printing either two timed responses or the `BLOCKED:` line. Record the numbers; do not assert a threshold.
**Forbidden:** no new deps; never run `ollama signin`, `ollama pull`, or `ollama run`; do not substitute a different model tag; do not fall back to a local model.
**Depends:** Task 1.
**Why:** Task 16's loop parses whatever shape this returns, so guessing it is the single most likely hallucination in the plan. Negative result is a valid outcome — an Unauthorized reply is a real finding that parks the phase for the user, not a failure to hide.

### Task 4: Capture Muse API response fixtures
- [ ] status
**Objective:** Real JSON responses from all eight Muse endpoints saved as test fixtures.
**Write-scope:**
- `harness/tests/fixtures/muse/` (new)
- `harness/scripts/capture_muse_fixtures.py` (new)
**Read-context:**
- `tools/muse_proxy.py:13-21` — `MUSE_BASE`, `LISTEN_PORT`, and the play-by-rowid proxy route shape.
- `docs/specs/2026-09-19-voice-music-agent-harness.md:199-209` — the eight-tool surface table.
**Anchors:**
- `MUSE_BASE = "http://ianshomeserver:8080"` @ `tools/muse_proxy.py`
**Steps:**
1. Write `harness/scripts/capture_muse_fixtures.py` using `httpx` with a 10-second timeout.
2. Fetch and save each of these to `harness/tests/fixtures/muse/<name>.json`, pretty-printed with
   two-space indent:
   - `search_vibe.json` from `GET /api/library/search/vibe?q=chill&n=5`
   - `search_text.json` from `GET /api/library/search?q=bieber&limit=5`
   - `recommend_next.json` from `GET /api/recommend/123458861?n=5`
   - `player_state.json` from `GET /api/player/state`
   - `dashboard.json` from `GET /api/dashboard`
   - `openapi.json` from `GET /openapi.json`
   - `ratings_422.json` from `POST /api/ratings` with body `{}` (the validation error body itself
     is the fixture — it documents the required-field contract)
3. For each fetch print `FIXTURE <name> <status> <bytes>`. If any status is not 200 except
   `ratings_422.json`, which must be 422, print `MUSE UNREACHABLE: <name> <status>` and exit 1.
4. Truncate `dashboard.json` and `search_*.json` to at most the first 5 entries of each top-level
   list before saving, so fixtures stay small.
**New symbols:** none.
**Verify:** `cd harness && .venv/bin/python scripts/capture_muse_fixtures.py && ls tests/fixtures/muse/` — expected: seven `FIXTURE ... 200|422 ...` lines, exit 0, and seven `.json` files listed.
**Forbidden:** no new deps; never `PUT /api/player/state` or send a non-empty `POST /api/ratings` — this task must not mutate the live library; do not hand-write any fixture content.
**Depends:** Task 1.
**Why:** Tasks 5 and 7 assert against real Muse shapes. Fixtures captured from the live API are the only way those tests stay honest without reaching the network on every run.

**Phase 1 gate:** `docs/preflight/runtime.md` and `docs/preflight/ollama.md` both exist and record
real measurements; seven fixture files exist. If Task 3 recorded `BLOCKED:`, stop and tell the
user to run `ollama signin` — do not start Phase 4.

---

## Phase 2 — Muse MCP server

### Task 5: Write Muse client tests against the captured fixtures [test]
- [ ] status
**Objective:** A red test file covering all eight Muse client methods, asserting against the Phase 1 fixtures.
**Write-scope:** `harness/tests/test_muse_client.py` (new)
**Read-context:**
- `harness/tests/fixtures/muse/` (from Task 4) — read every fixture before writing assertions; copy real `track_rowid` values out of them rather than inventing any.
- `docs/specs/2026-09-19-voice-music-agent-harness.md:199-209` — the tool surface table.
**Anchors:** (all from Task 6)
- `class MuseClient:` @ `harness/cadence/muse/client.py` (from Task 6)
- `def search_vibe(self, query: str, n: int = 10) -> list[dict]` (from Task 6)
- `def search_text(self, query: str, limit: int = 10) -> list[dict]` (from Task 6)
- `def recommend_next(self, track_rowid: int, n: int = 10) -> dict` (from Task 6)
- `def play(self, track_rowid: int) -> str` (from Task 6)
- `def get_player_state(self) -> dict` (from Task 6)
- `def set_player_state(self, queue: list[int], client_state: str, queue_index: int = 0, position_ms: int = 0, shuffle: bool = False, repeat_mode: str = "off") -> dict` (from Task 6)
- `def get_dashboard(self) -> dict` (from Task 6)
- `def rate(self, track_rowid: int, rating: int | None) -> dict` (from Task 6)
**Steps:**
1. Use `httpx.MockTransport` to serve each fixture for its endpoint; construct `MuseClient` with
   the mock transport injected.
2. `test_search_vibe_returns_candidate_list` — asserts the return is a list, each item has keys
   `track_rowid`, `score`, `track`, and each `track` has `track_name`, `artist_name`,
   `duration_ms`, `playable`.
3. `test_search_text_returns_tracks` — asserts a list of track dicts.
4. `test_recommend_next_returns_seed_and_results` — asserts keys `seed` and `results`, and that
   `seed` equals the `track_rowid` passed in.
5. `test_play_returns_proxy_url` — asserts `play(123458861)` returns exactly
   `"http://ianshomeserver:8765/play/123458861"` and performs no HTTP request at all.
6. `test_get_player_state_has_queue_keys` — asserts keys `queue`, `queue_index`, `position_ms`,
   `shuffle`, `repeat_mode`.
7. `test_set_player_state_sends_required_fields` — captures the outgoing request body and asserts
   it contains `queue` and `client_state`; asserts a `client_state` outside
   `{"playing","paused","idle"}` raises `ValueError` before any request is sent.
8. `test_get_dashboard_has_sections` — asserts keys `resume`, `mixes`, `recent_albums`,
   `never_played`, `forgotten`.
9. `test_rate_accepts_only_valid_ratings` — asserts `rate(id, 1)` and `rate(id, -1)` and
   `rate(id, None)` build a body of exactly `{"track_rowid": ..., "rating": ...}`, and that
   `rate(id, 5)` raises `ValueError` before any request is sent.
10. `test_unreachable_muse_raises_museunavailable` — the transport raises `httpx.ConnectError`;
    assert `MuseUnavailable` propagates and that no retry request was made (assert the transport
    saw exactly one call).
**New symbols:** none (test functions only).
**Verify:** `cd harness && .venv/bin/python -m pytest tests/test_muse_client.py -q` — expected: exit 2, `1 error`, a collection error reading `ModuleNotFoundError: No module named 'cadence.muse.client'`. Red is the correct outcome here.
**Forbidden:** do not create `harness/cadence/muse/client.py`; no real network call in any test; do not invent `track_rowid` values — copy them from the fixtures.
**Depends:** Task 4.
**Why:** Test-first per the plan's default pairing. The signatures in Anchors are copied verbatim from Task 6's New symbols so the two tasks cannot drift.

### Task 6: Implement the Muse HTTP client
- [ ] status
**Objective:** `MuseClient` wraps all eight Muse operations and turns any connection failure into `MuseUnavailable` without retrying.
**Write-scope:** `harness/cadence/muse/client.py` (new)
**Read-context:**
- `harness/tests/test_muse_client.py` (from Task 5) — the contract, in full.
- `harness/tests/fixtures/muse/openapi.json` (from Task 4) — the authoritative parameter names.
- `tools/muse_proxy.py:13-21` — the play-by-rowid proxy route.
**Anchors:**
- `MUSE_BASE = "http://ianshomeserver:8080"` @ `tools/muse_proxy.py`
- `TRACK_PATH_RE = re.compile(r"^/play/(\d+)$")` @ `tools/muse_proxy.py`
**Steps:**
1. Define `MuseUnavailable(Exception)`.
2. Define `MuseClient.__init__(self, base_url: str = "http://ianshomeserver:8080", proxy_url: str = "http://ianshomeserver:8765", transport=None)`, holding one `httpx.Client` with a 10-second timeout and the optional transport.
3. Implement a private `_get(path, params)` and `_send(method, path, json)` that wrap every
   `httpx.HTTPError` in `MuseUnavailable` and **make exactly one attempt** — no retry, no backoff.
4. `search_vibe` calls `GET /api/library/search/vibe` with `q` and `n`, returning `data["results"]`.
5. `search_text` calls `GET /api/library/search` with `q` and `limit`, returning the result list.
6. `recommend_next` calls `GET /api/recommend/{track_rowid}` with `n`, returning the whole
   `{seed, results}` object unchanged.
7. `play` performs no HTTP call; it returns `f"{self.proxy_url}/play/{track_rowid}"`.
8. `get_player_state` calls `GET /api/player/state`.
9. `set_player_state` validates `client_state` is one of `"playing"`, `"paused"`, `"idle"` and
   raises `ValueError` otherwise, then `PUT /api/player/state` with a body carrying `queue`,
   `client_state`, `queue_index`, `position_ms`, `shuffle`, `repeat_mode`.
10. `get_dashboard` calls `GET /api/dashboard`.
11. `rate` validates `rating in (1, -1, None)` and raises `ValueError` otherwise, then
    `POST /api/ratings` with body `{"track_rowid": ..., "rating": ...}`.
**New symbols:**
- `class MuseUnavailable(Exception)`
- `class MuseClient:`
- `def search_vibe(self, query: str, n: int = 10) -> list[dict]`
- `def search_text(self, query: str, limit: int = 10) -> list[dict]`
- `def recommend_next(self, track_rowid: int, n: int = 10) -> dict`
- `def play(self, track_rowid: int) -> str`
- `def get_player_state(self) -> dict`
- `def set_player_state(self, queue: list[int], client_state: str, queue_index: int = 0, position_ms: int = 0, shuffle: bool = False, repeat_mode: str = "off") -> dict`
- `def get_dashboard(self) -> dict`
- `def rate(self, track_rowid: int, rating: int | None) -> dict`
**Verify:** `cd harness && .venv/bin/python -m pytest tests/test_muse_client.py -q` — expected: 9 passed.
**Forbidden:** no new deps; no retry logic anywhere — the spec's Muse-unreachable decision is "say so and stop"; do not add a ninth method; do not edit the test file.
**Depends:** Task 5.
**Why:** The single point where Muse's HTTP surface enters the harness, so the no-retry rule is enforced in exactly one place.

### Task 7: Write MCP tool-surface tests [test]
- [ ] status
**Objective:** A red test file asserting the MCP server exposes exactly the eight spec'd tools with the right schemas and that each dispatches to the matching `MuseClient` method.
**Write-scope:** `harness/tests/test_muse_mcp_server.py` (new)
**Read-context:**
- `harness/cadence/muse/client.py` (from Task 6) — the method signatures to assert dispatch against.
- `docs/specs/2026-09-19-voice-music-agent-harness.md:199-210` — the tool table and the "none of them decide" consequence.
**Anchors:** (from Task 8)
- `def build_server(client: MuseClient) -> Server` @ `harness/cadence/muse/mcp_server.py` (from Task 8)
- `TOOL_NAMES: tuple[str, ...]` @ `harness/cadence/muse/mcp_server.py` (from Task 8)
**Steps:**
1. `test_tool_names_are_exactly_the_eight` — asserts `sorted(TOOL_NAMES)` equals
   `["get_dashboard", "get_player_state", "play", "rate", "recommend_next", "search_text", "search_vibe", "set_player_state"]`.
2. `test_listed_tools_match_tool_names` — lists tools from the built server and asserts the set of
   listed names equals `set(TOOL_NAMES)`.
3. `test_every_tool_has_a_description_and_schema` — for each listed tool, asserts a non-empty
   description and an `inputSchema` whose `type` is `"object"`.
4. `test_search_vibe_schema_requires_query` — asserts `search_vibe`'s schema has properties
   `query` and `n` and requires `query`.
5. `test_rate_schema_constrains_rating` — asserts `rate`'s schema requires `track_rowid` and
   `rating`, and that the `rating` property enumerates `-1` and `1`.
6. `test_call_search_vibe_dispatches_to_client` — with a stub `MuseClient` recording calls, calls
   the `search_vibe` tool with `{"query": "chill", "n": 3}` and asserts the stub saw
   `search_vibe("chill", 3)` exactly once.
7. `test_call_play_dispatches_to_client` — calls `play` with `{"track_rowid": 123458861}` and
   asserts the stub saw `play(123458861)`.
8. `test_muse_unavailable_surfaces_as_tool_error` — the stub raises `MuseUnavailable`; assert the
   tool result is an error carrying the exception text, and that the stub was called exactly once
   (no retry).
**New symbols:** none (test functions only).
**Verify:** `cd harness && .venv/bin/python -m pytest tests/test_muse_mcp_server.py -q` — expected: exit 2, `1 error`, a collection error reading `ModuleNotFoundError: No module named 'cadence.muse.mcp_server'`. Red is the correct outcome here.
**Forbidden:** do not create `harness/cadence/muse/mcp_server.py`; do not edit `harness/cadence/muse/client.py`; no real network call.
**Depends:** Task 6.
**Why:** The eight-name assertion is the frozen surface. If a ninth tool is ever added, this test is the thing that must be edited deliberately — which is the point.

### Task 8: Implement the Muse MCP server
- [ ] status
**Objective:** An MCP stdio server exposing the eight Muse tools, each a thin pass-through to `MuseClient`.
**Write-scope:**
- `harness/cadence/muse/mcp_server.py` (new)
- `harness/cadence/muse/__main__.py` (new)
**Read-context:**
- `harness/tests/test_muse_mcp_server.py` (from Task 7) — the contract.
- `harness/cadence/muse/client.py` (from Task 6) — the methods being wrapped.
- `docs/preflight/runtime.md` (from Task 2) — confirms which `mcp` version imported.
**Anchors:**
- `class MuseClient:` @ `harness/cadence/muse/client.py` (from Task 6)
- `class MuseUnavailable(Exception)` @ `harness/cadence/muse/client.py` (from Task 6)
**Steps:**
1. Define `TOOL_NAMES` as a tuple in this exact order: `("search_vibe", "search_text", "recommend_next", "play", "get_player_state", "set_player_state", "get_dashboard", "rate")`.
2. Write `build_server(client)` returning an `mcp` `Server` named `"muse"`, registering a
   list-tools handler that returns one tool per name with a JSON schema mirroring the matching
   `MuseClient` signature, and a call-tool handler dispatching by name.
3. Each tool description states what it returns and, in one clause, that it does not choose —
   e.g. `search_vibe`: `"Return ranked candidate tracks matching a vibe. Returns candidates for you to choose between; it does not pick one."`
4. `rate`'s schema gives `rating` an `enum` of `[-1, 1]`.
5. Catch `MuseUnavailable` in the call-tool handler and return an MCP tool error carrying
   `str(exc)`. Do not catch anything else, and never retry.
6. Write `harness/cadence/muse/__main__.py` so `python -m cadence.muse` builds a `MuseClient` from
   the default base URLs and serves `build_server` over stdio.
**New symbols:**
- `TOOL_NAMES: tuple[str, ...]`
- `def build_server(client: MuseClient) -> Server`
**Verify:** `cd harness && .venv/bin/python -m pytest tests/test_muse_mcp_server.py -q` — expected: 8 passed.
**Forbidden:** no new deps; no tool that performs more than one `MuseClient` call; no composite `play_by_vibe` tool — the spec withdrew it explicitly; do not edit the test file or `client.py`.
**Depends:** Task 7.
**Why:** The seam the whole "adding a tool never touches the core loop" Must rests on. Thin wrappers only — a tool that picks a track destroys the judgment the 3-call loop exists to preserve.

**Phase 2 gate:** `cd harness && .venv/bin/python -m pytest tests/ -q` is fully green, and
`.venv/bin/python -m cadence.muse` starts without traceback (kill it after one second).

---

## Phase 3 — Store, routines, context, session

### Task 9: Write SQLite store tests [test]
- [ ] status
**Objective:** A red test file covering diary and routine persistence, queries, and burn.
**Write-scope:** `harness/tests/test_store.py` (new)
**Read-context:** `docs/specs/2026-09-19-voice-music-agent-harness.md:127-134` — the diary-storage decision: harness-owned SQLite, decisions and context only, Muse track IDs referenced not copied.
**Anchors:** (from Task 10)
- `class Store:` @ `harness/cadence/store.py` (from Task 10)
- `def __init__(self, path: str)` (from Task 10)
- `def log_decision(self, asked: str, chosen: list[int], rejected: list[int], why: str, at: float) -> int` (from Task 10)
- `def query_decisions(self, since: float, until: float) -> list[dict]` (from Task 10)
- `def burn(self) -> None` (from Task 10)
- `def save_routine(self, name: str, trigger_type: str, trigger_value: str, steps: list[dict]) -> int` (from Task 10)
- `def list_routines(self) -> list[dict]` (from Task 10)
- `def delete_routine(self, routine_id: int) -> None` (from Task 10)
- `def due_routines(self, now: float) -> list[dict]` (from Task 10)
**Steps:**
1. Every test uses a `tmp_path` database file — never the default path.
2. `test_schema_has_two_tables` — asserts `sqlite_master` contains exactly the tables `decisions` and `routines`.
3. `test_log_and_query_decision_roundtrip` — logs one decision and reads it back with matching `asked`, `chosen`, `rejected`, `why`.
4. `test_query_decisions_respects_window` — logs three decisions at timestamps 1000.0, 2000.0, 3000.0; asserts `query_decisions(1500.0, 2500.0)` returns exactly the 2000.0 one.
5. `test_decisions_store_track_ids_not_track_data` — asserts the `decisions` table has no column whose name contains `track_name`, `artist`, or `album`.
6. `test_burn_empties_decisions_but_keeps_routines` — logs a decision and saves a routine, calls `burn()`, asserts `query_decisions(0.0, 9e9)` is empty and `list_routines()` still returns the routine.
7. `test_save_and_list_routine_roundtrip` — saves a routine with `trigger_type` `"utterance"` and steps `[{"tool": "search_vibe", "args": {"query": "chill"}}]`; asserts the steps come back as the same structure.
8. `test_routine_trigger_type_is_constrained` — asserts `save_routine` with `trigger_type="whenever"` raises `ValueError`; only `"utterance"` and `"schedule"` are legal.
9. `test_delete_routine_removes_it` — saves two, deletes one, asserts one remains.
10. `test_due_routines_returns_only_past_schedules` — saves two schedule routines with `trigger_value` `"1000.0"` and `"3000.0"` and one utterance routine; asserts `due_routines(2000.0)` returns exactly the 1000.0 one.
**New symbols:** none (test functions only).
**Verify:** `cd harness && .venv/bin/python -m pytest tests/test_store.py -q` — expected: exit 2, `1 error`, a collection error reading `ModuleNotFoundError: No module named 'cadence.store'`. Red is the correct outcome here.
**Forbidden:** do not create `harness/cadence/store.py`; never write to `harness/cadence.sqlite3`; no new deps.
**Depends:** Task 1.
**Why:** Test-first. Test 5 and test 6 are the executable form of two PRD Refusals — the harness owns context not taste, and burn must be one command that never touches Muse.

### Task 10: Implement the SQLite store
- [ ] status
**Objective:** `Store` persists decisions and routines in one harness-owned SQLite file with two tables.
**Write-scope:** `harness/cadence/store.py` (new)
**Read-context:** `harness/tests/test_store.py` (from Task 9) — the contract, in full.
**Anchors:** none.
**Steps:**
1. On `__init__`, connect with `sqlite3` and create both tables if absent.
2. `decisions` columns: `id INTEGER PRIMARY KEY`, `at REAL NOT NULL`, `asked TEXT NOT NULL`,
   `chosen TEXT NOT NULL`, `rejected TEXT NOT NULL`, `why TEXT NOT NULL`. `chosen` and `rejected`
   hold JSON arrays of Muse `track_rowid` integers — no track names, artists, or albums.
3. `routines` columns: `id INTEGER PRIMARY KEY`, `name TEXT NOT NULL`, `trigger_type TEXT NOT NULL`,
   `trigger_value TEXT NOT NULL`, `steps TEXT NOT NULL` (JSON array), `created_at REAL NOT NULL`.
4. `save_routine` raises `ValueError` unless `trigger_type` is `"utterance"` or `"schedule"`.
5. `query_decisions(since, until)` selects rows with `since <= at <= until`, ordered by `at`
   ascending, decoding the JSON columns back to lists.
6. `burn()` deletes every row from `decisions` only, then `VACUUM`s. It must not touch `routines`
   and must issue no HTTP call.
7. `due_routines(now)` selects `trigger_type = 'schedule'` rows whose `float(trigger_value)` is
   less than or equal to `now`.
**New symbols:**
- `class Store:`
- `def __init__(self, path: str)`
- `def log_decision(self, asked: str, chosen: list[int], rejected: list[int], why: str, at: float) -> int`
- `def query_decisions(self, since: float, until: float) -> list[dict]`
- `def burn(self) -> None`
- `def save_routine(self, name: str, trigger_type: str, trigger_value: str, steps: list[dict]) -> int`
- `def list_routines(self) -> list[dict]`
- `def delete_routine(self, routine_id: int) -> None`
- `def due_routines(self, now: float) -> list[dict]`
**Verify:** `cd harness && .venv/bin/python -m pytest tests/test_store.py -q` — expected: 9 passed.
**Forbidden:** no new deps — stdlib `sqlite3` and `json` only; no ORM; do not add a third table; do not copy Muse track metadata into any column; do not edit the test file.
**Depends:** Task 9.
**Why:** One file, two tables, so "burn it" is a single delete that can never endanger Muse's library.

### Task 11: Write routine matcher tests [test]
- [ ] status
**Objective:** A red test file covering utterance matching, misses, crystallization, and correction-driven invalidation.
**Write-scope:** `harness/tests/test_routines.py` (new)
**Read-context:**
- `harness/cadence/store.py` (from Task 10) — `save_routine` / `list_routines` shapes.
- `docs/specs/2026-09-19-voice-music-agent-harness.md:70-75` — routines are a cache, matching is deliberately dumb, corrections must bust the cache.
**Anchors:** (from Task 12)
- `def normalize(text: str) -> str` @ `harness/cadence/routines.py` (from Task 12)
- `def match(store: Store, text: str) -> dict | None` @ `harness/cadence/routines.py` (from Task 12)
- `def crystallize(store: Store, text: str, steps: list[dict]) -> int` @ `harness/cadence/routines.py` (from Task 12)
- `def invalidate(store: Store, text: str) -> int` @ `harness/cadence/routines.py` (from Task 12)
**Steps:**
1. Every test builds a `Store` on a `tmp_path` database.
2. `test_normalize_lowercases_and_strips_punctuation` — asserts `normalize("  Play Something CHILL! ")` equals `"play something chill"`.
3. `test_normalize_collapses_whitespace` — asserts `normalize("play   something\tchill")` equals `"play something chill"`.
4. `test_exact_normalized_match_hits` — crystallizes `"Play something chill"`, then asserts `match(store, "play something CHILL!")` returns that routine.
5. `test_different_wording_misses` — after the same crystallization, asserts `match(store, "put on something mellow")` returns `None`. Matching is exact-on-normalized by design; do not add fuzzy matching to make this pass.
6. `test_schedule_routines_never_match_utterances` — saves a `"schedule"` routine whose name is `"play something chill"`; asserts `match(store, "play something chill")` returns `None`.
7. `test_crystallize_is_idempotent` — crystallizes the same text twice with different steps; asserts `list_routines()` has exactly one utterance routine and it holds the second steps.
8. `test_invalidate_removes_matching_routine` — crystallizes, calls `invalidate(store, "play something chill")`, asserts it returns 1 and `match` now returns `None`.
9. `test_invalidate_returns_zero_when_nothing_matches` — asserts `invalidate(store, "nothing like this")` returns 0 and raises nothing.
**New symbols:** none (test functions only).
**Verify:** `cd harness && .venv/bin/python -m pytest tests/test_routines.py -q` — expected: exit 2, `1 error`, a collection error reading `ModuleNotFoundError: No module named 'cadence.routines'`. Red is the correct outcome here.
**Forbidden:** do not create `harness/cadence/routines.py`; no new deps; do not import any embedding or similarity library.
**Depends:** Task 10.
**Why:** Test 5 pins the dumb-matching decision so no executor "improves" it into the fuzzy-intent project the spec rules out.

### Task 12: Implement the routine matcher
- [ ] status
**Objective:** `routines` matches an utterance against the store, crystallizes a resolved path, and invalidates on correction.
**Write-scope:** `harness/cadence/routines.py` (new)
**Read-context:** `harness/tests/test_routines.py` (from Task 11) — the contract, in full.
**Anchors:**
- `class Store:` @ `harness/cadence/store.py` (from Task 10)
- `def save_routine(self, name: str, trigger_type: str, trigger_value: str, steps: list[dict]) -> int` @ `harness/cadence/store.py` (from Task 10)
- `def list_routines(self) -> list[dict]` @ `harness/cadence/store.py` (from Task 10)
- `def delete_routine(self, routine_id: int) -> None` @ `harness/cadence/store.py` (from Task 10)
**Steps:**
1. `normalize` lowercases, removes every character that is neither alphanumeric nor whitespace,
   collapses runs of whitespace to one space, and strips the ends.
2. `match` reads `list_routines()`, keeps only `trigger_type == "utterance"`, and returns the first
   whose `trigger_value` equals `normalize(text)`. Returns `None` on no match. No fuzzy scoring.
3. `crystallize` computes `key = normalize(text)`, deletes any existing utterance routine with that
   `trigger_value`, then saves a new one with `name = text`, `trigger_type = "utterance"`,
   `trigger_value = key`, and the given steps. Returns the new routine id.
4. `invalidate` deletes every utterance routine whose `trigger_value` equals `normalize(text)` and
   returns the number deleted.
**New symbols:**
- `def normalize(text: str) -> str`
- `def match(store: Store, text: str) -> dict | None`
- `def crystallize(store: Store, text: str, steps: list[dict]) -> int`
- `def invalidate(store: Store, text: str) -> int`
**Verify:** `cd harness && .venv/bin/python -m pytest tests/test_routines.py -q` — expected: 8 passed.
**Forbidden:** no new deps; no fuzzy, embedding, or edit-distance matching of any kind; do not edit `store.py` or the test file.
**Depends:** Task 11.
**Why:** The cache in front of the LLM. Every hit is a turn that costs zero model calls, which is the whole point of the routines decision.

### Task 13: Implement the context provider seam
- [ ] status
**Objective:** A `ContextProvider` interface plus a `SqliteContextProvider` that contributes a system prompt, prefetches pre-turn, and syncs post-turn.
**Write-scope:** `harness/cadence/context.py` (new)
**Read-context:**
- `harness/cadence/store.py` (from Task 10) — `query_decisions` and `log_decision`.
- `docs/specs/2026-09-19-voice-music-agent-harness.md:135-147` — the provider seam and the shared-context decision (~10 turns, in memory, lost on restart).
**Anchors:**
- `class Store:` @ `harness/cadence/store.py` (from Task 10)
- `def query_decisions(self, since: float, until: float) -> list[dict]` @ `harness/cadence/store.py` (from Task 10)
- `def log_decision(self, asked: str, chosen: list[int], rejected: list[int], why: str, at: float) -> int` @ `harness/cadence/store.py` (from Task 10)
**Steps:**
1. Define `CONTEXT_TURNS = 10`.
2. Define `ContextProvider` as an abstract base with three methods: `build_system_prompt() -> str`,
   `prefetch(text: str) -> str`, `sync(asked: str, chosen: list[int], rejected: list[int], why: str) -> None`.
3. Implement `SqliteContextProvider(ContextProvider)` taking a `Store`. `build_system_prompt`
   returns the harness persona text: a short paragraph stating it runs the user's music, keeps
   replies to a sentence or two because they are spoken aloud, reports tool failures instead of
   retrying, and never writes code. `prefetch` returns a compact digest of the last 7 days of
   decisions from `query_decisions` — at most 10 lines, each `asked -> chosen ids`. `sync` calls
   `log_decision` with `time.time()`.
4. Implement `RollingContext` holding a `collections.deque` of role/content dicts capped at
   `CONTEXT_TURNS * 2` entries, with `append(role, content)` and `messages() -> list[dict]`. It is
   in-memory only and is never persisted.
**New symbols:**
- `CONTEXT_TURNS: int`
- `class ContextProvider(abc.ABC)`
- `class SqliteContextProvider(ContextProvider)`
- `class RollingContext:`
- `def append(self, role: str, content: str) -> None`
- `def messages(self) -> list[dict]`
**Verify:** `cd harness && .venv/bin/python -c "from cadence.context import SqliteContextProvider, RollingContext, CONTEXT_TURNS; c=RollingContext(); [c.append('user', str(i)) for i in range(50)]; assert len(c.messages()) == CONTEXT_TURNS*2, len(c.messages()); print('ok', CONTEXT_TURNS)"` — expected: prints `ok 10`.
**Forbidden:** no new deps; do not persist `RollingContext` to disk; do not import `sentence_transformers` — embeddings are a later provider, not this one.
**Depends:** Task 10.
**Why:** Keeps the memory strategy behind an interface so the SQLite provider can be swapped without touching the loop, as the spec's provider-seam decision requires.

### Task 14: Implement the session abstraction
- [ ] status
**Objective:** A `Session` type that makes ASR and TTS optional per session, so a text client runs the same turn path with no audio stages.
**Write-scope:** `harness/cadence/session.py` (new)
**Read-context:** `docs/specs/2026-09-19-voice-music-agent-harness.md:56-61` — the client-interface decision; text sessions have no audio stage, so ASR and TTS must be optional per session rather than fixed pipeline stages.
**Anchors:** none.
**Steps:**
1. Define `SessionCaps` as a frozen dataclass with `audio_in: bool`, `audio_out: bool`,
   `text_in: bool`, `text_out: bool`, and a classmethod `from_list(caps: list[str]) -> SessionCaps`
   that raises `ValueError` on an unknown capability string.
2. Define `Session` as a dataclass with `client_id: str`, `caps: SessionCaps`,
   `last_active: float`, and two async callables `send_audio(chunk: bytes)` and
   `send_text(content: str)`.
3. `Session.needs_asr` is a property returning `caps.audio_in`; `needs_tts` returns `caps.audio_out`.
4. Define `SessionRegistry` holding sessions by `client_id`, with `add`, `remove`,
   `get(client_id)`, and `most_recent_audio() -> Session | None` — the last one returns the
   `audio_out`-capable session with the highest `last_active`, or `None`.
**New symbols:**
- `class SessionCaps:`
- `def from_list(cls, caps: list[str]) -> SessionCaps`
- `class Session:`
- `class SessionRegistry:`
- `def most_recent_audio(self) -> Session | None`
**Verify:** `cd harness && .venv/bin/python -c "from cadence.session import SessionCaps, SessionRegistry; c=SessionCaps.from_list(['audio_in','audio_out']); assert c.audio_in and c.audio_out and not c.text_in; assert SessionRegistry().most_recent_audio() is None; print('ok')"` — expected: prints `ok`.
**Forbidden:** no new deps; do not import `fastapi` or `websockets` here — this module must stay transport-free; nothing ESP32-specific, Telegram-specific, or Muse-specific.
**Depends:** Task 1.
**Why:** `most_recent_audio` is what the scheduler in Task 22 uses to resolve a push target, and the caps flags are what let one turn path serve both a speaker and a text client.

**Phase 3 gate:** `cd harness && .venv/bin/python -m pytest tests/ -q` is fully green and all four
new modules import cleanly.

---

## Phase 4 — The turn path

### Task 15: Write agent-loop tests [test]
- [ ] status
**Objective:** A red test file pinning the 3-call cap, the no-retry rule, and the tool-failure-ends-turn rule.
**Write-scope:** `harness/tests/test_agent.py` (new)
**Read-context:**
- `docs/preflight/ollama.md` (from Task 3) — the real `tool_calls` response shape to build fakes from. Copy the shape; do not invent it.
- `docs/specs/2026-09-19-voice-music-agent-harness.md:63-68` — the loop-depth decision: cap 3, model sees results between calls, a failed tool ends the turn with a spoken report, never a retry.
**Anchors:** (from Task 16)
- `MAX_TOOL_CALLS: int` @ `harness/cadence/agent.py` (from Task 16)
- `async def run_turn(llm, tools, messages: list[dict]) -> TurnResult` @ `harness/cadence/agent.py` (from Task 16)
- `class TurnResult:` @ `harness/cadence/agent.py` (from Task 16)
**Steps:**
1. Build a fake `llm` whose `chat(messages, tools, think)` returns a scripted queue of responses,
   each shaped exactly like the one recorded in `docs/preflight/ollama.md`, and which records
   every call it received.
2. Build a fake `tools` object with `list_tools()` and `call(name, args)`.
3. `test_max_tool_calls_is_three` — asserts `MAX_TOOL_CALLS == 3`.
4. `test_zero_tool_turn_returns_text` — the fake LLM returns plain content with no tool calls;
   asserts `TurnResult.text` is that content, `TurnResult.tool_calls` is empty, and the LLM was
   called exactly once.
5. `test_two_hop_turn_feeds_results_back` — the LLM asks for one tool, then replies with text;
   asserts the second LLM call's messages include the tool result, and that `tool_calls` has
   length 1.
6. `test_cap_stops_at_three_calls` — the LLM asks for a tool every single time; asserts the tool
   was called exactly 3 times, the LLM was called exactly 4 times, and `TurnResult.capped` is `True`.
7. `test_tool_failure_ends_turn_without_retry` — the tool raises on its first call; asserts the
   tool was called exactly once, `TurnResult.failed_tool` names it, and `TurnResult.text` is
   non-empty so there is something to speak.
8. `test_llm_unreachable_raises` — the fake LLM raises `ConnectionError`; asserts it propagates and
   that no second LLM call was made. There is no local fallback.
9. `test_think_false_for_live_turns` — asserts every LLM call `run_turn` made passed `think=False`.
**New symbols:** none (test functions only).
**Verify:** `cd harness && .venv/bin/python -m pytest tests/test_agent.py -q` — expected: exit 2, `1 error`, a collection error reading `ModuleNotFoundError: No module named 'cadence.agent'`. Red is the correct outcome here.
**Forbidden:** do not create `harness/cadence/agent.py`; no real HTTP call to Ollama or Muse; do not soften any of the three caps into a warning.
**Depends:** Task 3, Task 8.
**Why:** Test-first. Tests 6, 7, and 8 are the executable form of the line between personal assistant and software engineer — cap, no recovery, no fallback.

### Task 16: Implement the agent loop and Ollama client
- [ ] status
**Objective:** `run_turn` drives a bounded tool-calling loop against `gemma4:31b-cloud` with `think: false`, capped at three tool calls, with no retry anywhere.
**Write-scope:**
- `harness/cadence/agent.py` (new)
- `harness/cadence/llm.py` (new)
- `harness/cadence/mcp_client.py` (new)
**Read-context:**
- `harness/tests/test_agent.py` (from Task 15) — the contract, in full.
- `docs/preflight/ollama.md` (from Task 3) — the real request and response field names. Copy them.
- `harness/cadence/muse/mcp_server.py` (from Task 8) — what the MCP client connects to.
**Anchors:**
- `TOOL_NAMES: tuple[str, ...]` @ `harness/cadence/muse/mcp_server.py` (from Task 8)
- `def build_server(client: MuseClient) -> Server` @ `harness/cadence/muse/mcp_server.py` (from Task 8)
**Steps:**
1. In `llm.py`, define `LLM_MODEL = "gemma4:31b-cloud"` and `OLLAMA_URL = "http://localhost:11434/api/chat"`.
   Implement `OllamaLLM.chat(messages, tools, think)` posting `{"model": LLM_MODEL, "messages": ..., "tools": ..., "stream": False, "think": think}` with `httpx`, one attempt, no retry. Raise
   `ConnectionError` on any transport failure and on an HTTP status that is not 200.
2. In `mcp_client.py`, implement `ToolRegistry` that launches configured MCP servers over stdio,
   exposes `list_tools()` as JSON schemas in Ollama's tool format, and `call(name, args)`
   dispatching to the owning server. Server commands come from a config list, not from any
   hardcoded reference to Muse — the registry must contain no Muse-specific symbol.
3. In `agent.py`, define `MAX_TOOL_CALLS = 3` and a `TurnResult` dataclass with fields
   `text: str`, `tool_calls: list[dict]`, `capped: bool`, `failed_tool: str | None`.
4. `run_turn` loops: call `llm.chat(messages, tools.list_tools(), think=False)`; if the response
   carries no tool calls, return a `TurnResult` with its content. Otherwise call each requested
   tool once, append its result to `messages` as a tool-role message, and loop.
5. On the `MAX_TOOL_CALLS`-th executed tool call, make one final `llm.chat` so the model can speak
   about what it has, then return with `capped=True`.
6. If a tool call raises, do not call it again and do not call any other tool. Make one final
   `llm.chat` with the failure appended as a tool-role message so the model can report it aloud,
   then return with `failed_tool` set to that tool's name.
7. Let `ConnectionError` from the LLM propagate untouched — no local model, no degraded mode.
**New symbols:**
- `LLM_MODEL: str` @ `llm.py`
- `OLLAMA_URL: str` @ `llm.py`
- `class OllamaLLM:` @ `llm.py`
- `async def chat(self, messages: list[dict], tools: list[dict], think: bool) -> dict` @ `llm.py`
- `class ToolRegistry:` @ `mcp_client.py`
- `async def list_tools(self) -> list[dict]` @ `mcp_client.py`
- `async def call(self, name: str, args: dict) -> dict` @ `mcp_client.py`
- `MAX_TOOL_CALLS: int` @ `agent.py`
- `class TurnResult:` @ `agent.py`
- `async def run_turn(llm, tools, messages: list[dict]) -> TurnResult` @ `agent.py`
**Verify:** `cd harness && .venv/bin/python -m pytest tests/test_agent.py -q` — expected: 7 passed.
**Forbidden:** no new deps; no retry, backoff, or reconnect on any path; no local model fallback; no `import` of anything under `cadence.muse` from `agent.py` or `mcp_client.py`; do not edit the test file.
**Depends:** Task 15.
**Why:** The core loop. It must stay protocol-bound and Muse-free, which is exactly what the import ban in Forbidden enforces.

### Task 17: Write mixer and ducking tests [test]
- [ ] status
**Objective:** A red test file pinning the ducking gain, the ramp, and int16 clipping.
**Write-scope:** `harness/tests/test_mixer.py` (new)
**Read-context:**
- `tools/voice_chat_host.py:157-172` — the existing PCM helpers and their int16 conventions.
- `docs/specs/2026-09-19-voice-music-agent-harness.md:99-104` — ducking, mixed server-side, both streams already s16le/44100/stereo.
**Anchors:** (from Task 18)
- `DUCK_GAIN: float` @ `harness/cadence/audio/mixer.py` (from Task 18)
- `DUCK_RAMP_MS: int` @ `harness/cadence/audio/mixer.py` (from Task 18)
- `def mix(music: bytes, speech: bytes, duck: float) -> bytes` @ `harness/cadence/audio/mixer.py` (from Task 18)
- `def ramp(frames: int, start: float, end: float) -> "np.ndarray"` @ `harness/cadence/audio/mixer.py` (from Task 18)
**Steps:**
1. `test_constants` — asserts `DUCK_GAIN == 0.25` and `DUCK_RAMP_MS == 150`.
2. `test_mix_with_no_speech_returns_music_unchanged` — speech is all zeros and `duck` is 1.0;
   asserts the output bytes equal the music bytes exactly.
3. `test_mix_ducks_music_by_gain` — music is a constant 1000, speech is all zeros, `duck` is
   `DUCK_GAIN`; asserts every output sample equals 250.
4. `test_mix_sums_ducked_music_and_speech` — music constant 1000, speech constant 2000, `duck`
   `DUCK_GAIN`; asserts every output sample equals 2250.
5. `test_mix_clips_to_int16_range` — music constant 30000, speech constant 30000, `duck` 1.0;
   asserts every output sample equals 32767 and none wrapped negative.
6. `test_mix_requires_equal_lengths` — asserts a `ValueError` when music and speech byte lengths differ.
7. `test_ramp_endpoints_and_length` — asserts `ramp(100, 1.0, 0.25)` has length 100, its first
   element is 1.0 and its last is 0.25.
8. `test_ramp_is_monotonic_down` — asserts `np.all(np.diff(ramp(100, 1.0, 0.25)) <= 0)`.
**New symbols:** none (test functions only).
**Verify:** `cd harness && .venv/bin/python -m pytest tests/test_mixer.py -q` — expected: exit 2, `1 error`, a collection error reading `ModuleNotFoundError: No module named 'cadence.audio.mixer'`. Red is the correct outcome here.
**Forbidden:** do not create `harness/cadence/audio/mixer.py`; no new deps; no audio file I/O — build every buffer with numpy.
**Depends:** Task 1.
**Why:** Test-first. Test 5 is the one that matters: int16 overflow wraps to loud noise, which is the audible way "never breaks the mood" fails.

### Task 18: Implement the mixer
- [ ] status
**Objective:** `mix` combines ducked music with speech into clipped s16le stereo, with a linear gain ramp.
**Write-scope:** `harness/cadence/audio/mixer.py` (new)
**Read-context:**
- `harness/tests/test_mixer.py` (from Task 17) — the contract, in full.
- `tools/voice_chat_host.py:161-172` — the int16 conversion and clipping idiom already used in this repo.
**Anchors:**
- `def kokoro_audio_to_i2s_pcm(samples: np.ndarray, src_rate: int) -> bytes` @ `tools/voice_chat_host.py`
- `def silence_chunk(ms: int) -> bytes` @ `tools/voice_chat_host.py`
**Steps:**
1. Define `SPK_SAMPLE_RATE = 44100`, `SPK_CHANNELS = 2`, `DUCK_GAIN = 0.25`, `DUCK_RAMP_MS = 150`.
2. `mix(music, speech, duck)` raises `ValueError` when the two byte lengths differ. It reads both
   as `int16`, promotes to `int32`, computes `music * duck + speech`, clips to
   `[-32768, 32767]`, casts back to `int16`, and returns bytes.
3. `ramp(frames, start, end)` returns `np.linspace(start, end, frames, dtype=np.float32)`.
4. Add `duck_frames()` returning `SPK_SAMPLE_RATE * DUCK_RAMP_MS // 1000`.
**New symbols:**
- `SPK_SAMPLE_RATE: int`
- `SPK_CHANNELS: int`
- `DUCK_GAIN: float`
- `DUCK_RAMP_MS: int`
- `def mix(music: bytes, speech: bytes, duck: float) -> bytes`
- `def ramp(frames: int, start: float, end: float) -> "np.ndarray"`
- `def duck_frames() -> int`
**Verify:** `cd harness && .venv/bin/python -m pytest tests/test_mixer.py -q` — expected: 8 passed.
**Forbidden:** no new deps beyond numpy; no resampling here — both inputs are already 44100 Hz stereo; do not pause or stop music on speech, the spec chose ducking; do not edit the test file.
**Depends:** Task 17.
**Why:** Arithmetic, not a project — both streams already share a format, which is exactly why the spec chose mixing over pausing.

### Task 19: Port the audio stages into the harness package
- [ ] status
**Objective:** VAD segmentation, ASR, TTS, and the sentence chunker live in `cadence.audio` as reusable stages independent of any transport.
**Write-scope:**
- `harness/cadence/audio/chunker.py` (new)
- `harness/cadence/audio/vad.py` (new)
- `harness/cadence/audio/asr.py` (new)
- `harness/cadence/audio/tts.py` (new)
**Read-context:**
- `tools/voice_chat_host.py:50-85` — the frame, VAD, and model constants to carry over verbatim.
- `tools/voice_chat_host.py:88-152` — `PatchedKokoro` and the sentence chunker to port.
- `tools/voice_chat_host.py:201-253` — how ASR and TTS are called today, including the `no_speech_prob` floor.
- `tools/voice_chat_host.py:265-316` — the VAD state machine to extract.
- `docs/preflight/runtime.md` (from Task 2) — confirms these libraries load on this venv.
**Anchors:**
- `class SentenceChunker:` @ `tools/voice_chat_host.py`
- `def _find_boundary(text: str, start: int)` @ `tools/voice_chat_host.py`
- `class PatchedKokoro(Kokoro)` @ `tools/voice_chat_host.py`
- `def kokoro_audio_to_i2s_pcm(samples: np.ndarray, src_rate: int) -> bytes` @ `tools/voice_chat_host.py`
- `def pcm16_bytes_to_float32(pcm: bytes) -> np.ndarray` @ `tools/voice_chat_host.py`
- `NO_SPEECH_PROB_MAX = 0.6` @ `tools/voice_chat_host.py`
**Steps:**
1. `chunker.py`: copy `_find_boundary`, `SentenceChunker`, and `MIN_SENTENCE_LEN = 8` verbatim from
   `tools/voice_chat_host.py:117-152`. Change nothing about the algorithm.
2. `vad.py`: extract the state machine from `tools/voice_chat_host.py:265-316` into
   `VadSegmenter`, carrying over `MIC_SAMPLE_RATE = 16000`, `FRAME_MS = 30`,
   `FRAME_BYTES = MIC_SAMPLE_RATE * FRAME_MS // 1000 * 2`, `VAD_START_FRAMES = 10`,
   `VAD_END_FRAMES = 16`, `MIN_UTTERANCE_BYTES = FRAME_BYTES * 16`, and `webrtcvad.Vad(3)`.
   `feed(data: bytes) -> list[bytes]` accumulates bytes and returns zero or more completed
   utterances. It owns no socket and no mute window — the mute logic stays behind in the legacy
   host because ducking replaced it.
3. `asr.py`: `Asr` loads `WhisperModel("small.en", device="cpu", compute_type="int8")` once.
   `transcribe(pcm: bytes) -> str` converts with `pcm16_bytes_to_float32`, calls
   `transcribe(audio, beam_size=5, vad_filter=True)`, joins segments whose `no_speech_prob` is
   below `NO_SPEECH_PROB_MAX = 0.6`, and strips.
4. `tts.py`: copy `PatchedKokoro` verbatim, plus `kokoro_audio_to_i2s_pcm` and `silence_chunk`.
   `Tts.__init__` takes explicit model and voices paths, defaulting to the repo's
   `tools/kokoro-v1.0.onnx` and `tools/voices-v1.0.bin`. `speak(text: str) -> bytes` returns
   44100 Hz stereo s16le bytes using voice `af_sarah`.
**New symbols:**
- `MIN_SENTENCE_LEN: int`, `class SentenceChunker:` @ `chunker.py`
- `MIC_SAMPLE_RATE: int`, `FRAME_BYTES: int`, `class VadSegmenter:`, `def feed(self, data: bytes) -> list[bytes]` @ `vad.py`
- `NO_SPEECH_PROB_MAX: float`, `class Asr:`, `def transcribe(self, pcm: bytes) -> str` @ `asr.py`
- `class PatchedKokoro(Kokoro)`, `class Tts:`, `def speak(self, text: str) -> bytes` @ `tts.py`
**Verify:** `cd harness && .venv/bin/python -c "from cadence.audio.chunker import SentenceChunker; from cadence.audio.vad import VadSegmenter, FRAME_BYTES; from cadence.audio.asr import NO_SPEECH_PROB_MAX; from cadence.audio.tts import Tts; c=SentenceChunker(); assert c.feed('Hello there. Next one. ') == ['Hello there. ', 'Next one. '], c.feed(''); assert FRAME_BYTES == 960; assert NO_SPEECH_PROB_MAX == 0.6; print('ok')"` — expected: prints `ok`.
**Forbidden:** no new deps; do not edit, move, or delete `tools/voice_chat_host.py` — it stays runnable; do not port the `MUTE_MARGIN_S` mute window; do not change the chunker algorithm or the `no_speech_prob` floor; do not import `fastapi` or `websockets` in any of these four modules.
**Depends:** Task 2.
**Why:** These stages are proven on the bench and must arrive in the harness unchanged, so an M1 audio regression can only come from new code, never from a silent rewrite of working code.

### Task 20: Wire the WebSocket server and turn path
- [ ] status
**Objective:** A FastAPI WebSocket server on port 8768 that runs the full turn path — hello, VAD, ASR, routine lookup, agent loop, TTS, mix, stream out — for audio sessions, and the same path without ASR and TTS for text sessions.
**Write-scope:**
- `harness/cadence/server.py` (new)
- `harness/cadence/config.py` (new)
- `harness/cadence/__main__.py` (new)
**Read-context:**
- The "WebSocket session protocol" section of this plan — normative; Task 23 implements the other side of it.
- `harness/cadence/session.py` (from Task 14) — `SessionCaps`, `SessionRegistry`.
- `harness/cadence/agent.py` (from Task 16) — `run_turn`, `TurnResult`.
- `harness/cadence/routines.py` (from Task 12) — `match`, `crystallize`.
- `harness/cadence/audio/mixer.py` (from Task 18) — `mix`, `DUCK_GAIN`.
- `harness/cadence/context.py` (from Task 13) — `RollingContext`, `SqliteContextProvider`.
**Anchors:**
- `async def run_turn(llm, tools, messages: list[dict]) -> TurnResult` @ `harness/cadence/agent.py` (from Task 16)
- `class SessionRegistry:` @ `harness/cadence/session.py` (from Task 14)
- `def from_list(cls, caps: list[str]) -> SessionCaps` @ `harness/cadence/session.py` (from Task 14)
- `def match(store: Store, text: str) -> dict | None` @ `harness/cadence/routines.py` (from Task 12)
- `def mix(music: bytes, speech: bytes, duck: float) -> bytes` @ `harness/cadence/audio/mixer.py` (from Task 18)
- `class RollingContext:` @ `harness/cadence/context.py` (from Task 13)
- `class VadSegmenter:` @ `harness/cadence/audio/vad.py` (from Task 19)
- `class Asr:` @ `harness/cadence/audio/asr.py` (from Task 19)
- `class Tts:` @ `harness/cadence/audio/tts.py` (from Task 19)
- `class SentenceChunker:` @ `harness/cadence/audio/chunker.py` (from Task 19)
**Steps:**
1. `config.py` holds `WS_PORT = 8768`, `DB_PATH = "cadence.sqlite3"`, `MCP_SERVERS = [["python", "-m", "cadence.muse"]]`, and the Muse base URLs. Nothing else imports a hardcoded URL.
2. `server.py` builds one `FastAPI` app with a `@app.websocket("/session")` endpoint.
3. On connect, read the first text frame, parse `hello`, build `SessionCaps.from_list`, register a
   `Session` whose `send_audio` and `send_text` write binary and text frames back. Reject an
   unparseable hello with an `{"type":"error"}` frame and close.
4. Hold one global `asyncio.Lock` named `TURN_LOCK`. Every turn acquires it; background work must
   acquire it too, so a user turn and a scheduler tick can never both hold the single concurrency
   slot. Expose it as a module-level symbol so Task 22 uses the same lock object.
5. Audio session loop: feed every binary frame to `VadSegmenter.feed`; for each completed
   utterance, run `Asr.transcribe`. Skip empty transcriptions.
6. Text session loop: take `{"type":"text"}` frames' `content` directly as the turn text; run no
   ASR and no TTS for that session.
7. For each turn text: send `{"type":"turn_start"}`; look up `routines.match`. On a hit, execute
   its steps through the `ToolRegistry` with zero LLM calls. On a miss, append to `RollingContext`,
   build messages from the provider's system prompt plus prefetch plus the rolling messages, and
   call `run_turn`.
8. Stream the reply: feed `TurnResult.text` through `SentenceChunker`; for each sentence, if
   `session.needs_tts`, `Tts.speak` it and send the bytes — mixed via `mix(music_chunk, speech, DUCK_GAIN)`
   when that session has music playing, or sent directly when it does not. If the session is text,
   send `{"type":"text","content": ...}` instead.
9. Catch `ConnectionError` from the LLM and `MuseUnavailable` from a tool, send
   `{"type":"error","message": str(exc)}`, and end the turn. Never retry either one.
10. Send `{"type":"turn_end"}`, then `provider.sync(...)` the decision.
11. `__main__.py` runs `uvicorn.run(app, host="0.0.0.0", port=WS_PORT)`.
**New symbols:**
- `WS_PORT: int`, `DB_PATH: str`, `MCP_SERVERS: list[list[str]]` @ `config.py`
- `TURN_LOCK: asyncio.Lock` @ `server.py`
- `app: FastAPI` @ `server.py`
- `async def session_endpoint(ws)` @ `server.py`
- `async def handle_turn(session, text) -> None` @ `server.py`
**Verify:** `cd harness && .venv/bin/python -c "from cadence.server import app, TURN_LOCK; from cadence.config import WS_PORT; assert WS_PORT == 8768; routes=[getattr(r,'path','') for r in app.routes]; assert '/session' in routes, routes; print('ok')"` — expected: prints `ok`.
**Forbidden:** no new deps; do not import anything from `cadence.muse` in `server.py` — tools reach it only through `ToolRegistry`; no retry on LLM or tool failure; do not run ASR or TTS for a session whose caps exclude them; do not change the protocol defined in this plan's header.
**Depends:** Task 12, Task 13, Task 14, Task 16, Task 18, Task 19.
**Why:** The one place the pieces meet. `TURN_LOCK` is the concurrency-1 rule made real, and the caps check is what keeps one turn path serving both a speaker and a text client.

**Phase 4 gate:** `cd harness && .venv/bin/python -m pytest tests/ -q` fully green, and
`.venv/bin/python -m cadence` starts and binds port 8768 without traceback (kill after two seconds).

---

## Phase 5 — Scheduler, firmware, docs

### Task 21: Write scheduler tests [test]
- [ ] status
**Objective:** A red test file pinning due-routine detection, the yield-to-user-turn rule, and the v1 no-speak rule.
**Write-scope:** `harness/tests/test_scheduler.py` (new)
**Read-context:**
- `harness/cadence/store.py` (from Task 10) — `due_routines`, `save_routine`.
- `harness/cadence/session.py` (from Task 14) — `SessionRegistry.most_recent_audio`.
- `docs/specs/2026-09-19-voice-music-agent-harness.md:77-82` — the scheduled-routines decision, including that a v1 scheduled routine may start music but must not speak, and that a due routine yields to an in-flight turn.
**Anchors:** (from Task 22)
- `class Scheduler:` @ `harness/cadence/scheduler.py` (from Task 22)
- `async def tick(self, now: float) -> list[int]` @ `harness/cadence/scheduler.py` (from Task 22)
- `def is_speaking_step(step: dict) -> bool` @ `harness/cadence/scheduler.py` (from Task 22)
**Steps:**
1. Every test builds a `Store` on a `tmp_path` database and a `SessionRegistry` with one stub
   audio session recording what it was sent.
2. `test_tick_executes_due_routine` — one schedule routine at `trigger_value` `"1000.0"` with a
   `play` step; asserts `tick(2000.0)` returns that routine's id and the stub session received audio.
3. `test_tick_skips_future_routine` — one at `"3000.0"`; asserts `tick(2000.0)` returns an empty list.
4. `test_tick_yields_when_turn_lock_held` — acquire `TURN_LOCK` first; asserts `tick(2000.0)` returns an empty list and the stub session received nothing.
5. `test_tick_uses_zero_llm_calls` — a fake LLM that raises if called at all; asserts `tick(2000.0)` completes and the fake was never called.
6. `test_speaking_step_is_rejected_in_v1` — a routine whose steps include `{"say": "good morning"}`; asserts `is_speaking_step` is `True` for it and that `tick` skips the routine and sends no audio.
7. `test_no_audio_session_means_no_execution` — an empty registry; asserts `tick(2000.0)` returns an empty list and raises nothing.
**New symbols:** none (test functions only).
**Verify:** `cd harness && .venv/bin/python -m pytest tests/test_scheduler.py -q` — expected: exit 2, `1 error`, a collection error reading `ModuleNotFoundError: No module named 'cadence.scheduler'`. Red is the correct outcome here.
**Forbidden:** do not create `harness/cadence/scheduler.py`; no real timers or `sleep` in any test — call `tick(now)` directly with an explicit timestamp; no new deps.
**Depends:** Task 20.
**Why:** Test-first. Test 4 is the executable form of the concurrency-1 rule, and test 6 is the proactive-speech deferral — the only thing stopping v1 from talking to an empty room.

### Task 22: Implement the scheduler
- [ ] status
**Objective:** A tick-driven evaluator that executes due schedule-triggered routines through the same path a cache hit uses, yielding to any in-flight user turn.
**Write-scope:** `harness/cadence/scheduler.py` (new)
**Read-context:**
- `harness/tests/test_scheduler.py` (from Task 21) — the contract, in full.
- `harness/cadence/server.py` (from Task 20) — `TURN_LOCK`, and the routine-hit execution path to reuse.
**Anchors:**
- `TURN_LOCK: asyncio.Lock` @ `harness/cadence/server.py` (from Task 20)
- `def due_routines(self, now: float) -> list[dict]` @ `harness/cadence/store.py` (from Task 10)
- `def most_recent_audio(self) -> Session | None` @ `harness/cadence/session.py` (from Task 14)
**Steps:**
1. `Scheduler.__init__(self, store, registry, tools, tick_seconds: float = 30.0)`.
2. `is_speaking_step(step)` returns `True` when the step dict has a `"say"` key. v1 routines may
   start music but must not speak.
3. `tick(now)` returns immediately with an empty list when `TURN_LOCK.locked()` — a user turn wins.
4. Otherwise acquire `TURN_LOCK`, read `store.due_routines(now)`, and for each: skip it if any of
   its steps satisfies `is_speaking_step`; resolve a target with `registry.most_recent_audio()` and
   skip it if that is `None`; otherwise execute its steps through the `ToolRegistry` with zero LLM
   calls and stream the resulting audio to the target session.
5. Return the list of executed routine ids. Release the lock in a `finally`.
6. `run_forever()` loops `tick(time.time())` then `await asyncio.sleep(self.tick_seconds)`.
**New symbols:**
- `class Scheduler:`
- `def is_speaking_step(step: dict) -> bool`
- `async def tick(self, now: float) -> list[int]`
- `async def run_forever(self) -> None`
**Verify:** `cd harness && .venv/bin/python -m pytest tests/test_scheduler.py -q` — expected: 6 passed.
**Forbidden:** no new deps; no LLM call anywhere in this module; no spoken output in v1 — a step with a `"say"` key is skipped, never synthesized; do not create a second lock, import `TURN_LOCK` from `server.py`; do not edit the test file.
**Depends:** Task 21.
**Why:** The only component that originates a session rather than receiving one, which is why target resolution and the lock check both live here.

### Task 23: Rewrite the firmware as a WebSocket client
- [ ] status
**Objective:** `voice_chat/` builds green with one bidirectional WebSocket client replacing the separate TCP mic upload and HTTP speak-stream tasks.
**Write-scope:**
- `voice_chat/main/voice_chat.c`
- `voice_chat/main/CMakeLists.txt`
- `voice_chat/main/Kconfig.projbuild`
- `voice_chat/main/idf_component.yml` (new)
- `voice_chat/sdkconfig.defaults`
**Read-context:**
- `voice_chat/main/voice_chat.c:1-124` — WiFi bring-up and both I2S init functions, which stay unchanged.
- `voice_chat/main/voice_chat.c:125-253` — the three tasks being replaced and `app_main`'s task creation.
- The "WebSocket session protocol" section of this plan — normative; Task 20 implements the server side.
**Anchors:**
- `static void speak_stream_task(void *arg)` @ `voice_chat/main/voice_chat.c`
- `static void mic_upload_task(void *arg)` @ `voice_chat/main/voice_chat.c`
- `static void i2s_drain_task(void *arg)` @ `voice_chat/main/voice_chat.c`
- `static int mic_connect(void)` @ `voice_chat/main/voice_chat.c`
- `static esp_err_t http_event_handler(esp_http_client_event_t *evt)` @ `voice_chat/main/voice_chat.c`
- `void app_main(void)` @ `voice_chat/main/voice_chat.c`
- `static void i2s_speaker_init(void)` @ `voice_chat/main/voice_chat.c`
- `static void i2s_mic_init(void)` @ `voice_chat/main/voice_chat.c`
**Steps:**
1. In `Kconfig.projbuild`, replace `VOICE_HOST_IP`, `VOICE_MIC_PORT`, and `VOICE_SPEAK_URL` with a
   single `VOICE_WS_URL` string, default `"ws://ianshomeserver:8768/session"`, and add
   `VOICE_CLIENT_ID` string, default `"speaker-1"`. Keep `VOICE_WIFI_SSID` and
   `VOICE_WIFI_PASSWORD` exactly as they are.
2. In `sdkconfig.defaults`, leave the two WiFi lines untouched and add nothing else — the two new
   options take their Kconfig defaults.
3. `esp_websocket_client` is **not** a core ESP-IDF v5.3 component — verified: `ls ~/esp/esp-idf/components | grep -i websocket` returns nothing. It ships from the component registry, latest `1.0.1`. Create `voice_chat/main/idf_component.yml` containing:
   ```yaml
   dependencies:
     espressif/esp_websocket_client: "^1.0.1"
   ```
   The first build downloads it into `voice_chat/managed_components/`, so this task needs network access.
4. In `CMakeLists.txt`, replace `esp_http_client` in `PRIV_REQUIRES` with `esp_websocket_client`
   and keep every other component unchanged.
5. Delete `http_event_handler`, `speak_stream_task`, `mic_connect`, and `mic_upload_task`.
6. Add `ws_event_handler`: on `WEBSOCKET_EVENT_CONNECTED`, send one text frame
   `{"type":"hello","client_id":"<VOICE_CLIENT_ID>","caps":["audio_in","audio_out"]}`. On
   `WEBSOCKET_EVENT_DATA` with `op_code` 2 (binary), push the payload into `s_audio_ring` exactly
   as `http_event_handler` did. On `op_code` 1 (text), `ESP_LOGI` the payload and do nothing else.
7. Add `ws_client_task` creating an `esp_websocket_client` against `CONFIG_VOICE_WS_URL`, starting
   it, and keeping it alive with reconnect on disconnect.
8. Add `mic_ws_task` doing what `mic_upload_task` did — `i2s_channel_read`, the same
   `(int16_t)(raw[i] >> 14)` conversion — but sending each buffer as a binary WebSocket frame via
   `esp_websocket_client_send_bin` instead of `send()`. Skip sending while the client is not
   connected.
9. Keep `i2s_drain_task`, `i2s_speaker_init`, `i2s_mic_init`, and `wifi_init_sta` unchanged. In
   `app_main`, create `i2s_drain_task`, `ws_client_task`, and `mic_ws_task`.
**New symbols:**
- `static void ws_event_handler(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data)`
- `static void ws_client_task(void *arg)`
- `static void mic_ws_task(void *arg)`
**Verify:** `cd voice_chat && source ~/esp/esp-idf/export.sh && idf.py build` — expected: exits 0, ending with the `esptool` flash-command summary.
**Forbidden:** no changes to the I2S pin map or sample rates; do not touch the root project or `mic_test/`; do not add `esp-sr` or any wake-word component — that is a later plan; do not commit `voice_chat/build/`; do not change `VOICE_WIFI_SSID` or `VOICE_WIFI_PASSWORD`.
**Depends:** Task 20.
**Why:** Collapses two half-duplex channels into the one bidirectional protocol multiple speakers need. Verified by build only — no board was attached at plan time; flashing with `idf.py -p /dev/cu.usbmodem101 flash monitor` is a manual step for the user afterwards.

### Task 24: Write the harness README [docs]
- [ ] status
**Objective:** `harness/README.md` tells a reader how to run the harness, what M1 does, and what it deliberately does not do yet.
**Write-scope:** `harness/README.md` (new)
**Read-context:**
- `harness/cadence/config.py` (from Task 20) — the real port and paths.
- `harness/requirements.txt` (from Task 1) — the real dependency set.
- `docs/preflight/runtime.md` (from Task 2) and `docs/preflight/ollama.md` (from Task 3) — the measured numbers to cite.
- The Scope section of this plan — the deferred list, copied faithfully.
**Anchors:**
- `WS_PORT: int` @ `harness/cadence/config.py` (from Task 20)
- `TOOL_NAMES: tuple[str, ...]` @ `harness/cadence/muse/mcp_server.py` (from Task 8)
**Steps:**
1. Audience is the repo owner returning in three months. Keep it under 120 lines.
2. Sections: what this is, prerequisites, running it, the eight Muse tools, what M1 does not do.
3. Prerequisites state that `ollama signin` is required and that `tools/muse_proxy.py` must be
   running on port 8765 for playback to work — neither is started by the harness.
4. Running it: `python3 -m venv harness/.venv`, install from `harness/requirements.txt`, then
   `cd harness && .venv/bin/python -m cadence`, which listens on the port read from `config.py`.
5. List the eight tool names, read from `TOOL_NAMES`, with one line each.
6. "Not yet" section naming exactly the five deferred items from this plan's Scope: wake word,
   echo subtraction, acknowledgement clip pool, server deployment, Telegram and iMessage adapters.
   State that VAD is the only utterance gate until the wake word lands.
7. Every number cited must come from `docs/preflight/runtime.md` or `docs/preflight/ollama.md`. Cite
   no figure you cannot find in one of those two files.
**New symbols:** none.
**Verify:** `cd harness && .venv/bin/python -m pytest tests/ -q && wc -l README.md` — expected: all tests pass and the line count is at or below 120.
**Forbidden:** no performance claim absent from the two preflight files; do not document the wake word, echo cancellation, or the ack pool as if they exist; do not edit the root `CLAUDE.md`.
**Depends:** Task 22, Task 23.
**Why:** The deferred list is the part that matters — without it, the next session reads M1 as a finished v1 and rebuilds the wrong thing.

**Phase 5 gate:** `cd harness && .venv/bin/python -m pytest tests/ -q` fully green;
`cd voice_chat && source ~/esp/esp-idf/export.sh && idf.py build` exits 0; `harness/README.md` exists.
