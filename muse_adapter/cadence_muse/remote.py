from __future__ import annotations

import time


class RemotePort:
    """Port the music plugin drives; every action goes to the speaker as a media message."""

    def __init__(self, device_id: str, send, *, clock=time.monotonic) -> None:
        self._device = device_id
        self._send = send
        self._clock = clock
        self._url: str | None = None
        self._on_end = None
        self._start = 0.0
        self._paused_at: float | None = None
        self._paused_total = 0.0
        self._reported: int | None = None

    async def _media(self, action: str, **extra) -> None:
        await self._send({"type": "media", "device": self._device, "action": action, **extra})

    async def play_url(self, url: str, on_end) -> None:
        self._url, self._on_end = url, on_end
        self._start, self._paused_at, self._paused_total, self._reported = self._clock(), None, 0.0, None
        await self._media("play_url", url=url)

    async def pause(self) -> None:
        if self._paused_at is None:
            self._paused_at = self._clock()
        await self._media("pause")

    async def resume(self) -> None:
        if self._paused_at is not None:
            self._paused_total += self._clock() - self._paused_at
            self._paused_at = None
        await self._media("resume")

    async def stop(self, reason: str = "stopped") -> None:
        await self._media("stop")
        on_end, self._on_end, self._url, self._paused_at = self._on_end, None, None, None
        if on_end is not None:
            await on_end(reason)

    def is_paused(self) -> bool:
        return self._paused_at is not None

    # shortcut: position is wall-clock estimated between media_events, upgrade when the speaker reports position periodically
    def position_ms(self) -> int:
        if self._reported is not None:
            return self._reported
        now = self._clock() if self._paused_at is None else self._paused_at
        return int((now - self._start - self._paused_total) * 1000)

    async def on_media_event(self, event: str, position_ms: int, url: str) -> None:
        if url != self._url or event not in ("track_end", "lost"):
            return
        self._reported = position_ms
        on_end, self._on_end = self._on_end, None
        if on_end is not None:
            await on_end(event)
