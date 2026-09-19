"""Entry point: `python -m cadence.muse` serves the Muse MCP server over stdio."""

import asyncio

from mcp.server.stdio import stdio_server

from cadence.muse.client import MuseClient
from cadence.muse.mcp_server import build_server


async def main() -> None:
    client = MuseClient()
    server = build_server(client)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
