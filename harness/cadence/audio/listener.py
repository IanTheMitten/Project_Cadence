from __future__ import annotations

import time
from typing import Callable

from cadence.audio.vad import VadSegmenter
from cadence.audio.wakeword import WakeGate
from cadence.config import LISTEN_WINDOW_S


class Listener:
    def __init__(self, gate: WakeGate | None, *, vad_factory: Callable[[], object] = VadSegmenter,
                 window_s: float = LISTEN_WINDOW_S, clock: Callable[[], float] = time.monotonic) -> None:
        self._gate = gate
        self._vad_factory = vad_factory
        self._window_s = window_s
        self._clock = clock
        self._listening = False
        self._deadline = 0.0
        self.wake_at: float | None = None
        self._vad = vad_factory() if gate is None else None

    @property
    def listening(self) -> bool:
        return self._listening

    def feed(self, pcm: bytes) -> list[bytes]:
        if self._gate is None:
            return self._vad.feed(pcm)
        if not self._listening:
            if self._gate.feed(pcm):
                self._listening = True
                now = self._clock()
                self.wake_at = now
                self._deadline = now + self._window_s
                self._vad = self._vad_factory()
            return []
        if self._clock() > self._deadline:
            self._listening = False
            return []
        utts = self._vad.feed(pcm)
        if utts:
            self._listening = False
            return utts[:1]
        return []
