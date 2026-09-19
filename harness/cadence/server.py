"""The turn path, wired to a WebSocket.

One `/session` endpoint serves both audio clients (mic frames in, VAD ->
ASR -> agent/routine -> TTS -> mixed PCM out) and text clients (text frames
in, agent/routine -> text out, no ASR/TTS either way). `TURN_LOCK` is the
single concurrency-1 slot: a user turn and a scheduler tick (Task 22) both
acquire it, so only one is ever running.

Heavy collaborators (the Whisper model, the Kokoro model, the sqlite Store,
the MCP tool registry) are built lazily on first use, not at import time --
importing this module must stay cheap and side-effect-free.
"""

import asyncio
import json
import time

import httpx
from fastapi import FastAPI

from cadence.agent import run_turn
from cadence.audio.asr import Asr
from cadence.audio.chunker import SentenceChunker
from cadence.audio.mixer import DUCK_GAIN, mix
from cadence.audio.tts import Tts
from cadence.audio.vad import VadSegmenter
from cadence.config import DB_PATH, MCP_SERVERS
from cadence.context import RollingContext, SqliteContextProvider
from cadence.llm import OllamaLLM
from cadence.mcp_client import ToolRegistry
from cadence.routines import match
from cadence.session import Session, SessionCaps, SessionRegistry
from cadence.store import Store

app = FastAPI()
TURN_LOCK = asyncio.Lock()

REGISTRY = SessionRegistry()

_store: Store | None = None
_provider: SqliteContextProvider | None = None
_tools: ToolRegistry | None = None
_asr: Asr | None = None
_tts: Tts | None = None
_llm: OllamaLLM | None = None
_contexts: dict[str, RollingContext] = {}


def _get_store() -> Store:
    global _store
    if _store is None:
        _store = Store(DB_PATH)
    return _store


def _get_provider() -> SqliteContextProvider:
    global _provider
    if _provider is None:
        _provider = SqliteContextProvider(_get_store())
    return _provider


def _get_tools() -> ToolRegistry:
    global _tools
    if _tools is None:
        configs = [
            {"name": f"mcp{i}", "command": cmd[0], "args": cmd[1:]}
            for i, cmd in enumerate(MCP_SERVERS)
        ]
        _tools = ToolRegistry(configs)
    return _tools


def _get_asr() -> Asr:
    global _asr
    if _asr is None:
        _asr = Asr()
    return _asr


def _get_tts() -> Tts:
    global _tts
    if _tts is None:
        _tts = Tts()
    return _tts


def _get_llm() -> OllamaLLM:
    global _llm
    if _llm is None:
        _llm = OllamaLLM()
    return _llm


class MusicStream:
    """One in-flight `play` proxy fetch for a session. Bytes arrive from the
    proxy in arbitrary HTTP chunk sizes; while a turn is speaking we buffer
    them here instead of forwarding, and hand them out in TTS-chunk-sized
    slices for mixing."""

    def __init__(self):
        self.tail = b""
        self.speaking = False
        self.task: asyncio.Task | None = None

    def take(self, n: int) -> bytes:
        chunk, self.tail = self.tail[:n], self.tail[n:]
        if len(chunk) < n:
            chunk += b"\x00" * (n - len(chunk))
        return chunk


_music: dict[str, MusicStream] = {}


async def _pump_music(client_id: str, url: str) -> None:
    stream = _music.get(client_id)
    if stream is None:
        return
    session = REGISTRY.get(client_id)
    if session is None:
        return
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", url) as response:
                async for chunk in response.aiter_bytes():
                    if _music.get(client_id) is not stream:
                        return
                    if stream.speaking:
                        stream.tail += chunk
                    else:
                        await session.send_audio(chunk)
    except httpx.HTTPError:
        return


def _maybe_start_music(session: Session, tool_name: str, result) -> None:
    if tool_name != "play" or not isinstance(result, str):
        return
    stream = MusicStream()
    old = _music.get(session.client_id)
    if old is not None and old.task is not None and not old.task.done():
        old.task.cancel()
    _music[session.client_id] = stream
    stream.task = asyncio.create_task(_pump_music(session.client_id, result))


@app.websocket("/session")
async def session_endpoint(ws) -> None:
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
    vad = VadSegmenter() if session.needs_asr else None

    try:
        while True:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                break
            session.last_active = time.time()

            data = message.get("bytes")
            if data is not None:
                if vad is None:
                    continue
                for utterance in vad.feed(data):
                    text = _get_asr().transcribe(utterance)
                    if not text:
                        continue
                    await handle_turn(session, text)
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
                    await handle_turn(session, content)
    finally:
        REGISTRY.remove(client_id)
        _music.pop(client_id, None)


async def handle_turn(session, text) -> None:
    await session.send_text(json.dumps({"type": "turn_start"}))

    store = _get_store()
    tools = _get_tools()
    provider = _get_provider()
    stream = _music.get(session.client_id)

    routine = None
    reply_text = ""
    chosen: list[int] = []
    why = ""

    async with TURN_LOCK:
        try:
            await tools.start()
            routine = match(store, text)
            if routine is not None:
                for step in routine["steps"]:
                    result = await tools.call(step["tool"], step["args"])
                    _maybe_start_music(session, step["tool"], result)
                    if step["tool"] == "play" and "track_rowid" in step.get("args", {}):
                        chosen.append(step["args"]["track_rowid"])
                why = f"routine hit: {routine['name']}"
            else:
                rolling = _contexts.setdefault(session.client_id, RollingContext())
                rolling.append("user", text)
                messages = [{"role": "system", "content": provider.build_system_prompt()}]
                prefetch = provider.prefetch(text)
                if prefetch:
                    messages.append({"role": "system", "content": prefetch})
                messages.extend(rolling.messages())

                result = await run_turn(_get_llm(), tools, messages)
                reply_text = result.text
                rolling.append("assistant", reply_text)
                why = reply_text
                for call in result.tool_calls:
                    _maybe_start_music(session, call["name"], call["result"])
                    if call["name"] == "play" and "track_rowid" in call.get("arguments", {}):
                        chosen.append(call["arguments"]["track_rowid"])
        except (ConnectionError, RuntimeError) as exc:
            await session.send_text(json.dumps({"type": "error", "message": str(exc)}))
            await session.send_text(json.dumps({"type": "turn_end"}))
            return

        if stream is not None:
            stream.speaking = True
        try:
            chunker = SentenceChunker()
            sentences = chunker.feed(reply_text) + chunker.flush()
            for sentence in sentences:
                if session.needs_tts:
                    speech = _get_tts().speak(sentence)
                    if stream is not None:
                        music_chunk = stream.take(len(speech))
                        await session.send_audio(mix(music_chunk, speech, DUCK_GAIN))
                    else:
                        await session.send_audio(speech)
                else:
                    await session.send_text(json.dumps({"type": "text", "content": sentence}))
        finally:
            if stream is not None:
                stream.speaking = False

        await session.send_text(json.dumps({"type": "turn_end"}))
        provider.sync(text, chosen, [], why)
