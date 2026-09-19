"""Tests for the bounded tool-call agent loop.

Pins three caps from docs/specs/2026-09-19-voice-music-agent-harness.md:63-68:
MAX_TOOL_CALLS == 3, the model sees tool results between calls, a failed tool
ends the turn with a spoken report (never a retry), and there is no local
fallback if the LLM is unreachable.

The fake `llm.chat(messages, tools, think)` responses are shaped exactly like
the real `gemma4:31b-cloud` response recorded in docs/preflight/ollama.md:
`message.tool_calls` is a list of `{"id", "function": {"index", "name",
"arguments"}}`; `message.content` is a string, empty when a tool call is
made; no `tool_calls` key at all when the model returns plain text (that is
what Ollama actually sends); no `thinking` key anywhere, since run_turn always
passes think=False.
"""

import copy

import pytest

from cadence.agent import MAX_TOOL_CALLS, TurnResult, run_turn


def _tool_call_response(name, arguments, call_id="call_1"):
    return {
        "model": "gemma4:31b",
        "created_at": "2026-09-19T15:37:23.266797125Z",
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call_id,
                    "function": {
                        "index": 0,
                        "name": name,
                        "arguments": arguments,
                    },
                }
            ],
        },
        "done": True,
        "done_reason": "stop",
    }


def _text_response(content):
    return {
        "model": "gemma4:31b",
        "created_at": "2026-09-19T15:37:23.266797125Z",
        "message": {
            "role": "assistant",
            "content": content,
        },
        "done": True,
        "done_reason": "stop",
    }


class FakeLLM:
    """Returns a scripted queue of responses; records every call received."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def chat(self, messages, tools, think):
        self.calls.append((copy.deepcopy(messages), tools, think))
        return self._responses.pop(0)


class RepeatingFakeLLM:
    """Always returns the same tool-call response, regardless of call count."""

    def __init__(self, response):
        self._response = response
        self.calls = []

    async def chat(self, messages, tools, think):
        self.calls.append((copy.deepcopy(messages), tools, think))
        return self._response


class FakeTools:
    def __init__(self, result=None, fail_on_call=None):
        self._result = result if result is not None else {"ok": True}
        self._fail_on_call = fail_on_call
        self.calls = []

    def list_tools(self):
        return [{"name": "search_vibe", "description": "search", "input_schema": {}}]

    async def call(self, name, args):
        self.calls.append((name, args))
        if self._fail_on_call is not None and len(self.calls) == self._fail_on_call:
            raise RuntimeError("tool exploded")
        return self._result


def test_max_tool_calls_is_three():
    assert MAX_TOOL_CALLS == 3


async def test_zero_tool_turn_returns_text():
    llm = FakeLLM([_text_response("here's something chill")])
    tools = FakeTools()

    result = await run_turn(llm, tools, [{"role": "user", "content": "play something chill"}])

    assert result.text == "here's something chill"
    assert result.tool_calls == []
    assert len(llm.calls) == 1


async def test_two_hop_turn_feeds_results_back():
    llm = FakeLLM(
        [
            _tool_call_response("search_vibe", {"query": "chill"}),
            _text_response("playing something chill"),
        ]
    )
    tools = FakeTools(result={"track_rowid": 123})

    result = await run_turn(llm, tools, [{"role": "user", "content": "play something chill"}])

    assert len(llm.calls) == 2
    second_messages = llm.calls[1][0]
    assert any("123" in str(m.get("content", "")) for m in second_messages)
    assert len(result.tool_calls) == 1


async def test_cap_stops_at_three_calls():
    llm = RepeatingFakeLLM(_tool_call_response("search_vibe", {"query": "chill"}))
    tools = FakeTools(result={"track_rowid": 123})

    result = await run_turn(llm, tools, [{"role": "user", "content": "play something chill"}])

    assert len(tools.calls) == 3
    assert len(llm.calls) == 4
    assert result.capped is True


async def test_tool_failure_ends_turn_without_retry():
    llm = FakeLLM(
        [
            _tool_call_response("search_vibe", {"query": "chill"}),
            _text_response("Muse isn't answering, want me to try again?"),
        ]
    )
    tools = FakeTools(fail_on_call=1)

    result = await run_turn(llm, tools, [{"role": "user", "content": "play something chill"}])

    assert len(tools.calls) == 1
    assert result.failed_tool == "search_vibe"
    assert result.text


async def test_llm_unreachable_raises():
    class RaisingLLM:
        def __init__(self):
            self.calls = []

        async def chat(self, messages, tools, think):
            self.calls.append((copy.deepcopy(messages), tools, think))
            raise ConnectionError("ollama unreachable")

    llm = RaisingLLM()
    tools = FakeTools()

    with pytest.raises(ConnectionError):
        await run_turn(llm, tools, [{"role": "user", "content": "play something chill"}])

    assert len(llm.calls) == 1


async def test_think_false_for_live_turns():
    llm = FakeLLM(
        [
            _tool_call_response("search_vibe", {"query": "chill"}),
            _text_response("playing something chill"),
        ]
    )
    tools = FakeTools(result={"track_rowid": 123})

    await run_turn(llm, tools, [{"role": "user", "content": "play something chill"}])

    assert all(think is False for (_messages, _tools, think) in llm.calls)
