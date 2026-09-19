import sqlite3

from cadence.store import Store


def test_schema_has_two_tables(tmp_path):
    Store(str(tmp_path / "cadence.sqlite3"))
    conn = sqlite3.connect(str(tmp_path / "cadence.sqlite3"))
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    conn.close()
    names = {row[0] for row in rows}
    assert names == {"decisions", "routines"}


def test_log_and_query_decision_roundtrip(tmp_path):
    store = Store(str(tmp_path / "cadence.sqlite3"))
    store.log_decision(
        asked="play something chill",
        chosen=[12, 34],
        rejected=[56],
        why="matched vibe search",
        at=1000.0,
    )
    results = store.query_decisions(0.0, 9e9)
    assert len(results) == 1
    result = results[0]
    assert result["asked"] == "play something chill"
    assert result["chosen"] == [12, 34]
    assert result["rejected"] == [56]
    assert result["why"] == "matched vibe search"


def test_query_decisions_respects_window(tmp_path):
    store = Store(str(tmp_path / "cadence.sqlite3"))
    store.log_decision(asked="a", chosen=[1], rejected=[], why="first", at=1000.0)
    store.log_decision(asked="b", chosen=[2], rejected=[], why="second", at=2000.0)
    store.log_decision(asked="c", chosen=[3], rejected=[], why="third", at=3000.0)
    results = store.query_decisions(1500.0, 2500.0)
    assert len(results) == 1
    assert results[0]["asked"] == "b"


def test_decisions_store_track_ids_not_track_data(tmp_path):
    db_path = str(tmp_path / "cadence.sqlite3")
    Store(db_path)
    conn = sqlite3.connect(db_path)
    columns = conn.execute("PRAGMA table_info(decisions)").fetchall()
    conn.close()
    column_names = [col[1].lower() for col in columns]
    for name in column_names:
        assert "track_name" not in name
        assert "artist" not in name
        assert "album" not in name


def test_burn_empties_decisions_but_keeps_routines(tmp_path):
    store = Store(str(tmp_path / "cadence.sqlite3"))
    store.log_decision(asked="a", chosen=[1], rejected=[], why="first", at=1000.0)
    store.save_routine(
        name="chill routine",
        trigger_type="utterance",
        trigger_value="play something chill",
        steps=[{"tool": "search_vibe", "args": {"query": "chill"}}],
    )
    store.burn()
    assert store.query_decisions(0.0, 9e9) == []
    assert len(store.list_routines()) == 1


def test_save_and_list_routine_roundtrip(tmp_path):
    store = Store(str(tmp_path / "cadence.sqlite3"))
    steps = [{"tool": "search_vibe", "args": {"query": "chill"}}]
    store.save_routine(
        name="chill routine",
        trigger_type="utterance",
        trigger_value="play something chill",
        steps=steps,
    )
    routines = store.list_routines()
    assert len(routines) == 1
    assert routines[0]["steps"] == steps


def test_routine_trigger_type_is_constrained(tmp_path):
    store = Store(str(tmp_path / "cadence.sqlite3"))
    try:
        store.save_routine(
            name="bad routine",
            trigger_type="whenever",
            trigger_value="x",
            steps=[],
        )
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_delete_routine_removes_it(tmp_path):
    store = Store(str(tmp_path / "cadence.sqlite3"))
    first_id = store.save_routine(
        name="first",
        trigger_type="utterance",
        trigger_value="play something chill",
        steps=[],
    )
    store.save_routine(
        name="second",
        trigger_type="utterance",
        trigger_value="play something upbeat",
        steps=[],
    )
    store.delete_routine(first_id)
    routines = store.list_routines()
    assert len(routines) == 1
    assert routines[0]["name"] == "second"


def test_due_routines_returns_only_past_schedules(tmp_path):
    store = Store(str(tmp_path / "cadence.sqlite3"))
    store.save_routine(
        name="past",
        trigger_type="schedule",
        trigger_value="1000.0",
        steps=[],
    )
    store.save_routine(
        name="future",
        trigger_type="schedule",
        trigger_value="3000.0",
        steps=[],
    )
    store.save_routine(
        name="not scheduled",
        trigger_type="utterance",
        trigger_value="play something chill",
        steps=[],
    )
    due = store.due_routines(2000.0)
    assert len(due) == 1
    assert due[0]["name"] == "past"
