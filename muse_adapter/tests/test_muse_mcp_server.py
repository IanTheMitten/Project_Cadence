"""Tests for the Muse MCP server's frozen eight-tool surface.

Drives the lowlevel `mcp.server.Server` handlers directly via
`get_request_handler("tools/list" | "tools/call")`, passing `ctx=None` since
none of these thin dispatch handlers touch the request context. A stub
`MuseClient` records calls; no real `MuseClient` and no network call is ever
made.
"""

import mcp_types as types
import pytest

from cadence_muse.client import MuseUnavailable
from cadence_muse.mcp_server import TOOL_NAMES, build_server

EXPECTED_TOOL_NAMES = [
    "get_dashboard",
    "get_player_state",
    "play",
    "rate",
    "recommend_next",
    "search_text",
    "search_vibe",
    "set_player_state",
]


class StubMuseClient:
    def __init__(self):
        self.calls = []

    def search_vibe(self, query, n=10):
        self.calls.append(("search_vibe", query, n))
        return []

    def search_text(self, query, limit=10):
        self.calls.append(("search_text", query, limit))
        return []

    def recommend_next(self, track_rowid, n=10):
        self.calls.append(("recommend_next", track_rowid, n))
        return {}

    def play(self, track_rowid):
        self.calls.append(("play", track_rowid))
        return "http://example/play/1"

    def get_player_state(self):
        self.calls.append(("get_player_state",))
        return {}

    def set_player_state(
        self,
        queue,
        client_state,
        queue_index=0,
        position_ms=0,
        shuffle=False,
        repeat_mode="off",
    ):
        self.calls.append(
            (
                "set_player_state",
                queue,
                client_state,
                queue_index,
                position_ms,
                shuffle,
                repeat_mode,
            )
        )
        return {}

    def get_dashboard(self):
        self.calls.append(("get_dashboard",))
        return {}

    def rate(self, track_rowid, rating):
        self.calls.append(("rate", track_rowid, rating))
        return {}


async def list_tools(server):
    entry = server.get_request_handler("tools/list")
    result = await entry.handler(None, None)
    return result.tools


async def call_tool(server, name, arguments):
    entry = server.get_request_handler("tools/call")
    params = types.CallToolRequestParams(name=name, arguments=arguments)
    return await entry.handler(None, params)


def test_tool_names_are_exactly_the_eight():
    assert sorted(TOOL_NAMES) == EXPECTED_TOOL_NAMES


async def test_listed_tools_match_tool_names():
    server = build_server(StubMuseClient())
    tools = await list_tools(server)
    assert {tool.name for tool in tools} == set(TOOL_NAMES)


async def test_every_tool_has_a_description_and_schema():
    server = build_server(StubMuseClient())
    tools = await list_tools(server)
    for tool in tools:
        assert tool.description
        assert tool.input_schema["type"] == "object"


async def test_search_vibe_schema_requires_query():
    server = build_server(StubMuseClient())
    tools = await list_tools(server)
    tool = next(t for t in tools if t.name == "search_vibe")
    schema = tool.input_schema

    assert "query" in schema["properties"]
    assert "n" in schema["properties"]
    assert "query" in schema["required"]


async def test_rate_schema_constrains_rating():
    server = build_server(StubMuseClient())
    tools = await list_tools(server)
    tool = next(t for t in tools if t.name == "rate")
    schema = tool.input_schema

    assert "track_rowid" in schema["required"]
    assert "rating" in schema["required"]
    rating_enum = schema["properties"]["rating"]["enum"]
    assert -1 in rating_enum
    assert 1 in rating_enum


async def test_call_search_vibe_dispatches_to_client():
    client = StubMuseClient()
    server = build_server(client)

    await call_tool(server, "search_vibe", {"query": "chill", "n": 3})

    assert client.calls == [("search_vibe", "chill", 3)]


async def test_call_play_dispatches_to_client():
    client = StubMuseClient()
    server = build_server(client)

    await call_tool(server, "play", {"track_rowid": 123458861})

    assert client.calls == [("play", 123458861)]


async def test_muse_unavailable_surfaces_as_tool_error():
    class FailingClient(StubMuseClient):
        def search_vibe(self, query, n=10):
            self.calls.append(("search_vibe", query, n))
            raise MuseUnavailable("muse offline")

    client = FailingClient()
    server = build_server(client)

    result = await call_tool(server, "search_vibe", {"query": "chill", "n": 3})

    assert result.is_error is True
    assert any("muse offline" in block.text for block in result.content)
    assert client.calls == [("search_vibe", "chill", 3)]
