import uvicorn

from cadence_speaker.config import SPEAKER_PORT
from cadence_speaker.server import app

uvicorn.run(app, host="0.0.0.0", port=SPEAKER_PORT)
