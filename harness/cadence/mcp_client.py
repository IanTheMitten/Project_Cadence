"""Tool registry over MCP stdio servers.

Server commands come from the config list passed to `ToolRegistry`; this
module holds no reference to Muse or any other specific server — it only
knows how to launch stdio subprocesses, list their tools in Ollama's tool
format, and dispatch a call to whichever server owns a given tool name.
"""

import json
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class ToolRegistry:
    """Launches configured MCP servers over stdio and dispatches tool calls.

    `server_configs` is a list of `{"name": str, "command": str, "args": [str, ...]}`.
    """

    def __init__(self, server_configs: list[dict]):
        self._server_configs = server_configs
        self._sessions: dict[str, ClientSession] = {}
        self._tool_owner: dict[str, str] = {}
        self._exit_stack = AsyncExitStack()
        self._started = False
        self._tools: list[dict] = []

    async def start(self) -> None:
        if self._started:
            return
        for config in self._server_configs:
            params = StdioServerParameters(
                command=config["command"], args=config.get("args", [])
            )
            read, write = await self._exit_stack.enter_async_context(stdio_client(params))
            session = await self._exit_stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self._sessions[config["name"]] = session
        for server_name, session in self._sessions.items():
            result = await session.list_tools()
            for tool in result.tools:
                self._tool_owner[tool.name] = server_name
                self._tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description or "",
                            "parameters": tool.input_schema,
                        },
                    }
                )
        self._started = True

    async def aclose(self) -> None:
        await self._exit_stack.aclose()
        self._started = False

    def list_tools(self) -> list[dict]:
        return self._tools

    async def call(self, name: str, args: dict) -> dict:
        await self.start()
        server_name = self._tool_owner.get(name)
        if server_name is None:
            raise KeyError(f"unknown tool: {name}")
        result = await self._sessions[server_name].call_tool(name, args)
        text = "".join(getattr(block, "text", "") for block in result.content)
        if result.is_error:
            raise RuntimeError(text or f"tool {name} failed")
        return json.loads(text) if text else {}
