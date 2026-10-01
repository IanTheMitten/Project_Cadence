"""The turn path, wired to a WebSocket.

One `/session` endpoint serves both audio clients (mic frames in, wake/VAD ->
ASR -> pipeline -> TTS PCM out) and text clients (text frames in, pipeline ->
text out, no ASR/TTS either way). `TURN_LOCK` is the single concurrency-1
slot: a user turn and a scheduler tick both acquire it, so only one is ever
running.

The runtime (decider clients, plugins, models) is built lazily on first use
via `get_runtime()`, not at import time -- importing this module must stay
cheap and side-effect-free.
"""

import asyncio
import json
import time

from fastapi import FastAPI, WebSocket

from cadence.audio.chunker import SentenceChunker
from cadence.events import utterance
from cadence.plugins.speaker import SpeakerPort
from cadence.session import Session, SessionCaps, SessionRegistry
from cadence.wiring import Runtime

app = FastAPI()
TURN_LOCK = asyncio.Lock()

REGISTRY = SessionRegistry()

_runtime: Runtime | None = None


def set_runtime(runtime: Runtime | None) -> None:
    global _runtime
    _runtime = runtime


def get_runtime() -> Runtime:
    global _runtime
    if _runtime is None:
        from cadence import wiring
        _runtime = wiring.build_runtime()
    return _runtime


class SessionOutput:
    def __init__(self, session: Session, port: SpeakerPort | None, runtime: Runtime) -> None:
        self._session = session
        self._port = port
        self._runtime = runtime

    async def ack(self, category: str) -> None:
        if self._port is None:
            return
        clip = self._runtime.acks.pick(category)
        if clip is not None:
            await self._port.speak(clip)

    async def say(self, text: str) -> None:
        chunker = SentenceChunker()
        sentences = chunker.feed(text) + chunker.flush()
        for sentence in sentences:
            if self._port is not None and self._session.caps.audio_out and self._runtime.tts is not None:
                await self._port.speak(self._runtime.tts(sentence))
            else:
                await self._session.send_text(json.dumps({"type": "text", "content": sentence}))


@app.websocket("/session")
async def session_endpoint(ws: WebSocket) -> None:
    await ws.accept()

    first = await ws.receive()
    if first.get("type") == "websocket.disconnect":
        return
    try:
        hello = json.loads(first.get("text") or "")
        if hello.get("type") != "hello":
            raise ValueError(f"expected hello, got {hello.get('type')!r}")
        caps = SessionCaps.from_list(hello["caps"])
        client_id = hello["client_id"]
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        await ws.send_text(json.dumps({"type": "error", "message": str(exc)}))
        await ws.close()
        return

    runtime = get_runtime()

    async def send_audio(data: bytes) -> None:
        await ws.send_bytes(data)

    async def send_text(text: str) -> None:
        await ws.send_text(text)

    session = Session(
        client_id=client_id,
        caps=caps,
        last_active=time.time(),
        send_audio=send_audio,
        send_text=send_text,
    )
    REGISTRY.add(session)
    runtime.registry.set_online(client_id, True)
    port: SpeakerPort | None = None
    if caps.audio_out:
        port = SpeakerPort(send_audio)
        runtime.ports[client_id] = port
    listener = runtime.listener_factory() if session.needs_asr else None

    try:
        while True:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                break
            session.last_active = time.time()

            data = message.get("bytes")
            if data is not None:
                if listener is None or runtime.asr is None:
                    continue
                for pcm in listener.feed(data):
                    text = runtime.asr(pcm)
                    if not text:
                        continue
                    await handle_text(session, port, text)
                continue

            text_frame = message.get("text")
            if text_frame is None:
                continue
            try:
                payload = json.loads(text_frame)
            except json.JSONDecodeError:
                continue
            if payload.get("type") == "text":
                content = payload.get("content", "")
                if content:
                    await handle_text(session, port, content)
    finally:
        REGISTRY.remove(client_id)
        runtime.ports.pop(client_id, None)
        runtime.registry.set_online(client_id, False)
        if port is not None:
            await port.stop("lost")


async def handle_text(session: Session, port: SpeakerPort | None, text: str) -> None:
    runtime = get_runtime()
    device = runtime.registry.get(session.client_id)
    event = utterance(session.client_id, device.room if device else None, text)
    out = SessionOutput(session, port, runtime)
    await session.send_text(json.dumps({"type": "turn_start"}))
    async with TURN_LOCK:
        try:
            await runtime.pipeline.handle(event, out)
        except Exception as exc:
            await session.send_text(json.dumps({"type": "error", "message": str(exc)}))
    await session.send_text(json.dumps({"type": "turn_end"}))
