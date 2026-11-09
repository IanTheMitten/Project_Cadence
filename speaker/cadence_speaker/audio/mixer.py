import numpy as np

SPK_SAMPLE_RATE = 44100
SPK_CHANNELS = 2
DUCK_GAIN = 0.25
DUCK_RAMP_MS = 150


def mix(music: bytes, speech: bytes, duck: float) -> bytes:
    if len(music) != len(speech):
        raise ValueError("music and speech must have equal length")
    music_i16 = np.frombuffer(music, dtype=np.int16).astype(np.int32)
    speech_i16 = np.frombuffer(speech, dtype=np.int16).astype(np.int32)
    mixed = music_i16 * duck + speech_i16
    clipped = np.clip(mixed, -32768, 32767).astype(np.int16)
    return clipped.tobytes()


def ramp(frames: int, start: float, end: float) -> np.ndarray:
    return np.linspace(start, end, frames, dtype=np.float32)


def duck_frames() -> int:
    return SPK_SAMPLE_RATE * DUCK_RAMP_MS // 1000
