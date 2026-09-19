import abc
import time
from collections import deque

from cadence.store import Store

CONTEXT_TURNS = 10

_SYSTEM_PROMPT = (
    "You run the user's music. Keep replies to a sentence or two, since they are "
    "spoken aloud. If a tool fails, report the failure instead of retrying. "
    "You never write code."
)

_SECONDS_PER_DAY = 86400


class ContextProvider(abc.ABC):
    @abc.abstractmethod
    def build_system_prompt(self) -> str:
        raise NotImplementedError

    @abc.abstractmethod
    def prefetch(self, text: str) -> str:
        raise NotImplementedError

    @abc.abstractmethod
    def sync(self, asked: str, chosen: list[int], rejected: list[int], why: str) -> None:
        raise NotImplementedError


class SqliteContextProvider(ContextProvider):
    def __init__(self, store: Store):
        self._store = store

    def build_system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    def prefetch(self, text: str) -> str:
        now = time.time()
        decisions = self._store.query_decisions(now - 7 * _SECONDS_PER_DAY, now)
        lines = [f"{d['asked']} -> {d['chosen']}" for d in decisions[-10:]]
        return "\n".join(lines)

    def sync(self, asked: str, chosen: list[int], rejected: list[int], why: str) -> None:
        self._store.log_decision(asked, chosen, rejected, why, time.time())


class RollingContext:
    def __init__(self):
        self._messages = deque(maxlen=CONTEXT_TURNS * 2)

    def append(self, role: str, content: str) -> None:
        self._messages.append({"role": role, "content": content})

    def messages(self) -> list[dict]:
        return list(self._messages)
