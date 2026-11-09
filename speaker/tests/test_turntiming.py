"""Tests for TurnTimer. Imports of cadence_speaker.turntiming live inside each test."""

import json

import pytest


def test_mark_first_wins():
    from cadence_speaker.turntiming import TurnTimer

    timer = TurnTimer(clock=iter([1.0, 2.0]).__next__)
    timer.mark("turn_start")
    timer.mark("turn_start")
    assert timer.stamps == {"turn_start": 1.0}


def test_mark_at_overrides_clock():
    from cadence_speaker.turntiming import TurnTimer

    timer = TurnTimer(clock=lambda: 9.0)
    timer.mark("wake", at=3.0)
    assert timer.stamps == {"wake": 3.0}


def test_unknown_stage_raises():
    from cadence_speaker.turntiming import TurnTimer

    timer = TurnTimer(clock=lambda: 1.0)
    with pytest.raises(ValueError):
        timer.mark("bogus")


def test_durations_only_complete_pairs():
    from cadence_speaker.turntiming import TurnTimer

    timer = TurnTimer(clock=lambda: 0.0)
    timer.mark("speech_end", at=10.0)
    timer.mark("asr_done", at=10.25)
    assert timer.durations() == {"asr": 250.0}


def test_log_line_format():
    from cadence_speaker.turntiming import TurnTimer

    timer = TurnTimer(clock=lambda: 0.0)
    timer.mark("speech_end", at=10.0)
    timer.mark("asr_done", at=10.25)
    line = timer.log_line("speaker-1")
    assert line.startswith("turn_timing ")
    assert json.loads(line[len("turn_timing "):]) == {
        "client_id": "speaker-1", "durations_ms": {"asr": 250.0}}
