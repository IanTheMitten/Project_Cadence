"""Tests for the /peer endpoint and PeerHub over an in-process WebSocket (TestClient, no real ports)."""

import importlib
import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import cadence.peers as peers
from cadence.catalogue import Catalogue
from cadence.core import Core
from cadence.decisionlog import DecisionLog
from cadence.events import Call
from cadence.executor import Executor
from cadence.livecontext import LiveContext
from cadence.peers import PeerHub, app, set_runtime, capability_from_ability  # noqa: F401
from cadence.pipeline import Pipeline
from cadence.plugins.registry import DeviceRegistry
from cadence.protocol import hello
from cadence.schedules import PendingQuestions, ScheduleStore
from tests.test_pipeline import ScriptedDecider, _jev

X_DO = {"name": "x.do", "description": "do", "parameters": {"type": "object", "properties": {}},
        "closed_args": {}, "free_args": [], "target": None}
SPEAKER = hello("speaker-1", "device", "speaker", "bedroom", ["audio_out"], [])
SERVICE = hello("svc", "service", "test", None, [], [X_DO])
CLIENT = hello("cli", "device", "text", None, ["text_out"], [])
EVENT = {"type": "event", "kind": "utterance", "payload": {"text": "do it"}}
WELCOME = {"type": "welcome"}


@pytest.fixture
def env(tmp_path):
    hub = PeerHub(Catalogue([]), DeviceRegistry([]), call_timeout_s=0.2)
    log = DecisionLog(str(tmp_path / "l.db"))
    pipeline = Pipeline(ScriptedDecider(*[_jev("x.do", [Call("x.do", {})])] * 5), ScriptedDecider(),
                        hub.catalogue, Executor(hub.catalogue, hub.registry), log,
                        LiveContext(log, hub.now_playing))
    core = Core(pipeline, hub, log, ScheduleStore(str(tmp_path / "l.db")), PendingQuestions())
    set_runtime(SimpleNamespace(hub=hub, core=core, log=log))
    with TestClient(app) as client:
        yield SimpleNamespace(hub=hub, log=log, client=client)
    set_runtime(None)


def _eventually(pred, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


def _send(ws, msg):
    ws.send_text(json.dumps(msg))


def _recv(ws):
    return json.loads(ws.receive_text())


def _join(ws, msg):
    _send(ws, msg)
    assert _recv(ws) == WELCOME


def test_non_json_first_frame_errors(env):
    with env.client.websocket_connect("/peer") as ws:
        ws.send_text("not json")
        assert _recv(ws)["type"] == "error"


def test_wrong_version_errors(env):
    with env.client.websocket_connect("/peer") as ws:
        _send(ws, {**SPEAKER, "version": 2})
        msg = _recv(ws)
        assert msg["type"] == "error"
        assert "protocol version" in msg["message"]


def test_hello_registers_device_then_offline(env):
    with env.client.websocket_connect("/peer") as ws:
        _join(ws, SPEAKER)
        dev = env.hub.registry.get("speaker-1")
        assert dev.online is True
        assert dev.room == "bedroom"
        assert dev.kind == "speaker"
    assert _eventually(lambda: not env.hub.registry.get("speaker-1").online, 2.0)


def test_service_abilities_join_catalogue_then_leave(env):
    with env.client.websocket_connect("/peer") as ws:
        _join(ws, SERVICE)
        assert env.hub.catalogue.get("x.do") is not None
    assert _eventually(lambda: env.hub.catalogue.get("x.do") is None, 2.0)


def test_duplicate_peer_id_rejected_first_unaffected(env):
    with env.client.websocket_connect("/peer") as first:
        _join(first, SPEAKER)
        with env.client.websocket_connect("/peer") as second:
            _send(second, SPEAKER)
            msg = _recv(second)
            assert msg["type"] == "error"
            assert "peer_id in use" in msg["message"]
        _send(first, EVENT)
        assert _recv(first) == {"type": "turn_start"}


def test_round_trip_turn(env):
    with env.client.websocket_connect("/peer") as svc:
        _join(svc, SERVICE)
        with env.client.websocket_connect("/peer") as spk:
            _join(spk, SPEAKER)
            _send(spk, EVENT)
            call = _recv(svc)
            assert isinstance(call["call_id"], str)
            assert call == {"type": "call", "call_id": call["call_id"], "capability": "x.do",
                            "args": {}, "target": None}
            _send(svc, {"type": "result", "call_id": call["call_id"], "ok": True, "say": "done", "data": {}})
            frames = [_recv(spk) for _ in range(4)]
    assert frames[0] == {"type": "turn_start"}
    assert frames[1]["type"] == "ack"
    assert frames[2] == {"type": "say", "text": "done"}
    assert frames[3] == {"type": "turn_end"}
    assert env.log.export()[-1]["outcome"] == "ok"


def test_call_timeout(env):
    with env.client.websocket_connect("/peer") as svc:
        _join(svc, SERVICE)
        with env.client.websocket_connect("/peer") as spk:
            _join(spk, SPEAKER)
            _send(spk, EVENT)
            _recv(svc)
            frames = [_recv(spk) for _ in range(4)]
    assert frames[2] == {"type": "say", "text": "Sorry, that didn't work."}
    assert env.log.export()[-1]["results"][0]["error"] == "timeout"


def test_service_lost_mid_call(env):
    with env.client.websocket_connect("/peer") as spk:
        _join(spk, SPEAKER)
        with env.client.websocket_connect("/peer") as svc:
            _join(svc, SERVICE)
            _send(spk, EVENT)
            _recv(svc)
        frames = [_recv(spk) for _ in range(4)]
    assert frames[2] == {"type": "say", "text": "Sorry, that didn't work."}
    assert env.log.export()[-1]["results"][0]["error"] == "peer_lost"


def test_media_forwarded_both_ways(env):
    with env.client.websocket_connect("/peer") as svc:
        _join(svc, SERVICE)
        with env.client.websocket_connect("/peer") as spk:
            _join(spk, SPEAKER)
            _send(svc, {"type": "media", "device": "speaker-1", "action": "play_url", "url": "http://x/1"})
            assert _recv(spk) == {"type": "media", "action": "play_url", "url": "http://x/1"}
            _send(spk, {"type": "media_event", "event": "track_end", "position_ms": 5, "url": "http://x/1"})
            assert _recv(svc) == {"type": "media_event", "event": "track_end", "position_ms": 5,
                                  "url": "http://x/1", "device": "speaker-1"}


def test_state_updates_now_playing(env):
    with env.client.websocket_connect("/peer") as svc:
        _join(svc, SERVICE)
        _send(svc, {"type": "state", "state": {"now_playing": {"speaker-1": {"track_name": "T"}}}})
        assert _eventually(lambda: env.hub.now_playing("speaker-1") == {"track_name": "T"}, 2.0)
    assert _eventually(lambda: env.hub.now_playing("speaker-1") is None, 2.0)


def test_text_client_turn_not_a_speaker(env):
    with env.client.websocket_connect("/peer") as svc:
        _join(svc, SERVICE)
        with env.client.websocket_connect("/peer") as cli:
            _join(cli, CLIENT)
            _send(cli, EVENT)
            call = _recv(svc)
            _send(svc, {"type": "result", "call_id": call["call_id"], "ok": True, "say": "done", "data": {}})
            frames = [_recv(cli) for _ in range(4)]
            assert [f["type"] for f in frames] == ["turn_start", "ack", "say", "turn_end"]
            assert env.hub.registry.find("speaker") == []


def test_targets(env):
    with env.client.websocket_connect("/peer") as svc:
        _join(svc, SERVICE)
        with env.client.websocket_connect("/peer") as spk:
            _join(spk, SPEAKER)
            assert env.hub.targets("speaker-1") == ["speaker-1"]
            assert env.hub.targets("bedroom") == ["speaker-1"]
            assert env.hub.targets(None) == ["speaker-1"]


def test_import_does_not_build_runtime(monkeypatch):
    import cadence.wiring as wiring

    def boom(*a, **k):
        raise AssertionError("build_runtime called on import")

    monkeypatch.setattr(wiring, "build_runtime", boom)
    importlib.reload(peers)


def test_failed_welcome_does_not_leak_peer(env, monkeypatch):
    from starlette.websockets import WebSocket
    orig = WebSocket.send_text

    async def flaky(self, text):
        if "welcome" in text:
            raise RuntimeError("dropped")
        await orig(self, text)

    monkeypatch.setattr(WebSocket, "send_text", flaky)
    try:
        with env.client.websocket_connect("/peer") as ws:
            _send(ws, SPEAKER)
            _recv(ws)
    except Exception:
        pass
    assert _eventually(lambda: not env.hub.registry.get("speaker-1").online, 2.0)
    monkeypatch.setattr(WebSocket, "send_text", orig)
    with env.client.websocket_connect("/peer") as ws:
        _join(ws, SPEAKER)
