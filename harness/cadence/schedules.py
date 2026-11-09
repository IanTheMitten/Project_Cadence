"""Schedules (wake-ups / timed routines), pending yes/no questions, and the schedule plugin."""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass

from cadence.events import Event
from cadence.plugins.base import Capability, Manifest, Plugin, Result
from cadence.plugins.registry import Device

LISTEN_S = 8
QUESTION_TTL_S = 12.0
CLASH_WINDOW_MIN = 15
BAD_TIME_SAY = "I didn't catch the time."
EMPTY_SAY = "What should I do at that time?"

SCHEDULE_ADD = Capability(
    "schedule.add",
    "Set a wake-up or timed routine: a time, once or every day, an optional greeting, then an optional "
    "spoken command (e.g. 'wake me up at 7 and play jazz').",
    {"type": "object", "properties": {
        "time": {"type": "string", "description": "24-hour HH:MM"},
        "repeat": {"type": "string", "enum": ["once", "daily"]},
        "greeting": {"type": "boolean"},
        "command": {"type": "string",
                    "description": "what to do then, in the user's words, e.g. 'play jazz'; omit if nothing"},
        "room": {"type": "string"}},
     "required": ["time", "repeat", "greeting"]},
    closed_args={"repeat": {"once": "just once", "daily": "every day"},
                 "greeting": {"true": "wake-up or greeting wanted", "false": "no greeting"}},
    free_args=("time", "command", "room"))
SCHEDULE_CANCEL = Capability(
    "schedule.cancel",
    "Cancel or delete a scheduled wake-up or routine at a given time.",
    {"type": "object", "properties": {"time": {"type": "string", "description": "24-hour HH:MM"}},
     "required": ["time"]},
    free_args=("time",))


@dataclass
class Schedule:
    id: int
    time: str
    repeat: str
    greeting: bool
    command: str | None
    room: str | None
    next_at: float


def parse_hhmm(value) -> str | None:
    if not isinstance(value, str):
        return None
    m = re.match(r"^(\d{1,2}):(\d{2})$", value)
    if not m or int(m[1]) >= 24 or int(m[2]) >= 60:
        return None
    return f"{int(m[1]):02d}:{int(m[2]):02d}"


def next_occurrence(hhmm: str, now: float) -> float:
    h, m = int(hhmm[:2]), int(hhmm[3:])
    lt = time.localtime(now)
    at = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, h, m, 0, 0, 0, -1))
    if at <= now:
        at = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + 1, h, m, 0, 0, 0, -1))
    return at


def _minutes(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def clashes(time_: str, repeat: str, next_at: float, other: Schedule) -> bool:
    d = abs(_minutes(time_) - _minutes(other.time))
    if min(d, 1440 - d) > CLASH_WINDOW_MIN:
        return False
    return (repeat == "daily" or other.repeat == "daily"
            or abs(next_at - other.next_at) <= CLASH_WINDOW_MIN * 60)


class ScheduleStore:
    def __init__(self, path: str):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS schedules (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT NOT NULL, "
            "repeat TEXT NOT NULL, greeting INTEGER NOT NULL, command TEXT, room TEXT, "
            "next_at REAL NOT NULL)")
        self._db.commit()

    def _rows(self, where: str = "", params: tuple = ()) -> list[Schedule]:
        cur = self._db.execute(
            "SELECT id, time, repeat, greeting, command, room, next_at FROM schedules "
            f"{where} ORDER BY next_at, id", params)
        return [Schedule(r[0], r[1], r[2], bool(r[3]), r[4], r[5], r[6]) for r in cur.fetchall()]

    def add(self, time_, repeat, greeting, command, room, now) -> Schedule:
        at = next_occurrence(time_, now)
        cur = self._db.execute(
            "INSERT INTO schedules (time, repeat, greeting, command, room, next_at) VALUES (?,?,?,?,?,?)",
            (time_, repeat, int(greeting), command, room, at))
        self._db.commit()
        return Schedule(cur.lastrowid, time_, repeat, bool(greeting), command, room, at)

    def get_all(self) -> list[Schedule]:
        return self._rows()

    def at_time(self, hhmm) -> list[Schedule]:
        return self._rows("WHERE time = ?", (hhmm,))

    def due(self, now) -> list[Schedule]:
        return self._rows("WHERE next_at <= ?", (now,))

    def advance(self, schedule_id: int, now: float) -> None:
        for s in self._rows("WHERE id = ?", (schedule_id,)):
            if s.repeat == "daily":
                self._db.execute("UPDATE schedules SET next_at = ? WHERE id = ?",
                                 (next_occurrence(s.time, now), s.id))
                self._db.commit()
            else:
                self.delete([s.id])

    def delete(self, ids: list[int]) -> None:
        self._db.executemany("DELETE FROM schedules WHERE id = ?", [(i,) for i in ids])
        self._db.commit()

    def conflicts(self, time_, repeat, now) -> list[Schedule]:
        at = next_occurrence(time_, now)
        return [s for s in self.get_all() if clashes(time_, repeat, at, s)]


@dataclass
class PendingQuestion:
    kind: str
    device_id: str
    new: dict
    clash_ids: list[int]
    expires_at: float


class PendingQuestions:
    def __init__(self):
        self._qs: dict[str, PendingQuestion] = {}

    def ask(self, q: PendingQuestion) -> None:
        self._qs[q.device_id] = q

    def peek(self, device_id: str) -> PendingQuestion | None:
        return self._qs.get(device_id)

    def take(self, device_id: str, now: float) -> PendingQuestion | None:
        q = self._qs.pop(device_id, None)
        return None if q is None or now >= q.expires_at else q

    def drop(self, q: PendingQuestion) -> bool:
        if self._qs.get(q.device_id) is q:
            del self._qs[q.device_id]
            return True
        return False


def classify_yes_no(text: str) -> str | None:
    words = set(re.findall(r"[a-z']+", text.lower()))
    if words & {"no", "nope", "nah", "don't", "dont", "keep", "cancel"}:
        return "no"
    if words & {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "delete", "replace"}:
        return "yes"
    return None


class SchedulePlugin(Plugin):
    manifest = Manifest("schedule", "service", (SCHEDULE_ADD, SCHEDULE_CANCEL))

    def __init__(self, store, pending, *, clock=time.time):
        self._store = store
        self._pending = pending
        self._clock = clock

    async def call(self, capability: str, args: dict, target: Device | None, event: Event) -> Result:
        t = parse_hhmm(args.get("time"))
        if t is None:
            return Result(False, say=BAD_TIME_SAY, error="bad_time")
        now = self._clock()
        if capability == "schedule.cancel":
            found = self._store.at_time(t)
            if not found:
                return Result(False, say=f"There's no schedule at {t}.", error="not_found")
            self._store.delete([s.id for s in found])
            return Result(True, say=f"Cancelled the {t} schedule.")
        repeat = args.get("repeat") if args.get("repeat") in ("once", "daily") else "once"
        greeting = args.get("greeting") in (True, "true")
        command = (args.get("command") or "").strip() or None
        room = args.get("room") or event.room
        if not greeting and not command:
            return Result(False, say=EMPTY_SAY, error="empty")
        clash = self._store.conflicts(t, repeat, now)
        if clash:
            self._pending.ask(PendingQuestion(
                "schedule_conflict", event.source,
                {"time_": t, "repeat": repeat, "greeting": greeting, "command": command, "room": room},
                [c.id for c in clash], now + QUESTION_TTL_S))
            times = ", ".join(sorted({c.time for c in clash}))
            return Result(True, say=f"You already have a schedule at {times}. "
                                    "Should I delete it and save this one?",
                          data={"pending": "schedule_conflict"})
        s = self._store.add(t, repeat, greeting, command, room, now)
        return Result(True, say=f"Okay, {t} {'every day' if repeat == 'daily' else 'once'}.",
                      data={"id": s.id})
