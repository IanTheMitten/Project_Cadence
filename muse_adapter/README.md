# Cadence Muse adapter

## What this is

`cadence_muse`: a service peer that connects to Cadence's `/peer` endpoint (`cadence_muse/link.py`, `adapter.py`) and declares the music abilities. It owns the play queues and the Muse HTTP client (`client.py`, `music.py`). It returns stream URLs; Cadence forwards them to the target speaker as `media` messages. Protocol table: `harness/README.md`.

Setup uses the shared venv at `harness/.venv` (see `harness/README.md`).

## Run

From `muse_adapter/`, with Cadence running (`python -m cadence` in `harness/`):

```
../harness/.venv/bin/python -m cadence_muse
```

At startup it checks the Muse contract version (`MusicPlugin.check()`); an unavailable Muse does not stop the process. The Muse proxy (`tools/muse_proxy.py`, port 8765) is started separately on the host.

The Muse MCP server (stdio) is a separate entry point: `../harness/.venv/bin/python -m cadence_muse.mcp_main`.

## Config

Read in `cadence_muse/config.py`:

| Variable | Default | Meaning |
|---|---|---|
| `CADENCE_PEER_URL` | `ws://127.0.0.1:8770/peer` | Cadence `/peer` endpoint |
| `CADENCE_MUSE_BASE_URL` | `http://ianshomeserver:8080` | Muse library server |
| `CADENCE_MUSE_PROXY_URL` | `http://ianshomeserver:8765` | `tools/muse_proxy.py`, where speakers fetch PCM |

## Tests

From `muse_adapter/`:

```
../harness/.venv/bin/python -m pytest
```

`scripts/capture_muse_fixtures.py` captures Muse responses as test fixtures. Kokoro files and `acks/` belong to the speaker adapter, not this program (`speaker/README.md`).
