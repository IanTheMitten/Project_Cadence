import json
import sqlite3
import time

_VALID_TRIGGER_TYPES = {"utterance", "schedule"}


class Store:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY,
                at REAL NOT NULL,
                asked TEXT NOT NULL,
                chosen TEXT NOT NULL,
                rejected TEXT NOT NULL,
                why TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS routines (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                trigger_value TEXT NOT NULL,
                steps TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.commit()

    def log_decision(self, asked: str, chosen: list[int], rejected: list[int], why: str, at: float) -> int:
        cursor = self._conn.execute(
            "INSERT INTO decisions (at, asked, chosen, rejected, why) VALUES (?, ?, ?, ?, ?)",
            (at, asked, json.dumps(chosen), json.dumps(rejected), why),
        )
        self._conn.commit()
        return cursor.lastrowid

    def query_decisions(self, since: float, until: float) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, at, asked, chosen, rejected, why FROM decisions "
            "WHERE at >= ? AND at <= ? ORDER BY at ASC",
            (since, until),
        ).fetchall()
        return [
            {
                "id": row[0],
                "at": row[1],
                "asked": row[2],
                "chosen": json.loads(row[3]),
                "rejected": json.loads(row[4]),
                "why": row[5],
            }
            for row in rows
        ]

    def burn(self) -> None:
        self._conn.execute("DELETE FROM decisions")
        self._conn.commit()
        self._conn.execute("VACUUM")

    def save_routine(self, name: str, trigger_type: str, trigger_value: str, steps: list[dict]) -> int:
        if trigger_type not in _VALID_TRIGGER_TYPES:
            raise ValueError(f"invalid trigger_type: {trigger_type!r}")
        cursor = self._conn.execute(
            "INSERT INTO routines (name, trigger_type, trigger_value, steps, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, trigger_type, trigger_value, json.dumps(steps), time.time()),
        )
        self._conn.commit()
        return cursor.lastrowid

    def list_routines(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, name, trigger_type, trigger_value, steps, created_at FROM routines"
        ).fetchall()
        return [
            {
                "id": row[0],
                "name": row[1],
                "trigger_type": row[2],
                "trigger_value": row[3],
                "steps": json.loads(row[4]),
                "created_at": row[5],
            }
            for row in rows
        ]

    def delete_routine(self, routine_id: int) -> None:
        self._conn.execute("DELETE FROM routines WHERE id = ?", (routine_id,))
        self._conn.commit()

    def due_routines(self, now: float) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, name, trigger_type, trigger_value, steps, created_at FROM routines "
            "WHERE trigger_type = 'schedule'"
        ).fetchall()
        return [
            {
                "id": row[0],
                "name": row[1],
                "trigger_type": row[2],
                "trigger_value": row[3],
                "steps": json.loads(row[4]),
                "created_at": row[5],
            }
            for row in rows
            if float(row[3]) <= now
        ]
