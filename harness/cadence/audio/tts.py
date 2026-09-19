from pathlib import Path

import numpy as np
from kokoro_onnx import Kokoro
from kokoro_onnx.config import SAMPLE_RATE as KOKORO_SAMPLE_RATE
from scipy.signal import resample_poly

SPK_SAMPLE_RATE = 44100
TTS_VOICE = "af_sarah"

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_KOKORO_MODEL_PATH = REPO_ROOT / "tools" / "kokoro-v1.0.onnx"
DEFAULT_KOKORO_VOICES_PATH = REPO_ROOT / "tools" / "voices-v1.0.bin"


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


def kokoro_audio_to_i2s_pcm(samples: np.ndarray, src_rate: int) -> bytes:
    """float32 mono @ src_rate -> s16le stereo @ SPK_SAMPLE_RATE bytes."""
    resampled = resample_poly(samples, SPK_SAMPLE_RATE, src_rate)
    clipped = np.clip(resampled, -1.0, 1.0)
    mono16 = (clipped * 32767.0).astype(np.int16)
    stereo = np.repeat(mono16[:, None], 2, axis=1)
    return stereo.tobytes()


def silence_chunk(ms: int) -> bytes:
    n = SPK_SAMPLE_RATE * ms // 1000
    return np.zeros(n * 2, dtype=np.int16).tobytes()


class Tts:
    def __init__(self, model_path=DEFAULT_KOKORO_MODEL_PATH, voices_path=DEFAULT_KOKORO_VOICES_PATH):
        self.kokoro = PatchedKokoro(str(model_path), str(voices_path))

    def speak(self, text: str) -> bytes:
        samples, sr = self.kokoro.create(text, voice=TTS_VOICE)
        return kokoro_audio_to_i2s_pcm(samples, sr)
