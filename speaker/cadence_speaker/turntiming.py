from __future__ import annotations

import json
import time
from typing import Callable

STAGES = ("wake", "speech_end", "asr_done", "turn_start", "decided", "first_audio", "turn_end")

DURATIONS: dict[str, tuple[str, str]] = {
    "wake_to_speech_end": ("wake", "speech_end"),
    "asr": ("speech_end", "asr_done"),
    "decide": ("turn_start", "decided"),
    "speech_end_to_first_audio": ("speech_end", "first_audio"),
    "turn": ("turn_start", "turn_end"),
}


class TurnTimer:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._stamps: dict[str, float] = {}

    def mark(self, stage: str, at: float | None = None) -> None:
        if stage not in STAGES:
            raise ValueError(f"unknown stage: {stage!r}")
        if stage in self._stamps:
            return
        self._stamps[stage] = at if at is not None else self._clock()

    @property
    def stamps(self) -> dict[str, float]:
        return dict(self._stamps)

    def durations(self) -> dict[str, float]:
        return {name: (self._stamps[end] - self._stamps[start]) * 1000
                for name, (start, end) in DURATIONS.items()
                if start in self._stamps and end in self._stamps}

    def log_line(self, client_id: str) -> str:
        return "turn_timing " + json.dumps(
            {"client_id": client_id,
             "durations_ms": {k: round(v, 1) for k, v in self.durations().items()}},
            sort_keys=True)
