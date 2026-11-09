"""Central place for ports, paths, and URLs. Nothing else in `cadence` should
hardcode a URL or a port -- import it from here instead.
"""

import os

PEER_PORT = 8770
DB_PATH = "cadence.sqlite3"

JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"
JEV_TIMEOUT_S = 1.5
JEV_CLOSED_ARGS = True
TYPESAFE_ENV_PATH = os.path.expanduser("~/.config/cadence/typesafe.env")
CONF_MIN = 0.5
SHORTLIST_MIN = 0.25
CORRECTION_WINDOW_S = 60.0
