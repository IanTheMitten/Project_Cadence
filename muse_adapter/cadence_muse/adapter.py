from __future__ import annotations

import asyncio
import time
from dataclasses import asdict

from cadence_muse.config import PEER_URL, RECONNECT_S
from cadence_muse.link import LinkClosed, open_link
from cadence_muse.music import ABILITIES, Result
from cadence_muse.protocol import hello
from cadence_muse.remote import RemotePort


class MuseAdapter:
    def __init__(self, plugin, send, *, clock=time.monotonic) -> None:
        self.plugin = plugin
        self.send = send
        self._clock = clock
        self._ports: dict[str, RemotePort] = {}

    async def _emit(self, msg: dict) -> None:
        try:
            await self.send(msg)
        except LinkClosed:
            pass

    def _port(self, device_id: str) -> RemotePort:
        if device_id not in self._ports:
            self._ports[device_id] = RemotePort(device_id, self._emit, clock=self._clock)
        return self._ports[device_id]

    def hello(self) -> dict:
        return hello("muse", "service", "music", None, [], ABILITIES)

    def state(self) -> dict:
        return {"now_playing": {d: self.plugin.now_playing(d) for d in self._ports}}

    async def handle(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "call":
            target = msg.get("target")
            if not self.plugin.available():
                res = Result(False, say="Muse isn't answering.", error="muse_unavailable")
            else:
                port = self._port(target) if target else None
                res = await self.plugin.call(msg["capability"], msg.get("args") or {}, target, port)
            await self._emit({"type": "result", "call_id": msg["call_id"], **asdict(res)})
        elif kind == "media_event":
            await self._port(msg["device"]).on_media_event(msg["event"], msg["position_ms"], msg["url"])
        else:
            return
        await self._emit({"type": "state", "state": self.state()})


async def run(adapter, url: str = PEER_URL, *, open_link=open_link, reconnect_s: float = RECONNECT_S) -> None:
    while True:
        try:
            link = await open_link(url, adapter.hello())
            adapter.send = link.send
            while True:
                await adapter.handle(await link.recv())
        except (LinkClosed, OSError):
            await asyncio.sleep(reconnect_s)
