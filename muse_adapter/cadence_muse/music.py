from __future__ import annotations

import asyncio
import random
import sys
import time
from dataclasses import dataclass, field
from typing import Callable

from cadence_muse.config import (DEFAULT_QUEUE_LEN, MAX_QUEUE_LEN, MUSE_CONTRACT_MAJOR,
                            PAUSE_TIMEOUT_S, PLAY_SOURCE)
from cadence_muse.client import MuseUnavailable


@dataclass
class Result:
    ok: bool
    say: str | None = None
    data: dict = field(default_factory=dict)
    error: str | None = None


def _ability(name, description, parameters, closed_args=None, free_args=(), target=None) -> dict:
    return {"name": name, "description": description, "parameters": parameters,
            "closed_args": closed_args or {}, "free_args": list(free_args), "target": target}


PLAY = _ability("music.play", "Play music: a mood, genre, artist, song, or a playlist built from a vibe.",
    {"type": "object", "properties": {"artist": {"type": "string"}, "title": {"type": "string"},
     "mood": {"type": "string", "description": "mood, vibe, activity, or feeling"}, "genre": {"type": "string"},
     "count": {"type": "integer", "minimum": 1, "maximum": 50}, "room": {"type": "string"}}},
    free_args=("artist", "title", "mood", "genre"), target="speaker")
CONTROL = _ability("music.control", "Pause, stop, resume, skip, go back, or turn shuffle on or off for the music playing now.",
    {"type": "object", "properties": {"action": {"type": "string", "enum": ["pause", "resume", "skip", "previous", "shuffle_on", "shuffle_off"]},
     "room": {"type": "string"}}, "required": ["action"]},
    closed_args={"action": {"pause": "pause or stop the music", "resume": "resume or continue paused music",
     "skip": "skip to the next track", "previous": "go back to the previous track",
     "shuffle_on": "turn shuffle on", "shuffle_off": "turn shuffle off"}}, target="speaker")
RATE = _ability("music.rate", "Like or dislike the track playing now, or clear its rating.",
    {"type": "object", "properties": {"rating": {"type": "string", "enum": ["up", "down", "clear"]},
     "room": {"type": "string"}}, "required": ["rating"]},
    closed_args={"rating": {"up": "likes it, thumbs up", "down": "dislikes it, thumbs down", "clear": "remove the rating"}},
    target="speaker")
NOW = _ability("music.now_playing", "Say what is playing now, or whether the music is paused.",
    {"type": "object", "properties": {}}, target="speaker")

ABILITIES = [PLAY, CONTROL, RATE, NOW]

RECHECK_S = 30.0


def _warn(msg: str) -> None:
    print(f"music: {msg}", file=sys.stderr)


def compose_queue(text_results: list[dict] | None, vibe_results: list[dict] | None,
                  artist: str | None, count: int) -> list[dict]:
    text = [t for t in (text_results or []) if t.get("playable")]
    vibe = []
    for item in vibe_results or []:
        track = item.get("track") or {}
        if not track.get("playable"):
            continue
        track = dict(track)
        track.setdefault("track_rowid", item.get("track_rowid"))
        vibe.append((item.get("score", 0), track))
    if artist and text_results is not None:
        needle = artist.lower()
        text = [t for t in text
                if needle in (t.get("artist_name") or "").lower()
                or any(needle in (a or "").lower() for a in t.get("artist_names") or [])]
    vibe_sorted = [t for _, t in sorted(vibe, key=lambda p: -p[0])]
    if text_results and vibe_results:
        scores = {}
        for s, t in vibe:
            scores.setdefault(t["track_rowid"], s)
        in_vibe = sorted((t for t in text if t["track_rowid"] in scores),
                         key=lambda t: -scores[t["track_rowid"]])
        rest = [t for t in text if t["track_rowid"] not in scores]
        ordered = in_vibe + rest
    elif text_results:
        ordered = text
    else:
        ordered = vibe_sorted
    out, seen = [], set()
    for t in ordered:
        rid = t["track_rowid"]
        if rid in seen:
            continue
        seen.add(rid)
        out.append(t)
    return out[:count]


@dataclass
class _DeviceState:
    tracks: list[dict]
    index: int = 0
    play_id: int | None = None
    timed_out: bool = False
    timer: asyncio.Task | None = None
    shuffle: bool = False
    port: object = None


class MusicPlugin:
    def __init__(self, client, *, pause_timeout_s: float = PAUSE_TIMEOUT_S, rng: random.Random | None = None,
                 source: str = PLAY_SOURCE, contract_major: int = MUSE_CONTRACT_MAJOR,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._client = client
        self._pause_timeout_s = pause_timeout_s
        self._rng = rng or random.Random()
        self._source = source
        self._contract_major = contract_major
        self._clock = clock
        self._devices: dict[str, _DeviceState] = {}
        self._ok: bool | None = None
        self._checked_at = 0.0

    def check(self) -> bool:
        try:
            version = self._client.contract_version()
            ok = version is None or int(str(version).split(".")[0]) == self._contract_major
        except (MuseUnavailable, ValueError):
            ok = False
        self._ok = ok
        self._checked_at = self._clock()
        return ok

    def available(self) -> bool:
        if self._ok is None:
            return True
        if not self._ok and self._clock() - self._checked_at >= RECHECK_S:
            self.check()
        return self._ok

    def now_playing(self, device_id: str) -> dict | None:
        st = self._devices.get(device_id)
        if st is None:
            return None
        t = st.tracks[st.index]
        return {"track_name": t["track_name"], "artist_name": t["artist_name"],
                "paused": st.timed_out or bool(st.port is not None and st.port.is_paused())}

    # --- internals ---

    def _cancel_timer(self, st: _DeviceState) -> None:
        if st.timer is not None and st.timer is not asyncio.current_task():
            st.timer.cancel()
        st.timer = None

    async def _close(self, st: _DeviceState, reason: str, pos: int | None) -> None:
        if st.play_id is None:
            return
        play_id, st.play_id = st.play_id, None
        try:
            await asyncio.to_thread(self._client.close_play, play_id, reason, pos)
        except (MuseUnavailable, ValueError) as e:
            _warn(f"close_play failed: {e}")

    def _clear(self, device_id: str) -> None:
        st = self._devices.pop(device_id, None)
        if st is not None:
            self._cancel_timer(st)

    async def _start(self, device_id: str, st: _DeviceState, port, index: int) -> None:
        st.index = index
        st.timed_out = False
        track = st.tracks[index]
        try:
            st.play_id = await asyncio.to_thread(
                self._client.open_play, track["track_rowid"], track.get("duration_ms"), self._source)
        except MuseUnavailable as e:
            st.play_id = None
            _warn(f"open_play failed: {e}")

        async def on_end(reason: str) -> None:
            if self._devices.get(device_id) is not st or reason == "stopped":
                return
            if reason == "track_end":
                await self._close(st, "track_end", port.position_ms())
                if st.index + 1 < len(st.tracks):
                    await self._start(device_id, st, port, st.index + 1)
                else:
                    self._clear(device_id)
            elif reason == "lost":
                await self._close(st, "lost", port.position_ms())
                self._clear(device_id)

        await port.play_url(f"{self._client.proxy_url}/play/{track['track_rowid']}", on_end)

    async def _pause_timer(self, device_id: str, st: _DeviceState, port) -> None:
        await asyncio.sleep(self._pause_timeout_s)
        if self._devices.get(device_id) is st and port.is_paused():
            await self._close(st, "pause_timeout", port.position_ms())
            await port.stop()
            st.timed_out = True

    async def call(self, capability, args, target, port) -> Result:
        if target is None:
            return Result(False, say="No speaker is online.", error="no_target")
        if port is None:
            return Result(False, say="That speaker isn't connected.", error="no_port")
        dev = target
        if capability == "music.play":
            return await self._play(dev, args, port)
        st = self._devices.get(dev)
        if st is None:
            if capability == "music.now_playing":
                return Result(True, say="Nothing is playing right now.")
            return Result(False, say="Nothing is playing right now.", error="idle")
        if capability == "music.control":
            return await self._control(dev, st, args.get("action"), port)
        if capability == "music.rate":
            rating = args.get("rating")
            value = {"up": 1, "down": -1, "clear": None}[rating]
            try:
                await asyncio.to_thread(self._client.rate, st.tracks[st.index]["track_rowid"], value)
            except MuseUnavailable:
                return Result(False, say="Muse isn't answering.", error="muse_unavailable")
            say = {"up": "Noted, you like this one.", "down": "Noted, you don't like this one.",
                   "clear": "Rating cleared."}[rating]
            return Result(True, say=say)
        if capability == "music.now_playing":
            t = st.tracks[st.index]
            say = f"This is {t['track_name']} by {t['artist_name']}."
            if st.timed_out or port.is_paused():
                say += " It's paused."
            return Result(True, say=say)
        return Result(False, error="unknown_capability")

    async def _play(self, dev: str, args: dict, port) -> Result:
        artist, title = args.get("artist"), args.get("title")
        mood, genre = args.get("mood"), args.get("genre")
        if not (artist or title or mood or genre):
            return Result(False, say="What should I play?", error="no_slots")
        count = min(max(args.get("count") or DEFAULT_QUEUE_LEN, 1), MAX_QUEUE_LEN)
        text = vibe = None
        try:
            if title or artist:
                q = " ".join(s for s in (title, artist) if s)
                text = await asyncio.to_thread(self._client.search_text, q, limit=MAX_QUEUE_LEN)
            if mood or genre:
                q = " ".join(s for s in (mood, genre) if s)
                vibe = await asyncio.to_thread(self._client.search_vibe, q, n=200)
        except MuseUnavailable:
            return Result(False, say="Muse isn't answering.", error="muse_unavailable")
        queue = compose_queue(text, vibe, artist, count)
        if not queue:
            return Result(False, say="I couldn't find anything like that.", error="empty")
        old = self._devices.get(dev)
        if old is not None:
            pos = port.position_ms()
            await port.stop()
            await self._close(old, "new_selection", pos)
            self._cancel_timer(old)
        st = _DeviceState(tracks=queue, port=port)
        self._devices[dev] = st
        await self._start(dev, st, port, 0)
        first = queue[0]
        return Result(True, say=f"Playing {first['track_name']} by {first['artist_name']}.",
                      data={"queue": [t["track_rowid"] for t in queue]})

    async def _control(self, dev: str, st: _DeviceState, action: str, port) -> Result:
        if action == "pause":
            await port.pause()
            self._cancel_timer(st)
            st.timer = asyncio.create_task(self._pause_timer(dev, st, port))
        elif action == "resume":
            self._cancel_timer(st)
            if st.timed_out:
                await self._start(dev, st, port, st.index)
            else:
                await port.resume()
        elif action in ("skip", "previous"):
            pos = port.position_ms()
            self._cancel_timer(st)
            await port.stop()
            await self._close(st, "user_next" if action == "skip" else "user_prev", pos)
            if action == "previous":
                await self._start(dev, st, port, max(st.index - 1, 0))
            elif st.index + 1 < len(st.tracks):
                await self._start(dev, st, port, st.index + 1)
            else:
                self._clear(dev)
                return Result(True, say="That's the end of the queue.")
        elif action == "shuffle_on":
            st.shuffle = True
            rest = st.tracks[st.index + 1:]
            self._rng.shuffle(rest)
            st.tracks[st.index + 1:] = rest
        elif action == "shuffle_off":
            st.shuffle = False
        return Result(True)
