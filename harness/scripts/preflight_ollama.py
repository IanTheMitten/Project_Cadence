"""Preflight: prove gemma4:31b-cloud tool calling shape + latency, for both `think` settings.

Hits the local Ollama server directly (http://localhost:11434/api/chat). No sign-in, no pulling,
no model substitution — if Ollama reports Unauthorized, this prints BLOCKED and exits 0.
"""

import json
import time

import httpx

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "gemma4:31b-cloud"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_vibe",
            "description": "Search for music matching a vibe/mood description.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "n": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    }
]

MESSAGES = [{"role": "user", "content": "Find me something chill to play."}]


def send(think: bool):
    payload = {
        "model": MODEL,
        "stream": False,
        "think": think,
        "messages": MESSAGES,
        "tools": TOOLS,
    }
    start = time.monotonic()
    resp = httpx.post(OLLAMA_URL, json=payload, timeout=60.0)
    elapsed_ms = (time.monotonic() - start) * 1000
    try:
        body = resp.json()
    except ValueError:
        body = {"raw_text": resp.text}
    return resp.status_code, elapsed_ms, body


def is_unauthorized(body) -> bool:
    return isinstance(body, dict) and body.get("error") == "Unauthorized"


def main():
    blocked = False
    for think in (False, True):
        status, elapsed_ms, body = send(think)
        print(f"think={think} status={status} elapsed_ms={elapsed_ms:.1f}")
        print(json.dumps(body, indent=2))
        if is_unauthorized(body):
            blocked = True

    if blocked:
        print("BLOCKED: run 'ollama signin' on this machine, then re-run")


if __name__ == "__main__":
    main()
