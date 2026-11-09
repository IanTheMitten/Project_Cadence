"""Tests for Core.submit, announce, pending-question answers and the schedule tick."""

import asyncio
import time

import pytest

from cadence.core import Core, KEPT_SAY, LEAVE_SAY, REPLACED_SAY, TURN_LOCK, greeting_for
from cadence.decisionlog import DecisionLog
from cadence.events import utterance
from cadence.schedules import PendingQuestion, PendingQuestions, ScheduleStore

D0 = 1799971200.0  # 2027-01-15 00:00 UTC
H = 3600.0


@pytest.fixture(autouse=True)
def utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


class FakeHub:
    def __init__(self, connected):
        self.connected = connected
        self.sent = []

    async def send(self, peer_id, msg):
        if peer_id not in self.connected:
            return False
        self.sent.append((peer_id, msg))
        return True

    def targets(self, target):
        if target in self.connected:
            return [target]
        return [p for p, room in self.connected.items() if target is None or room == target]


class FakePipeline:
    def __init__(self, reply="done", hook=None, raises=None):
        self.reply = reply
        self.hook = hook
        self.raises = raises
        self.calls = []

    async def handle(self, event, out, timer=None):
        self.calls.append((event, timer))
        if self.raises:
            raise self.raises
        await out.ack("action")
        await out.say(self.reply)
        if self.hook:
            await self.hook(event)


class Env:
    def __init__(self, tmp_path, connected=None, **pipeline_kw):
        self.now = [D0 + 7 * H]
        self.hub = FakeHub(connected if connected is not None else {"speaker-1": "bedroom"})
        self.pipeline = FakePipeline(**pipeline_kw)
        self.log = DecisionLog(str(tmp_path / "l.db"))
        self.store = ScheduleStore(str(tmp_path / "l.db"))
        self.pending = PendingQuestions()
        self.core = Core(self.pipeline, self.hub, self.log, self.store, self.pending,
                         clock=lambda: self.now[0], question_ttl_s=0.05)

    def msgs(self, peer="speaker-1"):
        return [m for p, m in self.hub.sent if p == peer]


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def ev(text="hi"):
    return utterance("speaker-1", "bedroom", text)


def seed_question(env):
    old = env.store.add("07:00", "daily", False, "old", "bedroom", env.now[0] - H)
    new = {"time_": "07:05", "repeat": "once", "greeting": False,
           "command": "play jazz", "room": "bedroom"}
    env.pending.ask(PendingQuestion("schedule_conflict", "speaker-1", new,
                                    [old.id], env.now[0] + 60))
    return old


def ask_hook(holder):
    async def hook(event):
        e = holder[0]
        e.pending.ask(PendingQuestion("schedule_conflict", "speaker-1", {}, [], e.now[0] + 60))
    return hook


async def test_submit_order(env):
    await env.core.submit(ev())
    assert env.msgs() == [{"type": "turn_start"}, {"type": "ack", "category": "action"},
                          {"type": "say", "text": "done"}, {"type": "turn_end"}]


async def test_submit_pipeline_error(tmp_path):
    e = Env(tmp_path, raises=RuntimeError("boom"))
    await e.core.submit(ev())
    m = e.msgs()
    assert [x["type"] for x in m] == ["turn_start", "error", "turn_end"]
    assert "boom" in m[1]["message"]


async def test_submit_waits_for_turn_lock(env):
    await TURN_LOCK.acquire()
    try:
        task = asyncio.create_task(env.core.submit(ev()))
        await asyncio.sleep(0.05)
        assert env.pipeline.calls == []
    finally:
        TURN_LOCK.release()
    await task
    assert len(env.pipeline.calls) == 1


async def test_submit_timing(env, capsys):
    await env.core.submit(ev(), timing={"speech_end": 500.0, "asr_done": 100.0})
    timer = env.pipeline.calls[0][1]
    assert 350 < timer.durations()["asr"] < 450
    assert "turn_timing " in capsys.readouterr().err


async def test_submit_listen_after_pending_ask(tmp_path):
    holder = []
    e = Env(tmp_path, hook=ask_hook(holder))
    holder.append(e)
    await e.core.submit(ev())
    m = e.msgs()
    i = m.index({"type": "listen", "seconds": 8})
    assert m.index({"type": "say", "text": "done"}) < i < m.index({"type": "turn_end"})


async def test_answer_yes(env):
    old = seed_question(env)
    await env.core.submit(ev("yes"))
    assert env.pipeline.calls == []
    rows = env.store.get_all()
    assert old.id not in [s.id for s in rows]
    assert [(s.time, s.command) for s in rows] == [("07:05", "play jazz")]
    assert {"type": "say", "text": REPLACED_SAY} in env.msgs()
    row = env.log.recent(1)[0]
    assert row["decider"] == "pending"
    assert row["route"] == "schedule_conflict"


async def test_answer_no(env):
    old = seed_question(env)
    await env.core.submit(ev("no"))
    assert [s.id for s in env.store.get_all()] == [old.id]
    assert {"type": "say", "text": KEPT_SAY} in env.msgs()


async def test_answer_unclear(env):
    old = seed_question(env)
    await env.core.submit(ev("what?"))
    assert [s.id for s in env.store.get_all()] == [old.id]
    assert {"type": "say", "text": "I'll leave your schedules as they are."} in env.msgs()
    assert env.pending.peek("speaker-1") is None


async def test_question_expires(tmp_path):
    holder = []
    e = Env(tmp_path, hook=ask_hook(holder))
    holder.append(e)
    await e.core.submit(ev())
    await asyncio.sleep(0.2)
    assert {"type": "say", "text": LEAVE_SAY} in e.msgs("speaker-1")
    assert e.pending.peek("speaker-1") is None


MULTI = {"b1": "bedroom", "b2": "bedroom", "k1": "kitchen"}


async def test_announce_device(tmp_path):
    e = Env(tmp_path, MULTI)
    assert await e.core.announce("k1", "hi") == 1
    assert e.hub.sent == [("k1", {"type": "say", "text": "hi"})]


async def test_announce_room(tmp_path):
    e = Env(tmp_path, MULTI)
    assert await e.core.announce("bedroom", "hi") == 2
    assert sorted(p for p, _ in e.hub.sent) == ["b1", "b2"]


async def test_announce_all(tmp_path):
    e = Env(tmp_path, MULTI)
    assert await e.core.announce(None, "hi") == 3


async def test_announce_nobody(tmp_path):
    e = Env(tmp_path, {})
    assert await e.core.announce(None, "hi") == 0
    assert e.hub.sent == []


def add_sched(e, repeat="daily", greeting=True, command="play jazz"):
    return e.store.add("07:00", repeat, greeting, command, "bedroom", D0 + 6 * H)


async def test_tick_daily(tmp_path):
    e = Env(tmp_path, MULTI)
    s = add_sched(e)
    assert greeting_for(e.now[0]) == "Good morning."
    assert await e.core.tick() == [s.id]
    for p in ("b1", "b2"):
        assert {"type": "say", "text": "Good morning."} in e.msgs(p)
    assert e.msgs("k1") == []
    event = e.pipeline.calls[0][0]
    assert (event.kind, event.source, event.room) == ("schedule", "scheduler", "bedroom")
    assert event.payload == {"text": "play jazz", "schedule_id": s.id}
    assert e.store.get_all()[0].next_at == s.next_at + 86400


async def test_tick_once_deleted(tmp_path):
    e = Env(tmp_path, MULTI)
    s = add_sched(e, repeat="once")
    assert await e.core.tick() == [s.id]
    assert e.store.get_all() == []


async def test_tick_missed(tmp_path, capsys):
    e = Env(tmp_path, MULTI)
    add_sched(e, repeat="once")
    e.now[0] += 301
    assert await e.core.tick() == []
    assert e.pipeline.calls == []
    assert e.hub.sent == []
    assert "missed" in capsys.readouterr().err
    assert e.store.get_all() == []


async def test_tick_pipeline_error(tmp_path):
    e = Env(tmp_path, MULTI, raises=RuntimeError("boom"))
    s = add_sched(e)
    assert await e.core.tick() == [s.id]
    assert {"type": "say", "text": "Good morning."} in e.msgs("b1")
    assert e.store.get_all()[0].next_at == s.next_at + 86400


async def test_tick_say_goes_to_room_without_ack(tmp_path):
    e = Env(tmp_path, MULTI)
    add_sched(e, greeting=False)
    await e.core.tick()
    assert e.msgs("b1") == [{"type": "say", "text": "done"}]
    assert e.msgs("b2") == [{"type": "say", "text": "done"}]
    assert e.msgs("k1") == []
