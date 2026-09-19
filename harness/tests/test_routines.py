from cadence.routines import crystallize, invalidate, match, normalize
from cadence.store import Store


def test_normalize_lowercases_and_strips_punctuation():
    assert normalize("  Play Something CHILL! ") == "play something chill"


def test_normalize_collapses_whitespace():
    assert normalize("play   something\tchill") == "play something chill"


def test_exact_normalized_match_hits(tmp_path):
    store = Store(str(tmp_path / "cadence.sqlite3"))
    crystallize(store, "Play something chill", [{"tool": "play", "args": {"vibe": "chill"}}])
    result = match(store, "play something CHILL!")
    assert result is not None


def test_different_wording_misses(tmp_path):
    store = Store(str(tmp_path / "cadence.sqlite3"))
    crystallize(store, "Play something chill", [{"tool": "play", "args": {"vibe": "chill"}}])
    assert match(store, "put on something mellow") is None


def test_schedule_routines_never_match_utterances(tmp_path):
    store = Store(str(tmp_path / "cadence.sqlite3"))
    store.save_routine(
        name="play something chill",
        trigger_type="schedule",
        trigger_value="1000.0",
        steps=[{"tool": "play", "args": {"vibe": "chill"}}],
    )
    assert match(store, "play something chill") is None


def test_crystallize_is_idempotent(tmp_path):
    store = Store(str(tmp_path / "cadence.sqlite3"))
    crystallize(store, "Play something chill", [{"tool": "play", "args": {"vibe": "chill"}}])
    crystallize(store, "Play something chill", [{"tool": "play", "args": {"vibe": "mellow"}}])
    routines = [r for r in store.list_routines() if r["trigger_type"] == "utterance"]
    assert len(routines) == 1
    assert routines[0]["steps"] == [{"tool": "play", "args": {"vibe": "mellow"}}]


def test_invalidate_removes_matching_routine(tmp_path):
    store = Store(str(tmp_path / "cadence.sqlite3"))
    crystallize(store, "Play something chill", [{"tool": "play", "args": {"vibe": "chill"}}])
    assert invalidate(store, "play something chill") == 1
    assert match(store, "play something chill") is None


def test_invalidate_returns_zero_when_nothing_matches(tmp_path):
    store = Store(str(tmp_path / "cadence.sqlite3"))
    assert invalidate(store, "nothing like this") == 0
