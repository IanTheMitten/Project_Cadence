import dataclasses
import json

import pytest

from cadence.events import utterance, Event, Call, Decision, DEFAULT_USER
from cadence.plugins.registry import Device, DeviceRegistry
from cadence.plugins.base import Capability, Manifest, Result, Plugin
from cadence.catalogue import Catalogue, CHAT, CORRECTION, BUILTINS
from cadence.resolver import resolve
from cadence.deciders.base import Decider, DeciderUnavailable, UnavailableDecider


def cap(name, target=None):
    return Capability(name=name, description=name,
                      parameters={"type": "object", "properties": {}}, target=target)


class FakePlugin(Plugin):
    def __init__(self, pid, names, avail=True):
        self.manifest = Manifest(id=pid, kind="service",
                                 capabilities=tuple(cap(n) for n in names))
        self._avail = avail

    async def call(self, capability, args, target, event):
        return Result(True)

    def available(self):
        return self._avail


def test_utterance_fields():
    e = utterance("speaker-1", "bedroom", "hi")
    assert e.kind == "utterance"
    assert e.user_id == "household" == DEFAULT_USER
    assert e.payload == {"text": "hi", "asr_conf": None}
    assert len(e.id) == 32
    int(e.id, 16)
    assert utterance("speaker-1", "bedroom", "hi").id != e.id


def test_event_frozen():
    e = utterance("s", None, "hi")
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.room = "x"


def test_decision_defaults():
    d = Decision(decider="none", route=None, calls=[])
    assert d.candidates == {}
    assert d.escalation is None


def test_registry_from_file(tmp_path):
    p = tmp_path / "d.json"
    p.write_text(json.dumps({"devices": [
        {"id": "a", "kind": "speaker", "room": "bedroom"},
        {"id": "b", "kind": "speaker", "room": "kitchen"}]}))
    reg = DeviceRegistry.from_file(str(p))
    assert reg.get("a").room == "bedroom"
    assert reg.get("a").online is False
    assert reg.get("b").online is False
    assert DeviceRegistry.from_file(str(tmp_path / "missing.json")).rooms() == []
    assert DeviceRegistry.from_file(str(tmp_path / "missing.json")).find(
        "speaker", online_only=False) == []


def test_set_online_unknown_adds():
    reg = DeviceRegistry([])
    d = reg.set_online("new", True)
    assert d.room is None
    assert d.online is True
    assert reg.get("new") is d


def test_find_room_and_online_only():
    reg = DeviceRegistry([
        Device("a", "speaker", "bedroom"),
        Device("b", "speaker", "kitchen"),
        Device("c", "speaker", "bedroom"),
    ])
    reg.set_online("a", True)
    assert [d.id for d in reg.find("speaker", "bedroom")] == ["a"]
    assert [d.id for d in reg.find("speaker", "bedroom", online_only=False)] == ["a", "c"]
    assert reg.find("speaker", "kitchen") == []
    assert [d.id for d in reg.find("speaker")] == ["a"]
    assert [d.id for d in reg.find("speaker", online_only=False)] == ["a", "b", "c"]


def test_rooms_sorted_unique():
    reg = DeviceRegistry([
        Device("a", "speaker", "kitchen"),
        Device("b", "speaker", "bedroom"),
        Device("c", "speaker", "kitchen"),
        Device("d", "speaker", None),
    ])
    assert reg.rooms() == ["bedroom", "kitchen"]


def test_catalogue_available_order_and_exclusion():
    p1 = FakePlugin("p1", ["a", "b"])
    p2 = FakePlugin("p2", ["c"])
    p3 = FakePlugin("p3", ["z"], avail=False)
    cat = Catalogue([p1, p2, p3])
    assert [c.name for c in cat.available()] == ["a", "b", "c", "chat", "correction"]
    assert cat.get("a").name == "a"


def test_catalogue_duplicates_raise():
    with pytest.raises(ValueError):
        Catalogue([FakePlugin("p1", ["a"]), FakePlugin("p2", ["a"])])
    with pytest.raises(ValueError):
        Catalogue([FakePlugin("p1", ["chat"])])


def test_catalogue_add_remove():
    cat = Catalogue([])
    p = FakePlugin("p1", ["a", "b"])
    cat.add(p)
    assert cat.get("a") is not None and cat.plugin_for("b") is p
    assert [c.name for c in cat.available()] == ["a", "b", "chat", "correction"]
    with pytest.raises(ValueError):
        cat.add(FakePlugin("p2", ["b"]))
    with pytest.raises(ValueError):
        cat.add(FakePlugin("p3", ["chat"]))
    cat.remove(p)
    assert cat.get("a") is None and cat.plugin_for("b") is None
    assert [c.name for c in cat.available()] == ["chat", "correction"]
    cat.remove(p)


def test_set_online_sets_room():
    reg = DeviceRegistry([])
    assert reg.set_online("d1", True, room="bedroom").room == "bedroom"
    assert reg.set_online("d1", True).room == "bedroom"
    assert reg.set_online("d1", True, room="kitchen").room == "kitchen"


def test_catalogue_builtins():
    p1 = FakePlugin("p1", ["a"])
    cat = Catalogue([p1])
    assert cat.plugin_for("chat") is None
    assert cat.plugin_for("unknown") is None
    assert cat.plugin_for("a") is p1
    assert cat.get("chat") is CHAT
    assert cat.get("correction") is CORRECTION
    assert BUILTINS == (CHAT, CORRECTION)


def _reg():
    reg = DeviceRegistry([
        Device("s-bed", "speaker", "bedroom"),
        Device("s-kit", "speaker", "kitchen"),
        Device("s-liv", "speaker", "living"),
    ])
    return reg


def _ev(source="s-liv", room=None):
    return utterance(source, room, "x")


def test_resolve_untargeted():
    assert resolve(Call("c", {}), cap("c"), _ev(), _reg()) == [None]


def test_resolve_args_room_wins():
    reg = _reg()
    for i in ("s-bed", "s-kit", "s-liv"):
        reg.set_online(i, True)
    out = resolve(Call("c", {"room": "kitchen"}), cap("c", "speaker"),
                  _ev("s-liv", "bedroom"), reg)
    assert [d.id for d in out] == ["s-kit"]


def test_resolve_event_room():
    reg = _reg()
    for i in ("s-bed", "s-kit", "s-liv"):
        reg.set_online(i, True)
    out = resolve(Call("c", {}), cap("c", "speaker"), _ev("s-liv", "bedroom"), reg)
    assert [d.id for d in out] == ["s-bed"]


def test_resolve_source_device():
    reg = _reg()
    for i in ("s-bed", "s-kit", "s-liv"):
        reg.set_online(i, True)
    out = resolve(Call("c", {}), cap("c", "speaker"), _ev("s-liv", None), reg)
    assert [d.id for d in out] == ["s-liv"]


def test_resolve_all_online():
    reg = _reg()
    reg.set_online("s-bed", True)
    reg.set_online("s-kit", True)
    out = resolve(Call("c", {}), cap("c", "speaker"), _ev("s-liv", None), reg)
    assert [d.id for d in out] == ["s-bed", "s-kit"]


def test_resolve_none_online():
    assert resolve(Call("c", {}), cap("c", "speaker"), _ev("s-liv", None), _reg()) == []


async def test_unavailable_decider_raises():
    d = UnavailableDecider("x")
    assert isinstance(d, Decider)
    with pytest.raises(DeciderUnavailable):
        await d.decide(_ev(), {}, [])
