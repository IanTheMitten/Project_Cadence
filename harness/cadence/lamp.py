"""light.preset: named lamp settings Jev can pick on its own (closed choice), mapped here to exact light.set duty.

The lamp firmware exposes only raw light.set {cool, warm}; letting the LLM fill those numbers copied stale values
from chat history ("turn off" became 30/30). Presets keep the common requests deterministic and LLM-free.
"""
from __future__ import annotations

from cadence.catalogue import Catalogue
from cadence.plugins.base import Capability, Manifest, Plugin, Result

# preset -> (cool %, warm %)
PRESETS: dict[str, tuple[int, int]] = {
    "off": (0, 0),
    "on": (100, 100),
    "bright": (100, 100),
    "warm": (0, 100),
    "cool": (100, 0),
    "dim": (15, 15),
    "night": (0, 5),
}
_CHOICES = {
    "off": "turn the light off",
    "on": "turn the light on",
    "bright": "full brightness, brighter, max",
    "warm": "warm or yellow light only",
    "cool": "cool or white or daylight only",
    "dim": "dim, darker, low light",
    "night": "night light, barely on, very dim warm",
}
LIGHT_PRESET = Capability(
    "light.preset",
    "Turn the ceiling lamp off or on, or to a named setting: bright, warm, cool, dim, night. "
    "Use this unless the user gives exact percentages.",
    {"type": "object", "properties": {"preset": {"type": "string", "enum": list(PRESETS)}},
     "required": ["preset"]},
    closed_args={"preset": _CHOICES},
    free_args=(),
    target="lamp")


class LampPresetPlugin(Plugin):
    manifest = Manifest("lamp_preset", "service", (LIGHT_PRESET,))

    def __init__(self, catalogue: Catalogue) -> None:
        self._catalogue = catalogue

    def available(self) -> bool:
        return self._catalogue.plugin_for("light.set") is not None

    async def call(self, capability, args, target, event) -> Result:
        duty = PRESETS.get(args.get("preset"))
        if duty is None:
            return Result(False, say="I didn't catch the light setting.", error="bad_preset")
        lamp = self._catalogue.plugin_for("light.set")  # shortcut: one lamp; a second needs per-device routing
        if lamp is None:
            return Result(False, say="The lamp isn't connected.", error="no_lamp")
        return await lamp.call("light.set", {"cool": duty[0], "warm": duty[1]}, target, event)
