# Technical spec - Speaker firmware: baseline, wake bench, "hey cadence"

> Status: ready for planning. Feed to /autopilot-plan once ready - it verifies this line and refuses a spec that isn't "ready for planning".

## Source

Goal as stated by the user on 2026-10-06 (no PRD): flash the board with `voice_chat/` and tune it until it works well; consider moving the wake word from the server to the ESP32; the wake word becomes "hey cadence".

This is the "Firmware plan (separate)" row of `docs/specs/2026-10-01-cadence-decision-harness-v1.md` (Scope and roadmap). It revisits two v1 decisions there: "Wake word is server-side in v1" and "Echo handling moves to the firmware plan".

User-stated success criteria (these are the acceptance targets, see Testing strategy):
- S1 wakes reliably across the room
- S2 rare false wakes
- S3 wakes over music
- S4 fast response, and latency cut as far as possible

Board facts (read from the chip with `esptool.py flash_id` on 2026-10-06): ESP32-S3 (QFN56) rev v0.2, embedded PSRAM 2 MB (quad), flash 8 MB. Port `/dev/ttyACM0` on this host.

Repo facts this spec depends on:
- `voice_chat/` has never been flashed against the harness: no `build/`, no `voice_chat/sdkconfig.defaults` (WiFi SSID and password default to `""` in `voice_chat/main/Kconfig.projbuild`). The v1 e2e smoke (`docs/preflight/e2e-v1.md`) used a text session with wake disabled, so the real mic path (board mic, `WakeGate`, `VadSegmenter`, faster-whisper) is unverified on hardware.
- `SessionCaps.from_list` (`harness/cadence/session.py`) rejects unknown caps, so any new hello cap needs a harness change.
- The board's playback ring (`AUDIO_RING_BYTES`, 64 KB) holds about 370 ms of 44.1 kHz stereo audio and carries both music and TTS, so the board cannot tell them apart.
- ASR is `WhisperModel("small.en", device="cpu", compute_type="int8")` with `beam_size=5` (`harness/cadence/audio/asr.py`). The host has 8 CPU cores and no GPU.
- The `voice_chat/` section of `CLAUDE.md` is stale: it describes `speak_stream_task`/`mic_upload_task` and `tools/voice_chat_host.py`, but the code is now a `/session` WebSocket client.

## Architecture

Work runs in four phases. Each phase ends at a measured result, and the next phase's shape depends on it.

1. **Baseline.** Flash `voice_chat/` as-is (server wake, stock `hey_jarvis_v0.1`), run real spoken turns, fix only what blocks a turn.
2. **Measure.** Add per-stage turn timing and a bench recording mode to the harness. Record labelled wake attempts, background audio, and spoken commands from the real board in the real room.
3. **Bench and decide.** Replay the recordings offline through openWakeWord and microWakeWord (both on stock "hey jarvis") and through ASR configs. Apply the agreed rules, record the result in `docs/preflight/`.
4. **Ship "hey cadence".** Train "hey cadence" on Colab for the winning engine, build the winning path (board wake or server wake), and check the acceptance targets.

Components after phase 4, for either bench outcome:

- **Board (`voice_chat/main/voice_chat.c`).** Speaker TX and mic RX as now. The mic streams to the server all the time, as now. New: a local wake chime, self-mute on `tts_start`/`tts_end`, and, if board wake wins, a microWakeWord detector task that sends a `wake` frame.
- **Harness (`/session` in `harness/cadence/server.py`).** Opens the listen window either on its own `WakeGate` (server wake) or on the board's `wake` frame (board wake). VAD, ASR and the pipeline stay as they are. New: `tts_start`/`tts_end` frames around spoken output, a `wake` frame to the board when the server detects the wake word, per-stage timing, bench recording.
- **Bench scripts (`harness/scripts/`).** Record, replay and analyse. They run in a separate venv if microWakeWord's Python inference does not install on Python 3.14.

## Decisions

### Decision: Order of work - baseline before any firmware rewrite
- **Status:** Accepted
- **Context:** The real mic path has never run on hardware (see Source). Changing the wake engine before that would mix board, network and harness bugs in one debugging session.
- **Options considered:** (a) flash as-is first, get numbers, then change things; (b) go straight to the board-wake build.
- **Decision:** (a). It also produces the recordings the bench needs, so it costs little beyond the flash.
- **Consequences:** The first deliverable is a working, measured baseline, not "hey cadence". Baseline fixes are limited to what blocks a spoken turn; tuning waits for the bench.

### Decision: Wake site is decided by a replay bench, not up front
- **Status:** Accepted
- **Context:** The user prefers wake on the board but asked to bench-test first. Board wake would mean less traffic later and a faster chime; server wake means no firmware port. Which engine hears this mic in this room better is the open fact.
- **Options considered:** (a) record real board audio, replay offline through both engines on stock "hey jarvis"; (b) port microWakeWord to the board first, then A/B live; (c) train "hey cadence" for both engines first, then bench.
- **Decision:** (a). Same audio through both engines gives a fair comparison, and nothing gets built before the decision. microWakeWord is replayed in Python with the same `.tflite` model file the board would run (pymicro-wakeword or microWakeWord's own inference code). The on-board wake-to-detection latency is measured separately with a minimal benchmark firmware or taken from the port in phase 4.
- **Consequences:** The bench compares engines on "hey jarvis", not on "hey cadence". The "hey cadence" model is trained only for the winner and checked against the absolute targets in phase 4. The stock "hey jarvis" model for microWakeWord comes from the `esphome/micro-wake-word-models` repo; its exact file name is checked at plan time.

### Decision: Bench win rule
- **Status:** Accepted
- **Context:** Board wake brings a faster chime with no network hop and lays the groundwork for streaming only after wake, so it gets a tie-break margin.
- **Options considered:** (a) board wins unless its hit rate is at least 10 points worse or it has at least 2x the false wakes; (b) best numbers win, no preference; (c) board wins unless it misses the absolute targets.
- **Decision:** (a). Hit rate is measured on all labelled positive attempts pooled (1/3/5 m, quiet and over music). False wakes are counted per hour on the background recordings. Both engines run at their default thresholds, and both are also swept to the threshold that gives at most 1 false wake per 8 h; the rule is applied at the swept thresholds.
- **Consequences:** The result and the chosen thresholds go into `docs/preflight/wake-bench.md`. Phase 4's path follows from that file mechanically.

### Decision: Wake engines - microWakeWord on board, openWakeWord on server
- **Status:** Accepted
- **Context:** "Hey cadence" is a custom phrase. esp-sr WakeNet custom phrases are trained by Espressif for a fee, need at least 20,000 corpus samples and take 2-3 weeks ([Espressif customization process](https://docs.espressif.com/projects/esp-sr/en/latest/esp32/wake_word_engine/ESP_Wake_Words_Customization.html)). microWakeWord trains self-serve from synthetic Piper TTS samples and runs on ESP32-S3 under ESP-IDF via `espressif/esp-tflite-micro` plus `esphome/esp-micro-speech-features`. openWakeWord also trains self-serve from synthetic samples and is already wired in the harness.
- **Options considered:** board: (a) microWakeWord, (b) esp-sr WakeNet; server: (c) openWakeWord custom model.
- **Decision:** (a) as the board candidate and (c) as the server candidate. (b) is dropped because the phrase cannot be self-trained.
- **Consequences:** If board wins, the firmware gains a TFLite Micro dependency and a port of ESPHome's microWakeWord streaming logic. Its model and tensor arena are small enough for internal RAM, so 2 MB PSRAM is not a constraint here. If server wins, only the model file and `WAKE_MODEL` in `harness/cadence/config.py` change.

### Decision: "Hey cadence" is trained on Google Colab for the winning engine only; "hey jarvis" serves until then
- **Status:** Accepted
- **Context:** Training needs a GPU to finish in hours; this host has none.
- **Options considered:** (a) Colab GPU; (b) this host's CPU overnight or longer; (c) another machine.
- **Decision:** (a). Stock "hey jarvis" stays the live wake word through phases 1-3 and until the trained model passes phase 4.
- **Consequences:** Training is a manual, user-run step (Colab notebook or Docker trainer). Its output model file is copied into the repo: for board wake it goes into the firmware (see Model delivery), for server wake into `harness/`. Training config (phrase spellings, sample counts, negatives) is recorded next to the model.

### Decision: Echo handling - ducking plus wake self-mute while the assistant speaks; no AEC this round
- **Status:** Accepted
- **Context:** S3 (wake over music) argues for AEC. esp-sr's audio front end could do single-mic AEC with a playback reference, but that needs the reference downsampled from 44.1 kHz stereo to 16 kHz and time-aligned, and has not been shown to fit next to the playback ring and WebSocket on 2 MB PSRAM.
- **Options considered:** (a) keep music ducking under speech, and ignore wake while the assistant is speaking; (b) esp-sr AEC now; (c) no echo handling.
- **Decision:** (a). The bench measures wake over music without AEC first. If the "over music" target fails in phase 4, AEC becomes the next firmware plan with that data as its input.
- **Consequences:** Wake over loud music may miss. That is measured, not assumed away. The assistant cannot wake itself, but you also cannot interrupt a reply with the wake word.

### Decision: Self-mute signal - server sends `tts_start` / `tts_end`
- **Status:** Accepted
- **Context:** The board's ring carries music and TTS mixed (`SpeakerPort.speak` ducks music under speech), so it cannot detect "assistant speaking" from its own audio.
- **Options considered:** (a) server sends `{"type":"tts_start"}` / `{"type":"tts_end"}` text frames around each spoken output (ack clips and `say` sentences); (b) mute wake for the whole turn, `turn_start` to `turn_end`.
- **Decision:** (a). On `tts_end` the board keeps wake muted until the bytes already in its ring have played: about ring fill (bytes) / 176.4 bytes per ms, plus a fixed I2S tail margin. With server wake, the `Listener` ignores the gate between the same two points, plus a fixed tail margin, because it cannot see the board's ring fill.
- **Consequences:** Adds two frame types to the `/session` protocol. Old clients ignore unknown text frames: `voice_chat.c` logs them, `smoke_session.py` behaviour is checked at plan time. Reply barge-in stays out of scope.

### Decision: Board-wake turn protocol - mic keeps streaming, `wake` frame opens the listen window
- **Status:** Accepted
- **Context:** The user answered "for now (v1) lets just keep things simple" to the protocol question, and confirmed this reading at spec review: no streaming-on-demand yet. The mic streams continuously as today, and the board's detection only replaces the server's wake gate.
- **Options considered:** (a) board sends a wake frame, streams only after wake, and the server sends `listen_end`; (b) board also runs its own end-of-speech VAD; (c) board streams continuously and the wake frame only opens the window.
- **Decision:** (c), the simplest reading. Hello gains a `wake_local` cap. A session with `wake_local` gets a `Listener` with no `WakeGate`, and a `{"type":"wake"}` text frame starts the 8 s listen window with a fresh `VadSegmenter`. Because frames on one WebSocket arrive in order, a command spoken in the same breath as the wake word reaches VAD after the window opens.
- **Consequences:** The privacy and bandwidth win of streaming only after wake is deferred, and (a) is the next step when wanted. The `Listener` gains an external trigger, and `SessionCaps` gains `wake_local`. If the user meant (a), only the board's mic task and one server frame change, so this is cheap to reverse at spec review.

### Decision: Wake chime plays locally on the board
- **Status:** Accepted
- **Context:** S4. The server's acknowledgement clip plays only after the decider routes, so wake feedback arrives seconds late.
- **Options considered:** (a) board plays a short built-in earcon at wake; (b) rely on the ack pool only.
- **Decision:** (a). With board wake the chime fires on detection. With server wake the server sends `{"type":"wake"}` to the board and the board chimes on receipt. The earcon is a short PCM clip compiled into the firmware and written into the ring ahead of other audio.
- **Consequences:** The same `wake` frame type flows in both directions (board to server under board wake, server to board under server wake). Its timing is logged on the board (serial) for the 300 ms target.

### Decision: Latency work this round - instrumentation, local chime, ASR tuning; end-of-speech silence stays 480 ms
- **Status:** Accepted
- **Context:** S4 asks for latency cut as far as possible. Known stages: wake, VAD end (`VAD_END_FRAMES` = 16, about 480 ms), ASR (CPU `small.en`, beam 5), decide (Jev about 200-300 ms, LLM on escalation), execute (Muse `music.play` was about 5.9 s in `docs/preflight/e2e-v1.md`), TTS first sentence, network and ring.
- **Options considered:** per-stage timing; local chime; ASR speed tuning; shorter end-of-speech silence.
- **Decision:** First three in scope; the user declined shortening the end-of-speech silence. Timing: each turn logs monotonic stamps for wake, speech end, ASR done, decision done, first output audio byte sent, and turn end, written to a stable log line and to the decision log's `latency_ms` where the stage already exists. ASR tuning benches `beam_size` 1 vs 5 and `small.en` vs `base.en` vs a distil English model (the faster-whisper model name is checked at plan time) on the recorded commands. Pick the fastest config whose word error rate is within 2 points of today's `small.en`/beam 5.
- **Consequences:** Muse execute latency is visible in the numbers but out of scope for this spec (Muse-owned, per `docs/handoffs/2026-10-01-muse-cadence-contract.md`).

### Decision: Bench recording handling - local, gitignored, deleted after the bench
- **Status:** Accepted
- **Context:** The false-wake measurement needs hours of household audio.
- **Options considered:** (a) record only while a bench flag is set, under gitignored `harness/bench_audio/`, delete once results are written up; (b) keep the clips as a regression set.
- **Decision:** (a). Recording is off unless an env flag (for example `CADENCE_BENCH_RECORD_DIR`) is set. Only numbers go into `docs/preflight/`.
- **Consequences:** Future models (for example a retrained "hey cadence") cannot be re-checked on the same audio and need a fresh recording. The deletion step is an explicit plan task, not a manual afterthought.

### Decision: Board config and secrets - committed placeholders plus gitignored local override
- **Status:** Accepted
- **Context:** `.gitignore` already ignores every `sdkconfig.defaults` and `sdkconfig.defaults.local`, with a comment saying to un-ignore the placeholder file once credentials move to a local override.
- **Options considered:** (a) commit `voice_chat/sdkconfig.defaults` without secrets (PSRAM, flash size, WS URL), with SSID and password in gitignored `voice_chat/sdkconfig.defaults.local`, both listed via `SDKCONFIG_DEFAULTS` in `voice_chat/CMakeLists.txt`; (b) plaintext password in a committed `sdkconfig.defaults`.
- **Decision:** (a), and un-ignore `voice_chat/sdkconfig.defaults` only. Root and `mic_test/` stay as they are.
- **Consequences:** A fresh clone needs the user to create `voice_chat/sdkconfig.defaults.local` before building. The README or `CLAUDE.md` says so. The committed file sets 8 MB flash and enables PSRAM.

### Decision: Model delivery - wake model compiled into the firmware image
- **Status:** Accepted
- **Context:** This only applies if board wake wins. Swapping the model is rare (stock to "hey cadence", then occasional retrains), and 8 MB flash leaves room.
- **Options considered:** (a) embed the `.tflite` in the app binary (`EMBED_FILES`), update by reflashing; (b) separate model partition, flashed alone; (c) OTA download.
- **Decision:** (a). It is the simplest, and changing to (b) later only touches the partition table and the loader.
- **Consequences:** Every model swap is a full `idf.py flash`.

### Decision: CLAUDE.md `voice_chat/` section is corrected in phase 1
- **Status:** Accepted
- **Context:** The section describes the pre-harness HTTP/TCP design, and anyone flashing from it would point the board at the wrong server.
- **Options considered:** (a) rewrite the section to the `/session` WebSocket client during baseline; (b) leave it.
- **Decision:** (a), kept to the facts phase 1 touches (protocol, Kconfig names, config files).
- **Consequences:** Small docs task in phase 1.

## Data flow

Baseline (phase 1, unchanged code): board mic 16 kHz s16 mono, sent as WS binary frames, goes to `Listener` (`WakeGate` then `VadSegmenter`), then ASR, then `handle_text`, then the pipeline. Output is `SpeakerPort` 44.1 kHz s16 stereo binary frames into the board ring, then I2S.

After phase 4, server wake: as baseline, plus server sends `wake` to the board on detection (board chimes). `SessionOutput.ack`/`say` are wrapped in `tts_start`/`tts_end`, and the `Listener` ignores the gate in that span plus a tail.

After phase 4, board wake: board mic samples go both to the WS (continuous) and to the microWakeWord task. On detection the board writes the chime into the ring and sends `{"type":"wake"}`. The server `Listener` (no gate) opens the 8 s window and runs VAD, ASR and the pipeline as before. While muted (between `tts_start` and `tts_end` plus ring drain), the board's detector ignores detections.

Bench (phase 2): with the record flag set, the server appends each session's raw mic PCM to a file under `harness/bench_audio/`. A guided script prompts the user ("say 'hey jarvis' from 3 m now") and writes label timestamps next to the audio. Unprompted background recordings are counted as negatives. Replay scripts read these files offline.

Timing: stamps live in-process per turn and are flushed on `turn_end`. Board-side wake-to-chime is logged on serial.

## Error handling

- WiFi drop or server down: unchanged. `esp_websocket_client` reconnects, the mic task skips sends while disconnected, the server's `finally` marks the device offline and stops the port.
- Wake fires but no speech within 8 s: window closes silently (current `Listener` behaviour); the chime was the only effect.
- Server wake detected but board not ready for the `wake` frame: the board just plays the chime late; nothing waits on it.
- `tts_end` lost (disconnect mid-reply): the board clears self-mute on WebSocket reconnect; the server's `Listener` is rebuilt per session.
- Bench record flag set but directory missing or not writable: the server logs one error and runs without recording; it never crashes a session.
- Model fails to load on the board: log the error and run without wake (the mic still streams, so a server-side fallback is possible by restarting the harness with server wake). There is no silent fallback in the firmware itself.

## Testing strategy

- **Harness changes (red tests first, as in v1).** `SessionCaps` accepts `wake_local`. A `wake` frame opens the `Listener` window with no gate. The `Listener` ignores the gate between `tts_start` and `tts_end` plus the tail. `SessionOutput` emits `tts_start`/`tts_end` around ack and say. The server sends `wake` on server detection. Timing stamps are recorded and flushed. The bench recorder is off by default and writes when the flag is set. Fakes as in v1 (fake wake model, FastAPI WebSocket test client); no hardware.
- **Bench scripts.** Unit-tested on synthetic PCM plus label files for the scoring math (hit rate, false wakes per hour, threshold sweep, WER).
- **Firmware.** No unit tests on device. Each firmware change is verified by building (`idf.py build` exits 0), flashing, and a scripted serial-log check (wake detected, chime logged, frames sent).
- **Acceptance (phase 4, with "hey cadence", recorded in `docs/preflight/`):**
  - S1: at least 9/10 wakes at 3 m, normal voice, quiet room.
  - S2: at most 1 false wake per 8 h of TV and conversation.
  - S3: at least 8/10 wakes at 3 m with music at normal listening volume. A miss here triggers the AEC follow-up, not a redo of this spec.
  - S4: chime within 300 ms of the end of the wake phrase. End of speech to first audio byte sent at most 2 s on Jev-only routes (no LLM, no Muse execute). ASR config per the latency decision.
- **Out of scope:** AEC, reply barge-in, streaming only after wake, end-of-speech silence tuning, Muse execute latency, root and `mic_test/` firmware.

## Tech stack

- Firmware: ESP-IDF v5.3 (`~/esp/esp-idf`), `espressif/esp_websocket_client` (existing). If board wake wins: `espressif/esp-tflite-micro` and `esphome/esp-micro-speech-features` via `idf_component.yml`, versions pinned at plan time from the component registry. (Wake engines decision.)
- Server wake: `openwakeword` (existing, `--no-deps`, ONNX). (Wake engines decision.)
- Bench microWakeWord replay: pymicro-wakeword or microWakeWord's reference inference, in a separate venv if it will not install on Python 3.14. (Wake site decision.)
- ASR: faster-whisper (existing); model and beam per bench. (Latency decision.)
- Training: Google Colab GPU with the microWakeWord trainer or the openWakeWord training notebook. ("Hey cadence" training decision.)

## Open questions

- Deferred: exact microWakeWord stock "hey jarvis" model file and the esp-tflite-micro / esp-micro-speech-features versions - verified from the registries at plan time; they do not change any decision here.
- Deferred: the distil English faster-whisper model name for the ASR bench - checked at plan time; the bench rule stands whichever model names exist.
- Deferred: whether pymicro-wakeword installs on Python 3.14 - checked at plan time; the fallback (separate venv) is already decided.
- Deferred: the phase-4 build path (board wake or server wake) - set mechanically by `docs/preflight/wake-bench.md` using the bench win rule; the plan should cover both branches or split at that point.

## Provenance

- user-picked: wake site decided by a replay bench; bench win rule; latency scope (end-of-speech silence excluded); training on Colab; self-mute via `tts_start`/`tts_end`; secrets in a gitignored local override; recordings deleted after the bench.
- recommended-and-accepted: baseline before the firmware rewrite; echo handling as ducking plus self-mute, no AEC this round; wake engines (microWakeWord / openWakeWord, esp-sr dropped); wake chime on the board.
- assumed: none open - board-wake turn protocol (reading of "keep things simple"), model compiled into the firmware, and the CLAUDE.md `voice_chat/` fix were stated as assumptions and confirmed by the user at spec review (2026-10-06).
- overrides: none.
