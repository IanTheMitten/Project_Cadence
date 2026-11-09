import pytest

from cadence.decisionlog import DecisionLog
from cadence.events import Call, Decision, utterance
from cadence.plugins.base import Result

KEYS = {
    "id", "at", "event_id", "source", "room", "user_id", "text", "asr_conf", "context",
    "decider", "route", "calls", "reply", "escalation", "jev_route", "jev_confidence",
    "jev_candidates", "outcome", "results", "latency_ms", "models", "labels",
}


def make_log(tmp_path):
    return DecisionLog(str(tmp_path / "log.sqlite3"))


def make_decision(**kw):
    base = dict(
        decider="llm", route="music.control",
        calls=[Call("music.control", {"action": "pause"})],
        model="gemma4:31b-cloud",
    )
    base.update(kw)
    return Decision(**base)


def rec(log, results=None, decision=None, jev=None, event=None):
    event = event or utterance("speaker-1", "kitchen", "pause", asr_conf=0.9)
    return log.record(event, {"k": "v"}, decision or make_decision(), jev,
                      [] if results is None else results, {"total": 1.5})


def test_record_returns_int_and_export_keys(tmp_path):
    log = make_log(tmp_path)
    i = rec(log, [Result(True)])
    assert isinstance(i, int)
    row = log.export()[0]
    assert set(row) == KEYS
    assert row["labels"] == []


def test_calls_round_trip(tmp_path):
    log = make_log(tmp_path)
    rec(log)
    assert log.export()[0]["calls"] == [
        {"capability": "music.control", "args": {"action": "pause"}}
    ]


def test_jev_none(tmp_path):
    log = make_log(tmp_path)
    rec(log, jev=None)
    row = log.export()[0]
    assert row["jev_route"] is None
    assert row["jev_confidence"] is None
    assert row["jev_candidates"] is None
    assert row["models"] == {"decider": "gemma4:31b-cloud", "jev": None}


def test_outcomes(tmp_path):
    log = make_log(tmp_path)
    rec(log, [Result(True)])
    rec(log, [Result(False)])
    rec(log, [Result(True), Result(False)])
    rec(log, [], decision=make_decision(calls=[], reply="hi"))
    rec(log, [], decision=make_decision(calls=[], reply=None))
    assert [r["outcome"] for r in log.export()] == ["ok", "error", "partial", "reply", "none"]


def test_label_appears_in_export(tmp_path):
    log = make_log(tmp_path)
    id1 = rec(log)
    id2 = rec(log)
    log.label(id1, "wrong", "spoken_correction", corrected_by=id2)
    labels = log.export()[0]["labels"]
    assert len(labels) == 1
    assert labels[0]["decision_id"] == id1
    assert labels[0]["label"] == "wrong"
    assert labels[0]["source"] == "spoken_correction"
    assert labels[0]["corrected_by"] == id2


def test_label_invalid_raises(tmp_path):
    log = make_log(tmp_path)
    i = rec(log)
    with pytest.raises(ValueError):
        log.label(i, "right", "spoken_correction")
    with pytest.raises(ValueError):
        log.label(i, "wrong", "ui")
    with pytest.raises(ValueError):
        log.label(9999, "wrong", "spoken_correction")


def test_last_for_device_or_room(tmp_path):
    log = make_log(tmp_path)
    rec(log, event=utterance("speaker-1", None, "a", ts=100.0))
    new = rec(log, event=utterance("speaker-1", None, "b", ts=200.0))
    rec(log, event=utterance("other", None, "c", ts=300.0))
    assert log.last_for_device_or_room("speaker-1", None, 50.0)["id"] == new
    assert log.last_for_device_or_room("speaker-1", None, 250.0) is None
    assert log.last_for_device_or_room("nobody", None, 0.0) is None
    sched = rec(log, event=utterance("scheduler", "bedroom", "d", ts=400.0))
    assert log.last_for_device_or_room("speaker-1", "bedroom", 0.0)["id"] == sched
    assert log.last_for_device_or_room("speaker-1", None, 0.0)["id"] != sched
    assert log.last_for_device_or_room("speaker-1", "bedroom", 450.0) is None


def test_recent_newest_first(tmp_path):
    log = make_log(tmp_path)
    ids = [rec(log, event=utterance("speaker-1", None, t, ts=float(n)))
           for n, t in enumerate("abc", start=1)]
    assert [r["id"] for r in log.recent(2)] == [ids[2], ids[1]]


def test_no_update_or_delete_attrs(tmp_path):
    log = make_log(tmp_path)
    for name in dir(log):
        assert "update" not in name.lower()
        assert "delete" not in name.lower()


def test_reopen_keeps_rows(tmp_path):
    log = make_log(tmp_path)
    i = rec(log)
    again = make_log(tmp_path)
    assert [r["id"] for r in again.export()] == [i]
