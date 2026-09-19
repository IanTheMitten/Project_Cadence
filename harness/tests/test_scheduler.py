"""Tests for the scheduler tick, pinned to
docs/specs/2026-09-19-voice-music-agent-harness.md:77-82: a due schedule
routine executes with zero model calls, a due routine yields to an in-flight
user turn (the concurrency-1 rule), and a v1 scheduled routine may start
music but must not speak.
"""

from cadence.scheduler import Scheduler, is_speaking_step
from cadence.server import TURN_LOCK
from cadence.session import Session, SessionCaps, SessionRegistry
from cadence.store import Store


class FakeTools:
    """Duck-typed stand-in for ToolRegistry (see cadence/mcp_client.py)."""

    def __init__(self):
        self.calls = []

    def list_tools(self) -> list[dict]:
        return []

    async def start(self) -> None:
        pass

    async def call(self, name, args):
        self.calls.append((name, args))
        if name == "play":
            return f"http://ianshomeserver:8765/play/{args['track_rowid']}"
        return {}


def _stub_session():
    sent = []

    async def send_audio(data: bytes) -> None:
        sent.append(data)

    async def send_text(text: str) -> None:
        pass

    session = Session(
        client_id="stub",
        caps=SessionCaps.from_list(["audio_out"]),
        last_active=0.0,
        send_audio=send_audio,
        send_text=send_text,
    )
    return session, sent


async def test_tick_executes_due_routine(tmp_path):
    store = Store(str(tmp_path / "cadence.sqlite3"))
    registry = SessionRegistry()
    session, sent = _stub_session()
    registry.add(session)
    routine_id = store.save_routine(
        name="morning",
        trigger_type="schedule",
        trigger_value="1000.0",
        steps=[{"tool": "play", "args": {"track_rowid": 123}}],
    )
    tools = FakeTools()
    scheduler = Scheduler(store, registry, tools)

    fired = await scheduler.tick(2000.0)

    assert fired == [routine_id]
    assert sent
    assert tools.calls == [("play", {"track_rowid": 123})]


async def test_tick_skips_future_routine(tmp_path):
    store = Store(str(tmp_path / "cadence.sqlite3"))
    registry = SessionRegistry()
    session, sent = _stub_session()
    registry.add(session)
    store.save_routine(
        name="later",
        trigger_type="schedule",
        trigger_value="3000.0",
        steps=[{"tool": "play", "args": {"track_rowid": 123}}],
    )
    tools = FakeTools()
    scheduler = Scheduler(store, registry, tools)

    fired = await scheduler.tick(2000.0)

    assert fired == []
    assert tools.calls == []


async def test_tick_yields_when_turn_lock_held(tmp_path):
    store = Store(str(tmp_path / "cadence.sqlite3"))
    registry = SessionRegistry()
    session, sent = _stub_session()
    registry.add(session)
    store.save_routine(
        name="morning",
        trigger_type="schedule",
        trigger_value="1000.0",
        steps=[{"tool": "play", "args": {"track_rowid": 123}}],
    )
    tools = FakeTools()
    scheduler = Scheduler(store, registry, tools)

    async with TURN_LOCK:
        fired = await scheduler.tick(2000.0)

    assert fired == []
    assert sent == []
    assert tools.calls == []


async def test_tick_uses_zero_llm_calls(tmp_path):
    """The due-routine path needs no LLM collaborator at all -- only a
    ToolRegistry-shaped object is ever passed to the scheduler, and no
    LLM-shaped object is anywhere in scope.
    """
    store = Store(str(tmp_path / "cadence.sqlite3"))
    registry = SessionRegistry()
    session, sent = _stub_session()
    registry.add(session)
    routine_id = store.save_routine(
        name="morning",
        trigger_type="schedule",
        trigger_value="1000.0",
        steps=[{"tool": "play", "args": {"track_rowid": 123}}],
    )
    tools = FakeTools()
    scheduler = Scheduler(store, registry, tools)

    fired = await scheduler.tick(2000.0)

    assert fired == [routine_id]
    assert len(tools.calls) == 1


async def test_speaking_step_is_rejected_in_v1(tmp_path):
    store = Store(str(tmp_path / "cadence.sqlite3"))
    registry = SessionRegistry()
    session, sent = _stub_session()
    registry.add(session)
    store.save_routine(
        name="greeting",
        trigger_type="schedule",
        trigger_value="1000.0",
        steps=[{"say": "good morning"}],
    )
    tools = FakeTools()
    scheduler = Scheduler(store, registry, tools)

    assert is_speaking_step({"say": "good morning"}) is True

    fired = await scheduler.tick(2000.0)

    assert fired == []
    assert sent == []
    assert tools.calls == []


async def test_no_audio_session_means_no_execution(tmp_path):
    store = Store(str(tmp_path / "cadence.sqlite3"))
    registry = SessionRegistry()
    store.save_routine(
        name="morning",
        trigger_type="schedule",
        trigger_value="1000.0",
        steps=[{"tool": "play", "args": {"track_rowid": 123}}],
    )
    tools = FakeTools()
    scheduler = Scheduler(store, registry, tools)

    fired = await scheduler.tick(2000.0)

    assert fired == []
    assert tools.calls == []
