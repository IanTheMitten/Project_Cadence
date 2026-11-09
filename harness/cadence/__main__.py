"""Entry point: `python -m cadence` runs the /peer server and the schedule loop."""

import asyncio

import uvicorn

from cadence.config import PEER_PORT
from cadence.peers import app, get_runtime


async def main() -> None:
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=PEER_PORT))
    task = asyncio.create_task(get_runtime().core.run_schedules())
    try:
        await server.serve()
    finally:
        task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
