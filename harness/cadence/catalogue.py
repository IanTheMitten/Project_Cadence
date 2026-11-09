from __future__ import annotations

from cadence.plugins.base import Capability, Plugin

CHAT = Capability(name="chat", description="Chit-chat, a question, thanks, or a request no other function can perform.",
                  parameters={"type": "object", "properties": {}})
CORRECTION = Capability(name="correction", description="The user says the previous action was wrong or corrects it ('no, I meant...', 'not that', 'wrong song').",
                        parameters={"type": "object", "properties": {}})
BUILTINS: tuple[Capability, ...] = (CHAT, CORRECTION)


class Catalogue:
    def __init__(self, plugins: list[Plugin]) -> None:
        self._caps: dict[str, Capability] = {c.name: c for c in BUILTINS}
        self._owner: dict[str, Plugin] = {}
        self._plugins = []
        for p in plugins:
            self.add(p)

    def add(self, plugin: Plugin) -> None:
        for c in plugin.manifest.capabilities:
            if c.name in self._caps:
                raise ValueError(f"duplicate capability name: {c.name}")
        self._plugins.append(plugin)
        for c in plugin.manifest.capabilities:
            self._caps[c.name] = c
            self._owner[c.name] = plugin

    def remove(self, plugin: Plugin) -> None:
        if not any(p is plugin for p in self._plugins):
            return
        self._plugins = [p for p in self._plugins if p is not plugin]
        for c in plugin.manifest.capabilities:
            del self._caps[c.name]
            del self._owner[c.name]

    def get(self, name: str) -> Capability | None:
        return self._caps.get(name)

    def plugin_for(self, name: str) -> Plugin | None:
        return self._owner.get(name)

    def available(self) -> list[Capability]:
        out: list[Capability] = []
        for p in self._plugins:
            if p.available():
                out.extend(p.manifest.capabilities)
        out.extend(BUILTINS)
        return out
