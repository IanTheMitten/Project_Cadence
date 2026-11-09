import uvicorn

from cadence_chat.config import CHAT_HOST, CHAT_PORT
from cadence_chat.server import app

uvicorn.run(app, host=CHAT_HOST, port=CHAT_PORT)
