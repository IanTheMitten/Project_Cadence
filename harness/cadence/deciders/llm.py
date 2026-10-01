from __future__ import annotations

import json

from cadence.agent import MAX_TOOL_CALLS
from cadence.context import RollingContext
from cadence.deciders.base import Decider, DeciderUnavailable
from cadence.events import Call, Decision
from cadence.llm import LLM_MODEL
from cadence.plugins.base import Capability

SYSTEM_PROMPT = ("You are the voice of a home speaker. Use a function when the user wants something done; "
                 "otherwise answer in one or two short sentences, since replies are spoken aloud. Never write code.")


def tool_name(capability_name: str) -> str:
    return capability_name.replace(".", "__")


def capability_tools(capabilities: list[Capability]) -> list[dict]:
    return [
        {"type": "function",
         "function": {"name": tool_name(c.name), "description": c.description,
                      "parameters": c.parameters}}
        for c in capabilities if c.name not in ("chat", "correction")
    ]


class LlmDecider(Decider):
    name = "llm"

    def __init__(self, llm, rolling: RollingContext, *, max_calls: int = MAX_TOOL_CALLS) -> None:
        self._llm = llm
        self._rolling = rolling
        self._max_calls = max_calls

    async def decide(self, event, context, capabilities, instruction=None) -> Decision:
        text = event.payload["text"]
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "system", "content": "Context: " + json.dumps(context)}]
        if instruction:
            messages.append({"role": "system", "content": instruction})
        messages += self._rolling.messages()
        messages.append({"role": "user", "content": text})
        try:
            response = await self._llm.chat(messages, capability_tools(capabilities), think=False)
        except ConnectionError as exc:
            raise DeciderUnavailable(str(exc)) from exc

        message = response["message"]
        known = {c.name for c in capabilities}
        calls = []
        for tc in message.get("tool_calls") or []:
            fn = tc["function"]
            name = fn["name"].replace("__", ".")
            if name in known:
                calls.append(Call(name, fn["arguments"]))
        calls = calls[: self._max_calls]
        reply = (message.get("content") or "").strip() or None
        route = calls[0].capability if calls else "chat"
        self._rolling.append("user", text)
        if reply:
            self._rolling.append("assistant", reply)
        return Decision(decider="llm", route=route, calls=calls, reply=reply, model=LLM_MODEL)
