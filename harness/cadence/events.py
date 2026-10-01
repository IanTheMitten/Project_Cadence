from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

DEFAULT_USER = "household"


@dataclass(frozen=True)
class Event:
    id: str
    ts: float
    kind: str
    source: str
    room: str | None
    user_id: str
    payload: dict


def utterance(source: str, room: str | None, text: str, *, asr_conf: float | None = None,
              user_id: str = DEFAULT_USER, ts: float | None = None) -> Event:
    return Event(
        id=uuid.uuid4().hex,
        ts=time.time() if ts is None else ts,
        kind="utterance",
        source=source,
        room=room,
        user_id=user_id,
        payload={"text": text, "asr_conf": asr_conf},
    )


@dataclass(frozen=True)
class Call:
    capability: str
    args: dict


@dataclass
class Decision:
    decider: str  # "jev" | "llm" | "none"
    route: str | None  # capability name, "chat", or "correction"
    calls: list[Call]
    confidence: float | None = None
    candidates: dict[str, float] = field(default_factory=dict)
    reply: str | None = None
    escalation: str | None = None
    model: str | None = None
