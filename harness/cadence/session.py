from dataclasses import dataclass
from typing import Awaitable, Callable

_KNOWN_CAPS = {"audio_in", "audio_out", "text_in", "text_out"}


@dataclass(frozen=True)
class SessionCaps:
    audio_in: bool
    audio_out: bool
    text_in: bool
    text_out: bool

    @classmethod
    def from_list(cls, caps: list[str]) -> SessionCaps:
        unknown = set(caps) - _KNOWN_CAPS
        if unknown:
            raise ValueError(f"unknown capability: {sorted(unknown)}")
        return cls(
            audio_in="audio_in" in caps,
            audio_out="audio_out" in caps,
            text_in="text_in" in caps,
            text_out="text_out" in caps,
        )


@dataclass
class Session:
    client_id: str
    caps: SessionCaps
    last_active: float
    send_audio: Callable[[bytes], Awaitable[None]]
    send_text: Callable[[str], Awaitable[None]]

    @property
    def needs_asr(self) -> bool:
        return self.caps.audio_in

    @property
    def needs_tts(self) -> bool:
        return self.caps.audio_out


class SessionRegistry:
    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def add(self, session: Session) -> None:
        self._sessions[session.client_id] = session

    def remove(self, client_id: str) -> None:
        self._sessions.pop(client_id, None)

    def get(self, client_id: str) -> Session | None:
        return self._sessions.get(client_id)

    def most_recent_audio(self) -> Session | None:
        candidates = [s for s in self._sessions.values() if s.caps.audio_out]
        if not candidates:
            return None
        return max(candidates, key=lambda s: s.last_active)
