"""The /peer hub: devices and services join over one WebSocket (protocol in `cadence/protocol.py`).

Service abilities become catalogue capabilities backed by a `PeerPlugin` that relays calls to the
peer; device peers are tracked in the registry and addressed by `PeerHub.send`/`targets`.
The runtime is built lazily via `get_runtime()`, never at import.
"""

import asyncio
import sys
import uuid
from dataclasses import dataclass, field

from fastapi import FastAPI, WebSocket

from cadence.catalogue import Catalogue
from cadence.events import Event, utterance
from cadence.plugins.base import Capability, Manifest, Plugin, Result
from cadence.plugins.registry import Device, DeviceRegistry
from cadence.protocol import check_hello, decode, encode

CALL_TIMEOUT_S = 5.0
FAIL_SAY = "Sorry, that didn't work."


def capability_from_ability(a: dict) -> Capability:
    closed = a.get("closed_args") or {}
    free = a.get("free_args")
    if free is None:  # undeclared: every non-closed parameter is free, else Jev calls with no args
        free = [p for p in a["parameters"].get("properties", {}) if p not in closed]
    return Capability(a["name"], a["description"], a["parameters"],
                      closed_args=closed, free_args=tuple(free), target=a.get("target"))


@dataclass
class Peer:
    peer_id: str
    role: str
    kind: str
    room: str | None
    caps: frozenset[str]
    send: object  # async callable(msg: dict)
    state: dict = field(default_factory=dict)
    calls: dict[str, asyncio.Future] = field(default_factory=dict)
    plugin: "PeerPlugin | None" = None


class PeerPlugin(Plugin):
    def __init__(self, peer: Peer, abilities: list[dict], *, timeout_s: float = CALL_TIMEOUT_S) -> None:
        self._peer = peer
        self._timeout_s = timeout_s
        self.manifest = Manifest(peer.peer_id, peer.role,
                                 tuple(capability_from_ability(a) for a in abilities))

    async def call(self, capability: str, args: dict, target: Device | None, event: Event) -> Result:
        call_id = uuid.uuid4().hex
        fut = asyncio.get_running_loop().create_future()
        self._peer.calls[call_id] = fut
        try:
            await self._peer.send({"type": "call", "call_id": call_id, "capability": capability,
                                   "args": args, "target": target.id if target else None})
            m = await asyncio.wait_for(fut, self._timeout_s)
        except asyncio.TimeoutError:
            return Result(False, say=FAIL_SAY, error="timeout")
        finally:
            self._peer.calls.pop(call_id, None)
        return Result(bool(m.get("ok")), say=m.get("say"), data=m.get("data") or {}, error=m.get("error"))


class PeerHub:
    def __init__(self, catalogue: Catalogue, registry: DeviceRegistry, *,
                 call_timeout_s: float = CALL_TIMEOUT_S) -> None:
        self.catalogue = catalogue
        self.registry = registry
        self._call_timeout_s = call_timeout_s
        self._peers: dict[str, Peer] = {}
        self._media_owner: dict[str, str] = {}  # device id -> service peer id

    def add(self, peer: Peer, abilities: list[dict]) -> None:
        if peer.peer_id in self._peers:
            raise ValueError("peer_id in use")
        if abilities:
            plugin = PeerPlugin(peer, abilities, timeout_s=self._call_timeout_s)
            self.catalogue.add(plugin)  # duplicate capability names raise before the peer is stored
            peer.plugin = plugin
        self._peers[peer.peer_id] = peer
        if peer.role == "device":
            self.registry.set_online(peer.peer_id, True, kind=peer.kind, room=peer.room)

    def remove(self, peer: Peer) -> None:
        if self._peers.get(peer.peer_id) is not peer:
            return
        del self._peers[peer.peer_id]
        if peer.plugin is not None:
            self.catalogue.remove(peer.plugin)
        if peer.role == "device":
            self.registry.set_online(peer.peer_id, False, kind=peer.kind)
        for fut in list(peer.calls.values()):
            if not fut.done():
                fut.set_result({"ok": False, "say": FAIL_SAY, "error": "peer_lost"})
        self._media_owner = {d: o for d, o in self._media_owner.items()
                             if o != peer.peer_id and d != peer.peer_id}

    async def send(self, peer_id: str, msg: dict) -> bool:
        peer = self._peers.get(peer_id)
        if peer is None:
            return False
        try:
            await peer.send(msg)
        except Exception:
            return False
        return True

    def targets(self, target: str | None) -> list[str]:
        devs = [p for p in self._peers.values()
                if p.role == "device" and ({"audio_out", "text_out"} & p.caps)]
        ids = [p.peer_id for p in devs]
        if target in ids:
            return [target]
        return [p.peer_id for p in devs if target is None or p.room == target]

    def now_playing(self, device_id: str) -> dict | None:
        for p in self._peers.values():
            if p.role == "service":
                np = (p.state.get("now_playing") or {}).get(device_id)
                if np:
                    return np
        return None

    async def on_message(self, peer: Peer, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "result":
            fut = peer.calls.get(msg.get("call_id"))
            if fut is not None and not fut.done():
                fut.set_result(msg)
        elif kind == "media" and peer.role == "service":
            device = msg.get("device")
            self._media_owner[device] = peer.peer_id
            await self.send(device, {"type": "media", "action": msg.get("action"), "url": msg.get("url")})
        elif kind == "media_event" and peer.role == "device":
            owner = self._media_owner.get(peer.peer_id)
            if owner is not None:
                await self.send(owner, {**msg, "device": peer.peer_id})
        elif kind == "state":
            peer.state = msg.get("state") or {}


app = FastAPI()

_runtime = None


def set_runtime(runtime) -> None:
    global _runtime
    _runtime = runtime


def get_runtime():
    global _runtime
    if _runtime is None:
        from cadence import wiring
        _runtime = wiring.build_runtime()
    return _runtime


async def _guard(coro) -> None:
    try:
        await coro
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # e.g. the socket closed mid-turn
        print(f"turn task failed: {exc!r}", file=sys.stderr, flush=True)


@app.websocket("/peer")
async def peer_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    first = await ws.receive()
    if first.get("type") == "websocket.disconnect":
        return
    runtime = get_runtime()
    hub = runtime.hub

    async def send(msg: dict) -> None:
        await ws.send_text(encode(msg))

    try:
        h = check_hello(decode(first.get("text") or ""))
        peer = Peer(h["peer_id"], h["role"], h["kind"], h.get("room"), frozenset(h.get("caps", [])), send)
        hub.add(peer, h.get("abilities", []))
    except ValueError as exc:  # includes JSONDecodeError
        await ws.send_text(encode({"type": "error", "message": str(exc)}))
        await ws.close()
        return
    turns: set[asyncio.Task] = set()
    try:
        await send({"type": "welcome"})
        while True:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                break
            try:
                msg = decode(message.get("text") or "")
            except ValueError:
                continue
            payload = msg.get("payload") or {}
            if msg["type"] == "event" and msg.get("kind") == "utterance" and payload.get("text"):
                task = asyncio.create_task(_guard(runtime.core.submit(
                    utterance(peer.peer_id, peer.room, payload["text"], asr_conf=payload.get("asr_conf")),
                    timing=msg.get("timing"))))
                turns.add(task)
                task.add_done_callback(turns.discard)
            else:
                await hub.on_message(peer, msg)
    finally:
        for task in list(turns):
            task.cancel()
        await asyncio.gather(*turns, return_exceptions=True)
        hub.remove(peer)
