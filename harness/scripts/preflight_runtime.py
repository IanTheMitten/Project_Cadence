#!/usr/bin/env python3
"""Preflight check: do the voice-chat host's runtime deps import and run on
this interpreter, and how fast are ASR/TTS.

Prints IMPORT lines for each dependency (never aborting on a failed one),
then loads faster-whisper and Kokoro and times a representative ASR/TTS run
each. See docs/preflight/runtime.md for the recorded result.
"""
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import numpy as np

IMPORT_TARGETS = [
    ("mcp", "mcp"),
    ("faster_whisper", "faster-whisper"),
    ("kokoro_onnx", "kokoro-onnx"),
    ("webrtcvad", "webrtcvad"),
    ("fastapi", "fastapi"),
    ("websockets", "websockets"),
    ("httpx", "httpx"),
]


def check_imports():
    for module_name, dist_name in IMPORT_TARGETS:
        try:
            __import__(module_name)
            try:
                v = version(dist_name)
            except PackageNotFoundError:
                v = "unknown"
            print(f"IMPORT {module_name} OK {v}")
        except Exception as exc:  # noqa: BLE001 - report, never abort
            print(f"IMPORT {module_name} FAIL {exc!r}")


def time_whisper():
    from faster_whisper import WhisperModel

    t0 = time.time()
    model = WhisperModel("small.en", device="cpu", compute_type="int8")
    load_s = time.time() - t0

    sr = 16000
    duration_s = 3.0
    t = np.arange(int(sr * duration_s)) / sr
    rng = np.random.default_rng(0)
    audio = (
        0.1 * np.sin(2 * np.pi * 440.0 * t)
        + rng.uniform(-0.01, 0.01, size=t.shape)
    ).astype(np.float32)

    times = []
    for _ in range(3):
        t0 = time.time()
        segments, _info = model.transcribe(audio, beam_size=5, vad_filter=True)
        list(segments)  # force generator to run
        times.append(time.time() - t0)
    mean_asr_s = sum(times) / len(times)
    return load_s, mean_asr_s, duration_s


def time_kokoro():
    from kokoro_onnx import Kokoro
    from kokoro_onnx.config import SAMPLE_RATE as KOKORO_SAMPLE_RATE

    class PatchedKokoro(Kokoro):
        """kokoro-onnx 0.4.7's Kokoro._create_audio hardcodes speed as int32 for
        "input_ids"-schema models, but kokoro-v1.0.onnx's speed input is
        tensor(float) -- ONNXRuntimeError: Unexpected input data type. Actual:
        (tensor(int32)), expected: (tensor(float)). Same method, speed cast to
        float32 instead."""

        def _create_audio(self, phonemes, voice, speed):
            tokens = np.array(self.tokenizer.tokenize(phonemes), dtype=np.int64)
            voice = voice[len(tokens)]
            tokens = [[0, *tokens, 0]]
            if "input_ids" in [i.name for i in self.sess.get_inputs()]:
                inputs = {
                    "input_ids": tokens,
                    "style": np.array(voice, dtype=np.float32),
                    "speed": np.array([speed], dtype=np.float32),
                }
            else:
                inputs = {
                    "tokens": tokens,
                    "style": voice,
                    "speed": np.ones(1, dtype=np.float32) * speed,
                }
            audio = self.sess.run(None, inputs)[0]
            return audio, KOKORO_SAMPLE_RATE

    here = Path(__file__).resolve().parent.parent.parent / "tools"
    kokoro = PatchedKokoro(str(here / "kokoro-v1.0.onnx"), str(here / "voices-v1.0.bin"))

    text = "Sure, putting something on now."
    synth_times = []
    audio_durations = []
    for _ in range(3):
        t0 = time.time()
        samples, sr = kokoro.create(text, voice="af_sarah")
        synth_times.append(time.time() - t0)
        audio_durations.append(len(samples) / sr)
    mean_synth_s = sum(synth_times) / len(synth_times)
    mean_audio_s = sum(audio_durations) / len(audio_durations)
    return mean_synth_s, mean_audio_s


def main():
    check_imports()

    load_s, mean_asr_s, asr_audio_s = time_whisper()
    print(f"WHISPER load_s={load_s:.3f} mean_asr_s={mean_asr_s:.3f} audio_s={asr_audio_s:.3f}")

    mean_synth_s, mean_audio_s = time_kokoro()
    print(f"KOKORO mean_synth_s={mean_synth_s:.3f} mean_audio_s={mean_audio_s:.3f}")


if __name__ == "__main__":
    main()
