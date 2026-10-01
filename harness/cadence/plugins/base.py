from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Protocol

from cadence.plugins.registry import Device


@dataclass(frozen=True)
class Capability:
    name: str
    description: str
    parameters: dict  # JSON-schema object
    closed_args: dict[str, dict[str, str]] = field(default_factory=dict)  # arg -> {value: description}
    free_args: tuple[str, ...] = ()
    target: str | None = None  # device kind, e.g. "speaker"


@dataclass(frozen=True)
class Manifest:
    id: str
    kind: str  # "device" | "service" | "sensor"
    capabilities: tuple[Capability, ...]


@dataclass
class Result:
    ok: bool
    say: str | None = None
    data: dict = field(default_factory=dict)
    error: str | None = None


class AudioPort(Protocol):
    async def play_url(self, url: str, on_end: Callable[[str], Awaitable[None]]) -> None: ...
    async def pause(self) -> None: ...
    async def resume(self) -> None: ...
    async def stop(self, reason: str = "stopped") -> None: ...
    def position_ms(self) -> int: ...
    def is_paused(self) -> bool: ...


class Plugin(abc.ABC):
    manifest: Manifest

    @abc.abstractmethod
    async def call(self, capability: str, args: dict, target: Device | None,
                   port: AudioPort | None) -> Result: ...

    def available(self) -> bool:
        return True

    def state(self) -> dict:
        return {}
