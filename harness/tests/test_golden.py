import json
import os

import pytest

from cadence.catalogue import BUILTINS
from cadence.peers import capability_from_ability
from cadence.schedules import SchedulePlugin

HERE = os.path.join(os.path.dirname(__file__), "golden")
ABILITIES = json.load(open(os.path.join(HERE, "abilities.json")))


def test_ability_names():
    assert [a["name"] for a in ABILITIES] == [
        "music.play", "music.control", "music.rate", "music.now_playing", "speaker.volume"]


def test_utterance_catalogue_covered():
    known = {a["name"] for a in ABILITIES} | {c.name for c in SchedulePlugin.manifest.capabilities} \
        | {c.name for c in BUILTINS}
    assert set(json.load(open(os.path.join(HERE, "utterances.json")))["catalogue"]) <= known


@pytest.mark.parametrize("a", ABILITIES, ids=lambda a: a["name"])
def test_ability_valid(a):
    capability_from_ability(a)
