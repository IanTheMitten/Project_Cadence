from __future__ import annotations

from cadence.events import Call, Event
from cadence.plugins.base import Capability
from cadence.plugins.registry import Device, DeviceRegistry


def resolve(call: Call, capability: Capability, event: Event, registry: DeviceRegistry) -> list[Device | None]:
    target = capability.target
    if target is None:
        return [None]
    room = call.args.get("room")
    if room:
        found = registry.find(target, room)
        if found:
            return list(found)
    if event.room:
        found = registry.find(target, event.room)
        if found:
            return list(found)
    src = registry.get(event.source)
    if src and src.kind == target and src.online:
        return [src]
    return list(registry.find(target))
