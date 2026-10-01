"""Tests for JevDecider (I8) and LlmDecider (I9). No network: Jev via httpx.MockTransport,
the LLM via FakeLLM from test_agent."""

import json

import httpx
import pytest

from cadence.catalogue import CHAT, CORRECTION
from cadence.context import RollingContext
from cadence.deciders.base import DeciderUnavailable
from cadence.deciders.jev import JevDecider, load_api_key, render_state
from cadence.deciders.llm import LlmDecider, capability_tools
from cadence.events import Call, utterance
from cadence.plugins.base import Capability
from tests.test_agent import FakeLLM, _text_response, _tool_call_response

PARAMS = {"type": "object", "properties": {}}
CONTROL = Capability(
    name="music.control", description="control playback", parameters=PARAMS,
    closed_args={"action": {"pause": "p", "skip": "s"}},
)
PLAY = Capability(name="music.play", description="play music", parameters=PARAMS,
                  free_args=("mood",))
CAPS = [CONTROL, PLAY, CHAT, CORRECTION]


def _event(text="pause"):
    return utterance("test", "kitchen", text)


def _answers(route, arg=None):
    a = {"route": {"choice": route, "confidence": 0.9,
                   "probabilities": {"music.control": 0.9, "music.play": 0.1}}}
    if arg is not None:
        a["arg:music.control:action"] = {"choice": arg}
    return a


def _jev(answers=None, *, status=200, handler=None, **kw):
    seen = []

    def default(request):
        seen.append(request)
        if status != 200:
            return httpx.Response(status, text="boom")
        return httpx.Response(200, json={"answers": answers, "model": "jev-1.13.0", "usage": {}})

    def wrapped(request):
        seen.append(request)
        return handler(request)

    transport = httpx.MockTransport(wrapped if handler else default)
    return JevDecider("k", transport=transport, **kw), seen


async def test_request_body_shape():
    d, seen = _jev(_answers("chat"))
    await d.decide(_event(), {}, CAPS)
    body = json.loads(seen[0].content)
    assert "state" in body
    assert body["model"] == "jev-latest"
    assert set(body["questions"]["route"]["criteria"]) == {c.name for c in CAPS}
    assert "arg:music.control:action" in body["questions"]


async def test_closed_args_false_no_arg_questions():
    d, seen = _jev(_answers("chat"), closed_args=False)
    await d.decide(_event(), {}, CAPS)
    body = json.loads(seen[0].content)
    assert not [k for k in body["questions"] if k.startswith("arg:")]


async def test_authorization_header():
    d, seen = _jev(_answers("chat"))
    await d.decide(_event(), {}, CAPS)
    assert seen[0].headers["Authorization"] == "Bearer k"


async def test_route_closed_capability_builds_call():
    d, _ = _jev(_answers("music.control", "pause"))
    dec = await d.decide(_event(), {}, CAPS)
    assert dec.calls == [Call("music.control", {"action": "pause"})]
    assert dec.confidence == 0.9
    assert dec.candidates == {"music.control": 0.9, "music.play": 0.1}
    assert dec.model == "jev-1.13.0"


async def test_route_free_args_needs_args():
    d, _ = _jev(_answers("music.play"))
    dec = await d.decide(_event(), {}, CAPS)
    assert dec.calls == []
    assert dec.escalation == "needs_args"


async def test_route_chat_no_calls():
    d, _ = _jev(_answers("chat"))
    dec = await d.decide(_event(), {}, CAPS)
    assert dec.calls == []


async def test_status_500_unavailable_without_key():
    d, _ = _jev(status=500)
    with pytest.raises(DeciderUnavailable) as ei:
        await d.decide(_event(), {}, CAPS)
    assert "k" not in str(ei.value)


async def test_connect_error_unavailable():
    def handler(request):
        raise httpx.ConnectError("down")

    d, _ = _jev(handler=handler)
    with pytest.raises(DeciderUnavailable):
        await d.decide(_event(), {}, CAPS)


async def test_missing_arg_answer_unavailable():
    d, _ = _jev(_answers("music.control"))
    with pytest.raises(DeciderUnavailable):
        await d.decide(_event(), {}, CAPS)


def test_render_state_ends_with_user_text():
    assert render_state(_event("pause"), {}).endswith("\nUser said: pause")


def test_load_api_key_from_file(tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    f = tmp_path / "typesafe.env"
    f.write_text("TYPESAFE_API_KEY='abc'\n")
    assert load_api_key(str(f)) == "abc"


def test_load_api_key_env_wins(tmp_path, monkeypatch):
    f = tmp_path / "typesafe.env"
    f.write_text("TYPESAFE_API_KEY='abc'\n")
    monkeypatch.setenv("TYPESAFE_API_KEY", "fromenv")
    assert load_api_key(str(f)) == "fromenv"


def test_load_api_key_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(DeciderUnavailable):
        load_api_key(str(tmp_path / "nope.env"))


# --- LlmDecider ---

async def test_llm_tool_call_becomes_call():
    llm = FakeLLM([_tool_call_response("music__control", {"action": "skip"})])
    dec = await LlmDecider(llm, RollingContext()).decide(_event("skip"), {}, CAPS)
    assert dec.calls == [Call("music.control", {"action": "skip"})]
    assert dec.route == "music.control"
    assert llm.calls[0][2] is False


async def test_llm_tools_exclude_chat_and_correction():
    tools = capability_tools(CAPS)
    names = [t["function"]["name"] for t in tools]
    assert names == ["music__control", "music__play"]
    llm = FakeLLM([_text_response("hi")])
    await LlmDecider(llm, RollingContext()).decide(_event("hello"), {}, CAPS)
    assert [t["function"]["name"] for t in llm.calls[0][1]] == names


async def test_llm_text_only_is_chat_reply():
    llm = FakeLLM([_text_response("  Hello there.  ")])
    dec = await LlmDecider(llm, RollingContext()).decide(_event("hi"), {}, CAPS)
    assert dec.calls == []
    assert dec.reply == "Hello there."
    assert dec.route == "chat"


async def test_llm_unknown_tool_dropped():
    llm = FakeLLM([_tool_call_response("nope__thing", {})])
    dec = await LlmDecider(llm, RollingContext()).decide(_event("x"), {}, CAPS)
    assert dec.calls == []


async def test_llm_max_calls_truncates():
    resp = _text_response("")
    resp["message"]["tool_calls"] = [
        {"id": f"c{i}", "function": {"index": i, "name": "music__control",
                                     "arguments": {"action": "skip"}}}
        for i in range(4)
    ]
    llm = FakeLLM([resp])
    dec = await LlmDecider(llm, RollingContext(), max_calls=3).decide(_event("x"), {}, CAPS)
    assert len(dec.calls) == 3


async def test_llm_instruction_is_system_before_user():
    llm = FakeLLM([_text_response("ok")])
    await LlmDecider(llm, RollingContext()).decide(_event("hey"), {}, CAPS, instruction="be brief")
    msgs = llm.calls[0][0]
    idx = msgs.index({"role": "system", "content": "be brief"})
    assert idx < len(msgs) - 1
    assert msgs[-1] == {"role": "user", "content": "hey"}


async def test_llm_connection_error_unavailable():
    class Boom:
        async def chat(self, messages, tools, think):
            raise ConnectionError("no ollama")

    with pytest.raises(DeciderUnavailable):
        await LlmDecider(Boom(), RollingContext()).decide(_event("x"), {}, CAPS)


async def test_llm_rolling_context_updated():
    rolling = RollingContext()
    llm = FakeLLM([_text_response("Sure.")])
    await LlmDecider(llm, rolling).decide(_event("hello"), {}, CAPS)
    assert rolling.messages() == [{"role": "user", "content": "hello"},
                                  {"role": "assistant", "content": "Sure."}]
