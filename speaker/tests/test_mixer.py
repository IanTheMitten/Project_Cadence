import numpy as np
import pytest

from cadence_speaker.audio.mixer import DUCK_GAIN, DUCK_RAMP_MS, mix, ramp


def test_constants():
    assert DUCK_GAIN == 0.25
    assert DUCK_RAMP_MS == 150


def test_mix_with_no_speech_returns_music_unchanged():
    music = np.full(100, 1000, dtype=np.int16).tobytes()
    speech = np.zeros(100, dtype=np.int16).tobytes()
    out = mix(music, speech, 1.0)
    assert out == music


def test_mix_ducks_music_by_gain():
    music = np.full(100, 1000, dtype=np.int16).tobytes()
    speech = np.zeros(100, dtype=np.int16).tobytes()
    out = mix(music, speech, DUCK_GAIN)
    samples = np.frombuffer(out, dtype=np.int16)
    assert np.all(samples == 250)


def test_mix_sums_ducked_music_and_speech():
    music = np.full(100, 1000, dtype=np.int16).tobytes()
    speech = np.full(100, 2000, dtype=np.int16).tobytes()
    out = mix(music, speech, DUCK_GAIN)
    samples = np.frombuffer(out, dtype=np.int16)
    assert np.all(samples == 2250)


def test_mix_clips_to_int16_range():
    music = np.full(100, 30000, dtype=np.int16).tobytes()
    speech = np.full(100, 30000, dtype=np.int16).tobytes()
    out = mix(music, speech, 1.0)
    samples = np.frombuffer(out, dtype=np.int16)
    assert np.all(samples == 32767)
    assert not np.any(samples < 0)


def test_mix_requires_equal_lengths():
    music = np.full(100, 1000, dtype=np.int16).tobytes()
    speech = np.full(50, 1000, dtype=np.int16).tobytes()
    with pytest.raises(ValueError):
        mix(music, speech, DUCK_GAIN)


def test_ramp_endpoints_and_length():
    r = ramp(100, 1.0, 0.25)
    assert len(r) == 100
    assert r[0] == 1.0
    assert r[-1] == 0.25


def test_ramp_is_monotonic_down():
    r = ramp(100, 1.0, 0.25)
    assert np.all(np.diff(r) <= 0)
