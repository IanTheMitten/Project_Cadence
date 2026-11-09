"""Thin client for Google AI Studio (Gemini API, OpenAI-compatible endpoint).

Callers (`agent.run_turn`, `LlmDecider`) speak the Ollama message shape:
`response["message"]` with `tool_calls[].function.arguments` as a dict. This
client converts to and from the OpenAI shape at the boundary.

One attempt, no retry: a transport failure, a non-200 status, or a missing
`GEMINI_API_KEY` (env var, else ~/.config/cadence/typesafe.env) is a hard `ConnectionError` for the caller to handle.
"""

import json
import os

import httpx

from cadence.deciders.base import DeciderUnavailable
from cadence.deciders.jev import load_api_key

LLM_MODEL = os.environ.get("CADENCE_LLM_MODEL", "gemini-2.5-flash")
GOOGLE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"


def _to_openai(message: dict) -> dict:
    if not message.get("tool_calls"):
        return message
    calls = []
    for i, tc in enumerate(message["tool_calls"]):
        args = tc["function"]["arguments"]
        calls.append({
            "id": tc.get("id") or f"call_{i}",
            "type": "function",
            "function": {"name": tc["function"]["name"],
                         "arguments": args if isinstance(args, str) else json.dumps(args)},
        })
    return {**message, "tool_calls": calls}


def _from_openai(message: dict) -> dict:
    calls = [
        {"id": tc.get("id"),
         "function": {"name": tc["function"]["name"],
                      "arguments": json.loads(tc["function"].get("arguments") or "{}")}}
        for tc in message.get("tool_calls") or []
    ]
    out = {"role": "assistant", "content": message.get("content") or ""}
    if calls:
        out["tool_calls"] = calls
    return out


class GoogleLLM:
    async def chat(self, messages: list[dict], tools: list[dict], think: bool) -> dict:
        # `think` ignored: kept for interface parity with the old Ollama client.
        try:
            key = load_api_key(name="GEMINI_API_KEY")
        except DeciderUnavailable as exc:
            raise ConnectionError(str(exc)) from exc
        payload = {"model": LLM_MODEL, "messages": [_to_openai(m) for m in messages]}
        if tools:
            payload["tools"] = tools
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    GOOGLE_URL, json=payload, headers={"Authorization": f"Bearer {key}"})
        except httpx.HTTPError as exc:
            raise ConnectionError(f"google ai studio unreachable: {exc}") from exc

        if response.status_code != 200:
            raise ConnectionError(
                f"google ai studio returned HTTP {response.status_code}: {response.text}"
            )

        return {"message": _from_openai(response.json()["choices"][0]["message"])}
