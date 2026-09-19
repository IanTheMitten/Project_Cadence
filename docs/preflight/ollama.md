# Preflight: `gemma4:31b-cloud` tool calling shape + latency

Ran `harness/scripts/preflight_ollama.py` against `http://localhost:11434/api/chat`, model
`gemma4:31b-cloud`, one tool (`search_vibe`), message `"Find me something chill to play."`,
once with `think: false` and once with `think: true`.

## Result: working (post `ollama signin`)

Both requests returned HTTP 200 with a real tool call. Note the response body's `model` field
comes back as `gemma4:31b` (no `-cloud` suffix), even though the request was sent with
`model: "gemma4:31b-cloud"`.

| `think` | HTTP status | elapsed ms | `message.tool_calls` present? |
|---|---|---|---|
| `false` | 200 | 719.7 | yes |
| `true`  | 200 | 1739.4 | yes |

## `think: false` — full response body

```json
{
  "model": "gemma4:31b",
  "created_at": "2026-09-19T15:37:23.266797125Z",
  "message": {
    "role": "assistant",
    "content": "",
    "tool_calls": [
      {
        "id": "call_7t9m23ta",
        "function": {
          "index": 0,
          "name": "search_vibe",
          "arguments": {
            "query": "chill, relaxing, low-fi, ambient music"
          }
        }
      }
    ]
  },
  "done": true,
  "done_reason": "stop",
  "total_duration": 302028582,
  "prompt_eval_count": 81,
  "prompt_eval_cached_count": 64,
  "eval_count": 25
}
```

Tool call path: `message.tool_calls[0]`, with fields `id` (string), `function.index` (int),
`function.name` (string, `"search_vibe"`), `function.arguments` (object, `{"query": "..."}`).
No `thinking` field present when `think: false`. `message.content` is an empty string.

## `think: true` — full response body

```json
{
  "model": "gemma4:31b",
  "created_at": "2026-09-19T15:37:25.157529701Z",
  "message": {
    "role": "assistant",
    "content": "",
    "thinking": "The user is asking for \"something chill to play,\" which implies they are looking for music recommendations that fit a \"chill\" vibe.\nThe available tool `search_vibe` is specifically designed to \"Search for music matching a vibe/mood description.\"\nTherefore, I should call `search_vibe` with a query related to \"chill\" music.",
    "tool_calls": [
      {
        "id": "call_eoj2x4sv",
        "function": {
          "index": 0,
          "name": "search_vibe",
          "arguments": {
            "query": "chill music"
          }
        }
      }
    ]
  },
  "done": true,
  "done_reason": "stop",
  "total_duration": 1510299357,
  "prompt_eval_count": 79,
  "prompt_eval_cached_count": 64,
  "eval_count": 95
}
```

Same tool call path/shape as `think: false`: `message.tool_calls[0].function.name`,
`message.tool_calls[0].function.arguments`. The only structural difference is the additional
`message.thinking` field (string, the model's chain-of-thought) and higher `eval_count` (95 vs
25) and `total_duration` (~1.51s vs ~0.30s), consistent with the extra reasoning pass.

## Notes

- `prompt_eval_cached_count: 64` on this run reflects prompt caching from the immediately
  preceding invocation of the same script in this session; a cold run may show `0` here (as an
  earlier run did) without affecting the `tool_calls` shape.
- Elapsed ms in the table above is wall-clock round trip measured by the script
  (`time.monotonic()` around the `httpx.post` call), not `total_duration` from the response body
  (which is server-side nanoseconds and excludes HTTP overhead).
