"""Central place for ports, paths, and URLs. Nothing else in `cadence` should
hardcode a URL or a port -- import it from here instead.
"""

import os

WS_PORT = 8768
DB_PATH = "cadence.sqlite3"
MCP_SERVERS = [["python", "-m", "cadence.muse"]]

MUSE_BASE_URL = os.environ.get("CADENCE_MUSE_BASE_URL", "http://ianshomeserver:8080")
MUSE_PROXY_URL = os.environ.get("CADENCE_MUSE_PROXY_URL", "http://ianshomeserver:8765")
DEVICES_PATH = os.environ.get("CADENCE_DEVICES_PATH", "devices.json")
JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"
JEV_TIMEOUT_S = 1.5
JEV_CLOSED_ARGS = True
TYPESAFE_ENV_PATH = os.path.expanduser("~/.config/cadence/typesafe.env")
CONF_MIN = 0.5
SHORTLIST_MIN = 0.25
CORRECTION_WINDOW_S = 60.0
WAKE_ENABLED = os.environ.get("CADENCE_WAKE_ENABLED", "1") == "1"
WAKE_MODEL = "hey_jarvis_v0.1"
WAKE_THRESHOLD = 0.5
LISTEN_WINDOW_S = 8.0
ACK_DIR = "acks"
PAUSE_TIMEOUT_S = 600.0
VOLUME_STEP = 0.1
PLAY_SOURCE = "cadence"
MUSE_CONTRACT_MAJOR = 1
DEFAULT_QUEUE_LEN = 10
MAX_QUEUE_LEN = 50
