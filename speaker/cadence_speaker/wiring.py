"""Builds the speaker runtime. Models (Whisper, Kokoro) load on first use."""

from dataclasses import dataclass
from typing import Awaitable, Callable

from cadence_speaker import link
from cadence_speaker.acks import AckPool
from cadence_speaker.audio.listener import Listener
from cadence_speaker.audio.wakeword import WakeGate
from cadence_speaker.config import (ACK_DIR, BENCH_RECORD_DIR, PEER_URL, RECONNECT_S, ROOM,
                                    WAKE_ENABLED)


@dataclass
class SpeakerRuntime:
    acks: AckPool
    tts: Callable[[str], bytes] | None       # sentence -> speaker PCM
    asr: Callable[[bytes], str] | None       # mic PCM -> text
    listener_factory: Callable[[], Listener]
    open_link: Callable[[str, dict], Awaitable]
    room: str = ROOM
    peer_url: str = PEER_URL
    reconnect_s: float = RECONNECT_S
    bench_dir: str | None = None
    transport: object | None = None


def build_runtime() -> SpeakerRuntime:
    _tts = None
    _asr = None

    def tts(text: str) -> bytes:
        nonlocal _tts
        if _tts is None:
            from cadence_speaker.audio.tts import Tts
            _tts = Tts()
        return _tts.speak(text)

    def asr(pcm: bytes) -> str:
        nonlocal _asr
        if _asr is None:
            from cadence_speaker.audio.asr import Asr
            _asr = Asr()
        return _asr.transcribe(pcm)

    def listener_factory() -> Listener:
        return Listener(WakeGate() if WAKE_ENABLED else None)

    return SpeakerRuntime(acks=AckPool(ACK_DIR), tts=tts, asr=asr, listener_factory=listener_factory,
                          open_link=link.open_link, bench_dir=BENCH_RECORD_DIR)
