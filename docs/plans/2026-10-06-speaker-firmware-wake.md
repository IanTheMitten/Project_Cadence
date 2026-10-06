# Plan — Speaker firmware baseline, measurement, wake/ASR bench (spec phases 1–3 tooling)

Source spec: `docs/specs/2026-10-06-speaker-firmware-wake.md` (handoff lint exit 0, "ready for planning").
Executes the code side of spec phases 1–3. Every step that needs a person, a room, or the board
speaking (flash + spoken turns, recordings, Colab training) is in **Runbook (user)** below and runs
after this plan. Spec phase 4 ("hey cadence", chime, self-mute, `tts_start`/`tts_end`, `wake`
frames, `wake_local`) is a **separate plan**, written once `docs/preflight/wake-bench.md` names the
winner.

Run from repo root. Harness tests: `cd harness && .venv/bin/python -m pytest -q` (185 passing at plan time).
Firmware build: `bash -c 'source ~/esp/esp-idf/export.sh >/dev/null 2>&1 && cd voice_chat && idf.py build'`.

## Assumptions (spec Deferred items decided here, plus edge rules the spec left open)

- Deferred "phase-4 build path": **split**. This plan stops at bench tooling; phase 4 gets its own plan after the bench file exists (each branch is unknowable now, and the baseline must be flashed before any firmware change — `docs/specs/2026-10-06-speaker-firmware-wake.md:47`).
- Deferred "pymicro-wakeword on 3.14": installs and runs in `harness/.venv` (Python 3.14.4) — no separate venv. Pinned `pymicro-wakeword==2.5.0`, `pymicro-features==2.0.2`.
- Deferred "stock microWakeWord model": `esphome/micro-wake-word-models` `models/v2/hey_jarvis.tflite`, sha256 `21a7976add39ee24ec96c63d96b7aaa18e24d1d9824b963e451da8feb4b78b77`, `probability_cutoff` 0.97. pymicro-wakeword 2.5.0 bundles the byte-identical file (`Model.HEY_JARVIS`).
- Deferred "distil model": `distil-small.en`.
- Deferred "esp-tflite-micro / micro-speech-features versions": moved to the phase-4 plan (board branch only). Seen today: `espressif/esp-tflite-micro` 1.4.1; `esphome/micro-speech-features` is NOT in the component registry under that name — the phase-4 plan must resolve the real name.
- On-board wake-to-detection latency (`docs/specs/2026-10-06-speaker-firmware-wake.md:54`): taken from the phase-4 port, no separate benchmark firmware.
- `speech_end` stamp = instant VAD closes the utterance (includes the 480 ms end-of-speech silence). Phase 4 decides whether S4 subtracts it.
- Bench scoring rules: score `>=` threshold for both engines; detections closer than 2.0 s to the previous one merge (refractory); a wake attempt is a hit if any detection lands in [prompt, prompt + 6.0 s]; false wakes = detections outside guided-session spans; win rule's "2x false wakes" = board false wakes `>= 2 * max(server false wakes, 1)` (so 1 vs 0 does not lose the board the bench); "10 points" compared with a 1e-9 tolerance.
- Bench record dir missing or unwritable → one stderr error, session runs unrecorded; the dir is never auto-created (spec error-handling line `docs/specs/2026-10-06-speaker-firmware-wake.md:159`).
- Bench audio deletion (`docs/specs/2026-10-06-speaker-firmware-wake.md:118`) happens after the bench in the Runbook; the phase-4 plan's first task asserts `harness/bench_audio/` is gone.
- Committed `CONFIG_VOICE_WS_URL` stays `ws://ianshomeserver:8768/session` (this host's hostname); `.local` may override it if the board cannot resolve the name.
- Baseline "fix only what blocks a turn" is interactive debugging with the user (Runbook step 3), not an autopilot task.

## Premises

- `voice_chat/` builds clean with ESP-IDF v5.3 once cmake+ninja exist; cmake 3.24.0 and ninja 1.11.1 were installed into `~/.espressif/tools` at plan time — verified: `python ~/esp/esp-idf/tools/idf_tools.py install cmake ninja` then scratch-copy `idf.py set-target esp32s3 && idf.py build` → exit 0.
- Committed `sdkconfig.defaults` + optional `sdkconfig.defaults.local` via `SDKCONFIG_DEFAULTS` works and yields `CONFIG_ESPTOOLPY_FLASHSIZE_8MB=y`, `CONFIG_SPIRAM=y`, `CONFIG_SPIRAM_MODE_QUAD=y`; a listed-but-missing defaults file is FATAL — verified: scratch build + `~/esp/esp-idf/tools/cmake/project.cmake:645`.
- First build writes `voice_chat/dependencies.lock` and `voice_chat/managed_components/` (neither ignored nor tracked) — verified: scratch `ls` after build; `git ls-files | grep -i lock` empty.
- `voice_chat/sdkconfig.defaults` is gitignored at `.gitignore:19`; `.local` at `.gitignore:22`.
- No `voice_chat/sdkconfig.defaults*` exists; WiFi creds default `""` — verified: `ls voice_chat`, `voice_chat/main/Kconfig.projbuild:3-14`.
- Firmware hello sends caps `audio_in`,`audio_out`; text frames only logged — `voice_chat/main/voice_chat.c:146`, `voice_chat/main/voice_chat.c:160-162`.
- CLAUDE.md `voice_chat/` section is stale (`speak_stream_task`, `VOICE_SPEAK_URL`) — `CLAUDE.md:70-93`, `CLAUDE.md:112`.
- Server audio loop: `listener.feed` → `runtime.asr(pcm)` → `handle_text` — `harness/cadence/server.py:118-127`; `handle_text` sends `turn_start`/`turn_end` — `harness/cadence/server.py:148-159`.
- `Listener` stamps nothing at wake today — `harness/cadence/audio/listener.py:29-34`.
- Pipeline already records `latency` dict (`jev`,`llm`,`execute`,`total`) into `latency_ms` — `harness/cadence/pipeline.py:52-123`; only `in`-checks pin it — `harness/tests/test_pipeline.py:271-276`.
- `tests/test_server.py:83` monkeypatches `pipeline.handle` with a 2-arg fake (`boom(event, out)`) — must accept `timer=None` once server passes it.
- `Runtime` is a plain dataclass built by keyword in tests — `harness/cadence/wiring.py:32-41`, `harness/tests/test_server.py:35-37`.
- `Asr` hardcodes `small.en`/`beam_size=5`; only callers `Asr()` — `harness/cadence/audio/asr.py:13-22`, `harness/cadence/wiring.py:80`, `harness/scripts/preflight_v1.py:49`.
- faster-whisper 1.2.1 knows `small.en`, `base.en`, `distil-small.en` — verified: `.venv/bin/python -c "import faster_whisper.utils as u; print(sorted(u._MODELS))"`.
- openWakeWord `hey_jarvis_v0.1.onnx` + feature models already in the venv — verified: `ls .venv/lib/python3.14/site-packages/openwakeword/resources/models`.
- pymicro-wakeword API: `MicroWakeWord.from_builtin(Model.HEY_JARVIS)`, `.process_streaming_prob(features) -> float | None`, `.probability_cutoff == 0.97`, `.model_path` is `bytes`; `MicroWakeWordFeatures().process_streaming(audio_bytes)` yields 10 ms feature frames — verified in scratch venv on 3.14.4.
- Existing `harness/scripts/bench_*.py` are the decider benchmark — new wake/ASR scripts use distinct names (`wake_*.py`, `asr_bench.py`).
- Collection errors abort a pytest run (`Interrupted: N errors during collection`; no `--continue-on-collection-errors` in `harness/pyproject.toml:6-8`), so red tests import not-yet-existing modules inside test functions, never at module top.

## Runbook (user, after this plan's autopilot run)

1. Create `voice_chat/sdkconfig.defaults.local` with `CONFIG_VOICE_WIFI_SSID="..."` and `CONFIG_VOICE_WIFI_PASSWORD="..."` (plus `CONFIG_VOICE_WS_URL="ws://<host-ip>:8768/session"` if the board can't resolve `ianshomeserver`). `rm -f voice_chat/sdkconfig`.
2. `cd voice_chat && idf.py set-target esp32s3 && idf.py -p /dev/ttyACM0 flash monitor`. Start harness: `cd harness && .venv/bin/python -m cadence`.
3. Baseline: speak 10 real turns ("hey jarvis", pause, command). Fix only what blocks a turn (interactive session). Note `turn_timing` lines on harness stderr.
4. Record: `mkdir harness/bench_audio`, restart harness with `CADENCE_BENCH_RECORD_DIR=bench_audio`. Run `.venv/bin/python scripts/wake_guide.py --block wake` (60 attempts) and `--block commands` (20). Leave the board and harness running ≥ 8 h of normal TV/conversation for background.
5. Bench: `.venv/bin/python scripts/wake_bench.py` → `docs/preflight/wake-bench.md`; `.venv/bin/python scripts/asr_bench.py` → `docs/preflight/asr-bench.md`. Commit both.
6. `rm -rf harness/bench_audio`. Train "hey cadence" on Colab for the `Winner:` engine. Then run `/autopilot-plan` for spec phase 4 with the winner and model file in hand.

## Phase 1 — Board config, docs, bench artifact preflight

Full check: `cd harness && .venv/bin/python -m pytest -q` and `bash -c 'source ~/esp/esp-idf/export.sh >/dev/null 2>&1 && cd voice_chat && idf.py build >/dev/null && echo BUILD_OK'`.

### Task 1: Split voice_chat config into committed defaults plus gitignored local override [mechanical]
- [x] status
**Objective:** `voice_chat/` builds from a committed `sdkconfig.defaults` (8 MB flash, quad PSRAM, WS URL) with WiFi creds read from an optional gitignored `sdkconfig.defaults.local`.
**Write-scope:**
`voice_chat/CMakeLists.txt`
`voice_chat/sdkconfig.defaults` (new)
`voice_chat/dependencies.lock` (new)
`.gitignore`
**Read-context:** `voice_chat/CMakeLists.txt:1-3`; `.gitignore:1-22`; `voice_chat/main/Kconfig.projbuild:16-18`
**Anchors:**
`project(voice_chat)` @ `voice_chat/CMakeLists.txt`
`config VOICE_WS_URL` @ `voice_chat/main/Kconfig.projbuild`
**Steps:**
1. Replace `voice_chat/CMakeLists.txt` with exactly:
```cmake
cmake_minimum_required(VERSION 3.16)

# Committed defaults first, then the gitignored local override (WiFi SSID/password).
set(SDKCONFIG_DEFAULTS "sdkconfig.defaults")
if(EXISTS "${CMAKE_CURRENT_LIST_DIR}/sdkconfig.defaults.local")
    list(APPEND SDKCONFIG_DEFAULTS "sdkconfig.defaults.local")
else()
    message(WARNING "voice_chat/sdkconfig.defaults.local not found: WiFi SSID/password stay empty. See CLAUDE.md.")
endif()

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(voice_chat)
```
2. Create `voice_chat/sdkconfig.defaults` with exactly:
```
# Committed board defaults. WiFi SSID/password go in the gitignored
# sdkconfig.defaults.local (see CLAUDE.md), which is applied after this file.
CONFIG_ESPTOOLPY_FLASHSIZE_8MB=y
CONFIG_SPIRAM=y
CONFIG_SPIRAM_MODE_QUAD=y
CONFIG_VOICE_WS_URL="ws://ianshomeserver:8768/session"
```
3. `.gitignore`: delete the line `voice_chat/sdkconfig.defaults` (line 19) only; keep `voice_chat/sdkconfig.defaults.local`. Replace the 3-line comment above that block (lines 14-16) with: `# Contain the WiFi password in plaintext. voice_chat/ commits its sdkconfig.defaults` / `# (no secrets) and keeps credentials in the ignored sdkconfig.defaults.local.` After the line `voice_chat/build/` add `voice_chat/managed_components/`.
4. Run the Verify command; it generates `voice_chat/dependencies.lock` — keep it (commit it).
**New symbols:** none
**Verify:** `bash -c 'source ~/esp/esp-idf/export.sh >/dev/null 2>&1 && cd voice_chat && rm -rf build sdkconfig && idf.py set-target esp32s3 >/dev/null 2>&1 && idf.py build >/dev/null 2>&1 && grep -cE "^(CONFIG_ESPTOOLPY_FLASHSIZE_8MB|CONFIG_SPIRAM|CONFIG_SPIRAM_MODE_QUAD)=y" sdkconfig' && git status --porcelain voice_chat` — expected: prints `3`; porcelain lists only `voice_chat/CMakeLists.txt`, `voice_chat/sdkconfig.defaults`, `voice_chat/dependencies.lock`.
**Forbidden:** no edits to `voice_chat/main/`; don't touch root or `mic_test/` ignore lines; never create `voice_chat/sdkconfig.defaults.local`; no WiFi values anywhere.
**Depends:** none
**Why:** Spec decision "Board config and secrets" (`docs/specs/2026-10-06-speaker-firmware-wake.md:120-125`). Build must pass without the local file so executors and fresh clones can build.

### Task 2: Rewrite CLAUDE.md voice_chat section to the /session WebSocket client [docs]
- [ ] status
**Objective:** CLAUDE.md describes the current `voice_chat/` firmware (WebSocket `/session` client) and its config files, with no pre-harness HTTP/TCP facts left.
**Write-scope:** `CLAUDE.md`
**Read-context:** `CLAUDE.md:36-54`; `CLAUDE.md:70-93`; `CLAUDE.md:110-112`; `voice_chat/main/voice_chat.c:124-221`; `voice_chat/main/Kconfig.projbuild:1-32`; `voice_chat/CMakeLists.txt` (from Task 1); `voice_chat/sdkconfig.defaults` (from Task 1); `harness/cadence/server.py:70-159`
**Anchors:**
`static void ws_event_handler(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data)` @ `voice_chat/main/voice_chat.c`
`async def session_endpoint(ws: WebSocket) -> None:` @ `harness/cadence/server.py`
**Steps:**
1. Audience: a developer about to flash the board. Replace the body of `## Voice conversation test (\`voice_chat/\`)` (lines 71-93) with prose covering, each fact checked against the files above: tasks `i2s_drain_task`, `ws_client_task`, `mic_ws_task`; WiFi STA connect; hello frame `{"type":"hello","client_id":<CONFIG_VOICE_CLIENT_ID>,"caps":["audio_in","audio_out"]}` on connect; mic = 16 kHz s16le mono binary frames (256 samples, 32-bit I2S shifted `>> 14`) sent continuously while connected; server binary frames = 44.1 kHz s16le stereo PCM into the 64 KB `s_audio_ring`; text frames (`turn_start`, `turn_end`, `text`, `error`) are only logged (`ws text: ...`); `esp_websocket_client` reconnects on its own. Server side = harness `python -m cadence`, `/session` on port 8768, server-side wake "hey jarvis", then VAD and ASR. Echo: no AEC; the harness ducks music under speech. One sentence: `tools/voice_chat_host.py` is the pre-harness server and is not used by this firmware.
2. In `## Config`, replace the `voice_chat/` sentence (line 112) with: menu "Voice Chat" options `VOICE_WIFI_SSID`, `VOICE_WIFI_PASSWORD`, `VOICE_WS_URL`, `VOICE_CLIENT_ID`; committed `voice_chat/sdkconfig.defaults` (8 MB flash, quad PSRAM, WS URL `ws://ianshomeserver:8768/session`); gitignored `voice_chat/sdkconfig.defaults.local`, which a fresh clone must create by hand — show a 2-line example with placeholder values `CONFIG_VOICE_WIFI_SSID="your-ssid"` / `CONFIG_VOICE_WIFI_PASSWORD="your-password"`, and say it may also override `CONFIG_VOICE_WS_URL`; defaults apply only when `sdkconfig` is generated, so `rm voice_chat/sdkconfig` after editing either file.
3. In `## Commands`, add one line after the `source` block: on Linux, cmake and ninja come from `python ~/esp/esp-idf/tools/idf_tools.py install cmake ninja` (after sourcing `export.sh`).
**New symbols:** none
**Verify:** `! grep -nE "speak_stream_task|mic_upload_task|VOICE_SPEAK_URL|VOICE_MIC_PORT|VOICE_HOST_IP" CLAUDE.md && grep -c "sdkconfig.defaults.local" CLAUDE.md` — expected: exit 0, count ≥ 2.
**Forbidden:** no edits outside the three named sections; no phase-4 features (`wake` frame, `tts_start`, chime, microWakeWord) described as existing; no real SSID/password.
**Depends:** Task 1
**Why:** Spec decision "CLAUDE.md voice_chat section is corrected in phase 1" (`docs/specs/2026-10-06-speaker-firmware-wake.md:134-139`); anyone flashing from the stale text points the board at the wrong server.

### Task 3: Preflight the bench artifacts (microWakeWord, openWakeWord, Whisper models)
- [x] status
**Objective:** A preflight script proves pymicro-wakeword, the stock models, and the three Whisper models load in `harness/.venv`; its output is committed.
**Write-scope:**
`harness/requirements.txt`
`harness/scripts/preflight_wake_bench.py` (new)
`docs/preflight/wake-bench-preflight.md` (new)
**Read-context:** `harness/scripts/preflight_v1.py:1-30` (style: `row()` markdown rows, caught exceptions); `harness/cadence/audio/wakeword.py:13-16`; `harness/cadence/audio/asr.py:11-27`; `harness/cadence/config.py:23-24`
**Anchors:**
`WAKE_MODEL = "hey_jarvis_v0.1"` @ `harness/cadence/config.py`
`def row(check, ok, detail, ms):` @ `harness/scripts/preflight_v1.py`
**Steps:**
1. Append two lines to the end of `harness/requirements.txt`: `pymicro-wakeword==2.5.0` and `pymicro-features==2.0.2`. From `harness/`: `.venv/bin/pip install pymicro-wakeword==2.5.0 pymicro-features==2.0.2`.
2. Write `harness/scripts/preflight_wake_bench.py`, modelled on `preflight_v1.py` (same `sys.path` insert, same `row(check, ok, detail, ms)` helper, every check in try/except recording the exception as detail). Prints `# Wake bench preflight (<date.today().isoformat()>)`, a blank line, `| check | ok | detail | ms |`, `|---|---|---|---|`, then 5 rows:
   - `mww hey_jarvis`: `MicroWakeWord.from_builtin(Model.HEY_JARVIS)`; ok iff `probability_cutoff == 0.97` and sha256 of `open(m.model_path.decode() if isinstance(m.model_path, bytes) else m.model_path, "rb").read()` equals `MWW_SHA256 = "21a7976add39ee24ec96c63d96b7aaa18e24d1d9824b963e451da8feb4b78b77"`, and 1 s of zeros (`bytes(32000)`) fed through `MicroWakeWordFeatures().process_streaming` → `m.process_streaming` yields no `True`.
   - `oww hey_jarvis_v0.1`: `openwakeword.model.Model(wakeword_models=[WAKE_MODEL], inference_framework="onnx").predict(np.zeros(1280, np.int16))`; ok iff `WAKE_MODEL` in the result.
   - `whisper small.en`, `whisper base.en`, `whisper distil-small.en`: `WhisperModel(name, device="cpu", compute_type="int8")` then `list(model.transcribe(np.zeros(16000, np.float32), beam_size=1, vad_filter=True)[0])`; ok iff no exception.
   Exit status 1 if any row is not ok, else 0.
3. From `harness/`: `.venv/bin/python scripts/preflight_wake_bench.py > ../docs/preflight/wake-bench-preflight.md` (first run downloads `base.en` and `distil-small.en`).
**New symbols:** `MWW_SHA256: str` in the script; script entry `main() -> int`.
**Verify:** `cd harness && .venv/bin/python scripts/preflight_wake_bench.py | grep -c "| True |"` — expected: `5`, exit 0.
**Forbidden:** no changes to `cadence/`; no `--no-deps` install; no other new dependencies; no separate venv.
**Depends:** none
**Why:** External-artifact preflight: Tasks 11 and 12 replay through these models. Spec defers model/package names to plan time (`docs/specs/2026-10-06-speaker-firmware-wake.md:184-186`).

## Phase 2 — Harness measurement: per-stage turn timing and bench recording

Full check: `cd harness && .venv/bin/python -m pytest -q`.

### Task 4: Write red tests for turn timing and the bench recorder [test]
- [x] status
**Objective:** 17 new tests encode the timing and recorder contract and fail against the current tree.
**Write-scope:**
`harness/tests/test_turntiming.py` (new)
`harness/tests/test_benchrec.py` (new)
`harness/tests/test_listener.py`
`harness/tests/test_pipeline.py`
`harness/tests/test_server.py`
**Read-context:** `harness/tests/test_listener.py:24-114`; `harness/tests/test_pipeline.py:54-92`; `harness/tests/test_pipeline.py:271-276`; `harness/tests/test_server.py:23-94`
**Anchors:**
`class FakeVad:` @ `harness/tests/test_listener.py`
`def _pipeline(tmp_path, jev, llm, plugin=None, log=None, **kw):` @ `harness/tests/test_pipeline.py`
`def rt(tmp_path):` @ `harness/tests/test_server.py`
**Steps:** Every import of `cadence.turntiming`, `cadence.benchrec`, and `cadence.config` reloads goes INSIDE the test function. Contract: `TurnTimer(clock=time.monotonic)`, `.mark(stage, at=None)` (first mark wins; unknown stage → `ValueError`), `.stamps` (dict copy), `.durations()` (ms, only complete pairs from `DURATIONS = {"wake_to_speech_end": ("wake","speech_end"), "asr": ("speech_end","asr_done"), "decide": ("turn_start","decided"), "speech_end_to_first_audio": ("speech_end","first_audio"), "turn": ("turn_start","turn_end")}`), `.log_line(client_id)` = `"turn_timing " + json.dumps({"client_id": ..., "durations_ms": {k: round(v, 1)}})`. `BenchRecorder.open(directory, client_id, *, clock=time.time) -> BenchRecorder | None`, `.path`, `._file`, `.write(pcm)`, `.save_utterance(pcm)`, `.close()`.
1. `test_turntiming.py` (5): `test_mark_first_wins` (clock from `iter([1.0, 2.0])`, mark `turn_start` twice → `stamps == {"turn_start": 1.0}`); `test_mark_at_overrides_clock` (clock `lambda: 9.0`, `mark("wake", at=3.0)` → 3.0); `test_unknown_stage_raises` (`mark("bogus")` → `ValueError`); `test_durations_only_complete_pairs` (`speech_end` at 10.0, `asr_done` at 10.25 → `durations() == {"asr": 250.0}`); `test_log_line_format` (same stamps; line starts `"turn_timing "`, rest parses to `{"client_id": "speaker-1", "durations_ms": {"asr": 250.0}}`).
2. `test_benchrec.py` (6): `test_open_missing_dir_returns_none_and_logs` (`open(str(tmp_path/"missing"), "speaker-1")` is None; capsys err contains `"bench recorder disabled"`); `test_open_writes_meta_and_appends_pcm` (clock `lambda: 1000.0`; `rec.path == str(tmp_path/"speaker-1-1000000.pcm")`; `speaker-1-1000000.json` parses to `{"client_id": "speaker-1", "start_wall": 1000.0, "sample_rate": 16000, "format": "s16le"}`; write `b"ab"`, `b"cd"`, close → file bytes `b"abcd"`); `test_save_utterance_file` (clock 1000.0 → `utt-speaker-1-1000000.pcm` == `b"xyz"`); `test_write_error_disables_once` (replace `rec._file` with an object whose `write` raises `OSError("disk full")` and `close` does nothing; two `write` calls don't raise; err count of `"bench recorder write failed"` == 1); `test_close_idempotent`; `test_config_reads_env` (monkeypatch.setenv `CADENCE_BENCH_RECORD_DIR`=str(tmp_path), `importlib.reload(cadence.config)` → `BENCH_RECORD_DIR == str(tmp_path)`; delenv + reload → `None`).
3. `test_listener.py` (2): `test_listener_wake_at_set_on_gate_fire` (FakeGate fires, clock `lambda: 42.0` → `listener.wake_at == 42.0`); `test_listener_wake_at_none_without_gate`.
4. `test_pipeline.py` (1): `test_timer_marks_decided_and_latency_has_decide` (timer clock from `iter([1.0, 1.5])`; test marks `turn_start`; `await pipe.handle(_event(), FakeOut(), timer=timer)`; `timer.stamps["decided"] == 1.5`; `log.recent(1)[0]["latency_ms"]["decide"] == 500.0`).
5. `test_server.py` (3) + change `boom` to `async def boom(event, out, timer=None)`: `test_audio_turn_logs_timing(rt, capsys)` (set `rt.asr = lambda pcm: "do it"`, `rt.listener_factory = lambda: Listener(None, vad_factory=lambda: FakeVad([b"\x00\x00" * 8000]))`; hello caps `["audio_in", "text_out"]`; `ws.send_bytes(b"\x00\x00" * 160)`; frames turn_start, `{"type":"text","content":"done"}`, turn_end; stderr line starting `"turn_timing "` has `client_id == "speaker-1"` and `{"asr","decide","turn"} <= durations_ms.keys()`; `rt.log.export()[0]["latency_ms"]` has `"asr"` and `"decide"`); `test_bench_recorder_writes_session_audio(rt, tmp_path)` (`bench = tmp_path/"rec"`, mkdir, `rt.bench_dir = str(bench)`, same fakes with VAD utterance `b"\x01\x00" * 8000`, send `b"\x01\x00" * 160`, read 3 frames, close; exactly one `speaker-1-*.pcm` == `b"\x01\x00" * 160`, its `.json` exists, exactly one `utt-speaker-1-*.pcm` == `b"\x01\x00" * 8000`); `test_runtime_bench_dir_defaults_none(rt)` (`rt.bench_dir is None`).
**New symbols:** none (tests only)
**Verify:** `cd harness && .venv/bin/python -m pytest -q 2>&1 | tail -1` — expected: `17 failed, 185 passed` (plus warnings); failures name `ModuleNotFoundError: No module named 'cadence.turntiming'`/`'cadence.benchrec'`, `AttributeError` (`wake_at`, `BENCH_RECORD_DIR`, `bench_dir`), `TypeError` (`timer`), or a missing `turn_timing` line.
**Forbidden:** never edit `harness/cadence/`; no top-level imports of the new modules; don't alter existing assertions (only `boom`'s signature).
**Depends:** none
**Why:** Spec testing strategy: red tests first for timing stamps and an off-by-default recorder (`docs/specs/2026-10-06-speaker-firmware-wake.md:164`). Signatures here are the binding contract for Tasks 5–7.

### Task 5: Implement TurnTimer, Listener.wake_at, and Pipeline timer stamps
- [x] status
**Objective:** `TurnTimer` exists, `Listener` records the wake instant, and `Pipeline.handle` marks `decided` and merges timer durations into `latency_ms`.
**Write-scope:**
`harness/cadence/turntiming.py` (new)
`harness/cadence/audio/listener.py`
`harness/cadence/pipeline.py`
**Read-context:** `harness/cadence/audio/listener.py:11-42`; `harness/cadence/pipeline.py:51-129`; `harness/tests/test_turntiming.py` (from Task 4); `harness/tests/test_listener.py` (from Task 4)
**Anchors:**
`def feed(self, pcm: bytes) -> list[bytes]:` @ `harness/cadence/audio/listener.py`
`async def handle(self, event: Event, out: TurnOutput) -> Decision:` @ `harness/cadence/pipeline.py`
**Steps:**
1. `cadence/turntiming.py`: `STAGES = ("wake", "speech_end", "asr_done", "turn_start", "decided", "first_audio", "turn_end")`; `DURATIONS` dict exactly as in Task 4's contract; `class TurnTimer` with `__init__(self, clock: Callable[[], float] = time.monotonic)`; `mark(self, stage: str, at: float | None = None) -> None` (`ValueError(f"unknown stage: {stage!r}")` if not in STAGES; no-op if already marked; else `at if at is not None else self._clock()`); `stamps` property returning `dict(self._stamps)`; `durations(self) -> dict[str, float]` = `(end - start) * 1000` for each DURATIONS entry with both stamps, insertion order of DURATIONS; `log_line(self, client_id: str) -> str` = `"turn_timing " + json.dumps({"client_id": client_id, "durations_ms": {k: round(v, 1) for k, v in self.durations().items()}}, sort_keys=True)`.
2. `Listener.__init__`: add `self.wake_at: float | None = None`. In `feed`, on gate fire: `now = self._clock()`, `self.wake_at = now`, `self._deadline = now + self._window_s` (one clock call, replaces the existing deadline line).
3. `Pipeline.handle(self, event: Event, out: TurnOutput, timer: TurnTimer | None = None)`: immediately after the `if llm_args is not None:` block and before `results = []`, `if timer is not None: timer.mark("decided")`; immediately before `new_id = self._log.record(...)`, `if timer is not None: latency.update(timer.durations())`. Import `TurnTimer` from `cadence.turntiming`.
**New symbols:** `STAGES: tuple[str, ...]`, `DURATIONS: dict[str, tuple[str, str]]`, `class TurnTimer` (methods above) in `harness/cadence/turntiming.py`; attribute `Listener.wake_at: float | None`; kwarg `timer` on `Pipeline.handle`.
**Verify:** `cd harness && .venv/bin/python -m pytest -q tests/test_turntiming.py tests/test_listener.py tests/test_pipeline.py 2>&1 | tail -1` — expected: all passed, 0 failed.
**Forbidden:** no edits to `server.py` or tests; no change to `Listener` window/VAD behaviour; no new deps.
**Depends:** Task 4
**Why:** Spec latency decision: per-stage monotonic stamps, written to `latency_ms` where the stage exists at record time (`docs/specs/2026-10-06-speaker-firmware-wake.md:110`).

### Task 6: Implement BenchRecorder, CADENCE_BENCH_RECORD_DIR, and Runtime.bench_dir
- [x] status
**Objective:** An off-by-default recorder writes session mic PCM plus per-utterance PCM under a configured directory, never crashing a session.
**Write-scope:**
`harness/cadence/benchrec.py` (new)
`harness/cadence/config.py`
`harness/cadence/wiring.py`
`harness/.gitignore`
**Read-context:** `harness/cadence/config.py:1-32`; `harness/cadence/wiring.py:15-16`; `harness/cadence/wiring.py:32-42`; `harness/cadence/wiring.py:83-87`; `harness/tests/test_benchrec.py` (from Task 4)
**Anchors:**
`class Runtime:` @ `harness/cadence/wiring.py`
`WAKE_ENABLED = os.environ.get("CADENCE_WAKE_ENABLED", "1") == "1"` @ `harness/cadence/config.py`
**Steps:**
1. `cadence/benchrec.py`: `SAMPLE_RATE = 16000`; `class BenchRecorder`. `open(cls, directory, client_id, *, clock=time.time)`: if `not os.path.isdir(directory) or not os.access(directory, os.W_OK)` → `print(f"bench recorder disabled: {directory!r} is not a writable directory", file=sys.stderr)`, return None. Else `start = clock()`, `stem = f"{client_id}-{int(start * 1000)}"`, write `<stem>.json` = `{"client_id", "start_wall": start, "sample_rate": SAMPLE_RATE, "format": "s16le"}`, open `<stem>.pcm` with `open(path, "wb", buffering=0)` as `self._file`, `self.path` = that path. Any OSError during open → same disabled message pattern with the exception, return None.
2. `write(pcm)`: if `self._file is None` return; on `OSError as exc`: `print(f"bench recorder write failed: {exc}", file=sys.stderr)`, close the file ignoring errors, `self._file = None`.
3. `save_utterance(pcm)`: write `<dir>/utt-<client_id>-<int(clock()*1000)>.pcm`; on OSError print `f"bench recorder utterance write failed: {exc}"` to stderr, never raise.
4. `close()`: idempotent; sets `self._file = None`.
5. `config.py`: after `LISTEN_WINDOW_S`, add `BENCH_RECORD_DIR = os.environ.get("CADENCE_BENCH_RECORD_DIR")`.
6. `wiring.py`: `Runtime` gains last field `bench_dir: str | None = None`; import `BENCH_RECORD_DIR`; `build_runtime` passes `bench_dir=BENCH_RECORD_DIR`.
7. `harness/.gitignore`: add line `bench_audio/`.
**New symbols:** `SAMPLE_RATE: int`, `class BenchRecorder` (`open` classmethod, `path: str`, `_file`, `write`, `save_utterance`, `close`) in `harness/cadence/benchrec.py`; `BENCH_RECORD_DIR: str | None` in config; `Runtime.bench_dir: str | None = None`.
**Verify:** `cd harness && .venv/bin/python -m pytest -q tests/test_benchrec.py tests/test_server.py::test_runtime_bench_dir_defaults_none 2>&1 | tail -1` — expected: `7 passed`.
**Forbidden:** never create the record directory; no edits to `server.py` or tests; no new deps.
**Depends:** Task 4
**Why:** Spec decision "Bench recording handling" and error-handling rule for an unwritable dir (`docs/specs/2026-10-06-speaker-firmware-wake.md:113-118`, `:159`).

### Task 7: Wire timing and recording into the /session server
- [ ] status
**Objective:** Every turn prints one `turn_timing` stderr line and logs stage durations; audio sessions record to `runtime.bench_dir` when set.
**Write-scope:** `harness/cadence/server.py`
**Read-context:** `harness/cadence/server.py:47-159`; `harness/cadence/turntiming.py` (from Task 5); `harness/cadence/benchrec.py` (from Task 6); `harness/tests/test_server.py` (from Task 4)
**Anchors:**
`class SessionOutput:` @ `harness/cadence/server.py`
`async def handle_text(session: Session, port: SpeakerPort | None, text: str) -> None:` @ `harness/cadence/server.py`
`class TurnTimer` @ `harness/cadence/turntiming.py` (from Task 5)
`class BenchRecorder` @ `harness/cadence/benchrec.py` (from Task 6)
**Steps:**
1. Imports: `sys`, `TurnTimer`, `BenchRecorder`.
2. `SessionOutput.__init__` gains `timer: TurnTimer | None = None`; helper `_mark_audio()` marks `"first_audio"` when timer set. `ack`: call `_mark_audio()` right before `await self._port.speak(clip)`. `say` audio branch: `pcm = self._runtime.tts(sentence)`, `self._mark_audio()`, `await self._port.speak(pcm)`.
3. `session_endpoint`: after the `listener = ...` line, `recorder = BenchRecorder.open(runtime.bench_dir, client_id) if runtime.bench_dir and caps.audio_in else None`. In the bytes branch, before `if listener is None or runtime.asr is None:`, `if recorder is not None: recorder.write(data)`. Replace the `for pcm in listener.feed(data):` body with: `timer = TurnTimer()`; `if listener.wake_at is not None: timer.mark("wake", at=listener.wake_at)`; `timer.mark("speech_end")`; `if recorder is not None: recorder.save_utterance(pcm)`; `text = runtime.asr(pcm)`; `timer.mark("asr_done")`; `if not text: continue`; `await handle_text(session, port, text, timer=timer)`. In `finally`, `if recorder is not None: recorder.close()` first.
4. `handle_text(session, port, text, timer: TurnTimer | None = None)`: `if timer is None: timer = TurnTimer()`; `timer.mark("turn_start")` as first statement after that; `SessionOutput(session, port, runtime, timer)`; `await runtime.pipeline.handle(event, out, timer=timer)`; after the `async with TURN_LOCK` block and before sending `turn_end`: `timer.mark("turn_end")`, `print(timer.log_line(session.client_id), file=sys.stderr, flush=True)`.
**New symbols:** kwarg `timer` on `SessionOutput.__init__` and `handle_text`; method `SessionOutput._mark_audio(self) -> None`.
**Verify:** `cd harness && .venv/bin/python -m pytest -q 2>&1 | tail -1` — expected: `202 passed`.
**Forbidden:** no protocol changes (no new frame types, caps, or hello fields); no edits outside `server.py`; don't move ASR off the event loop.
**Depends:** Task 5, Task 6
**Why:** Spec data flow: stamps live in-process per turn and flush on `turn_end`; recorder appends each session's raw mic PCM (`docs/specs/2026-10-06-speaker-firmware-wake.md:149-151`).

## Phase 3 — Bench tooling: scoring library, guided recording, wake replay, ASR bench

Full check: `cd harness && .venv/bin/python -m pytest -q`.

### Task 8: Write red tests for the wake/ASR bench scoring library [test]
- [x] status
**Objective:** 22 tests pin the scoring math and file loaders of `cadence.wakebench` and fail against the current tree.
**Write-scope:** `harness/tests/test_wakebench.py` (new)
**Read-context:** `harness/tests/test_listener.py:1-20` (style); `harness/tests/test_pipeline.py:1-20` (imports style)
**Anchors:**
`class FakeVad:` @ `harness/tests/test_listener.py`
**Steps:** Every test imports `from cadence import wakebench as wb` inside the function. `_r(hit, fw)` helper = `wb.EngineResult(0.5, hit, fw, 0.0, True)`. Cases (assert exact values; use `pytest.approx` only where noted):
1. `detections([(0.0,0.1),(1.0,0.6),(1.5,0.9),(3.1,0.7),(3.2,0.2)], 0.5, 2.0) == [1.0, 3.1]`. 2. `detections([(0.0,0.5)], 0.5) == [0.0]`.
3. `hit_rate([10.0, 30.0], [9.0, 20.0, 29.0, 50.0], 6.0) == 0.5`. 4. `hit_rate([], []) == 0.0`.
5. `evaluate([[(100.0,0.9),(200.0,0.9),(5000.0,0.9)]], [99.0], [(90.0,210.0)], 7200.0, 0.5) == wb.EngineResult(0.5, 1.0, 1, 0.5, False)`. 6. `evaluate(..., background_s=0.0, ...)` raises `ValueError`.
7. `sweep([[(100.0,0.8),(5000.0,0.6)]], [99.0], [(90.0,110.0)], 8*3600.0, grid=(0.5,0.7,0.9))` → threshold 0.5, hit 1.0, false_wakes 1, target_met True. 8. `sweep([[(5000.0,0.95),(9000.0,0.6)]], [], [], 3600.0, grid=(0.5,0.9))` → threshold 0.9, false_wakes 1, target_met False.
9. `board_wins(_r(0.85,0), _r(0.95,0)) is False`. 10. `board_wins(_r(0.90,0), _r(0.95,0)) is True`. 11. `board_wins(_r(0.9,2), _r(0.9,0)) is False` and `board_wins(_r(0.9,1), _r(0.9,0)) is True`. 12. `board_wins(_r(0.9,3), _r(0.9,2)) is True`.
13. `normalize("Play, Something CHILL!") == ["play","something","chill"]`; `normalize("what's playing") == ["what's","playing"]`. 14. `wer(["play something chill"], ["play something"]) == pytest.approx(1/3)`; `wer(["a b","c d"], ["a x","c d"]) == 0.25`. 15. `wer([], [])` and `wer(["a"], [])` raise `ValueError`.
16. `pick_asr([AsrResult("small.en/beam5",0.10,900.0), AsrResult("base.en/beam1",0.115,300.0), AsrResult("distil-small.en/beam1",0.13,200.0)], "small.en/beam5").name == "base.en/beam1"`.
17. `load_recordings(tmp)`: files `speaker-1-1000000.json` (meta, start_wall 1000.0) + `speaker-1-1000000.pcm` (64000 bytes) + stray `utt-speaker-1-1000500.pcm` → `[Recording(str(tmp/"speaker-1-1000000.pcm"), 1000.0, 2.0)]`.
18. `load_labels(tmp)`: `labels-1.jsonl` (2 lines, t 5.0 and 1.0) + `labels-2.jsonl` (1 line, t 3.0) → 3 dicts, `[d["t"] for d in ...] == [1.0, 3.0, 5.0]`.
19. `guided_spans([{"kind":"session_start","t":10.0},{"kind":"wake","t":12.0},{"kind":"session_end","t":50.0},{"kind":"session_start","t":100.0}]) == [(10.0,50.0),(100.0,math.inf)]`.
20. `background_seconds([Recording("x.pcm",0.0,100.0)], [(10.0,30.0),(90.0,math.inf)]) == 70.0`.
21. `load_utterances(tmp)` with `utt-speaker-1-1000500.pcm` → `[(1000.5, str(path))]`.
22. `pair_commands([{"kind":"command","t":100.0,"text":"turn it up"},{"kind":"command","t":200.0,"text":"pause"}], [(105.0,"a.pcm"),(230.0,"b.pcm")]) == [("turn it up","a.pcm")]`.
**New symbols:** none (tests only)
**Verify:** `cd harness && .venv/bin/python -m pytest -q tests/test_wakebench.py 2>&1 | tail -1` — expected: `22 failed`, each from `ImportError`/`ModuleNotFoundError` on `cadence.wakebench`.
**Forbidden:** never create `harness/cadence/wakebench.py`; no top-level import of it; no real audio or models.
**Depends:** none
**Why:** Spec: bench scoring math is unit-tested on synthetic data (`docs/specs/2026-10-06-speaker-firmware-wake.md:165`). These cases encode the plan-header scoring rules (refractory, window, 2x-with-floor, 1e-9 tolerances).

### Task 9: Implement the cadence.wakebench scoring library
- [ ] status
**Objective:** `cadence/wakebench.py` implements detection, hit rate, false wakes, threshold sweep, win rule, WER, ASR pick, and bench file loaders.
**Write-scope:** `harness/cadence/wakebench.py` (new)
**Read-context:** `harness/tests/test_wakebench.py` (from Task 8); `harness/cadence/benchrec.py` (from Task 6)
**Anchors:**
`class BenchRecorder` @ `harness/cadence/benchrec.py` (from Task 6)
**Steps:**
1. Constants: `REFRACTORY_S = 2.0`, `POSITIVE_WINDOW_S = 6.0`, `COMMAND_WINDOW_S = 15.0`, `FW_TARGET_PER_HOUR = 1 / 8`, `HIT_MARGIN = 0.10`, `ASR_WER_MARGIN = 0.02`, `EPS = 1e-9`, `THRESHOLD_GRID = tuple(round(i / 100, 2) for i in range(1, 100)) + tuple(round(0.99 + i / 1000, 3) for i in range(1, 10))`.
2. Frozen dataclasses `Recording(pcm_path: str, start_wall: float, seconds: float)`, `EngineResult(threshold: float, hit_rate: float, false_wakes: int, fw_per_hour: float, target_met: bool)`, `AsrResult(name: str, wer: float, median_ms: float)`.
3. `detections`: walk trace in order; event when `score >= threshold` and (no previous event or `t >= last + refractory_s`). `hit_rate`: fraction of labels with an event in `[lt, lt + window_s]`; 0 labels → 0.0. `evaluate(traces, label_times, guided, background_s, threshold)`: `background_s <= 0` → `ValueError("no background audio")`; events = all traces' detections; false wakes = events not inside any `start <= e <= end` span; `fw_per_hour = fw / (background_s / 3600)`; `target_met = fw_per_hour <= FW_TARGET_PER_HOUR + EPS`. `sweep(..., grid=THRESHOLD_GRID)`: evaluate each; if any target_met → max hit_rate, ties lowest threshold; else fewest false_wakes, then highest hit_rate, then lowest threshold.
4. `board_wins(board, server)`: False if `server.hit_rate - board.hit_rate >= HIT_MARGIN - EPS`; False if `board.false_wakes >= 2 * max(server.false_wakes, 1)`; else True.
5. `normalize`: lowercase, every char not in `a-z0-9'` or space → space, split. `wer(refs, hyps)`: `ValueError` if lengths differ or total ref words is 0; word-level Levenshtein summed / total ref words. `pick_asr(results, baseline)`: baseline result by name; among results with `wer <= baseline.wer + ASR_WER_MARGIN + EPS` return min `median_ms`.
6. Loaders: `load_recordings(directory)` — each `*.json` not starting `labels-` whose sibling `.pcm` exists; `seconds = size / 32000`; sorted by start_wall. `load_labels` — all `labels-*.jsonl` lines, sorted by `t`. `guided_spans` — pair `session_start` with the next `session_end`; unterminated start → `(t, math.inf)`. `background_seconds` — total recording seconds minus overlap of each `[start_wall, start_wall+seconds]` with spans. `load_utterances` — `utt-*.pcm`, wall = int(last `-` field of stem) / 1000, sorted. `pair_commands` — for each `command` label in order, first unused utterance with wall in `[t, t + window_s]` → `(text, path)`.
**New symbols:** all names above, signatures as in Task 8 Anchors plus: `hit_rate(events: list[float], label_times: list[float], window_s: float = POSITIVE_WINDOW_S) -> float`; `evaluate(traces: list[list[tuple[float, float]]], label_times: list[float], guided: list[tuple[float, float]], background_s: float, threshold: float) -> EngineResult`; `sweep(traces, label_times, guided, background_s, grid: tuple[float, ...] = THRESHOLD_GRID) -> EngineResult`; `board_wins(board: EngineResult, server: EngineResult) -> bool`; `normalize(text: str) -> list[str]`; `wer(refs: list[str], hyps: list[str]) -> float`; `pick_asr(results: list[AsrResult], baseline: str) -> AsrResult`; `load_recordings(directory: str) -> list[Recording]`; `load_labels(directory: str) -> list[dict]`; `guided_spans(labels: list[dict]) -> list[tuple[float, float]]`; `background_seconds(recordings: list[Recording], spans: list[tuple[float, float]]) -> float`; `load_utterances(directory: str) -> list[tuple[float, str]]`; `pair_commands(labels: list[dict], utterances: list[tuple[float, str]], window_s: float = COMMAND_WINDOW_S) -> list[tuple[str, str]]`.
**Verify:** `cd harness && .venv/bin/python -m pytest -q tests/test_wakebench.py 2>&1 | tail -1` — expected: `22 passed`.
**Forbidden:** stdlib only (no numpy, no jiwer); no model imports; no edits to tests.
**Depends:** Task 8
**Why:** Spec bench win rule and ASR pick rule (`docs/specs/2026-10-06-speaker-firmware-wake.md:57-62`, `:110`), kept pure so replay scripts stay thin.

### Task 10: Add the guided wake/command labelling script
- [ ] status
**Objective:** `scripts/wake_guide.py` prompts the user through wake attempts or commands and writes a `labels-<ms>.jsonl` file the bench loaders read.
**Write-scope:** `harness/scripts/wake_guide.py` (new)
**Read-context:** `harness/scripts/smoke_session.py:1-30` (script style)
**Anchors:**
`UTTERANCES = [` @ `harness/scripts/smoke_session.py`
**Steps:**
1. argparse: `--dir` (default `os.environ.get("CADENCE_BENCH_RECORD_DIR", "bench_audio")`), `--block` required choice `wake|commands`, `--reps` int default 10, `--dry-run`.
2. `COMMANDS` (exact, 20): "what's playing", "turn it up", "turn it down", "pause the music", "resume the music", "skip this song", "play something chill", "play some jazz", "I like this song", "who sings this", "make it quieter", "mute the speaker", "unmute the speaker", "play the next track", "what album is this", "tell me a joke", "play something upbeat", "go back to the previous song", "stop the music", "how are you today".
3. Non-dry: file `<dir>/labels-<int(time.time()*1000)>.jsonl`, one JSON object per line, flushed per line. First line `{"kind":"session_start","t":time.time(),"block":block}`; `{"kind":"session_end","t":time.time()}` written in a `finally`.
4. Wake block: for condition in `("quiet","music")`, for distance in `(1, 3, 5)`: ready prompt `f"Stand {distance} m from the speaker ({condition}{'; start music at normal listening volume first' if condition == 'music' else ''}). Press Enter when ready: "`; then for i in 1..reps: print `f"[{i}/{reps}] Say 'hey jarvis' now"`, label `{"kind":"wake","t":time.time(),"distance_m":distance,"condition":condition}`, sleep 6.0 (comment: matches `cadence.wakebench.POSITIVE_WINDOW_S`), sleep 2.0.
5. Commands block: ready prompt `"Stand 3 m from the speaker, music off. Press Enter when ready: "`; for each command: print `f"Say: 'hey jarvis', pause one second, then '{cmd}'"`, label `{"kind":"command","t":time.time(),"text":cmd}`, sleep 15.0 (comment: matches `COMMAND_WINDOW_S`).
6. `--dry-run`: print each ready prompt as a line prefixed `READY: ` instead of `input()`, print the same Say lines, no sleeps, no file.
**New symbols:** `COMMANDS: list[str]`, `main() -> int` in the script.
**Verify:** `cd harness && .venv/bin/python scripts/wake_guide.py --block wake --reps 1 --dry-run | grep -c "Say 'hey jarvis' now" && .venv/bin/python scripts/wake_guide.py --block commands --dry-run | grep -c "^Say:"` — expected: `6` then `20`.
**Forbidden:** no import of `cadence.wakebench` (keeps this task independent); no network; no edits outside the script.
**Depends:** none
**Why:** Spec data flow: guided script prompts and writes label timestamps next to the audio (`docs/specs/2026-10-06-speaker-firmware-wake.md:149`).

### Task 11: Add the wake replay bench that writes docs/preflight/wake-bench.md
- [ ] status
**Objective:** `scripts/wake_bench.py` replays recordings through openWakeWord and microWakeWord, applies the win rule, and writes the report; `--selftest` proves the pipeline end to end.
**Write-scope:** `harness/scripts/wake_bench.py` (new)
**Read-context:** `harness/cadence/wakebench.py` (from Task 9); `harness/scripts/preflight_wake_bench.py` (from Task 3); `harness/cadence/audio/wakeword.py:9-16`
**Anchors:**
`def sweep(traces, label_times, guided, background_s, grid: tuple[float, ...] = THRESHOLD_GRID) -> EngineResult` @ `harness/cadence/wakebench.py` (from Task 9)
`WAKE_FRAME_BYTES = 2560` @ `harness/cadence/audio/wakeword.py`
**Steps:**
1. args: `--dir` (default env `CADENCE_BENCH_RECORD_DIR` or `bench_audio`), `--out` (default `../docs/preflight/wake-bench.md`), `--selftest`.
2. `oww_trace(rec)`: fresh `openwakeword.model.Model(wakeword_models=[WAKE_MODEL], inference_framework="onnx")`; read the pcm in `WAKE_FRAME_BYTES` frames; frame k score `predict(np.frombuffer(frame, np.int16))[WAKE_MODEL]` at `t = rec.start_wall + (k + 1) * 0.08`. `mww_trace(rec)`: fresh `MicroWakeWordFeatures()` and `MicroWakeWord.from_builtin(Model.HEY_JARVIS)`; feed 3200-byte chunks; feature index k → `t = rec.start_wall + (k + 1) * 0.010`; append `(t, p)` when `process_streaming_prob` returns non-None. Defaults: oww `WAKE_THRESHOLD`, mww `probability_cutoff`.
3. `run(directory, out) -> str`: load recordings/labels, spans, background seconds, wake label times; per engine compute traces once, `evaluate` at default and `sweep`; at swept thresholds, hit rate per (condition in quiet,music × distance in 1,3,5) with attempt counts; verdict `board_wins(mww_swept, oww_swept)`.
4. Report (write to `out`, also return): `# Wake bench (generated by harness/scripts/wake_bench.py on <date>)`; `Background audio: <h:.2f> h. Positive attempts: <n>.`; table `| engine | thresholds | threshold | hit rate | false wakes | false wakes/h | target met |` with rows openWakeWord default/swept, microWakeWord default/swept; `## Hit rate by condition (swept thresholds)` table `| condition | distance m | attempts | openWakeWord | microWakeWord |`; `## Verdict`; exactly one line `Winner: board (microWakeWord, threshold <x>)` or `Winner: server (openWakeWord, threshold <x>)`; then `Rule: board wins unless server hit rate >= board + 10 points, or board false wakes >= 2x max(server false wakes, 1); applied at swept thresholds.`
5. `--selftest`: temp dir with `selftest-1000000.json` (start_wall 1000.0) + 60 s zeros `.pcm`, labels file with session_start t=1000.0, wake t=1005.0 (distance_m 3, quiet), session_end t=1010.0; `run` with out in the temp dir; print the report.
**New symbols:** `oww_trace(rec: Recording) -> list[tuple[float, float]]`, `mww_trace(rec: Recording) -> list[tuple[float, float]]`, `run(directory: str, out: str) -> str`, `main() -> int`.
**Verify:** `cd harness && .venv/bin/python scripts/wake_bench.py --selftest | grep -cE "^Winner: (board|server) "` — expected: `1`.
**Forbidden:** no edits to `cadence/`; don't write under `docs/` in selftest; no new deps.
**Depends:** Task 9, Task 3
**Why:** Spec decision "Wake site is decided by a replay bench" — same audio through both engines, report applies the rule mechanically (`docs/specs/2026-10-06-speaker-firmware-wake.md:50-62`).

### Task 12: Add the ASR bench and make Asr model/beam configurable
- [ ] status
**Objective:** `scripts/asr_bench.py` times six Whisper configs on recorded command utterances and writes the pick per the 2-point WER rule; `Asr` accepts model and beam.
**Write-scope:**
`harness/scripts/asr_bench.py` (new)
`harness/cadence/audio/asr.py`
**Read-context:** `harness/cadence/audio/asr.py:11-27`; `harness/cadence/wakebench.py` (from Task 9)
**Anchors:**
`class Asr:` @ `harness/cadence/audio/asr.py`
`def pick_asr(results: list[AsrResult], baseline: str) -> AsrResult` @ `harness/cadence/wakebench.py` (from Task 9)
**Steps:**
1. `Asr.__init__(self, model_name: str = "small.en", beam_size: int = 5)`: `WhisperModel(model_name, device="cpu", compute_type="int8")`, store `self.beam_size`; `transcribe` passes `beam_size=self.beam_size` (everything else unchanged).
2. Script: `CONFIGS = [("small.en",5),("small.en",1),("base.en",5),("base.en",1),("distil-small.en",5),("distil-small.en",1)]`, name `f"{model}/beam{beam}"`, `BASELINE = "small.en/beam5"`. args `--dir`, `--out` (default `../docs/preflight/asr-bench.md`), `--selftest`.
3. `run(directory, out) -> str`: `pair_commands(load_labels(d), load_utterances(d))`; none → print `no command utterances found` to stderr, return exit 1 from main. Per config: `Asr(m, b)`; one untimed warm-up transcribe of the first pcm; time each transcribe with `time.perf_counter`; `AsrResult(name, wer(refs, hyps), statistics.median(ms))`; p90 = sorted ms at index `int(0.9 * (n - 1))` (display only). `chosen = pick_asr(results, BASELINE)`.
4. Report: `# ASR bench (generated by harness/scripts/asr_bench.py on <date>)`; `Command utterances: <paired> (of <prompted> prompted).`; table `| config | WER | median ms | p90 ms |`; line `Chosen: <name>`; line `Rule: fastest median within 2 WER points of small.en/beam5.`
5. `--selftest`: temp dir, labels with command t=1000.0 "turn it up" and t=1100.0 "pause the music", utterance files `utt-selftest-1001000.pcm` and `utt-selftest-1101000.pcm` each 1 s of zeros; run with out in the temp dir; print report.
**New symbols:** `Asr.__init__(self, model_name: str = "small.en", beam_size: int = 5)`; script `CONFIGS`, `BASELINE`, `run(directory: str, out: str) -> str`, `main() -> int`.
**Verify:** `cd harness && .venv/bin/python scripts/asr_bench.py --selftest | grep -c "^Chosen: " && .venv/bin/python -m pytest -q 2>&1 | tail -1` — expected: `1`, then `224 passed`.
**Forbidden:** no change to `vad_filter`/`NO_SPEECH_PROB_MAX` behaviour; don't change `wiring.py` defaults (phase 4 adopts the pick); no new deps.
**Depends:** Task 9, Task 3
**Why:** Spec latency decision: bench beam 1 vs 5 and small/base/distil, pick fastest within 2 WER points (`docs/specs/2026-10-06-speaker-firmware-wake.md:110`).
