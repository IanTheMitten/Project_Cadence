"""Tests for AckPool (I16)."""

from cadence.acks import AckPool


def _clips(root, category, n):
    d = root / category
    d.mkdir()
    for i in range(n):
        (d / f"{i:02d}.pcm").write_bytes(bytes([i]) * 4)


def test_count_loads_pcm_files(tmp_path):
    _clips(tmp_path, "action", 2)
    assert AckPool(str(tmp_path)).count("action") == 2


def test_pick_never_repeats_back_to_back(tmp_path):
    _clips(tmp_path, "action", 2)
    pool = AckPool(str(tmp_path))
    picks = [pool.pick("action") for _ in range(20)]
    assert all(a != b for a, b in zip(picks, picks[1:]))


def test_single_clip_returned_each_time(tmp_path):
    _clips(tmp_path, "chat", 1)
    pool = AckPool(str(tmp_path))
    assert [pool.pick("chat") for _ in range(3)] == [bytes([0]) * 4] * 3


def test_empty_or_unknown_category_is_none(tmp_path):
    (tmp_path / "correction").mkdir()
    pool = AckPool(str(tmp_path))
    assert pool.pick("correction") is None
    assert pool.pick("bogus") is None


def test_missing_root_counts_zero(tmp_path):
    pool = AckPool(str(tmp_path / "nope"))
    assert pool.count("action") == 0
    assert pool.count("chat") == 0
