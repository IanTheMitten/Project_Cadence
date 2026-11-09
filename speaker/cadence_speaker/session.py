from dataclasses import dataclass

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
