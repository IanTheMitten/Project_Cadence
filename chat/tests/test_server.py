"""Tests for the chat bridge. Fake /peer link, no sockets."""
import asyncio

from fastapi.testclient import TestClient

import cadence_chat.server as server
from cadence_chat.link import LinkClosed


class FakeLink:
    def __init__(self, hello_msg):
        self.hello = hello_msg
        self.sent = []
        self.inbox = asyncio.Queue()
        self.closed = False

    async def send(self, msg):
        self.sent.append(msg)
        if msg.get("type") == "event":  # Cadence answers every utterance
            for reply in ({"type": "turn_start"}, {"type": "say", "text": "hi " + msg["payload"]["text"]}, {"type": "turn_end"}):
                await self.inbox.put(reply)

    async def recv(self):
        return await self.inbox.get()

    async def close(self):
        self.closed = True


def test_page_served():
    r = TestClient(server.app).get("/")
    assert r.status_code == 200 and "<title>Cadence</title>" in r.text


def test_text_becomes_utterance_and_say_comes_back(monkeypatch):
    links = []

    async def fake_open(url, hello_msg):
        links.append(FakeLink(hello_msg))
        return links[-1]

    monkeypatch.setattr(server.link_mod, "open_link", fake_open)
    with TestClient(server.app).websocket_connect("/ws") as ws:
        ws.send_text("  ")  # blank lines are dropped
        ws.send_text("there")
        assert [ws.receive_json() for _ in range(3)] == [
            {"type": "turn_start"}, {"type": "say", "text": "hi there"}, {"type": "turn_end"}]
    h = links[0].hello
    assert (h["role"], h["kind"], h["room"], h["caps"]) == ("device", "chat", server.ROOM, ["text_out"])
    assert h["peer_id"].startswith("chat-")
    assert links[0].sent == [{"type": "event", "kind": "utterance", "payload": {"text": "there"}}]


def test_unreachable_cadence_reports_error(monkeypatch):
    async def fail(url, hello_msg):
        raise LinkClosed()

    monkeypatch.setattr(server.link_mod, "open_link", fail)
    with TestClient(server.app).websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "error"
