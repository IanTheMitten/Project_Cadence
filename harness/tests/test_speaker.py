"""Tests for SpeakerPort and SpeakerPlugin (I15). No network or audio: httpx.MockTransport."""

import asyncio

import httpx
import numpy as np

from cadence.plugins.speaker import SpeakerPlugin, SpeakerPort


def _pcm(values):
    return np.array(values, dtype=np.int16).tobytes()


def _samples(data):
    return np.frombuffer(data, dtype=np.int16).tolist()


class Rig:
    def __init__(self, chunks, *, gate=None, error=None, gain=1.0):
        self.chunks = chunks
        self.gate = gate  # (index, asyncio.Event): wait before yielding chunks[index]
        self.error = error
        self.sent = []
        self.ends = []

        async def stream():
            for i, c in enumerate(self.chunks):
                if self.gate and self.gate[0] == i:
                    await self.gate[1].wait()
                yield c
            if self.error:
                raise self.error

        def handler(request):
            return httpx.Response(200, stream=_Stream(stream()))

        self.port = SpeakerPort(self._send, transport=httpx.MockTransport(handler), gain=gain)

    async def _send(self, data):
        self.sent.append(data)

    async def on_end(self, reason):
        self.ends.append(reason)

    @property
    def out(self):
        return b"".join(self.sent)

    async def play(self, url="http://x/a"):
        await self.port.play_url(url, self.on_end)


class _Stream(httpx.AsyncByteStream):
    def __init__(self, it):
        self._it = it

    async def __aiter__(self):
        async for c in self._it:
            yield c


async def _spin(n=50):
    for _ in range(n):
        await asyncio.sleep(0)


async def test_play_url_forwards_unchanged_then_track_end():
    chunks = [_pcm([1, 2, 3, 4]), _pcm([5, 6])]
    rig = Rig(chunks)
    await rig.play()
    await rig.port.drain()
    assert rig.out == b"".join(chunks)
    assert rig.ends == ["track_end"]


async def test_position_ms():
    chunks = [_pcm(range(100)), _pcm(range(50))]
    rig = Rig(chunks)
    await rig.play()
    await rig.port.drain()
    assert rig.port.position_ms() == int(300 / 176.4)


async def test_set_gain_halves_and_clamps():
    rig = Rig([_pcm([1000, -2000, 400, 8])], gain=1.0)
    rig.port.set_gain(0.5)
    assert rig.port.gain == 0.5
    await rig.play()
    await rig.port.drain()
    assert _samples(rig.out) == [500, -1000, 200, 4]
    rig.port.set_gain(2.0)
    assert rig.port.gain == 1.0


async def test_mute_sends_zeros():
    chunk = _pcm([1000, -2000, 300, 7])
    rig = Rig([chunk])
    rig.port.mute()
    assert rig.port.muted
    await rig.play()
    await rig.port.drain()
    assert rig.out == bytes(len(chunk))


async def test_odd_length_chunk_loses_no_bytes_at_half_gain():
    data = _pcm([100, 200, 300, 400])  # 8 bytes
    rig = Rig([data[:3], data[3:]], gain=0.5)
    await rig.play()
    await rig.port.drain()
    assert len(rig.out) == len(data)
    assert _samples(rig.out) == [50, 100, 150, 200]


async def test_stop_calls_on_end_stopped_once():
    rig = Rig([_pcm([1])], gate=(0, asyncio.Event()))
    await rig.play()
    await _spin()
    await rig.port.stop()
    await rig.port.stop()
    assert rig.ends == ["stopped"]


async def test_stop_passes_reason():
    rig = Rig([_pcm([1])], gate=(0, asyncio.Event()))
    await rig.play()
    await _spin()
    await rig.port.stop("lost")
    assert rig.ends == ["lost"]


async def test_stop_with_nothing_playing_is_noop():
    rig = Rig([])
    await rig.port.stop()
    assert rig.ends == []


async def test_second_play_url_stops_first():
    rig = Rig([_pcm([1])], gate=(0, asyncio.Event()))
    await rig.play("http://x/a")
    await _spin()
    await rig.play("http://x/b")
    assert rig.ends == ["stopped"]
    await rig.port.stop()


async def test_pause_stops_forwarding_until_resume():
    gate = asyncio.Event()
    c1, c2 = _pcm([1, 2]), _pcm([3, 4])
    rig = Rig([c1, c2], gate=(1, gate))
    await rig.play()
    await _spin()
    assert rig.out == c1
    await rig.port.pause()
    assert rig.port.is_paused()
    gate.set()
    await _spin()
    assert rig.out == c1
    await rig.port.resume()
    assert not rig.port.is_paused()
    await rig.port.drain()
    assert rig.out == c1 + c2
    assert rig.ends == ["track_end"]


async def test_speak_without_stream_sends_speech_unchanged():
    rig = Rig([])
    speech = _pcm([10, -20, 30, -40])
    await rig.port.speak(speech)
    assert rig.out == speech


async def test_read_error_reports_lost():
    rig = Rig([_pcm([1, 2])], error=httpx.ReadError("boom"))
    await rig.play()
    await rig.port.drain()
    assert rig.ends == ["lost"]


# plugin

def _plugin_port():
    sent = []

    async def send(b):
        sent.append(b)

    return SpeakerPort(send)


async def test_plugin_up_from_half_unmutes():
    port = _plugin_port()
    port.set_gain(0.5)
    port.mute()
    res = await SpeakerPlugin().call("speaker.volume", {"action": "up"}, None, port)
    assert res.ok
    assert abs(port.gain - 0.6) < 1e-9
    assert not port.muted
    assert res.data["muted"] is False


async def test_plugin_down_floors_at_zero():
    port = _plugin_port()
    port.set_gain(0.05)
    res = await SpeakerPlugin().call("speaker.volume", {"action": "down"}, None, port)
    assert res.ok
    assert port.gain == 0.0


async def test_plugin_mute_unmute():
    port = _plugin_port()
    plugin = SpeakerPlugin()
    await plugin.call("speaker.volume", {"action": "mute"}, None, port)
    assert port.muted
    await plugin.call("speaker.volume", {"action": "unmute"}, None, port)
    assert not port.muted


async def test_plugin_no_port():
    res = await SpeakerPlugin().call("speaker.volume", {"action": "up"}, None, None)
    assert not res.ok
    assert res.say == "That speaker isn't connected."
