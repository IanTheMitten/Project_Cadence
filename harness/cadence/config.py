"""Central place for ports, paths, and URLs. Nothing else in `cadence` should
hardcode a URL or a port -- import it from here instead.
"""

WS_PORT = 8768
DB_PATH = "cadence.sqlite3"
MCP_SERVERS = [["python", "-m", "cadence.muse"]]

MUSE_BASE_URL = "http://ianshomeserver:8080"
MUSE_PROXY_URL = "http://ianshomeserver:8765"
