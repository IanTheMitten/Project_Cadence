"""Tests for the schedule store, clash rule, yes/no parser, pending questions and SchedulePlugin."""

import time

import pytest

from cadence.events import utterance
from cadence.schedules import (
    SCHEDULE_ADD, SCHEDULE_CANCEL, PendingQuestion, PendingQuestions, Schedule, SchedulePlugin,
    ScheduleStore, classify_yes_no, clashes, next_occurrence, parse_hhmm,
)

D0 = 1799971200.0  # 2027-01-15 00:00 UTC
H = 3600.0


@pytest.fixture(autouse=True)
def utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture
def store(tmp_path):
    return ScheduleStore(str(tmp_path / "s.db"))


@pytest.mark.parametrize("raw,want", [
    ("07:00", "07:00"), ("7:05", "07:05"), ("23:59", "23:59"),
    ("24:00", None), ("7", None), (None, None), ("ab:cd", None),
])
def test_parse_hhmm(raw, want):
    assert parse_hhmm(raw) == want


def test_next_occurrence():
    assert next_occurrence("07:00", D0 + 6 * H) == D0 + 7 * H
    assert next_occurrence("07:00", D0 + 7 * H) == D0 + 7 * H + 86400
    assert next_occurrence("07:00", D0 + 8 * H) == D0 + 86400 + 7 * H


def test_store_add_due_advance_delete(store):
    s = store.add("07:00", "once", True, "play jazz", "bedroom", now=D0 + 6 * H)
    assert isinstance(s, Schedule)
    assert s.next_at == D0 + 7 * H
    assert store.due(D0 + 6 * H) == []
    assert [x.id for x in store.due(D0 + 7 * H)] == [s.id]
    assert [x.id for x in store.at_time("07:00")] == [s.id]
    store.advance(s.id, D0 + 7 * H + 10)  # once -> deleted
    assert store.get_all() == []

    d = store.add("07:00", "daily", True, None, None, now=D0 + 6 * H)
    store.advance(d.id, D0 + 7 * H + 10)
    assert store.get_all()[0].next_at == D0 + 86400 + 7 * H

    store.delete([d.id])
    assert store.get_all() == []


def test_conflicts(store):
    store.add("07:00", "daily", True, None, None, now=D0 + 6 * H)
    assert len(store.conflicts("07:10", "once", D0 + 6 * H)) == 1
    assert store.conflicts("07:16", "once", D0 + 6 * H) == []


def test_conflicts_across_midnight(store):
    store.add("23:55", "daily", True, None, None, now=D0 + 6 * H)
    assert len(store.conflicts("00:05", "once", D0 + 6 * H)) == 1


def test_conflicts_once_on_other_day(store):
    store.add("07:00", "once", True, None, None, now=D0 + 8 * H)  # next_at tomorrow
    assert store.conflicts("07:05", "once", D0 + 6 * H) == []


@pytest.mark.parametrize("text,want", [
    ("yes", "yes"), ("Yeah, delete it.", "yes"), ("no", "no"),
    ("no, don't delete it", "no"), ("keep the old one", "no"),
    ("what time is it", None), ("", None),
])
def test_classify_yes_no(text, want):
    assert classify_yes_no(text) == want


def test_pending_questions():
    pq = PendingQuestions()
    q = PendingQuestion("schedule_conflict", "speaker-1", {}, [1], expires_at=100.0)
    pq.ask(q)
    assert pq.peek("speaker-1") is q
    assert pq.take("speaker-1", 99.0) is q
    assert pq.peek("speaker-1") is None

    pq.ask(q)
    assert pq.take("speaker-1", 101.0) is None
    assert pq.peek("speaker-1") is None

    pq.ask(q)
    assert pq.drop(q) is True
    assert pq.drop(q) is False


def make(store):
    pending = PendingQuestions()
    plugin = SchedulePlugin(store, pending, clock=lambda: D0 + 6 * H)
    return plugin, pending, utterance("speaker-1", "bedroom", "x")


ADD = {"time": "07:00", "repeat": "daily", "greeting": True, "command": "play jazz"}


async def test_add_ok(store):
    plugin, _, ev = make(store)
    r = await plugin.call("schedule.add", dict(ADD), None, ev)
    assert r.ok is True
    assert r.say == "Okay, 07:00 every day."
    assert store.get_all()[0].room == "bedroom"


async def test_add_relative_minutes(store):
    # "turn off after one minute" was stored as 00:01; +N is a delay from now
    plugin = SchedulePlugin(store, PendingQuestions(), clock=lambda: D0 + 6 * H + 30)
    ev = utterance("speaker-1", "bedroom", "x")
    r = await plugin.call("schedule.add", {**ADD, "repeat": "once", "time": "+5"}, None, ev)
    assert r.ok is True
    s = store.get_all()[0]
    assert s.time == "06:05"
    assert s.next_at == D0 + 6 * H + 5 * 60


async def test_add_bad_time(store):
    plugin, _, ev = make(store)
    r = await plugin.call("schedule.add", {**ADD, "time": "7"}, None, ev)
    assert r.ok is False
    assert r.error == "bad_time"
    assert r.say == "I didn't catch the time."


async def test_add_empty(store):
    plugin, _, ev = make(store)
    r = await plugin.call("schedule.add", {"time": "07:00", "repeat": "once", "greeting": False}, None, ev)
    assert r.ok is False
    assert r.error == "empty"


async def test_add_greeting_string_true(store):
    plugin, _, ev = make(store)
    r = await plugin.call("schedule.add", {"time": "07:00", "repeat": "once", "greeting": "true"}, None, ev)
    assert r.ok is True


async def test_add_clash_sets_pending(store):
    plugin, pending, ev = make(store)
    old = store.add("07:00", "daily", True, None, None, now=D0 + 6 * H)
    r = await plugin.call(
        "schedule.add", {"time": "07:05", "repeat": "once", "greeting": True}, None, ev)
    assert r.ok is True
    assert r.data == {"pending": "schedule_conflict"}
    assert r.say == "You already have a schedule at 07:00. Should I delete it and save this one?"
    q = pending.peek("speaker-1")
    assert q.clash_ids == [old.id]
    assert q.new == {"time_": "07:05", "repeat": "once", "greeting": True, "command": None, "room": "bedroom"}
    assert len(store.get_all()) == 1


async def test_cancel_existing(store):
    plugin, _, ev = make(store)
    store.add("07:00", "daily", True, None, None, now=D0 + 6 * H)
    r = await plugin.call("schedule.cancel", {"time": "07:00"}, None, ev)
    assert r.say == "Cancelled the 07:00 schedule."


async def test_cancel_missing(store):
    plugin, _, ev = make(store)
    r = await plugin.call("schedule.cancel", {"time": "08:00"}, None, ev)
    assert r.ok is False
    assert r.error == "not_found"
    assert r.say == "There's no schedule at 08:00."


def test_manifest():
    assert tuple(c.name for c in SchedulePlugin(None, None).manifest.capabilities) == (
        "schedule.add", "schedule.cancel")
    assert SCHEDULE_ADD.closed_args.keys() == {"repeat", "greeting"}
    assert SCHEDULE_ADD.free_args == ("time", "command", "room")
    assert SCHEDULE_CANCEL.name == "schedule.cancel"
