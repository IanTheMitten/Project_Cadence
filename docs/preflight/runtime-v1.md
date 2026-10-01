# Runtime preflight v1 (ianshomeserver)

Run: `cd harness && CADENCE_MUSE_BASE_URL=http://100.122.149.75:8080 .venv/bin/python scripts/preflight_v1.py`

Host: 8 CPUs, 15 GiB RAM (4.0 GiB used at run time).

| check | ok | detail | ms |
|---|---|---|---|
| asr load | yes | faster-whisper small.en | 47839 |
| asr transcribe | yes | transcribe 1s silence -> '' | 48040 |
| tts load | yes | kokoro | 916 |
| tts speak | yes | speak -> 361268 bytes | 3562 |
| openwakeword download | yes | hey_jarvis_v0.1 | 0 |
| openwakeword load | yes | onnx | 103 |
| openwakeword predict | yes | 50 frames predict, 2.7 ms/frame | 394 |
| jev multi-question | yes | model=jev-1.13.0 answers_type=dict keys_back=4/4 all=True | 217 |
| ollama gemma4:31b-cloud | yes | reply='Hi' | 457 |
| muse health | yes | GET http://100.122.149.75:8080/api/health -> HTTP 200 | 16 |

Notes:
- `asr transcribe` and `tts speak` ms include the preceding load (script timer spans both). Net: transcribe of 1 s silence ~201 ms; speak ~2646 ms (first call, 361268 bytes = ~2.05 s audio at 44.1 kHz stereo s16).
- ASR load 47.8 s is a cold first load (likely includes model download); a second run (not the first) had openwakeword download at 0 ms because models were cached by run 1 (run 1: download 3408 ms, predict 4581 ms for 50 frames incl. warmup).
- Kokoro files `tools/kokoro-v1.0.onnx` (325 MB) and `tools/voices-v1.0.bin` (28 MB) downloaded this task (gitignored, not committed).
- Jev: single POST, no retries; all four answer keys (`route`, `arg:kind`, `arg:when`, `arg:loud`) returned as a dict keyed by question name. Key not printed or stored.
- All checks green; no negative results.
