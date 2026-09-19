"""Bounded tool-calling agent loop.

Drives `llm.chat` against a `tools` collaborator (duck-typed: anything with
`list_tools()` and an async `call(name, args)`), capped at `MAX_TOOL_CALLS`
executed tool calls per turn. The model always sees tool results between
calls. A failed tool ends the turn with one final `llm.chat` so the model can
report it aloud — never a retry. `ConnectionError` from the LLM propagates
untouched: no local fallback.
"""

import json
from dataclasses import dataclass

MAX_TOOL_CALLS = 3


@dataclass
class TurnResult:
    text: str
    tool_calls: list[dict]
    capped: bool = False
    failed_tool: str | None = None


async def run_turn(llm, tools, messages: list[dict]) -> TurnResult:
    messages = list(messages)
    executed: list[dict] = []
    tool_call_count = 0

    while True:
        response = await llm.chat(messages, tools.list_tools(), think=False)
        message = response["message"]
        tool_calls = message.get("tool_calls")

        if not tool_calls:
            return TurnResult(text=message.get("content", ""), tool_calls=executed)

        messages.append(message)

        for tool_call in tool_calls:
            function = tool_call["function"]
            name = function["name"]
            arguments = function["arguments"]

            try:
                result = await tools.call(name, arguments)
            except Exception as exc:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id"),
                        "content": str(exc),
                    }
                )
                final = await llm.chat(messages, tools.list_tools(), think=False)
                return TurnResult(
                    text=final["message"].get("content", ""),
                    tool_calls=executed,
                    failed_tool=name,
                )

            tool_call_count += 1
            executed.append({"name": name, "arguments": arguments, "result": result})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.get("id"),
                    "content": json.dumps(result),
                }
            )

            if tool_call_count >= MAX_TOOL_CALLS:
                final = await llm.chat(messages, tools.list_tools(), think=False)
                return TurnResult(
                    text=final["message"].get("content", ""),
                    tool_calls=executed,
                    capped=True,
                )
