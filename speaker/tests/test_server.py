"""Tests for the speaker /session endpoint and its peer link to Cadence. Fake link, no sockets."""

import asyncio
import json
import queue
import time

import httpx
import pytest
from fastapi.testclient import TestClient

import cadence_speaker.server as server
from cadence_speaker.acks import AckPool
from cadence_speaker.audio.listener import Listener
from cadence_speaker.link import LinkClosed
from cadence_speaker.protocol import hello
from cadence_speaker.speaker import VOLUME
from cadence_speaker.wiring import SpeakerRuntime
from tests.test_listener import FakeGate, FakeVad

HELLO = {"type": "hello", "client_id": "speaker-1", "caps": ["audio_in", "audio_out"]}
FRAME = b"\x00\x00" * 160
UTT = b"\x00\x00" * 8000


class FakeLink:
    def __init__(self, hello_msg):
        self.hello = hello_msg
        self.outbox = queue.Queue()
        self.inbox = queue.Queue()
        self.closed = False

    async def send(self, msg):
        if self.closed:
            raise LinkClosed()
        self.outbox.put(msg)

    async def recv(self):
        while True:
            if self.closed:
                raise LinkClosed()
            try:
                return self.inbox.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.01)

    async def close(self):
        self.closed = True


class RepeatVad:
    def feed(self, pcm):
        return [UTT]


class SpyListener:
    def __init__(self):
        self.listens = []

    def feed(self, pcm):
        return []

    def listen_for(self, seconds):
        self.listens.append(seconds)


def _out(link):
    return link.outbox.get(timeout=2)


def _bytes(ws):
    while True:
        msg = ws.receive()
        if msg.get("bytes") is not None:
            return msg["bytes"]


def _connect(client, rt):
    ws = client.websocket_connect("/session").__enter__()
    ws.send_text(json.dumps(HELLO))
    link = rt.links.get(timeout=2)
    assert _out(link) == link.hello
    return ws, link


def _wait(cond):
    for _ in range(200):
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met")


@pytest.fixture
def rt(tmp_path):
    links = queue.Queue()
    tts_calls = []

    async def open_link(url, hello_msg):
        link = FakeLink(hello_msg)
        links.put(link)
        return link

    def tts(text):
        tts_calls.append(text)
        return b"\x00\x00" * 100

    runtime = SpeakerRuntime(
        acks=AckPool(str(tmp_path / "acks")), tts=tts, asr=lambda pcm: "do it",
        listener_factory=lambda: Listener(None, vad_factory=lambda: FakeVad([UTT])),
        open_link=open_link, room="bedroom", reconnect_s=0.05)
    runtime.links = links
    runtime.tts_calls = tts_calls
    server.set_runtime(runtime)
    yield runtime
    server.set_runtime(None)


def test_link_hello(rt):
    with TestClient(server.app) as client:
        ws, link = _connect(client, rt)
        assert link.hello == hello("speaker-1", "device", "speaker", "bedroom",
                                   ["audio_in", "audio_out"], [VOLUME])


def test_bad_board_hello_error_frame(rt):
    with TestClient(server.app).websocket_connect("/session") as ws:
        ws.send_text(json.dumps({"type": "nope"}))
        assert json.loads(ws.receive_text())["type"] == "error"


def test_mic_frame_emits_utterance_event(rt):
    with TestClient(server.app) as client:
        ws, link = _connect(client, rt)
        ws.send_bytes(FRAME)
        msg = _out(link)
        assert msg["type"] == "event"
        assert msg["kind"] == "utterance"
        assert msg["payload"] == {"text": "do it", "asr_conf": None}
        assert {"speech_end", "asr_done"} <= msg["timing"].keys()


def test_frames_ignored_until_turn_end(rt):
    rt.listener_factory = lambda: Listener(None, vad_factory=RepeatVad)
    with TestClient(server.app) as client:
        ws, link = _connect(client, rt)
        ws.send_bytes(FRAME)
        assert _out(link)["type"] == "event"
        ws.send_bytes(FRAME)
        ws.send_bytes(FRAME)
        time.sleep(0.3)
        assert link.outbox.empty()
        link.inbox.put({"type": "turn_end"})
        time.sleep(0.3)
        ws.send_bytes(FRAME)
        assert _out(link)["type"] == "event"


def test_say_sends_tts_audio_to_board(rt):
    with TestClient(server.app) as client:
        ws, link = _connect(client, rt)
        link.inbox.put({"type": "say", "text": "Hi."})
        assert _bytes(ws) == b"\x00\x00" * 100


def test_ack_sends_clip_to_board(rt, tmp_path):
    clip = tmp_path / "acks" / "action"
    clip.mkdir(parents=True)
    (clip / "01.pcm").write_bytes(b"\x00\x00" * 10)
    rt.acks = AckPool(str(tmp_path / "acks"))
    with TestClient(server.app) as client:
        ws, link = _connect(client, rt)
        link.inbox.put({"type": "ack", "category": "action"})
        assert _bytes(ws) == b"\x00\x00" * 10


def test_call_volume_mute_result(rt):
    with TestClient(server.app) as client:
        ws, link = _connect(client, rt)
        link.inbox.put({"type": "call", "call_id": "c1", "capability": "speaker.volume",
                        "args": {"action": "mute"}, "target": "speaker-1"})
        assert _out(link) == {"type": "result", "call_id": "c1", "ok": True, "say": None,
                              "data": {"gain": 1.0, "muted": True}, "error": None}


def test_media_play_url_reports_track_end(rt):
    rt.transport = httpx.MockTransport(lambda r: httpx.Response(200, content=b"\x00" * 400))
    with TestClient(server.app) as client:
        ws, link = _connect(client, rt)
        link.inbox.put({"type": "media", "action": "play_url", "url": "http://m/1"})
        msg = _out(link)
        assert msg["type"] == "media_event"
        assert msg["event"] == "track_end"
        assert isinstance(msg["position_ms"], int)
        assert msg["url"] == "http://m/1"


def test_listen_opens_window(rt):
    spy = SpyListener()
    rt.listener_factory = lambda: spy
    with TestClient(server.app) as client:
        ws, link = _connect(client, rt)
        link.inbox.put({"type": "listen", "seconds": 8})
        _wait(lambda: spy.listens == [8])


def test_link_unreachable_speaks_fallback(rt):
    async def dead(url, hello_msg):
        raise LinkClosed()

    rt.open_link = dead
    with TestClient(server.app) as client:
        ws = client.websocket_connect("/session").__enter__()
        ws.send_text(json.dumps(HELLO))
        ws.send_bytes(FRAME)
        assert _bytes(ws) == b"\x00\x00" * 100
    assert rt.tts_calls == ["I can't reach my brain right now."]


def test_bench_recorder_writes_session_audio(rt, tmp_path):
    bench = tmp_path / "rec"
    bench.mkdir()
    rt.bench_dir = str(bench)
    rt.listener_factory = lambda: Listener(None, vad_factory=lambda: FakeVad([b"\x01\x00" * 8000]))
    with TestClient(server.app) as client:
        ws, link = _connect(client, rt)
        ws.send_bytes(b"\x01\x00" * 160)
        _out(link)
    pcms = list(bench.glob("speaker-1-*.pcm"))
    assert len(pcms) == 1
    assert pcms[0].read_bytes() == b"\x01\x00" * 160
    assert pcms[0].with_suffix(".json").exists()
    utts = list(bench.glob("utt-speaker-1-*.pcm"))
    assert len(utts) == 1
    assert utts[0].read_bytes() == b"\x01\x00" * 8000


def test_same_id_sessions_get_own_links(rt):
    client = TestClient(server.app)
    with client:
        first = client.websocket_connect("/session")
        ws1 = first.__enter__()
        ws1.send_text(json.dumps(HELLO))
        link1 = rt.links.get(timeout=2)
        with client.websocket_connect("/session") as ws2:
            ws2.send_text(json.dumps(HELLO))
            link2 = rt.links.get(timeout=2)
            assert link1 is not link2
            first.__exit__(None, None, None)
            _wait(lambda: link1.closed)
            assert link2.closed is False


def test_listen_for_returns_vad_utterances_without_wake():
    gate = FakeGate()
    listener = Listener(gate, vad_factory=lambda: FakeVad([UTT]))
    listener.listen_for(8)
    assert listener.feed(FRAME) == [UTT]
