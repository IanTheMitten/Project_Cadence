"""Builds the v1 runtime: devices, plugins, deciders, pipeline, audio.

`build_runtime()` is called lazily (first `server.get_runtime()`), never at
import time. Models (Whisper, Kokoro) load on first use.
"""

import sys
from dataclasses import dataclass
from typing import Callable

from cadence.acks import AckPool
from cadence.audio.listener import Listener
from cadence.audio.wakeword import WakeGate
from cadence.catalogue import Catalogue
from cadence.config import (ACK_DIR, BENCH_RECORD_DIR, DB_PATH, DEVICES_PATH, MUSE_BASE_URL,
                            MUSE_PROXY_URL, WAKE_ENABLED)
from cadence.context import RollingContext
from cadence.deciders.base import DeciderUnavailable, UnavailableDecider
from cadence.deciders.jev import JevDecider, load_api_key
from cadence.deciders.llm import LlmDecider
from cadence.decisionlog import DecisionLog
from cadence.executor import Executor
from cadence.livecontext import LiveContext
from cadence.llm import OllamaLLM
from cadence.muse.client import MuseClient
from cadence.pipeline import Pipeline
from cadence.plugins.music import MusicPlugin
from cadence.plugins.registry import DeviceRegistry
from cadence.plugins.speaker import SpeakerPlugin, SpeakerPort


@dataclass
class Runtime:
    registry: DeviceRegistry
    ports: dict[str, SpeakerPort]
    music: MusicPlugin | None
    pipeline: Pipeline
    acks: AckPool
    tts: Callable[[str], bytes] | None       # sentence -> speaker PCM
    asr: Callable[[bytes], str] | None       # mic PCM -> text
    listener_factory: Callable[[], Listener]
    bench_dir: str | None = None


def build_runtime() -> Runtime:
    registry = DeviceRegistry.from_file(DEVICES_PATH)
    ports: dict[str, SpeakerPort] = {}
    client = MuseClient(MUSE_BASE_URL, MUSE_PROXY_URL)
    music = MusicPlugin(client)
    music.check()
    speaker = SpeakerPlugin()
    catalogue = Catalogue([music, speaker])
    log = DecisionLog(DB_PATH)

    try:
        jev = JevDecider(load_api_key())
    except DeciderUnavailable as exc:
        print(f"jev unavailable: {exc}", file=sys.stderr)
        jev = UnavailableDecider(str(exc))
    llm = LlmDecider(OllamaLLM(), RollingContext())

    executor = Executor(catalogue, registry)
    context = LiveContext(log, music.now_playing)
    pipeline = Pipeline(jev, llm, catalogue, executor, log, context)
    acks = AckPool(ACK_DIR)

    _tts = None
    _asr = None

    def tts(text: str) -> bytes:
        nonlocal _tts
        if _tts is None:
            from cadence.audio.tts import Tts
            _tts = Tts()
        return _tts.speak(text)

    def asr(pcm: bytes) -> str:
        nonlocal _asr
        if _asr is None:
            from cadence.audio.asr import Asr
            _asr = Asr()
        return _asr.transcribe(pcm)

    def listener_factory() -> Listener:
        return Listener(WakeGate() if WAKE_ENABLED else None)

    return Runtime(registry=registry, ports=ports, music=music, pipeline=pipeline, acks=acks,
                   tts=tts, asr=asr, listener_factory=listener_factory, bench_dir=BENCH_RECORD_DIR)
