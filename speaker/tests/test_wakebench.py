"""Tests for the wake/ASR bench scoring library (cadence_speaker.wakebench). Synthetic data only."""

import json
import math

import pytest


def _r(hit, fw):
    from cadence_speaker import wakebench as wb

    return wb.EngineResult(0.5, hit, fw, 0.0, True)


def test_detections_refractory():
    from cadence_speaker import wakebench as wb

    trace = [(0.0, 0.1), (1.0, 0.6), (1.5, 0.9), (3.1, 0.7), (3.2, 0.2)]
    assert wb.detections(trace, 0.5, 2.0) == [1.0, 3.1]


def test_detections_threshold_inclusive():
    from cadence_speaker import wakebench as wb

    assert wb.detections([(0.0, 0.5)], 0.5) == [0.0]


def test_hit_rate_window():
    from cadence_speaker import wakebench as wb

    assert wb.hit_rate([10.0, 30.0], [9.0, 20.0, 29.0, 50.0], 6.0) == 0.5


def test_hit_rate_empty():
    from cadence_speaker import wakebench as wb

    assert wb.hit_rate([], []) == 0.0


def test_evaluate():
    from cadence_speaker import wakebench as wb

    got = wb.evaluate([[(100.0, 0.9), (200.0, 0.9), (5000.0, 0.9)]], [99.0],
                      [(90.0, 210.0)], 7200.0, 0.5)
    assert got == wb.EngineResult(0.5, 1.0, 1, 0.5, False)


def test_evaluate_zero_background_raises():
    from cadence_speaker import wakebench as wb

    with pytest.raises(ValueError):
        wb.evaluate([[(100.0, 0.9)]], [99.0], [(90.0, 210.0)], 0.0, 0.5)


def test_sweep_picks_lowest_meeting_target():
    from cadence_speaker import wakebench as wb

    got = wb.sweep([[(100.0, 0.8), (5000.0, 0.6)]], [99.0], [(90.0, 110.0)],
                   8 * 3600.0, grid=(0.5, 0.7, 0.9))
    assert got.threshold == 0.5
    assert got.hit_rate == 1.0
    assert got.false_wakes == 1
    assert got.target_met is True


def test_sweep_target_not_met():
    from cadence_speaker import wakebench as wb

    got = wb.sweep([[(5000.0, 0.95), (9000.0, 0.6)]], [], [], 3600.0, grid=(0.5, 0.9))
    assert got.threshold == 0.9
    assert got.false_wakes == 1
    assert got.target_met is False


def test_board_wins_hit_margin_fail():
    from cadence_speaker import wakebench as wb

    assert wb.board_wins(_r(0.85, 0), _r(0.95, 0)) is False


def test_board_wins_hit_margin_ok():
    from cadence_speaker import wakebench as wb

    assert wb.board_wins(_r(0.90, 0), _r(0.95, 0)) is True


def test_board_wins_false_wake_2x():
    from cadence_speaker import wakebench as wb

    assert wb.board_wins(_r(0.9, 2), _r(0.9, 0)) is False
    assert wb.board_wins(_r(0.9, 1), _r(0.9, 0)) is True


def test_board_wins_false_wake_floor():
    from cadence_speaker import wakebench as wb

    assert wb.board_wins(_r(0.9, 3), _r(0.9, 2)) is True


def test_normalize():
    from cadence_speaker import wakebench as wb

    assert wb.normalize("Play, Something CHILL!") == ["play", "something", "chill"]
    assert wb.normalize("what's playing") == ["what's", "playing"]


def test_wer():
    from cadence_speaker import wakebench as wb

    assert wb.wer(["play something chill"], ["play something"]) == pytest.approx(1 / 3)
    assert wb.wer(["a b", "c d"], ["a x", "c d"]) == 0.25


def test_wer_empty_raises():
    from cadence_speaker import wakebench as wb

    with pytest.raises(ValueError):
        wb.wer([], [])
    with pytest.raises(ValueError):
        wb.wer(["a"], [])


def test_pick_asr():
    from cadence_speaker import wakebench as wb

    results = [wb.AsrResult("small.en/beam5", 0.10, 900.0),
               wb.AsrResult("base.en/beam1", 0.115, 300.0),
               wb.AsrResult("distil-small.en/beam1", 0.13, 200.0)]
    assert wb.pick_asr(results, "small.en/beam5").name == "base.en/beam1"


def test_load_recordings(tmp_path):
    from cadence_speaker import wakebench as wb

    (tmp_path / "speaker-1-1000000.json").write_text(json.dumps(
        {"client_id": "speaker-1", "start_wall": 1000.0, "sample_rate": 16000, "format": "s16le"}))
    (tmp_path / "speaker-1-1000000.pcm").write_bytes(b"\0" * 64000)
    (tmp_path / "utt-speaker-1-1000500.pcm").write_bytes(b"\0" * 10)
    assert wb.load_recordings(str(tmp_path)) == [
        wb.Recording(str(tmp_path / "speaker-1-1000000.pcm"), 1000.0, 2.0)]


def test_load_labels(tmp_path):
    from cadence_speaker import wakebench as wb

    (tmp_path / "labels-1.jsonl").write_text(
        json.dumps({"kind": "wake", "t": 5.0}) + "\n" + json.dumps({"kind": "wake", "t": 1.0}) + "\n")
    (tmp_path / "labels-2.jsonl").write_text(json.dumps({"kind": "wake", "t": 3.0}) + "\n")
    got = wb.load_labels(str(tmp_path))
    assert len(got) == 3
    assert [d["t"] for d in got] == [1.0, 3.0, 5.0]


def test_guided_spans():
    from cadence_speaker import wakebench as wb

    labels = [{"kind": "session_start", "t": 10.0}, {"kind": "wake", "t": 12.0},
              {"kind": "session_end", "t": 50.0}, {"kind": "session_start", "t": 100.0}]
    assert wb.guided_spans(labels) == [(10.0, 50.0), (100.0, math.inf)]


def test_background_seconds():
    from cadence_speaker import wakebench as wb

    recs = [wb.Recording("x.pcm", 0.0, 100.0)]
    assert wb.background_seconds(recs, [(10.0, 30.0), (90.0, math.inf)]) == 70.0


def test_load_utterances(tmp_path):
    from cadence_speaker import wakebench as wb

    path = tmp_path / "utt-speaker-1-1000500.pcm"
    path.write_bytes(b"\0" * 10)
    assert wb.load_utterances(str(tmp_path)) == [(1000.5, str(path))]


def test_pair_commands():
    from cadence_speaker import wakebench as wb

    labels = [{"kind": "command", "t": 100.0, "text": "turn it up"},
              {"kind": "command", "t": 200.0, "text": "pause"}]
    assert wb.pair_commands(labels, [(105.0, "a.pcm"), (230.0, "b.pcm")]) == [("turn it up", "a.pcm")]
