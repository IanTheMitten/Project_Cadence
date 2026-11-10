from __future__ import annotations

import json
import sys
import time
from typing import Callable, Protocol

from cadence.catalogue import Catalogue
from cadence.config import CONF_MIN, CORRECTION_WINDOW_S, SHORTLIST_MIN
from cadence.deciders.base import Decider, DeciderUnavailable
from cadence.decisionlog import DecisionLog
from cadence.events import Decision, Event
from cadence.executor import Executor
from cadence.livecontext import LiveContext
from cadence.turntiming import TurnTimer

UNAVAILABLE_SAY = "I can't reach my brain right now."
NOTHING_SAY = "I'm not sure what to do with that."
CHAT_INSTRUCTION = "Reply conversationally. Only call a function if the user clearly asked for an action."
ARGS_INSTRUCTION = "The user wants this function. Fill in its arguments from what they said."
LOW_CONF_INSTRUCTION = "Pick the function that best matches what the user said, or reply if none fits."


def correction_instruction(previous: dict) -> str:
    return (f"The user is correcting your previous action. Their previous request: {previous['text']!r}. "
            f"What you did: {json.dumps(previous['calls'])}, reply {previous['reply']!r}. "
            "Work out what they actually want now.")


class TurnOutput(Protocol):
    async def ack(self, category: str) -> None: ...
    async def say(self, text: str) -> None: ...


class Pipeline:
    def __init__(self, jev: Decider, llm: Decider, catalogue: Catalogue, executor: Executor,
                 log: DecisionLog, context: LiveContext, *, conf_min: float = CONF_MIN,
                 shortlist_min: float = SHORTLIST_MIN, correction_window_s: float = CORRECTION_WINDOW_S,
                 clock: Callable[[], float] = time.time) -> None:
        self.log_healthy = True
        self._jev = jev
        self._llm = llm
        self._catalogue = catalogue
        self._executor = executor
        self._log = log
        self._context = context
        self._conf_min = conf_min
        self._shortlist_min = shortlist_min
        self._window = correction_window_s
        self._clock = clock

    async def handle(self, event: Event, out: TurnOutput, timer: TurnTimer | None = None) -> Decision:
        t0 = time.perf_counter()
        latency: dict[str, float] = {}
        ctx = self._context.snapshot(event)
        caps = self._catalogue.available()
        no_corr = [c for c in caps if c.name != "correction"]

        t = time.perf_counter()
        try:
            jev_d: Decision | None = await self._jev.decide(event, ctx, caps)
        except DeciderUnavailable:
            jev_d = None
        latency["jev"] = (time.perf_counter() - t) * 1000

        prev = None
        escalation: str | None = None
        final: Decision
        unavailable = False
        llm_args: tuple | None = None

        if jev_d is None:
            escalation = "jev_unavailable"
            llm_args = (caps, None)
        else:
            route = jev_d.route
            await out.ack("chat" if route == "chat" else "correction" if route == "correction" else "action")
            if route == "correction":
                prev = self._log.last_for_device_or_room(event.source, event.room, self._clock() - self._window)
                escalation = "correction" if prev else "correction_no_previous"
                llm_args = (no_corr, correction_instruction(prev) if prev else None)
            elif route == "chat":
                escalation = "chat"
                llm_args = (no_corr, CHAT_INSTRUCTION)
            elif jev_d.confidence is None or jev_d.confidence < self._conf_min:
                escalation = "low_confidence"
                ranked = sorted(
                    (c for c in caps if c.name not in ("chat", "correction")
                     and jev_d.candidates.get(c.name, 0) >= self._shortlist_min),
                    key=lambda c: jev_d.candidates.get(c.name, 0), reverse=True)[:2]
                llm_args = (ranked or no_corr, LOW_CONF_INSTRUCTION)
            elif jev_d.escalation == "needs_args":
                escalation = "needs_args"
                llm_args = ([self._catalogue.get(route)], ARGS_INSTRUCTION)
            else:
                final = jev_d

        if llm_args is not None:
            t = time.perf_counter()
            try:
                final = await self._llm.decide(event, ctx, llm_args[0], llm_args[1])
                final.escalation = escalation
            except DeciderUnavailable as exc:
                print(f"llm unavailable: {str(exc)[:300]}", file=sys.stderr, flush=True)
                unavailable = True
                await out.say(UNAVAILABLE_SAY)
                final = Decision("none", None, [], escalation=escalation)
            latency["llm"] = (time.perf_counter() - t) * 1000

        if timer is not None:
            timer.mark("decided")

        results = []
        if not unavailable:
            t = time.perf_counter()
            results = await self._executor.run(final, event)
            latency["execute"] = (time.perf_counter() - t) * 1000
            for r in results:
                if r.say:
                    await out.say(r.say)
            if final.reply:
                await out.say(final.reply)
            if not results and not final.reply:
                await out.say(NOTHING_SAY)

        latency["total"] = (time.perf_counter() - t0) * 1000
        if timer is not None:
            latency.update(timer.durations())
        try:
            new_id = self._log.record(event, ctx, final, jev_d, results, latency)
            if prev:
                self._log.label(prev["id"], "wrong", "spoken_correction", corrected_by=new_id)
        except Exception as exc:
            print(f"decision log write failed: {exc}", file=sys.stderr)
            self.log_healthy = False
        return final
