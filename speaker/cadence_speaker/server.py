"""The speaker's /session endpoint: one board session = one Cadence /peer link.

Board mic frames -> wake/VAD -> ASR -> `event` to Cadence; Cadence's `say`/`ack`/`media`/`call`
commands are played out to the board. The runtime is built lazily via `get_runtime()`.
"""

import asyncio
import contextlib
import json
import sys
import time

from fastapi import FastAPI, WebSocket

from cadence_speaker.audio.chunker import SentenceChunker
from cadence_speaker.benchrec import BenchRecorder
from cadence_speaker.config import MAX_VOLUME, UNREACHABLE_SAY
from cadence_speaker.link import LinkClosed
from cadence_speaker.protocol import hello as peer_hello_msg
from cadence_speaker.session import SessionCaps
from cadence_speaker.speaker import VOLUME, SpeakerPort, set_volume
from cadence_speaker.turntiming import TurnTimer
from cadence_speaker.wiring import SpeakerRuntime

app = FastAPI()

_runtime: SpeakerRuntime | None = None


def set_runtime(rt: SpeakerRuntime | None) -> None:
    global _runtime
    _runtime = rt


def get_runtime() -> SpeakerRuntime:
    global _runtime
    if _runtime is None:
        from cadence_speaker import wiring
        _runtime = wiring.build_runtime()
    return _runtime


async def _guard(coro) -> None:
    try:
        await coro
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # e.g. the socket closed mid-turn
        print(f"turn task failed: {exc!r}", file=sys.stderr, flush=True)


@app.websocket("/session")
async def session_endpoint(ws: WebSocket) -> None:
    await ws.accept()

    first = await ws.receive()
    if first.get("type") == "websocket.disconnect":
        return
    try:
        board_hello = json.loads(first.get("text") or "")
        if board_hello.get("type") != "hello":
            raise ValueError(f"expected hello, got {board_hello.get('type')!r}")
        caps = SessionCaps.from_list(board_hello["caps"])
        client_id = board_hello["client_id"]
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        await ws.send_text(json.dumps({"type": "error", "message": str(exc)}))
        await ws.close()
        return

    rt = get_runtime()

    async def send_audio(data: bytes) -> None:
        await ws.send_bytes(data)

    port = SpeakerPort(send_audio, transport=rt.transport, max_gain=MAX_VOLUME) if caps.audio_out else None
    listener = rt.listener_factory() if caps.audio_in else None
    recorder = BenchRecorder.open(rt.bench_dir, client_id) if rt.bench_dir and caps.audio_in else None
    hello_msg = peer_hello_msg(client_id, "device", "speaker", rt.room, board_hello["caps"],
                               [VOLUME] if port else [])

    link = None
    in_turn = False
    timer = TurnTimer()
    turns: set[asyncio.Task] = set()

    def spawn(coro) -> None:
        task = asyncio.create_task(_guard(coro))
        turns.add(task)
        task.add_done_callback(turns.discard)

    async def dispatch(cur, msg: dict) -> None:
        nonlocal in_turn
        kind = msg.get("type")
        if kind == "turn_start":
            timer.mark("turn_start")
        elif kind == "ack" and port is not None:
            clip = rt.acks.pick(msg.get("category", ""))
            if clip is not None:
                await port.speak(clip)
        elif kind == "say" and port is not None:
            chunker = SentenceChunker()
            for sentence in chunker.feed(msg.get("text", "")) + chunker.flush():
                await port.speak(await asyncio.to_thread(rt.tts, sentence))
        elif kind == "listen" and listener is not None:
            listener.listen_for(msg.get("seconds", 0))
        elif kind == "media" and port is not None:
            action, url = msg.get("action"), msg.get("url")
            if action == "play_url":
                async def on_end(reason: str) -> None:
                    if link is not None:
                        with contextlib.suppress(LinkClosed):
                            await link.send({"type": "media_event", "event": reason,
                                             "position_ms": port.position_ms(), "url": url})
                await port.play_url(url, on_end)
            elif action == "pause":
                await port.pause()
            elif action == "resume":
                await port.resume()
            elif action == "stop":
                await port.stop()
        elif kind == "call" and msg.get("capability") == "speaker.volume":
            res = set_volume(port, (msg.get("args") or {}).get("action"))
            await cur.send({"type": "result", "call_id": msg.get("call_id"), **res})
        elif kind == "turn_end":
            in_turn = False
            timer.mark("turn_end")
            print("speaker_timing " + json.dumps(timer.durations()), file=sys.stderr, flush=True)
        elif kind == "error":
            print(f"peer error: {msg}", file=sys.stderr, flush=True)

    async def link_loop() -> None:
        nonlocal link, in_turn
        while True:
            try:
                link = await rt.open_link(rt.peer_url, hello_msg)
                while True:
                    msg = await link.recv()
                    try:
                        await dispatch(link, msg)
                    except LinkClosed:
                        raise
                    except Exception as exc:
                        print(f"dispatch failed: {exc!r}", file=sys.stderr, flush=True)
            except (LinkClosed, OSError):
                link = None
                in_turn = False
                await asyncio.sleep(rt.reconnect_s)

    async def audio_turns(utterances: list[bytes], wake_at) -> None:
        nonlocal in_turn, timer
        try:
            for pcm in utterances:
                timer = TurnTimer()
                if wake_at is not None:
                    timer.mark("wake", at=wake_at)
                timer.mark("speech_end")
                if recorder is not None:
                    recorder.save_utterance(pcm)
                text = await asyncio.to_thread(rt.asr, pcm)
                timer.mark("asr_done")
                if not text:
                    in_turn = False
                elif link is None:
                    await port.speak(await asyncio.to_thread(rt.tts, UNREACHABLE_SAY))
                    in_turn = False
                else:
                    now = time.monotonic()
                    await link.send({"type": "event", "kind": "utterance",
                                     "payload": {"text": text, "asr_conf": None},
                                     "timing": {s: (now - at) * 1000 for s, at in timer.stamps.items()}})
        except Exception:
            in_turn = False
            raise

    link_task = asyncio.create_task(link_loop())
    try:
        while True:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                break
            data = message.get("bytes")
            if data is None:
                continue  # text frames from the board are ignored
            if recorder is not None:
                recorder.write(data)
            if listener is None or rt.asr is None or in_turn:
                continue  # mic audio during a turn is the speaker's own output
            utterances = listener.feed(data)
            if utterances:
                in_turn = True
                spawn(audio_turns(utterances, listener.wake_at))
    finally:
        for task in list(turns):
            task.cancel()
        await asyncio.gather(*turns, return_exceptions=True)
        if recorder is not None:
            recorder.close()
        if port is not None:
            await port.stop("lost")  # link still up so the media_event goes out
        link_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await link_task
        if link is not None:
            await link.close()
