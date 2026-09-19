"""Thin client for the Ollama chat endpoint.

One attempt, no retry: a transport failure or a non-200 status is a hard
`ConnectionError` for the caller to handle (or not — see `agent.run_turn`,
which lets it propagate).
"""

import httpx

LLM_MODEL = "gemma4:31b-cloud"
OLLAMA_URL = "http://localhost:11434/api/chat"


class OllamaLLM:
    async def chat(self, messages: list[dict], tools: list[dict], think: bool) -> dict:
        payload = {
            "model": LLM_MODEL,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "think": think,
        }
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(OLLAMA_URL, json=payload)
        except httpx.HTTPError as exc:
            raise ConnectionError(f"ollama unreachable: {exc}") from exc

        if response.status_code != 200:
            raise ConnectionError(
                f"ollama returned HTTP {response.status_code}: {response.text}"
            )

        return response.json()
