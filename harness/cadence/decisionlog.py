import json
import sqlite3
import time

from cadence.events import Decision, Event
from cadence.plugins.base import Result

LABELS = ("wrong",)
LABEL_SOURCES = ("spoken_correction",)

_COLUMNS = (
    "id", "at", "event_id", "source", "room", "user_id", "text", "asr_conf", "context",
    "decider", "route", "calls", "reply", "escalation", "jev_route", "jev_confidence",
    "jev_candidates", "outcome", "results", "latency_ms", "models",
)
_JSON_COLUMNS = ("context", "calls", "jev_candidates", "results", "latency_ms", "models")
_SELECT = "SELECT " + ", ".join(_COLUMNS) + " FROM decision_log"


def _outcome(decision: Decision, results: list[Result]) -> str:
    if not results:
        return "reply" if decision.reply else "none"
    oks = [r.ok for r in results]
    if all(oks):
        return "ok"
    if not any(oks):
        return "error"
    return "partial"


class DecisionLog:
    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS decision_log (
                id INTEGER PRIMARY KEY,
                at REAL NOT NULL,
                event_id TEXT NOT NULL,
                source TEXT NOT NULL,
                room TEXT,
                user_id TEXT NOT NULL,
                text TEXT,
                asr_conf REAL,
                context TEXT NOT NULL,
                decider TEXT NOT NULL,
                route TEXT,
                calls TEXT NOT NULL,
                reply TEXT,
                escalation TEXT,
                jev_route TEXT,
                jev_confidence REAL,
                jev_candidates TEXT,
                outcome TEXT NOT NULL,
                results TEXT NOT NULL,
                latency_ms TEXT NOT NULL,
                models TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS decision_labels (
                id INTEGER PRIMARY KEY,
                decision_id INTEGER NOT NULL,
                at REAL NOT NULL,
                label TEXT NOT NULL,
                source TEXT NOT NULL,
                corrected_by INTEGER
            )
            """
        )
        self._conn.commit()

    def record(self, event: Event, context: dict, decision: Decision, jev: Decision | None,
               results: list[Result], latency_ms: dict[str, float]) -> int:
        calls = [{"capability": c.capability, "args": c.args} for c in decision.calls]
        res = [{"ok": r.ok, "say": r.say, "error": r.error} for r in results]
        models = {"decider": decision.model, "jev": jev.model if jev else None}
        cursor = self._conn.execute(
            "INSERT INTO decision_log (at, event_id, source, room, user_id, text, asr_conf, "
            "context, decider, route, calls, reply, escalation, jev_route, jev_confidence, "
            "jev_candidates, outcome, results, latency_ms, models) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event.ts, event.id, event.source, event.room, event.user_id,
                event.payload.get("text"), event.payload.get("asr_conf"),
                json.dumps(context), decision.decider, decision.route, json.dumps(calls),
                decision.reply, decision.escalation,
                jev.route if jev else None,
                jev.confidence if jev else None,
                json.dumps(jev.candidates) if jev else None,
                _outcome(decision, results), json.dumps(res),
                json.dumps(latency_ms), json.dumps(models),
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def label(self, decision_id: int, label: str, source: str, corrected_by: int | None = None) -> int:
        if label not in LABELS:
            raise ValueError(f"unknown label: {label!r}")
        if source not in LABEL_SOURCES:
            raise ValueError(f"unknown label source: {source!r}")
        found = self._conn.execute(
            "SELECT 1 FROM decision_log WHERE id = ?", (decision_id,)
        ).fetchone()
        if found is None:
            raise ValueError(f"unknown decision_id: {decision_id}")
        cursor = self._conn.execute(
            "INSERT INTO decision_labels (decision_id, at, label, source, corrected_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (decision_id, time.time(), label, source, corrected_by),
        )
        self._conn.commit()
        return cursor.lastrowid

    def _row(self, values) -> dict:
        row = dict(zip(_COLUMNS, values))
        for col in _JSON_COLUMNS:
            if row[col] is not None:
                row[col] = json.loads(row[col])
        return row

    def last_for_source(self, source: str, since: float) -> dict | None:
        values = self._conn.execute(
            _SELECT + " WHERE source = ? AND at >= ? ORDER BY at DESC, id DESC LIMIT 1",
            (source, since),
        ).fetchone()
        return self._row(values) if values else None

    def recent(self, n: int) -> list[dict]:
        rows = self._conn.execute(_SELECT + " ORDER BY id DESC LIMIT ?", (n,)).fetchall()
        return [self._row(v) for v in rows]

    def export(self) -> list[dict]:
        rows = [self._row(v) for v in self._conn.execute(_SELECT + " ORDER BY id ASC").fetchall()]
        labels: dict[int, list[dict]] = {}
        for lid, did, at, label, source, by in self._conn.execute(
            "SELECT id, decision_id, at, label, source, corrected_by FROM decision_labels "
            "ORDER BY id ASC"
        ).fetchall():
            labels.setdefault(did, []).append(
                {"id": lid, "decision_id": did, "at": at, "label": label,
                 "source": source, "corrected_by": by}
            )
        for row in rows:
            row["labels"] = labels.get(row["id"], [])
        return rows
