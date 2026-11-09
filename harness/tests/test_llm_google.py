import functools
import json

import httpx
import pytest

from cadence import llm
from cadence.deciders import jev


async def test_chat_converts_tool_calls_both_ways(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    sent = {}

    async def fake_post(self, url, json=None, headers=None):
        sent.update(json=json, headers=headers)
        msg = {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "music__play", "arguments": '{"query": "jazz"}'}}]}
        return httpx.Response(200, json={"choices": [{"message": msg}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    history = [{"role": "assistant", "content": "",
                "tool_calls": [{"function": {"name": "x", "arguments": {"a": 1}}}]}]
    out = await llm.GoogleLLM().chat(history, [], think=False)

    assert out["message"]["tool_calls"][0]["function"] == {"name": "music__play", "arguments": {"query": "jazz"}}
    assert out["message"]["content"] == ""
    resent = sent["json"]["messages"][0]["tool_calls"][0]
    assert resent["id"] == "call_0" and json.loads(resent["function"]["arguments"]) == {"a": 1}
    assert "tools" not in sent["json"]
    assert sent["headers"]["Authorization"] == "Bearer k"


async def test_missing_key_is_connection_error(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(llm, "load_api_key", functools.partial(jev.load_api_key, str(tmp_path / "none.env")))
    with pytest.raises(ConnectionError):
        await llm.GoogleLLM().chat([], [], think=False)


async def test_key_read_from_env_file(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    f = tmp_path / "typesafe.env"
    f.write_text("TYPESAFE_API_KEY=t\nGEMINI_API_KEY='g'\n")
    assert jev.load_api_key(str(f), name="GEMINI_API_KEY") == "g"
