"""Tests for RemotePort and MuseAdapter (plan task 13). No network."""

from cadence_muse.client import MuseUnavailable
from cadence_muse.adapter import MuseAdapter
from cadence_muse.music import ABILITIES, MusicPlugin
from cadence_muse.protocol import hello
from cadence_muse.remote import RemotePort

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

    def contract_version(self):
        self._maybe_raise("contract_version")
        return self.version


def _three():
    return [_track(1, duration=111), _track(2, duration=222), _track(3, duration=333)]



def _port():
    sent, t = [], [10.0]

    async def send(msg):
        sent.append(msg)

    return RemotePort("speaker-1", send, clock=lambda: t[0]), sent, t


def _media(action, **extra):
    return {"type": "media", "device": "speaker-1", "action": action, **extra}


async def test_play_url_sends_media():
    port, sent, _ = _port()
    await port.play_url("http://p/1", None)
    assert sent == [_media("play_url", url="http://p/1")]
    assert port.is_paused() is False


async def test_pause_resume_send_and_toggle():
    port, sent, _ = _port()
    await port.play_url("http://p/1", None)
    await port.pause()
    assert sent[-1] == _media("pause")
    assert port.is_paused() is True
    await port.resume()
    assert sent[-1] == _media("resume")
    assert port.is_paused() is False


async def test_stop_calls_on_end_once():
    port, sent, _ = _port()
    ended = []

    async def on_end(reason):
        ended.append(reason)

    await port.play_url("http://p/1", on_end)
    await port.stop()
    assert sent[-1] == _media("stop")
    assert ended == ["stopped"]
    await port.stop()
    assert sent[-1] == _media("stop")
    assert len(sent) == 3
    assert ended == ["stopped"]


async def test_track_end_event_calls_on_end_and_sets_position():
    port, _, _ = _port()
    ended = []

    async def on_end(reason):
        ended.append(reason)

    await port.play_url("http://p/1", on_end)
    await port.on_media_event("track_end", 1234, "http://p/1")
    assert ended == ["track_end"]
    assert port.position_ms() == 1234


async def test_other_url_and_stopped_events_ignored():
    port, _, _ = _port()
    ended = []

    async def on_end(reason):
        ended.append(reason)

    await port.play_url("http://p/1", on_end)
    await port.on_media_event("track_end", 5, "http://p/other")
    await port.on_media_event("stopped", 5, "http://p/1")
    assert ended == []


async def test_position_estimate_with_pause():
    port, _, t = _port()
    await port.play_url("http://p/1", None)
    t[0] = 12.5
    assert port.position_ms() == 2500
    t[0] = 13.0
    await port.pause()
    t[0] = 20.0
    assert port.position_ms() == 3000
    await port.resume()
    t[0] = 21.0
    assert port.position_ms() == 4000


# --- MuseAdapter ---

def _adapter(muse, plugin=None):
    sent = []

    async def send(msg):
        sent.append(msg)

    return MuseAdapter(plugin or MusicPlugin(muse), send), sent


def _muse():
    return FakeMuse(vibe=[_vibe(t, 1.0 - i / 10) for i, t in enumerate(_three())])


_CALL = {"type": "call", "call_id": "c1", "capability": "music.play",
         "args": {"mood": "chill"}, "target": "speaker-1"}


async def test_play_call_sends_media_result_state():
    adapter, sent = _adapter(_muse())
    await adapter.handle(_CALL)
    assert [m["type"] for m in sent] == ["media", "result", "state"]
    assert sent[0]["device"] == "speaker-1" and sent[0]["action"] == "play_url"
    res = sent[1]
    assert res["call_id"] == "c1" and res["ok"] is True
    assert res["say"].startswith("Playing ")
    assert res["data"] == {"queue": [1, 2, 3]}
    assert res["error"] is None
    assert sent[2]["state"]["now_playing"]["speaker-1"]["paused"] is False


async def test_unavailable_plugin_result():
    muse = _muse()
    plugin = MusicPlugin(muse)
    adapter, sent = _adapter(muse, plugin)
    muse.version = "2.0"
    plugin.check()
    await adapter.handle(_CALL)
    res = next(m for m in sent if m["type"] == "result")
    assert res["ok"] is False
    assert res["error"] == "muse_unavailable"
    assert res["say"] == "Muse isn't answering."


async def test_track_end_media_event_plays_next():
    adapter, sent = _adapter(_muse())
    await adapter.handle(_CALL)
    first = sent[0]["url"]
    sent.clear()
    await adapter.handle({"type": "media_event", "device": "speaker-1",
                          "event": "track_end", "position_ms": 111, "url": first})
    plays = [m for m in sent if m["type"] == "media" and m["action"] == "play_url"]
    assert len(plays) == 1 and plays[0]["url"] != first
    assert plays[0]["url"].endswith("/play/2")
    assert sent[-1]["type"] == "state"


def test_hello():
    adapter, _ = _adapter(_muse())
    assert adapter.hello() == hello("muse", "service", "music", None, [], ABILITIES)
