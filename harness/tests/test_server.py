"""Tests for the rewritten /session endpoint (I17). Fake runtime, no network, no real models."""

import asyncio
import importlib
import json

import pytest
from fastapi.testclient import TestClient

import cadence.server as server
from cadence.acks import AckPool
from cadence.audio.listener import Listener
from cadence.catalogue import Catalogue
from cadence.decisionlog import DecisionLog
from cadence.executor import Executor
from cadence.livecontext import LiveContext
from cadence.pipeline import Pipeline
from cadence.plugins.base import Result
from cadence.plugins.registry import Device, DeviceRegistry
from cadence.wiring import Runtime
from tests.test_listener import FakeVad
from tests.test_pipeline import DO_CALL, FakePlugin, ScriptedDecider, _jev

HELLO = {"type": "hello", "client_id": "speaker-1", "caps": ["text_in", "text_out"]}


@pytest.fixture
def rt(tmp_path):
    plugin = FakePlugin(result=Result(True, say="done"))
    catalogue = Catalogue([plugin])
    registry = DeviceRegistry([Device("speaker-1", "speaker", "bedroom")])
    log = DecisionLog(str(tmp_path / "log.db"))
    pipeline = Pipeline(ScriptedDecider(_jev("x.do", [DO_CALL])), ScriptedDecider(), catalogue,
                        Executor(catalogue, registry, lambda i: None), log,
                        LiveContext(log, lambda s: None))
    runtime = Runtime(registry=registry, ports={}, music=None, pipeline=pipeline,
                      acks=AckPool(str(tmp_path / "acks")), tts=None, asr=None,
                      listener_factory=lambda: Listener(None))
    runtime.log = log
    server.set_runtime(runtime)
    yield runtime
    server.set_runtime(None)


def _hello(ws, hello=HELLO):
    ws.send_text(json.dumps(hello))


def _recv(ws):
    return json.loads(ws.receive_text())


def test_text_turn_frames_and_log(rt):
    with TestClient(server.app).websocket_connect("/session") as ws:
        _hello(ws)
        ws.send_text(json.dumps({"type": "text", "content": "do it"}))
        assert _recv(ws) == {"type": "turn_start"}
        assert _recv(ws) == {"type": "text", "content": "done"}
        assert _recv(ws) == {"type": "turn_end"}
    rows = rt.log.export()
    assert len(rows) == 1
    assert rows[0]["source"] == "speaker-1"
    assert rows[0]["room"] == "bedroom"


def test_bad_hello_error_frame(rt):
    with TestClient(server.app).websocket_connect("/session") as ws:
        ws.send_text(json.dumps({"type": "nope"}))
        assert _recv(ws)["type"] == "error"


def test_device_online_during_session_offline_after(rt):
    with TestClient(server.app).websocket_connect("/session") as ws:
        _hello(ws)
        ws.send_text(json.dumps({"type": "text", "content": "do it"}))
        assert _recv(ws) == {"type": "turn_start"}
        assert _recv(ws)["type"] == "text"
        assert _recv(ws) == {"type": "turn_end"}
        assert rt.registry.get("speaker-1").online is True
    assert rt.registry.get("speaker-1").online is False


def test_pipeline_error_then_turn_end(rt):
    async def boom(event, out, timer=None):
        raise RuntimeError("boom")

    rt.pipeline.handle = boom
    with TestClient(server.app).websocket_connect("/session") as ws:
        _hello(ws)
        ws.send_text(json.dumps({"type": "text", "content": "do it"}))
        frames = [_recv(ws) for _ in range(3)]
    assert frames[0] == {"type": "turn_start"}
    assert frames[1]["type"] == "error"
    assert frames[2] == {"type": "turn_end"}


def test_turn_lock_is_asyncio_lock():
    assert isinstance(server.TURN_LOCK, asyncio.Lock)


def test_import_does_not_build_runtime(monkeypatch):
    import cadence.wiring

    def boom():
        raise AssertionError("build_runtime called at import")

    monkeypatch.setattr(cadence.wiring, "build_runtime", boom)
    importlib.reload(server)


AUDIO_HELLO = {"type": "hello", "client_id": "speaker-1", "caps": ["audio_in", "text_out"]}


def test_audio_turn_logs_timing(rt, capsys):
    rt.asr = lambda pcm: "do it"
    rt.listener_factory = lambda: Listener(None, vad_factory=lambda: FakeVad([b"\x00\x00" * 8000]))
    with TestClient(server.app).websocket_connect("/session") as ws:
        _hello(ws, AUDIO_HELLO)
        ws.send_bytes(b"\x00\x00" * 160)
        assert _recv(ws) == {"type": "turn_start"}
        assert _recv(ws) == {"type": "text", "content": "done"}
        assert _recv(ws) == {"type": "turn_end"}
    lines = [l for l in capsys.readouterr().err.splitlines() if l.startswith("turn_timing ")]
    payload = json.loads(lines[0][len("turn_timing "):])
    assert payload["client_id"] == "speaker-1"
    assert {"asr", "decide", "turn"} <= payload["durations_ms"].keys()
    latency = rt.log.export()[0]["latency_ms"]
    assert "asr" in latency
    assert "decide" in latency


def test_bench_recorder_writes_session_audio(rt, tmp_path):
    bench = tmp_path / "rec"
    bench.mkdir()
    rt.bench_dir = str(bench)
    rt.asr = lambda pcm: "do it"
    rt.listener_factory = lambda: Listener(None, vad_factory=lambda: FakeVad([b"\x01\x00" * 8000]))
    with TestClient(server.app).websocket_connect("/session") as ws:
        _hello(ws, AUDIO_HELLO)
        ws.send_bytes(b"\x01\x00" * 160)
        for _ in range(3):
            _recv(ws)
    pcms = list(bench.glob("speaker-1-*.pcm"))
    assert len(pcms) == 1
    assert pcms[0].read_bytes() == b"\x01\x00" * 160
    assert pcms[0].with_suffix(".json").exists()
    utts = list(bench.glob("utt-speaker-1-*.pcm"))
    assert len(utts) == 1
    assert utts[0].read_bytes() == b"\x01\x00" * 8000


def test_runtime_bench_dir_defaults_none(rt):
    assert rt.bench_dir is None


def test_stale_session_cleanup_does_not_unregister_newer_one(rt):
    # The board reconnects after any hiccup; the old connection can finish closing after the
    # new one registered. Its cleanup must not mark the live session offline.
    client = TestClient(server.app)
    old = client.websocket_connect("/session")
    ws_old = old.__enter__()
    _hello(ws_old)
    ws_old.send_text(json.dumps({"type": "text", "content": "do it"}))
    for _ in range(3):
        _recv(ws_old)
    with client.websocket_connect("/session") as ws_new:
        _hello(ws_new)
        ws_new.send_text(json.dumps({"type": "text", "content": "do it"}))
        for _ in range(3):
            _recv(ws_new)
        old.__exit__(None, None, None)  # old connection finishes closing while the new one is live
        ws_new.send_text(json.dumps({"type": "text", "content": "do it"}))
        for _ in range(3):
            _recv(ws_new)
        assert rt.registry.get("speaker-1").online is True
        assert server.REGISTRY.get("speaker-1") is not None
