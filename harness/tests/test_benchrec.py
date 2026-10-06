"""Tests for BenchRecorder. Imports of cadence.benchrec / cadence.config live inside each test."""

import importlib
import json


def test_open_missing_dir_returns_none_and_logs(tmp_path, capsys):
    from cadence.benchrec import BenchRecorder

    assert BenchRecorder.open(str(tmp_path / "missing"), "speaker-1") is None
    assert "bench recorder disabled" in capsys.readouterr().err


def test_open_writes_meta_and_appends_pcm(tmp_path):
    from cadence.benchrec import BenchRecorder

    rec = BenchRecorder.open(str(tmp_path), "speaker-1", clock=lambda: 1000.0)
    assert rec.path == str(tmp_path / "speaker-1-1000000.pcm")
    meta = json.loads((tmp_path / "speaker-1-1000000.json").read_text())
    assert meta == {"client_id": "speaker-1", "start_wall": 1000.0,
                    "sample_rate": 16000, "format": "s16le"}
    rec.write(b"ab")
    rec.write(b"cd")
    rec.close()
    assert (tmp_path / "speaker-1-1000000.pcm").read_bytes() == b"abcd"


def test_save_utterance_file(tmp_path):
    from cadence.benchrec import BenchRecorder

    rec = BenchRecorder.open(str(tmp_path), "speaker-1", clock=lambda: 1000.0)
    rec.save_utterance(b"xyz")
    rec.close()
    assert (tmp_path / "utt-speaker-1-1000000.pcm").read_bytes() == b"xyz"


def test_write_error_disables_once(tmp_path, capsys):
    from cadence.benchrec import BenchRecorder

    class BadFile:
        def write(self, data):
            raise OSError("disk full")

        def close(self):
            pass

    rec = BenchRecorder.open(str(tmp_path), "speaker-1", clock=lambda: 1000.0)
    rec._file = BadFile()
    rec.write(b"a")
    rec.write(b"b")
    assert capsys.readouterr().err.count("bench recorder write failed") == 1


def test_close_idempotent(tmp_path):
    from cadence.benchrec import BenchRecorder

    rec = BenchRecorder.open(str(tmp_path), "speaker-1", clock=lambda: 1000.0)
    rec.close()
    rec.close()


def test_config_reads_env(tmp_path, monkeypatch):
    import cadence.config

    monkeypatch.setenv("CADENCE_BENCH_RECORD_DIR", str(tmp_path))
    importlib.reload(cadence.config)
    assert cadence.config.BENCH_RECORD_DIR == str(tmp_path)
    monkeypatch.delenv("CADENCE_BENCH_RECORD_DIR")
    importlib.reload(cadence.config)
    assert cadence.config.BENCH_RECORD_DIR is None
