import os

PEER_URL = os.environ.get("CADENCE_PEER_URL", "ws://127.0.0.1:8770/peer")
RECONNECT_S = 2.0
MUSE_BASE_URL = os.environ.get("CADENCE_MUSE_BASE_URL", "http://ianshomeserver:8080")
MUSE_PROXY_URL = os.environ.get("CADENCE_MUSE_PROXY_URL", "http://ianshomeserver:8765")
PAUSE_TIMEOUT_S = 600.0
PLAY_SOURCE = "cadence"
MUSE_CONTRACT_MAJOR = 1
DEFAULT_QUEUE_LEN = 10
MAX_QUEUE_LEN = 50
