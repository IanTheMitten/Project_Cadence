from __future__ import annotations

import json
import os

import httpx

from cadence.config import JEV_CLOSED_ARGS, JEV_MODEL, JEV_TIMEOUT_S, JEV_URL, TYPESAFE_ENV_PATH
from cadence.deciders.base import Decider, DeciderUnavailable
from cadence.events import Call, Decision, Event
from cadence.plugins.base import Capability

ROUTE_INSTRUCTIONS = "Which single function best serves what the user just said?"


def load_api_key(path: str = TYPESAFE_ENV_PATH, name: str = "TYPESAFE_API_KEY") -> str:
    key = os.environ.get(name)
    if key:
        return key
    try:
        with open(path) as f:
            for line in f:
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    raise DeciderUnavailable(f"no {name}")


def render_state(event: Event, context: dict) -> str:
    lines = "".join(
        f"{k}: {v if isinstance(v, str) else json.dumps(v)}\n" for k, v in context.items()
    )
    return "Home speaker assistant.\n" + lines + "\nUser said: " + event.payload["text"]


def build_questions(capabilities: list[Capability], closed_args: bool) -> dict:
    questions = {
        "route": {
            "type": "choice",
            "instructions": ROUTE_INSTRUCTIONS,
            "criteria": {c.name: c.description for c in capabilities},
        }
    }
    if closed_args:
        for c in capabilities:
            for a in c.closed_args:
                questions[f"arg:{c.name}:{a}"] = {
                    "type": "choice",
                    "instructions": f"If the user wants {c.name}, which {a}?",
                    "criteria": c.closed_args[a],
                }
    return questions


class JevDecider(Decider):
    name = "jev"

    def __init__(self, api_key: str, *, url: str = JEV_URL, model: str = JEV_MODEL,
                 timeout_s: float = JEV_TIMEOUT_S, closed_args: bool = JEV_CLOSED_ARGS,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._key = api_key
        self._url = url
        self._model = model
        self._timeout_s = timeout_s
        self._closed_args = closed_args
        self._transport = transport

    async def decide(self, event, context, capabilities, instruction=None) -> Decision:
        body = {
            "state": render_state(event, context),
            "model": self._model,
            "questions": build_questions(capabilities, self._closed_args),
        }
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout_s) as client:
                response = await client.post(
                    self._url, json=body, headers={"Authorization": f"Bearer {self._key}"}
                )
        except httpx.HTTPError:
            raise DeciderUnavailable("jev transport error") from None
        if response.status_code != 200:
            raise DeciderUnavailable(f"jev HTTP {response.status_code}")

        try:
            j = response.json()
            answers = j["answers"]
            a = answers["route"]
            route = a["choice"]
            candidates = a["probabilities"]
            calls: list[Call] = []
            escalation = None
            if route not in ("chat", "correction"):
                cap = next((c for c in capabilities if c.name == route), None)
                if cap is None:
                    raise KeyError(route)
                if cap.free_args or (cap.closed_args and not self._closed_args):
                    escalation = "needs_args"
                else:
                    calls = [Call(route, {x: answers[f"arg:{route}:{x}"]["choice"]
                                          for x in cap.closed_args})]
        except (KeyError, TypeError, ValueError):
            raise DeciderUnavailable("jev malformed response") from None

        return Decision(decider="jev", route=route, calls=calls, confidence=a.get("confidence"),
                        candidates=candidates, escalation=escalation, model=j.get("model"))
