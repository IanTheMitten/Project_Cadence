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
import sys
import time

from fastapi import FastAPI, WebSocket

from cadence.audio.chunker import SentenceChunker
from cadence.benchrec import BenchRecorder
from cadence.events import utterance
from cadence.plugins.speaker import SpeakerPort
from cadence.session import Session, SessionCaps, SessionRegistry
from cadence.turntiming import TurnTimer
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
    def __init__(
        self,
        session: Session,
        port: SpeakerPort | None,
        runtime: Runtime,
        timer: TurnTimer | None = None,
    ) -> None:
        self._session = session
        self._port = port
        self._runtime = runtime
        self._timer = timer

    def _mark_audio(self) -> None:
        if self._timer is not None:
            self._timer.mark("first_audio")

    async def ack(self, category: str) -> None:
        if self._port is None:
            return
        clip = self._runtime.acks.pick(category)
        if clip is not None:
            self._mark_audio()
            await self._port.speak(clip)

    async def say(self, text: str) -> None:
        chunker = SentenceChunker()
        sentences = chunker.feed(text) + chunker.flush()
        for sentence in sentences:
            if self._port is not None and self._session.caps.audio_out and self._runtime.tts is not None:
                pcm = await asyncio.to_thread(self._runtime.tts, sentence)
                self._mark_audio()
                await self._port.speak(pcm)
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
    recorder = BenchRecorder.open(runtime.bench_dir, client_id) if runtime.bench_dir and caps.audio_in else None

    # Turns run as tasks so this loop keeps reading the socket (ping/pong, mic frames)
    # while ASR, TTS and the pipeline work; otherwise the board's sends back up.
    turns: set[asyncio.Task] = set()

    def spawn(coro) -> None:
        task = asyncio.create_task(_guard(coro))
        turns.add(task)
        task.add_done_callback(turns.discard)

    async def audio_turns(utterances: list[bytes], listener_wake_at) -> None:
        for pcm in utterances:
            timer = TurnTimer()
            if listener_wake_at is not None:
                timer.mark("wake", at=listener_wake_at)
            timer.mark("speech_end")
            if recorder is not None:
                recorder.save_utterance(pcm)
            text = await asyncio.to_thread(runtime.asr, pcm)
            timer.mark("asr_done")
            if text:
                await handle_text(session, port, text, timer=timer)

    try:
        while True:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                break
            session.last_active = time.time()

            data = message.get("bytes")
            if data is not None:
                if recorder is not None:
                    recorder.write(data)
                if listener is None or runtime.asr is None or turns:
                    continue  # mic audio during a turn is the speaker's own output
                utterances = listener.feed(data)
                if utterances:
                    spawn(audio_turns(utterances, listener.wake_at))
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
                    spawn(handle_text(session, port, content))
    finally:
        for task in list(turns):
            task.cancel()
        await asyncio.gather(*turns, return_exceptions=True)
        if recorder is not None:
            recorder.close()
        # A reconnecting client can register a newer session before this one finishes closing;
        # only tear down shared state if it is still ours.
        if REGISTRY.get(client_id) is session:
            REGISTRY.remove(client_id)
            runtime.ports.pop(client_id, None)
            runtime.registry.set_online(client_id, False)
        if port is not None:
            await port.stop("lost")


async def _guard(coro) -> None:
    try:
        await coro
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # e.g. the socket closed mid-turn
        print(f"turn task failed: {exc!r}", file=sys.stderr, flush=True)


async def handle_text(
    session: Session, port: SpeakerPort | None, text: str, timer: TurnTimer | None = None
) -> None:
    if timer is None:
        timer = TurnTimer()
    timer.mark("turn_start")
    runtime = get_runtime()
    device = runtime.registry.get(session.client_id)
    event = utterance(session.client_id, device.room if device else None, text)
    out = SessionOutput(session, port, runtime, timer)
    await session.send_text(json.dumps({"type": "turn_start"}))
    async with TURN_LOCK:
        try:
            await runtime.pipeline.handle(event, out, timer=timer)
        except Exception as exc:
            await session.send_text(json.dumps({"type": "error", "message": str(exc)}))
    timer.mark("turn_end")
    print(timer.log_line(session.client_id), file=sys.stderr, flush=True)
    await session.send_text(json.dumps({"type": "turn_end"}))
