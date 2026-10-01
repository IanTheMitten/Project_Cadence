from __future__ import annotations

import random
from pathlib import Path

ACK_CATEGORIES = ("action", "chat", "correction")


class AckPool:
    def __init__(self, root: str, *, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()
        self._clips: dict[str, list[bytes]] = {}
        for category in ACK_CATEGORIES:
            d = Path(root) / category
            files = sorted(d.glob("*.pcm")) if d.is_dir() else []
            self._clips[category] = [f.read_bytes() for f in files]
        self._last: dict[str, int] = {}

    def count(self, category: str) -> int:
        return len(self._clips.get(category, []))

    def pick(self, category: str) -> bytes | None:
        clips = self._clips.get(category)
        if not clips:
            return None
        choices = [i for i in range(len(clips)) if i != self._last.get(category)]
        idx = self._rng.choice(choices) if choices else 0
        self._last[category] = idx
        return clips[idx]
