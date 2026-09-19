"""Entry point: `python -m cadence` runs the WebSocket server."""

import uvicorn

from cadence.config import WS_PORT
from cadence.server import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=WS_PORT)
