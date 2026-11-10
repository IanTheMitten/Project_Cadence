"""Tests for light.preset: Jev picks a named setting, the harness maps it to exact light.set duty."""

from cadence.catalogue import Catalogue
from cadence.events import utterance
from cadence.lamp import LIGHT_PRESET, PRESETS, LampPresetPlugin
from cadence.plugins.base import Capability, Manifest, Plugin, Result


class FakeLamp(Plugin):
    manifest = Manifest("lamp", "device", (Capability("light.set", "d", {}, target="lamp"),))

    def __init__(self):
        self.calls = []

    async def call(self, capability, args, target, event):
        self.calls.append((capability, args, target))
        return Result(True)


EV = utterance("chat-1", "bedroom", "turn off the light")


async def test_preset_maps_to_exact_light_set():
    cat = Catalogue([])
    lamp = FakeLamp()
    cat.add(lamp)
    preset = LampPresetPlugin(cat)
    r = await preset.call("light.preset", {"preset": "off"}, "dev", EV)
    assert r.ok
    assert lamp.calls == [("light.set", {"cool": 0, "warm": 0}, "dev")]


async def test_preset_only_offered_while_a_lamp_is_connected():
    cat = Catalogue([])
    preset = LampPresetPlugin(cat)
    assert not preset.available()
    r = await preset.call("light.preset", {"preset": "on"}, None, EV)
    assert not r.ok and r.error == "no_lamp"
    cat.add(FakeLamp())
    assert preset.available()


async def test_unknown_preset_rejected():
    cat = Catalogue([])
    cat.add(FakeLamp())
    r = await LampPresetPlugin(cat).call("light.preset", {"preset": "disco"}, None, EV)
    assert not r.ok and r.error == "bad_preset"


def test_every_preset_is_a_closed_choice_for_jev():
    assert set(LIGHT_PRESET.closed_args["preset"]) == set(PRESETS)
    assert LIGHT_PRESET.free_args == ()
    assert all(0 <= v <= 100 for pair in PRESETS.values() for v in pair)
