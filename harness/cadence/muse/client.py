"""HTTP client for the Muse library server.

Wraps all Muse operations behind a single ``httpx.Client``. Any connection
failure is turned into ``MuseUnavailable`` with exactly one attempt made —
no retry, no backoff.
"""

import httpx

DEFAULT_BASE_URL = "http://ianshomeserver:8080"
DEFAULT_PROXY_URL = "http://ianshomeserver:8765"


class MuseUnavailable(Exception):
    """Raised when the Muse server cannot be reached."""


class MuseClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        proxy_url: str = DEFAULT_PROXY_URL,
        transport=None,
    ):
        self.base_url = base_url
        self.proxy_url = proxy_url
        self._client = httpx.Client(
            base_url=base_url, timeout=10.0, transport=transport
        )

    def _get(self, path: str, params: dict | None = None) -> dict:
        try:
            response = self._client.get(path, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MuseUnavailable(str(exc)) from exc
        return response.json()

    def _send(self, method: str, path: str, json: dict | None = None) -> dict:
        try:
            response = self._client.request(method, path, json=json)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MuseUnavailable(str(exc)) from exc
        return response.json()

    def search_vibe(self, query: str, n: int = 10) -> list[dict]:
        data = self._get("/api/library/search/vibe", params={"q": query, "n": n})
        return data["results"]

    def search_text(self, query: str, limit: int = 10) -> list[dict]:
        data = self._get("/api/library/search", params={"q": query, "limit": limit})
        return data["results"]

    def recommend_next(self, track_rowid: int, n: int = 10) -> dict:
        return self._get(f"/api/recommend/{track_rowid}", params={"n": n})

    def play(self, track_rowid: int) -> str:
        return f"{self.proxy_url}/play/{track_rowid}"

    def get_player_state(self) -> dict:
        return self._get("/api/player/state")

    def set_player_state(
        self,
        queue: list[int],
        client_state: str,
        queue_index: int = 0,
        position_ms: int = 0,
        shuffle: bool = False,
        repeat_mode: str = "off",
    ) -> dict:
        if client_state not in ("playing", "paused", "idle"):
            raise ValueError(f"invalid client_state: {client_state!r}")
        body = {
            "queue": queue,
            "client_state": client_state,
            "queue_index": queue_index,
            "position_ms": position_ms,
            "shuffle": shuffle,
            "repeat_mode": repeat_mode,
        }
        return self._send("PUT", "/api/player/state", json=body)

    def get_dashboard(self) -> dict:
        return self._get("/api/dashboard")

    def rate(self, track_rowid: int, rating: int | None) -> dict:
        if rating not in (1, -1, None):
            raise ValueError(f"invalid rating: {rating!r}")
        body = {"track_rowid": track_rowid, "rating": rating}
        return self._send("POST", "/api/ratings", json=body)
