"""Tests for compose_queue and MusicPlugin (I14). No network: FakeMuse and FakePort."""

import asyncio

from cadence.muse.client import MuseUnavailable
from cadence.plugins.registry import Device
from cadence.plugins.music import MusicPlugin, compose_queue

DEVICE = Device("speaker-1", "speaker", "bedroom", True)


def _track(rowid, name=None, artist="Artist", artists=None, playable=True, duration=1000):
    return {
        "track_rowid": rowid,
        "track_name": name or f"Track {rowid}",
        "artist_name": artist,
        "artist_names": artists if artists is not None else [artist],
        "duration_ms": duration,
        "playable": playable,
    }


def _vibe(track, score):
    return {"track_rowid": track["track_rowid"], "score": score, "track": track}


class FakeMuse:
    proxy_url = "http://proxy"

    def __init__(self, text=None, vibe=None, version=None):
        self.text = text or []
        self.vibe = vibe or []
        self.version = version
        self.raise_on = set()
        self.calls = []
        self.opened = []
        self.closed = []
        self.rated = []
        self._next_id = 100

    def _maybe_raise(self, name):
        self.calls.append(name)
        if name in self.raise_on:
            raise MuseUnavailable(name)

    def search_text(self, q, limit=None):
        self._maybe_raise("search_text")
        return self.text

    def search_vibe(self, q, n=None):
        self._maybe_raise("search_vibe")
        self.vibe_args = (q, n)
        return self.vibe

    def open_play(self, track_rowid, duration_ms, source=None):
        self._maybe_raise("open_play")
        self._next_id += 1
        self.opened.append((track_rowid, duration_ms, source))
        return self._next_id

    def close_play(self, play_id, ended_reason, position_ms=None):
        self._maybe_raise("close_play")
        self.closed.append((play_id, ended_reason, position_ms))

    def rate(self, track_rowid, rating):
        self._maybe_raise("rate")
        self.rated.append((track_rowid, rating))

    def contract_version(self):
        self._maybe_raise("contract_version")
        return self.version


class FakePort:
    def __init__(self):
        self.urls = []
        self.on_end = None
        self.position_ms_value = 0
        self.paused = False
        self.stopped = 0

    async def play_url(self, url, on_end):
        self.urls.append(url)
        self.on_end = on_end
        self.paused = False

    async def pause(self):
        self.paused = True

    async def resume(self):
        self.paused = False

    async def stop(self, reason="stopped"):
        self.stopped += 1
        self.paused = False

    def position_ms(self):
        return self.position_ms_value

    def is_paused(self):
        return self.paused


def _three():
    return [_track(1, duration=111), _track(2, duration=222), _track(3, duration=333)]


def _setup(tracks=None, **kw):
    muse = FakeMuse(vibe=[_vibe(t, 1.0 - i / 10) for i, t in enumerate(_three() if tracks is None else tracks)])
    plugin = MusicPlugin(muse, **kw)
    return muse, plugin, FakePort()


async def _play(plugin, port, **args):
    return await plugin.call("music.play", args or {"mood": "chill"}, DEVICE, port)


# --- compose_queue ---

def test_compose_artist_filter_case_insensitive():
    text = [
        _track(1, artist="Justin Bieber"),
        _track(2, artist="Other", artists=["Other", "JUSTIN bieber"]),
        _track(3, artist="Nobody"),
    ]
    out = compose_queue(text, None, "justin BIEBER", 10)
    assert [t["track_rowid"] for t in out] == [1, 2]


def test_compose_text_and_vibe_ordering():
    text = [_track(1), _track(2), _track(3), _track(4)]
    vibe = [_vibe(text[2], 0.9), _vibe(text[0], 0.5), _vibe(_track(9), 0.99)]
    out = compose_queue(text, vibe, None, 10)
    assert [t["track_rowid"] for t in out] == [3, 1, 2, 4]


def test_compose_drops_unplayable():
    text = [_track(1), _track(2, playable=False), _track(3)]
    out = compose_queue(text, None, None, 10)
    assert [t["track_rowid"] for t in out] == [1, 3]


def test_compose_dedupe_and_count_cap():
    text = [_track(1), _track(1), _track(2), _track(3)]
    out = compose_queue(text, None, None, 2)
    assert [t["track_rowid"] for t in out] == [1, 2]


# --- plugin ---

async def test_play_no_slots():
    muse, plugin, port = _setup()
    r = await plugin.call("music.play", {}, DEVICE, port)
    assert (r.ok, r.say, r.error) == (False, "What should I play?", "no_slots")


async def test_play_mood():
    muse, plugin, port = _setup()
    r = await _play(plugin, port, mood="chill")
    assert muse.vibe_args == ("chill", 200)
    assert port.urls == ["http://proxy/play/1"]
    assert muse.opened == [(1, 111, "cadence")]
    assert r.ok and r.say == "Playing Track 1 by Artist."


async def test_play_muse_unavailable():
    muse, plugin, port = _setup()
    muse.raise_on.add("search_vibe")
    r = await _play(plugin, port)
    assert (r.ok, r.say, r.error) == (False, "Muse isn't answering.", "muse_unavailable")


async def test_play_empty():
    muse, plugin, port = _setup(tracks=[])
    r = await _play(plugin, port)
    assert (r.ok, r.say, r.error) == (False, "I couldn't find anything like that.", "empty")


async def test_new_play_closes_new_selection():
    muse, plugin, port = _setup()
    await _play(plugin, port)
    port.position_ms_value = 500
    await _play(plugin, port)
    assert muse.closed == [(101, "new_selection", 500)]
    assert port.stopped == 1


async def test_track_end_starts_next_then_clears():
    muse, plugin, port = _setup(tracks=[_track(1), _track(2)])
    await _play(plugin, port)
    port.position_ms_value = 900
    await port.on_end("track_end")
    assert muse.closed == [(101, "track_end", 900)]
    assert port.urls[-1] == "http://proxy/play/2"
    await port.on_end("track_end")
    assert muse.closed[-1][1] == "track_end"
    assert plugin.now_playing("speaker-1") is None


async def test_lost_closes_lost():
    muse, plugin, port = _setup()
    await _play(plugin, port)
    await port.on_end("lost")
    assert muse.closed[0][:2] == (101, "lost")
    assert plugin.now_playing("speaker-1") is None


async def test_skip_and_end_of_queue():
    muse, plugin, port = _setup(tracks=[_track(1), _track(2)])
    await _play(plugin, port)
    r = await plugin.call("music.control", {"action": "skip"}, DEVICE, port)
    assert muse.closed[0][:2] == (101, "user_next")
    assert port.urls[-1] == "http://proxy/play/2"
    assert r.ok
    r = await plugin.call("music.control", {"action": "skip"}, DEVICE, port)
    assert muse.closed[1][:2] == (102, "user_next")
    assert r.say == "That's the end of the queue."
    assert plugin.now_playing("speaker-1") is None


async def test_previous_closes_user_prev():
    muse, plugin, port = _setup()
    await _play(plugin, port)
    await plugin.call("music.control", {"action": "skip"}, DEVICE, port)
    await plugin.call("music.control", {"action": "previous"}, DEVICE, port)
    assert muse.closed[-1][:2] == (102, "user_prev")
    assert port.urls[-1] == "http://proxy/play/1"


async def test_pause_timeout_and_resume():
    muse, plugin, port = _setup(pause_timeout_s=0.01)
    await _play(plugin, port)
    await plugin.call("music.control", {"action": "pause"}, DEVICE, port)
    await asyncio.sleep(0.05)
    assert muse.closed[0][:2] == (101, "pause_timeout")
    assert port.stopped == 1
    await plugin.call("music.control", {"action": "resume"}, DEVICE, port)
    assert port.urls == ["http://proxy/play/1", "http://proxy/play/1"]


async def test_control_idle():
    muse, plugin, port = _setup()
    r = await plugin.call("music.control", {"action": "pause"}, DEVICE, port)
    assert (r.ok, r.say, r.error) == (False, "Nothing is playing right now.", "idle")


async def test_rate_up():
    muse, plugin, port = _setup()
    await _play(plugin, port)
    r = await plugin.call("music.rate", {"rating": "up"}, DEVICE, port)
    assert muse.rated == [(1, 1)]
    assert r.say == "Noted, you like this one."


async def test_now_playing_text():
    muse, plugin, port = _setup()
    await _play(plugin, port)
    r = await plugin.call("music.now_playing", {}, DEVICE, port)
    assert r.ok and r.say == "This is Track 1 by Artist."
    await plugin.call("music.control", {"action": "pause"}, DEVICE, port)
    r = await plugin.call("music.now_playing", {}, DEVICE, port)
    assert r.say == "This is Track 1 by Artist. It's paused."


def test_check_versions():
    assert MusicPlugin(FakeMuse(version=None)).check() is True
    assert MusicPlugin(FakeMuse(version="1.0")).check() is True
    assert MusicPlugin(FakeMuse(version="2.0")).check() is False
    down = FakeMuse()
    down.raise_on.add("contract_version")
    assert MusicPlugin(down).check() is False


async def test_open_play_unavailable_still_plays():
    muse, plugin, port = _setup()
    muse.raise_on.add("open_play")
    r = await _play(plugin, port)
    assert r.ok
    assert port.urls == ["http://proxy/play/1"]


async def test_no_port():
    muse, plugin, port = _setup()
    r = await plugin.call("music.play", {"mood": "chill"}, DEVICE, None)
    assert (r.ok, r.say, r.error) == (False, "That speaker isn't connected.", "no_port")


def test_available_rechecks_after_30s():
    now = [0.0]
    muse = FakeMuse(version="1.0")
    muse.raise_on.add("contract_version")
    plugin = MusicPlugin(muse, clock=lambda: now[0])
    assert plugin.check() is False
    n = muse.calls.count("contract_version")
    now[0] = 29.0
    assert plugin.available() is False
    assert muse.calls.count("contract_version") == n
    muse.raise_on.clear()
    now[0] = 30.0
    assert plugin.available() is True
    assert muse.calls.count("contract_version") == n + 1
