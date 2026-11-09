import os

SPEAKER_PORT = 8768
PEER_URL = os.environ.get("CADENCE_PEER_URL", "ws://127.0.0.1:8770/peer")
ROOM = os.environ.get("CADENCE_SPEAKER_ROOM", "bedroom")
RECONNECT_S = 2.0
UNREACHABLE_SAY = "I can't reach my brain right now."

WAKE_ENABLED = os.environ.get("CADENCE_WAKE_ENABLED", "1") == "1"
WAKE_MODEL = "hey_jarvis_v0.1"
WAKE_THRESHOLD = 0.5
LISTEN_WINDOW_S = 8.0
BENCH_RECORD_DIR = os.environ.get("CADENCE_BENCH_RECORD_DIR")
ACK_DIR = "acks"

VOLUME_STEP = 0.1
MAX_VOLUME = 0.7  # speaker output ceiling: full volume is 70% of raw PCM level
