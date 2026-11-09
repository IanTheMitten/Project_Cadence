from __future__ import annotations

import json
import os
from dataclasses import dataclass


@dataclass
class Device:
    id: str
    kind: str
    room: str | None
    online: bool = False


class DeviceRegistry:
    def __init__(self, devices: list[Device]) -> None:
        self._devices: dict[str, Device] = {d.id: d for d in devices}

    @classmethod
    def from_file(cls, path: str) -> "DeviceRegistry":
        if not os.path.exists(path):
            return cls([])
        with open(path) as f:
            data = json.load(f)
        return cls([Device(d["id"], d["kind"], d.get("room")) for d in data.get("devices", [])])

    def get(self, device_id: str) -> Device | None:
        return self._devices.get(device_id)

    def set_online(self, device_id: str, online: bool, kind: str = "speaker",
                   room: str | None = None) -> Device:
        dev = self._devices.get(device_id)
        if dev is None:
            dev = Device(device_id, kind, room)
            self._devices[device_id] = dev
        elif room is not None:
            dev.room = room
        dev.online = online
        return dev

    def find(self, kind: str, room: str | None = None, online_only: bool = True) -> list[Device]:
        return [d for d in self._devices.values()
                if d.kind == kind
                and (room is None or d.room == room)
                and (d.online or not online_only)]

    def rooms(self) -> list[str]:
        return sorted({d.room for d in self._devices.values() if d.room is not None})
