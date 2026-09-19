"""Capture real JSON responses from the Muse API as test fixtures.

Hits the live Muse server directly and saves each response under
tests/fixtures/muse/. Read-only by design: never PUTs player state and
never sends a non-empty ratings POST, so the live library is untouched.
"""

import json
import sys
from pathlib import Path

import httpx

MUSE_BASE = "http://ianshomeserver:8080"
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "muse"
MAX_ENTRIES = 5

FETCHES = [
    ("search_vibe", "GET", "/api/library/search/vibe", {"q": "chill", "n": 5}, 200),
    ("search_text", "GET", "/api/library/search", {"q": "bieber", "limit": 5}, 200),
    ("recommend_next", "GET", "/api/recommend/123458861", {"n": 5}, 200),
    ("player_state", "GET", "/api/player/state", None, 200),
    ("dashboard", "GET", "/api/dashboard", None, 200),
    ("openapi", "GET", "/openapi.json", None, 200),
    ("ratings_422", "POST", "/api/ratings", {}, 422),
]


def truncate_lists(body):
    """Truncate every top-level list value to at most MAX_ENTRIES entries."""
    if not isinstance(body, dict):
        return body
    for key, value in body.items():
        if isinstance(value, list):
            body[key] = value[:MAX_ENTRIES]
    return body


def main():
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    client = httpx.Client(base_url=MUSE_BASE, timeout=10.0)

    for name, method, path, params_or_json, expected_status in FETCHES:
        if method == "GET":
            resp = client.get(path, params=params_or_json)
        else:
            resp = client.post(path, json=params_or_json)

        body = resp.json()
        if name in ("dashboard", "search_vibe", "search_text"):
            body = truncate_lists(body)

        out_path = FIXTURES_DIR / f"{name}.json"
        text = json.dumps(body, indent=2)
        num_bytes = out_path.write_text(text)

        print(f"FIXTURE {name} {resp.status_code} {num_bytes}")

        if resp.status_code != expected_status:
            print(f"MUSE UNREACHABLE: {name} {resp.status_code}")
            sys.exit(1)


if __name__ == "__main__":
    main()
