# Cadence chat

`cadence_chat`: a text chat page for Cadence. It serves one page on `/` and a browser WebSocket on `/ws` (port 8771). Each open tab joins Cadence's `/peer` as its own `device` peer (`kind` `chat`, `caps` `["text_out"]`, no abilities, `peer_id` `chat-<random>`). Typed lines become `utterance` events; Cadence's `say` replies show up as messages. Because the chat peer sits in a room (default `bedroom`), "play some jazz" plays on that room's speaker, and announcements for that room show up in the chat too.

No login: anyone who can reach the port can talk to Cadence. Bind it to the Tailscale address (below) to keep it off the LAN.

## Run

From `chat/`, with Cadence running (`python -m cadence` in `harness/`):

```
CADENCE_CHAT_HOST=$(tailscale ip -4) ../harness/.venv/bin/python -m cadence_chat
```

Then open `http://ianshomeserver:8771` (MagicDNS) or `http://<tailscale-ip>:8771` on any machine in the tailnet.

## Config

Read in `cadence_chat/config.py`:

| Env var | Default | Meaning |
|---|---|---|
| `CADENCE_CHAT_HOST` | `0.0.0.0` | Bind address |
| `CADENCE_CHAT_PORT` | `8771` | Port |
| `CADENCE_PEER_URL` | `ws://127.0.0.1:8770/peer` | Cadence `/peer` |
| `CADENCE_CHAT_ROOM` | `bedroom` | Room the chat peer is in |

## Tests

```
../harness/.venv/bin/python -m pytest
```
