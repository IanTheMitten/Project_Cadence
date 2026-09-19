# Preflight: audio stack runtime check (Python 3.14.7)

Ran via `cd harness && .venv/bin/python scripts/preflight_runtime.py` against the
Task 1 venv (`harness/.venv`, all 14 deps from `harness/requirements.txt` installed).

## Imports

```
IMPORT mcp OK 2.2.0
IMPORT faster_whisper OK 1.2.1
IMPORT kokoro_onnx OK 0.4.7
IMPORT webrtcvad OK 2.0.10
IMPORT fastapi OK 0.141.1
IMPORT websockets OK 17.1
IMPORT httpx OK 0.28.1
```

Every import succeeded. No second-venv fallback needed for this dep set on 3.14.7.

(`webrtcvad` emits a `pkg_resources is deprecated` `UserWarning` on import via
`import pkg_resources` — harmless, not a failure.)

## Whisper (ASR) load + transcribe timing

- Model: `WhisperModel("small.en", device="cpu", compute_type="int8")`
- Model weights (`models--Systran--faster-whisper-small.en`) were already present
  in `~/.cache/huggingface/hub` from before this session (dir mtime 2026-09-15,
  predates this preflight run on 2026-09-19) — no download performed.
- Load time: first observed run **1.146 s** (cold filesystem cache), **0.627 s**
  on a repeat run in the same session (warm).
- Test signal: 3.000 s of 16000 Hz mono float32 (440 Hz sine, amplitude 0.1 —
  amplitude not pinned by the brief, chosen arbitrarily — plus uniform noise at
  amplitude 0.01) — measures decode/pipeline cost, not transcription accuracy
  (no real speech in the signal).
- `model.transcribe(audio, beam_size=5, vad_filter=True)`, 3 runs:
  - mean ASR time: **0.006 s**
  - real-time factor (ASR time / audio duration): **0.002**

**This ASR figure is not an ASR latency budget.** `vad_filter=True` correctly
identifies the synthetic sine+noise signal as non-speech and short-circuits
most/all of the audio before it reaches the decoder, so 0.006 s measures VAD
rejection cost, not transcription cost. Per the brief, the signal and flags
here are fixed (no real speech, `vad_filter=True`) — this number establishes
only that the model loads and the transcribe pipeline runs end-to-end without
error on 3.14.7; a real-speech re-measure would be a separate, follow-on
measurement.

## Kokoro (TTS) synthesis timing

- `PatchedKokoro` (copied verbatim from `tools/voice_chat_host.py:88-112`) loaded
  against `tools/kokoro-v1.0.onnx` / `tools/voices-v1.0.bin`.
- Text: `"Sure, putting something on now."`, voice `af_sarah`, 3 runs:
  - mean synthesis time: **0.631 s**
  - mean audio duration: **1.643 s**
  - real-time factor (synthesis time / audio duration): **0.384**

RTF < 1 means Kokoro synthesizes this sentence faster than it plays back on
this machine (CPU, onnxruntime 1.30.0).

## Verdict

All seven imports (`mcp`, `faster-whisper`, `kokoro-onnx`, `webrtcvad`,
`fastapi`, `websockets`, `httpx`) succeed on Python 3.14.7 in `harness/.venv`.
Whisper loads and runs; Kokoro loads and synthesizes faster than real time.
No blockers found for running this stack on 3.14.7 as-is.
