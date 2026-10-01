from __future__ import annotations

import abc

from cadence.events import Decision, Event
from cadence.plugins.base import Capability


class DeciderUnavailable(Exception):
    pass


class Decider(abc.ABC):
    name: str

    @abc.abstractmethod
    async def decide(self, event: Event, context: dict, capabilities: list[Capability],
                     instruction: str | None = None) -> Decision: ...


class UnavailableDecider(Decider):
    name = "jev"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    async def decide(self, event, context, capabilities, instruction=None) -> Decision:
        raise DeciderUnavailable(self.reason)
