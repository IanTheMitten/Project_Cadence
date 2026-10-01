from __future__ import annotations

import time
from typing import Callable

from cadence.decisionlog import DecisionLog
from cadence.events import Event


class LiveContext:
    def __init__(self, log: DecisionLog, now_playing: Callable[[str], dict | None], *,
                 clock: Callable[[], float] = time.time) -> None:
        self._log = log
        self._now_playing = now_playing
        self._clock = clock

    def snapshot(self, event: Event) -> dict:
        now = time.localtime(self._clock())
        return {
            "time": time.strftime("%H:%M", now),
            "weekday": time.strftime("%A", now),
            "room": event.room,
            "now_playing": self._now_playing(event.source),
            "recent": [{"text": r["text"], "route": r["route"]} for r in self._log.recent(3)],
        }
