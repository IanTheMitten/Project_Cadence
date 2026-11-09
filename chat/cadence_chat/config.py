import os

CHAT_HOST = os.environ.get("CADENCE_CHAT_HOST", "0.0.0.0")
CHAT_PORT = int(os.environ.get("CADENCE_CHAT_PORT", "8771"))
PEER_URL = os.environ.get("CADENCE_PEER_URL", "ws://127.0.0.1:8770/peer")
ROOM = os.environ.get("CADENCE_CHAT_ROOM", "bedroom")  # music asked for in chat plays in this room
