"""Tick-driven evaluator for schedule-triggered routines.

Runs due routines through the same tool-call path a routine cache hit uses
in `cadence.server.handle_turn`, but with zero LLM involvement, and yields
to any in-flight user turn via `TURN_LOCK` (the concurrency-1 rule).
"""

import asyncio
import json
import time

from cadence.server import TURN_LOCK


def is_speaking_step(step: dict) -> bool:
    return "say" in step


class Scheduler:
    def __init__(self, store, registry, tools, tick_seconds: float = 30.0):
        self.store = store
        self.registry = registry
        self.tools = tools
        self.tick_seconds = tick_seconds

    async def tick(self, now: float) -> list[int]:
        if TURN_LOCK.locked():
            return []

        async with TURN_LOCK:
            fired = []
            for routine in self.store.due_routines(now):
                if any(is_speaking_step(step) for step in routine["steps"]):
                    continue
                session = self.registry.most_recent_audio()
                if session is None:
                    continue
                for step in routine["steps"]:
                    result = await self.tools.call(step["tool"], step["args"])
                    data = result.encode() if isinstance(result, str) else json.dumps(result).encode()
                    await session.send_audio(data)
                fired.append(routine["id"])
            return fired

    async def run_forever(self) -> None:
        while True:
            await self.tick(time.time())
            await asyncio.sleep(self.tick_seconds)
