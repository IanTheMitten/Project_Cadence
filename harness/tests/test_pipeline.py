"""Tests for Executor (I10), LiveContext (I11), Pipeline.handle (I12). No network, no real deciders."""

import time

import pytest

from cadence.pipeline import (
    ARGS_INSTRUCTION, CHAT_INSTRUCTION, LOW_CONF_INSTRUCTION, NOTHING_SAY, UNAVAILABLE_SAY, Pipeline,
)
from cadence.catalogue import Catalogue
from cadence.deciders.base import Decider, DeciderUnavailable
from cadence.decisionlog import DecisionLog
from cadence.events import Call, Decision, utterance
from cadence.executor import Executor
from cadence.livecontext import LiveContext
from cadence.plugins.base import Capability, Manifest, Plugin, Result
from cadence.plugins.registry import Device, DeviceRegistry

PARAMS = {"type": "object", "properties": {}}
DO = Capability("x.do", "do it", PARAMS, closed_args={"mode": {"a": "A", "b": "B"}}, target="speaker")
ASK = Capability("x.ask", "ask it", PARAMS, free_args=("what",), target="speaker")
THREE = Capability("x.three", "three", PARAMS, target="speaker")


class ScriptedDecider(Decider):
    name = "scripted"

    def __init__(self, *queue):
        self.queue = list(queue)
        self.calls = []

    async def decide(self, event, context, capabilities, instruction=None):
        self.calls.append((capabilities, instruction))
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakePlugin(Plugin):
    def __init__(self, result=None, raises=None, caps=(DO, ASK)):
        self.manifest = Manifest("x", "device", tuple(caps))
        self.result = result or Result(True)
        self.raises = raises
        self.seen = []

    async def call(self, capability, args, target, port):
        self.seen.append((capability, args, target))
        if self.raises:
            raise self.raises
        return self.result


class FakeOut:
    def __init__(self):
        self.events = []

    async def ack(self, c):
        self.events.append(("ack", c))

    async def say(self, t):
        self.events.append(("say", t))


def _registry(online=True):
    return DeviceRegistry([Device("speaker-1", "speaker", "bedroom", online)])


def _event(text="do it"):
    return utterance("test", "bedroom", text, ts=1000.0)


def _executor(plugin, registry=None, **kw):
    return Executor(Catalogue([plugin]), registry or _registry(), lambda i: None, **kw)


def _jev(route, calls=(), confidence=0.9, candidates=None, escalation=None):
    return Decision("jev", route, list(calls), confidence=confidence,
                    candidates=candidates or {}, escalation=escalation)


def _llm(route="chat", calls=(), reply=None):
    return Decision("llm", route, list(calls), reply=reply)


def _pipeline(tmp_path, jev, llm, plugin=None, log=None, **kw):
    plugin = plugin or FakePlugin()
    catalogue = Catalogue([plugin])
    log = log or DecisionLog(str(tmp_path / "log.db"))
    pipe = Pipeline(jev, llm, catalogue, Executor(catalogue, _registry(), lambda i: None), log,
                    LiveContext(log, lambda s: None), clock=lambda: 1000.0, **kw)
    return pipe, log, plugin


DO_CALL = Call("x.do", {"mode": "a"})


# --- Executor ---

async def test_executor_success_returns_plugin_result():
    res = Result(True, say="done")
    plugin = FakePlugin(result=res)
    out = await _executor(plugin).run(_llm("x.do", [DO_CALL]), _event())
    assert out == [res]
    assert plugin.seen[0][0] == "x.do"


async def test_executor_unknown_capability():
    out = await _executor(FakePlugin()).run(_llm("x.nope", [Call("x.nope", {})]), _event())
    assert len(out) == 1
    assert out[0].ok is False
    assert out[0].say == "I can't do that yet."


async def test_executor_no_online_target():
    plugin = FakePlugin()
    out = await _executor(plugin, _registry(online=False)).run(_llm("x.do", [DO_CALL]), _event())
    assert out[0].ok is False
    assert out[0].say == "No speaker is online."
    assert plugin.seen == []


async def test_executor_plugin_raises_skips_later_calls():
    plugin = FakePlugin(raises=RuntimeError("boom"))
    out = await _executor(plugin).run(_llm("x.do", [DO_CALL, DO_CALL]), _event())
    assert len(out) == 1
    assert out[0].ok is False
    assert out[0].say == "Sorry, that didn't work."
    assert len(plugin.seen) == 1


async def test_executor_only_max_calls_run():
    plugin = FakePlugin()
    out = await _executor(plugin, max_calls=2).run(_llm("x.do", [DO_CALL] * 3), _event())
    assert len(plugin.seen) == 2
    assert len(out) == 2


# --- LiveContext ---

def test_livecontext_keys_in_order(tmp_path):
    log = DecisionLog(str(tmp_path / "log.db"))
    ctx = LiveContext(log, lambda s: {"title": "t"}, clock=lambda: 1000.0)
    snap = ctx.snapshot(_event())
    assert list(snap) == ["time", "weekday", "room", "now_playing", "recent"]
    assert snap["time"] == time.strftime("%H:%M", time.localtime(1000.0))
    assert snap["weekday"] == time.strftime("%A", time.localtime(1000.0))
    assert snap["room"] == "bedroom"
    assert snap["now_playing"] == {"title": "t"}
    assert snap["recent"] == []


# --- Pipeline ---

async def test_jev_confident_action_executed(tmp_path):
    llm = ScriptedDecider()
    pipe, log, plugin = _pipeline(tmp_path, ScriptedDecider(_jev("x.do", [DO_CALL])), llm)
    out = FakeOut()
    await pipe.handle(_event(), out)
    assert out.events == [("ack", "action")]
    assert llm.calls == []
    assert len(plugin.seen) == 1
    assert log.recent(1)[0]["decider"] == "jev"


async def test_route_chat_escalates_to_llm(tmp_path):
    llm = ScriptedDecider(_llm(reply="hello"))
    pipe, log, _ = _pipeline(tmp_path, ScriptedDecider(_jev("chat")), llm)
    out = FakeOut()
    await pipe.handle(_event(), out)
    assert out.events == [("ack", "chat"), ("say", "hello")]
    assert llm.calls[0][1] == CHAT_INSTRUCTION
    assert log.recent(1)[0]["escalation"] == "chat"


async def test_low_confidence_shortlist(tmp_path):
    llm = ScriptedDecider(_llm(reply="ok"))
    cands = {"chat": 0.9, "x.ask": 0.6, "x.three": 0.4, "x.do": 0.3, "correction": 0.5}
    plugin = FakePlugin(caps=(DO, ASK, THREE))
    pipe, log, _ = _pipeline(tmp_path, ScriptedDecider(_jev("x.do", confidence=0.3, candidates=cands)),
                             llm, plugin=plugin)
    await pipe.handle(_event(), FakeOut())
    caps, instruction = llm.calls[0]
    assert [c.name for c in caps] == ["x.ask", "x.three"]
    assert instruction == LOW_CONF_INSTRUCTION
    assert log.recent(1)[0]["escalation"] == "low_confidence"


async def test_low_confidence_excludes_below_shortlist_min(tmp_path):
    llm = ScriptedDecider(_llm(reply="ok"))
    cands = {"x.do": 0.3, "x.ask": 0.1}
    pipe, _, _ = _pipeline(tmp_path, ScriptedDecider(_jev("x.do", confidence=0.3, candidates=cands)), llm)
    await pipe.handle(_event(), FakeOut())
    assert [c.name for c in llm.calls[0][0]] == ["x.do"]


async def test_needs_args_llm_gets_only_that_capability(tmp_path):
    llm = ScriptedDecider(_llm("x.ask", [Call("x.ask", {"what": "w"})]))
    pipe, log, _ = _pipeline(tmp_path, ScriptedDecider(_jev("x.ask", escalation="needs_args")), llm)
    await pipe.handle(_event(), FakeOut())
    caps, instruction = llm.calls[0]
    assert [c.name for c in caps] == ["x.ask"]
    assert instruction == ARGS_INSTRUCTION
    assert log.recent(1)[0]["escalation"] == "needs_args"


async def test_jev_unavailable_llm_gets_all_capabilities(tmp_path):
    llm = ScriptedDecider(_llm(reply="hi"))
    pipe, log, plugin = _pipeline(tmp_path, ScriptedDecider(DeciderUnavailable("down")), llm)
    out = FakeOut()
    await pipe.handle(_event(), out)
    assert ("ack", "action") not in out.events
    assert not any(e[0] == "ack" for e in out.events)
    assert [c.name for c in llm.calls[0][0]] == [c.name for c in Catalogue([plugin]).available()]
    assert log.recent(1)[0]["escalation"] == "jev_unavailable"


async def test_jev_and_llm_unavailable(tmp_path):
    pipe, log, _ = _pipeline(tmp_path, ScriptedDecider(DeciderUnavailable("a")),
                             ScriptedDecider(DeciderUnavailable("b")))
    out = FakeOut()
    await pipe.handle(_event(), out)
    assert ("say", UNAVAILABLE_SAY) in out.events
    assert log.recent(1)[0]["decider"] == "none"


async def test_correction_with_previous_row_labels_it(tmp_path):
    llm = ScriptedDecider(_llm(reply="sorry"))
    pipe, log, _ = _pipeline(tmp_path, ScriptedDecider(_jev("correction")), llm)
    prev_id = log.record(utterance("test", "bedroom", "play jazz", ts=990.0), {},
                         Decision("jev", "x.do", [DO_CALL]), None, [], {})
    await pipe.handle(_event("no not that"), FakeOut())
    assert llm.calls[0][1].startswith("The user is correcting")
    new = log.recent(1)[0]
    assert new["id"] != prev_id
    assert new["escalation"] == "correction"
    labels = [r for r in log.export() if r["id"] == prev_id][0]["labels"]
    assert len(labels) == 1
    assert labels[0]["label"] == "wrong"
    assert labels[0]["corrected_by"] == new["id"]


async def test_correction_without_previous_row(tmp_path):
    llm = ScriptedDecider(_llm(reply="sorry"))
    pipe, log, _ = _pipeline(tmp_path, ScriptedDecider(_jev("correction")), llm)
    await pipe.handle(_event("no"), FakeOut())
    assert log.recent(1)[0]["escalation"] == "correction_no_previous"
    assert all(r["labels"] == [] for r in log.export())


async def test_no_results_no_reply_says_nothing_phrase(tmp_path):
    pipe, _, _ = _pipeline(tmp_path, ScriptedDecider(_jev("x.do", [])), ScriptedDecider())
    out = FakeOut()
    await pipe.handle(_event(), out)
    assert ("say", NOTHING_SAY) in out.events


async def test_log_record_raises_handle_returns(tmp_path):
    class BrokenLog(DecisionLog):
        def record(self, *a, **k):
            raise RuntimeError("disk full")

    log = BrokenLog(str(tmp_path / "broken.db"))
    pipe, _, _ = _pipeline(tmp_path, ScriptedDecider(_jev("x.do", [DO_CALL])), ScriptedDecider(), log=log)
    assert pipe.log_healthy is True
    final = await pipe.handle(_event(), FakeOut())
    assert final.decider == "jev"
    assert pipe.log_healthy is False


async def test_latency_has_jev_and_total(tmp_path):
    pipe, log, _ = _pipeline(tmp_path, ScriptedDecider(_jev("x.do", [DO_CALL])), ScriptedDecider())
    await pipe.handle(_event(), FakeOut())
    latency = log.recent(1)[0]["latency_ms"]
    assert "jev" in latency
    assert "total" in latency
