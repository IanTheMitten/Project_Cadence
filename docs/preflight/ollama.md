# Preflight: `gemma4:31b-cloud` tool calling shape + latency

Ran `harness/scripts/preflight_ollama.py` against `http://localhost:11434/api/chat`, model
`gemma4:31b-cloud`, one tool (`search_vibe`), message `"Find me something chill to play."`,
once with `think: false` and once with `think: true`.

## Result: BLOCKED

Both requests returned HTTP 401 with body `{"error": "Unauthorized"}`. This is the known
open Ollama-auth issue on this machine (see spec decision "LLM model",
`docs/specs/2026-09-19-voice-music-agent-harness.md:176`: "`ollama signin` on the server is
an interactive prerequisite the user must run"). Per the brief, no sign-in was attempted and
no other model was substituted.

| `think` | HTTP status | elapsed ms | `message.tool_calls` present? |
|---|---|---|---|
| `false` | 401 | 228.7 | n/a — response was `{"error": "Unauthorized"}`, no `message` field at all |
| `true`  | 401 | 211.7 | n/a — response was `{"error": "Unauthorized"}`, no `message` field at all |

No `tool_calls` JSON shape could be recorded — Ollama never got past auth to run the model, so
there is no `message`, `message.tool_calls`, function name, or arguments object to copy field
names from. Elapsed times above are for the 401 round trip only, not model inference, and are
not representative of eventual tool-call latency.

## Next step

Blocked on `ollama signin` on this machine, which is a user-run interactive step (per Forbidden
in the task brief, not run by this script). Re-run
`cd harness && .venv/bin/python scripts/preflight_ollama.py` after sign-in to capture the real
`tool_calls` shape and latency for both `think` settings.
