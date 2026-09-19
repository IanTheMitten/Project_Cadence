"""MCP stdio server exposing the eight Muse tools.

Each tool is a thin pass-through to a single `MuseClient` method — no tool
performs more than one client call, and none of them choose a track; they
return candidates/state for the caller to decide on.
"""

import json

import mcp_types as types
from mcp.server import Server

from cadence.muse.client import MuseClient, MuseUnavailable

TOOL_NAMES: tuple[str, ...] = (
    "search_vibe",
    "search_text",
    "recommend_next",
    "play",
    "get_player_state",
    "set_player_state",
    "get_dashboard",
    "rate",
)

_TOOL_DEFS: dict[str, dict] = {
    "search_vibe": {
        "description": (
            "Return ranked candidate tracks matching a vibe. Returns "
            "candidates for you to choose between; it does not pick one."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "n": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    "search_text": {
        "description": (
            "Return ranked candidate tracks matching a text search. Returns "
            "candidates for you to choose between; it does not pick one."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    "recommend_next": {
        "description": (
            "Return ranked candidate tracks recommended to follow a given "
            "track. Returns candidates for you to choose between; it does "
            "not pick one."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "track_rowid": {"type": "integer"},
                "n": {"type": "integer", "default": 10},
            },
            "required": ["track_rowid"],
        },
    },
    "play": {
        "description": (
            "Return the playback URL for a track. Returns the URL for you "
            "to use; it does not decide which track to play."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "track_rowid": {"type": "integer"},
            },
            "required": ["track_rowid"],
        },
    },
    "get_player_state": {
        "description": (
            "Return the current player state. Returns state for you to "
            "read; it does not change it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "set_player_state": {
        "description": (
            "Set the player state (queue, playback status, position). "
            "Applies exactly the state you provide; it does not decide "
            "what to play next."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "queue": {"type": "array", "items": {"type": "integer"}},
                "client_state": {"type": "string"},
                "queue_index": {"type": "integer", "default": 0},
                "position_ms": {"type": "integer", "default": 0},
                "shuffle": {"type": "boolean", "default": False},
                "repeat_mode": {"type": "string", "default": "off"},
            },
            "required": ["queue", "client_state"],
        },
    },
    "get_dashboard": {
        "description": (
            "Return the library dashboard summary. Returns data for you "
            "to read; it does not choose what to surface."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "rate": {
        "description": (
            "Record a rating for a track. Applies exactly the rating you "
            "provide; it does not decide how to rate it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "track_rowid": {"type": "integer"},
                "rating": {"type": "integer", "enum": [-1, 1]},
            },
            "required": ["track_rowid", "rating"],
        },
    },
}


def build_server(client: MuseClient) -> Server:
    dispatch = {name: getattr(client, name) for name in TOOL_NAMES}

    async def on_list_tools(ctx, params):
        tools = [
            types.Tool(
                name=name,
                description=_TOOL_DEFS[name]["description"],
                input_schema=_TOOL_DEFS[name]["input_schema"],
            )
            for name in TOOL_NAMES
        ]
        return types.ListToolsResult(tools=tools)

    async def on_call_tool(ctx, params: types.CallToolRequestParams):
        arguments = params.arguments or {}
        try:
            result = dispatch[params.name](**arguments)
        except MuseUnavailable as exc:
            return types.CallToolResult(
                is_error=True,
                content=[types.TextContent(type="text", text=str(exc))],
            )
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(result))]
        )

    return Server("muse", on_list_tools=on_list_tools, on_call_tool=on_call_tool)
