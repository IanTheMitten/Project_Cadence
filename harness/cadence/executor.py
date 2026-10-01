from __future__ import annotations

from typing import Callable

from cadence.agent import MAX_TOOL_CALLS
from cadence.catalogue import Catalogue
from cadence.events import Decision, Event
from cadence.plugins.base import AudioPort, Result
from cadence.plugins.registry import DeviceRegistry
from cadence.resolver import resolve


class Executor:
    def __init__(self, catalogue: Catalogue, registry: DeviceRegistry,
                 ports: Callable[[str], AudioPort | None], *, max_calls: int = MAX_TOOL_CALLS) -> None:
        self._catalogue = catalogue
        self._registry = registry
        self._ports = ports
        self._max_calls = max_calls

    async def run(self, decision: Decision, event: Event) -> list[Result]:
        results: list[Result] = []
        for call in decision.calls[:self._max_calls]:
            cap = self._catalogue.get(call.capability)
            plugin = self._catalogue.plugin_for(call.capability)
            if cap is None or plugin is None:
                results.append(Result(False, say="I can't do that yet.",
                                      error=f"unknown capability {call.capability}"))
                return results
            targets = resolve(call, cap, event, self._registry)
            if not targets:
                results.append(Result(False, say=f"No {cap.target} is online.", error="no_target"))
                return results
            for t in targets:
                port = self._ports(t.id) if t else None
                try:
                    res = await plugin.call(cap.name, call.args, t, port)
                except Exception as exc:
                    res = Result(False, say="Sorry, that didn't work.",
                                 error=f"{type(exc).__name__}: {exc}")
                results.append(res)
                if not res.ok:
                    return results
        return results
