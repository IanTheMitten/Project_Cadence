"""Cadence device protocol v1 (/peer, JSON text frames). Copied verbatim into each peer package; a hello with another PROTOCOL_VERSION is rejected."""
import json

PROTOCOL_VERSION = 1
ROLES = ("device", "service")


def encode(msg: dict) -> str:
    return json.dumps(msg)


def decode(text: str) -> dict:
    msg = json.loads(text)
    if not isinstance(msg, dict) or not isinstance(msg.get("type"), str):
        raise ValueError("message must be a JSON object with a string 'type'")
    return msg


def hello(peer_id: str, role: str, kind: str, room: str | None,
          caps: list[str], abilities: list[dict]) -> dict:
    return {"type": "hello", "version": PROTOCOL_VERSION, "peer_id": peer_id,
            "role": role, "kind": kind, "room": room,
            "caps": list(caps), "abilities": list(abilities)}


def check_hello(msg: dict) -> dict:
    if msg.get("type") != "hello":
        raise ValueError(f"expected hello, got {msg.get('type')!r}")
    if msg.get("version") != PROTOCOL_VERSION:
        raise ValueError(f"protocol version {msg.get('version')!r} != {PROTOCOL_VERSION}")
    peer_id = msg.get("peer_id")
    if not isinstance(peer_id, str) or not peer_id:
        raise ValueError("peer_id must be a non-empty string")
    if msg.get("role") not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    if not isinstance(msg.get("kind"), str):
        raise ValueError("kind must be a string")
    room = msg.get("room")
    if room is not None and not isinstance(room, str):
        raise ValueError("room must be a string or null")
    caps = msg.get("caps", [])
    if not isinstance(caps, list) or not all(isinstance(c, str) for c in caps):
        raise ValueError("caps must be a list of strings")
    abilities = msg.get("abilities", [])
    if not isinstance(abilities, list) or not all(
        isinstance(a, dict) and all(k in a for k in ("name", "description", "parameters"))
        for a in abilities
    ):
        raise ValueError("abilities must be a list of dicts with name, description, parameters")
    return msg
