from __future__ import annotations

import json

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, WebSocketException


class LinkClosed(Exception):
    pass


class WsLink:
    def __init__(self, ws) -> None:
        self._ws = ws

    async def send(self, msg: dict) -> None:
        try:
            await self._ws.send(json.dumps(msg))
        except ConnectionClosed as exc:
            raise LinkClosed() from exc

    async def recv(self) -> dict:
        try:
            return json.loads(await self._ws.recv())
        except ConnectionClosed as exc:
            raise LinkClosed() from exc

    async def close(self) -> None:
        await self._ws.close()


async def open_link(url: str, hello: dict) -> WsLink:
    try:
        link = WsLink(await connect(url, max_size=None))
    except (OSError, WebSocketException) as exc:
        raise LinkClosed() from exc
    await link.send(hello)
    reply = await link.recv()
    if reply.get("type") != "welcome":
        await link.close()
        raise LinkClosed(reply.get("message") or "no welcome")
    return link
