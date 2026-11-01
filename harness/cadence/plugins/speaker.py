from __future__ import annotations

import asyncio
import contextlib
from typing import Awaitable, Callable

import httpx
import numpy as np

from cadence.audio.mixer import DUCK_GAIN, mix
from cadence.config import VOLUME_STEP
from cadence.plugins.base import Capability, Manifest, Plugin, Result

BYTES_PER_MS = 176.4  # 44100 Hz * 2 ch * 2 bytes / 1000
PACE_LEAD_S = 0.3  # how far ahead of real time _pump may run; must stay below the board's ~370 ms ring

VOLUME = Capability(
    "speaker.volume",
    "Make the speaker louder or quieter, or mute or unmute it.",
    {"type": "object",
     "properties": {"action": {"type": "string", "enum": ["up", "down", "mute", "unmute"]},
                    "room": {"type": "string"}},
     "required": ["action"]},
    closed_args={"action": {"up": "louder, turn it up", "down": "quieter, turn it down",
                            "mute": "mute", "unmute": "unmute"}},
    target="speaker",
)


class SpeakerPort:
    def __init__(self, send_audio: Callable[[bytes], Awaitable[None]], *,
                 transport: httpx.AsyncBaseTransport | None = None, gain: float = 1.0,
                 max_gain: float = 1.0) -> None:
        self._send = send_audio
        self._transport = transport
        self._gain = max(0.0, min(1.0, gain))
        self._max_gain = max(0.0, min(1.0, max_gain))  # output ceiling; gain 1.0 plays at this level
        self._muted = False
        self._carry = b""
        self._on_end: Callable[[str], Awaitable[None]] | None = None
        self._task: asyncio.Task | None = None
        self._resumed = asyncio.Event()
        self._resumed.set()
        self._paused = False
        self._bytes = 0
        self._tail = b""
        self._speaking = False

    @property
    def gain(self) -> float:
        return self._gain

    @property
    def muted(self) -> bool:
        return self._muted

    def set_gain(self, gain: float) -> None:
        self._gain = max(0.0, min(1.0, gain))

    def mute(self) -> None:
        self._muted = True

    def unmute(self) -> None:
        self._muted = False

    def _apply_gain(self, data: bytes) -> bytes:
        eff = 0.0 if self._muted else self._gain * self._max_gain
        data = self._carry + data
        self._carry = b""
        if eff == 1.0:
            return data
        if len(data) % 2:
            data, self._carry = data[:-1], data[-1:]
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) * eff
        return np.clip(samples, -32768, 32767).astype(np.int16).tobytes()

    async def play_url(self, url: str, on_end: Callable[[str], Awaitable[None]]) -> None:
        await self.stop()
        self._on_end = on_end
        self._paused = False
        self._resumed.set()
        self._bytes = 0
        self._tail = b""
        self._speaking = False
        self._carry = b""
        self._task = asyncio.create_task(self._pump(url))

    async def _pump(self, url: str) -> None:
        reason = "track_end"
        try:
            loop = asyncio.get_running_loop()
            t0, sent = None, 0  # pacing baseline (set at the first forwarded chunk, not the request: ffmpeg startup is not playback time)
            async with httpx.AsyncClient(transport=self._transport, timeout=None) as client:
                async with client.stream("GET", url) as response:
                    async for chunk in response.aiter_bytes():
                        waited = loop.time()
                        await self._resumed.wait()
                        if loop.time() - waited > 0.2:  # paused: restart the baseline
                            t0, sent = None, 0
                        self._bytes += len(chunk)
                        if self._speaking:
                            self._tail += chunk
                        else:
                            if t0 is None:
                                t0 = loop.time()
                            await self._send(self._apply_gain(chunk))
                            sent += len(chunk)
                            ahead = sent / BYTES_PER_MS / 1000 - (loop.time() - t0) - PACE_LEAD_S
                            if ahead > 0:
                                await asyncio.sleep(ahead)
        except httpx.HTTPError:
            reason = "lost"
        on_end, self._on_end = self._on_end, None
        if on_end is not None:
            await on_end(reason)

    async def pause(self) -> None:
        if self.is_playing():
            self._paused = True
            self._resumed.clear()

    async def resume(self) -> None:
        self._paused = False
        self._resumed.set()

    async def stop(self, reason: str = "stopped") -> None:
        on_end, self._on_end = self._on_end, None
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._paused = False
        self._resumed.set()
        if on_end is not None:
            await on_end(reason)

    def position_ms(self) -> int:
        return int(self._bytes / BYTES_PER_MS)

    def is_paused(self) -> bool:
        return self._paused

    def is_playing(self) -> bool:
        return self._task is not None and not self._task.done()

    async def speak(self, pcm: bytes) -> None:
        if not (self.is_playing() and not self._paused):
            await self._send(self._apply_gain(pcm))
            return
        self._speaking = True
        try:
            music, self._tail = self._tail[:len(pcm)], self._tail[len(pcm):]
            music += b"\x00" * (len(pcm) - len(music))
            await self._send(self._apply_gain(mix(music, pcm, DUCK_GAIN)))
        finally:
            self._speaking = False
        if self._tail:
            rest, self._tail = self._tail, b""
            await self._send(self._apply_gain(rest))

    async def drain(self) -> None:
        task = self._task
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await task


class SpeakerPlugin(Plugin):
    manifest = Manifest("speaker", "device", (VOLUME,))

    def __init__(self, *, step: float = VOLUME_STEP) -> None:
        self._step = step

    async def call(self, capability, args, target, port) -> Result:
        if port is None:
            return Result(False, say="That speaker isn't connected.", error="no_port")
        action = args.get("action")
        if action == "up":
            port.unmute()
            port.set_gain(min(1.0, port.gain + self._step))
        elif action == "down":
            port.set_gain(max(0.0, port.gain - self._step))
        elif action == "mute":
            port.mute()
        elif action == "unmute":
            port.unmute()
        return Result(True, data={"gain": port.gain, "muted": port.muted})
