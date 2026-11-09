"""Tests for WakeGate and Listener (I16). The real openwakeword model is never loaded."""

import numpy as np

from cadence_speaker.audio.listener import Listener
from cadence_speaker.audio.wakeword import WAKE_FRAME_BYTES, WakeGate

NAME = "hey_jarvis_v0.1"
FRAME = np.zeros(1280, dtype=np.int16).tobytes()


class FakeModel:
    def __init__(self, scores):
        self.scores = list(scores)
        self.resets = 0

    def predict(self, frame):
        return {NAME: self.scores.pop(0)}

    def reset(self):
        self.resets += 1


class FakeVad:
    def __init__(self, utts=()):
        self.utts = list(utts)

    def feed(self, pcm):
        out, self.utts = self.utts, []
        return out


class FakeGate:
    def __init__(self):
        self.fire = False

    def feed(self, pcm):
        return self.fire


def _gate(model):
    return WakeGate(NAME, 0.5, model_factory=lambda name: model)


def test_gate_fires_on_full_frame_over_threshold_and_resets():
    assert WAKE_FRAME_BYTES == len(FRAME) == 2560
    model = FakeModel([0.2, 0.5])
    gate = _gate(model)
    assert gate.feed(FRAME) is False
    assert model.resets == 0
    assert gate.feed(FRAME) is True
    assert model.resets == 1


def test_gate_buffers_partial_frames():
    model = FakeModel([0.9])
    gate = _gate(model)
    assert gate.feed(FRAME[:1000]) is False
    assert model.scores == [0.9]  # predict not called yet
    assert gate.feed(FRAME[1000:]) is True
    assert model.scores == []


def test_model_factory_not_called_until_first_feed():
    calls = []

    def factory(name):
        calls.append(name)
        return FakeModel([0.0])

    gate = WakeGate(NAME, 0.5, model_factory=factory)
    assert calls == []
    gate.feed(FRAME)
    assert calls == [NAME]


def test_listener_without_gate_returns_vad_utterances():
    vad = FakeVad([b"utt"])
    listener = Listener(None, vad_factory=lambda: vad)
    assert listener.feed(b"x") == [b"utt"]


def test_listener_gate_flow():
    gate = FakeGate()
    vads = []

    def factory():
        vads.append(FakeVad([b"a", b"b"]))
        return vads[-1]

    listener = Listener(gate, vad_factory=factory, window_s=5.0, clock=lambda: 0.0)
    assert listener.feed(b"x") == []
    assert listener.listening is False
    gate.fire = True
    assert listener.feed(b"x") == []
    assert listener.listening is True
    gate.fire = False
    assert listener.feed(b"x") == [b"a"]
    assert listener.listening is False
    assert listener.feed(b"x") == []


def test_listener_window_expiry_returns_to_idle():
    gate = FakeGate()
    now = [0.0]
    listener = Listener(gate, vad_factory=lambda: FakeVad([b"a"]), window_s=5.0,
                        clock=lambda: now[0])
    gate.fire = True
    listener.feed(b"x")
    gate.fire = False
    assert listener.listening is True
    now[0] = 5.1
    assert listener.feed(b"x") == []
    assert listener.listening is False


def test_listener_wake_at_set_on_gate_fire():
    gate = FakeGate()
    listener = Listener(gate, vad_factory=lambda: FakeVad(), clock=lambda: 42.0)
    gate.fire = True
    listener.feed(b"x")
    assert listener.wake_at == 42.0


def test_listener_wake_at_none_without_gate():
    listener = Listener(None, vad_factory=lambda: FakeVad())
    listener.feed(b"x")
    assert listener.wake_at is None
