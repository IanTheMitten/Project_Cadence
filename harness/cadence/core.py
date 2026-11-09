from __future__ import annotations

import asyncio
import sys
import time
import uuid
from typing import Protocol

from .events import DEFAULT_USER, Decision, Event
from .schedules import LISTEN_S, QUESTION_TTL_S, PendingQuestion, classify_yes_no
from .turntiming import STAGES, TurnTimer

TURN_LOCK = asyncio.Lock()
REPLACED_SAY = "Done, I replaced it."
KEPT_SAY = "Okay, I kept your old schedule."
LEAVE_SAY = "I'll leave your schedules as they are."
MISSED_GRACE_S = 300.0
TICK_S = 30.0
SCHEDULER_SOURCE = "scheduler"


def greeting_for(now: float) -> str:
    hour = time.localtime(now).tm_hour
    return "Good morning." if hour < 12 else "Good afternoon." if hour < 18 else "Good evening."


class Hub(Protocol):
    async def send(self, peer_id: str, msg: dict) -> bool: ...
    def targets(self, target: str | None) -> list[str]: ...


class PeerOutput:
    def __init__(self, hub: Hub, peer_id: str) -> None:
        self._hub = hub
        self._peer = peer_id

    async def ack(self, category: str) -> None:
        await self._hub.send(self._peer, {"type": "ack", "category": category})

    async def say(self, text: str) -> None:
        await self._hub.send(self._peer, {"type": "say", "text": text})


class RoomOutput:
    def __init__(self, core: "Core", room: str | None) -> None:
        self._core = core
        self._room = room

    async def ack(self, category: str) -> None:
        pass

    async def say(self, text: str) -> None:
        await self._core.announce(self._room, text)


class Core:
    def __init__(self, pipeline, hub, log, schedules, pending, *, clock=time.time,
                 question_ttl_s: float = QUESTION_TTL_S) -> None:
        self._pipeline = pipeline
        self._hub = hub
        self._log = log
        self._schedules = schedules
        self._pending = pending
        self._clock = clock
        self._question_ttl_s = question_ttl_s

    async def submit(self, event: Event, timing: dict[str, float] | None = None) -> None:
        src = event.source
        await self._hub.send(src, {"type": "turn_start"})
        timer = TurnTimer()
        for stage, age_ms in (timing or {}).items():
            if stage in STAGES:
                timer.mark(stage, at=time.monotonic() - age_ms / 1000)
        timer.mark("turn_start")
        async with TURN_LOCK:
            try:
                q = self._pending.take(src, self._clock())
                if q:
                    await self._answer(q, event)
                else:
                    await self._pipeline.handle(event, PeerOutput(self._hub, src), timer=timer)
                    asked = self._pending.peek(src)
                    if asked is not None:
                        await self._hub.send(src, {"type": "listen", "seconds": LISTEN_S})
                        asyncio.create_task(self._expire(asked))
            except Exception as exc:
                await self._hub.send(src, {"type": "error", "message": str(exc)})
        timer.mark("turn_end")
        print(timer.log_line(src), file=sys.stderr, flush=True)
        await self._hub.send(src, {"type": "turn_end"})

    async def _answer(self, q: PendingQuestion, event: Event) -> None:
        answer = classify_yes_no(event.payload.get("text", ""))
        if answer == "yes":
            self._schedules.delete(q.clash_ids)
            self._schedules.add(**q.new, now=self._clock())
            say = REPLACED_SAY
        elif answer == "no":
            say = KEPT_SAY
        else:
            say = LEAVE_SAY
        await self._hub.send(event.source, {"type": "say", "text": say})
        self._log.record(event, {}, Decision("pending", "schedule_conflict", [], reply=say), None, [], {})

    async def _expire(self, q: PendingQuestion) -> None:
        await asyncio.sleep(self._question_ttl_s)
        if self._pending.drop(q):
            async with TURN_LOCK:
                await self.announce(q.device_id, LEAVE_SAY)

    async def announce(self, target: str | None, text: str) -> int:
        sent = 0
        for peer in self._hub.targets(target):
            if await self._hub.send(peer, {"type": "say", "text": text}):
                sent += 1
        return sent

    async def tick(self) -> list[int]:
        now = self._clock()
        ran: list[int] = []
        for row in self._schedules.due(now):
            if now - row.next_at > MISSED_GRACE_S:
                print(f"schedule {row.id} missed by {int(now - row.next_at)} s, skipped",
                      file=sys.stderr, flush=True)
                self._schedules.advance(row.id, now)
                continue
            async with TURN_LOCK:
                if row.greeting:
                    await self.announce(row.room, greeting_for(now))
                if row.command:
                    ev = Event(uuid.uuid4().hex, now, "schedule", SCHEDULER_SOURCE, row.room,
                               DEFAULT_USER, {"text": row.command, "schedule_id": row.id})
                    try:
                        await self._pipeline.handle(ev, RoomOutput(self, row.room))
                    except Exception as exc:
                        print(f"schedule {row.id} failed: {exc!r}", file=sys.stderr, flush=True)
            self._schedules.advance(row.id, now)
            ran.append(row.id)
        return ran

    async def run_schedules(self) -> None:
        while True:
            await self.tick()
            await asyncio.sleep(TICK_S)
