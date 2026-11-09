"""Text chat with Cadence: serves a page on /, and bridges each browser socket on /ws to its own /peer link."""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse

from cadence_chat import link as link_mod
from cadence_chat.config import PEER_URL, ROOM
from cadence_chat.protocol import hello

PAGE = (Path(__file__).parent / "chat.html").read_text()

app = FastAPI()


@app.get("/")
async def index() -> HTMLResponse:
    return HTMLResponse(PAGE)


@app.websocket("/ws")
async def chat(ws: WebSocket) -> None:
    await ws.accept()
    peer_id = f"chat-{uuid.uuid4().hex[:6]}"
    try:
        link = await link_mod.open_link(PEER_URL, hello(peer_id, "device", "chat", ROOM, ["text_out"], []))
    except link_mod.LinkClosed as exc:
        await ws.send_json({"type": "error", "message": f"Can't reach Cadence ({exc or PEER_URL})."})
        await ws.close()
        return

    async def up() -> None:
        while True:
            text = (await ws.receive_text()).strip()
            if text:
                await link.send({"type": "event", "kind": "utterance", "payload": {"text": text}})

    async def down() -> None:
        while True:
            await ws.send_json(await link.recv())  # say, ack, turn_start/turn_end, error

    tasks = [asyncio.create_task(up()), asyncio.create_task(down())]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)  # browser disconnect / LinkClosed end the bridge
    await link.close()
    if tasks[1] in done:  # Cadence went away while the browser is still open
        try:
            await ws.send_json({"type": "error", "message": "Lost Cadence. Reconnecting."})
            await ws.close()
        except Exception:
            pass
