from __future__ import annotations

from typing import Callable

import numpy as np

from cadence_speaker.config import WAKE_MODEL, WAKE_THRESHOLD

WAKE_FRAME_SAMPLES = 1280
WAKE_FRAME_BYTES = 2560


def _default_factory(name: str):
    from openwakeword.model import Model

    return Model(wakeword_models=[name], inference_framework="onnx")


class WakeGate:
    def __init__(self, model_name: str = WAKE_MODEL, threshold: float = WAKE_THRESHOLD, *,
                 model_factory: Callable[[str], object] | None = None) -> None:
        self._name = model_name
        self._threshold = threshold
        self._factory = model_factory or _default_factory
        self._model = None
        self._buf = b""

    def feed(self, pcm: bytes) -> bool:
        if self._model is None:
            self._model = self._factory(self._name)
        self._buf += pcm
        while len(self._buf) >= WAKE_FRAME_BYTES:
            frame, self._buf = self._buf[:WAKE_FRAME_BYTES], self._buf[WAKE_FRAME_BYTES:]
            scores = self._model.predict(np.frombuffer(frame, np.int16))
            if scores.get(self._name, 0) >= self._threshold:
                self._model.reset()
                self._buf = b""
                return True
        return False
