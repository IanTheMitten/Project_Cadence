"""Tests for the Muse client against captured Phase 1 fixtures.

Uses httpx.MockTransport so no real network call is ever made; the client is
injected with a mock transport per test. Fixtures live in
tests/fixtures/muse/ and were captured from the live Muse server.
"""

import json
from pathlib import Path

import httpx
import pytest

from cadence.muse.client import MuseClient, MuseUnavailable

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "muse"


def load_fixture(name):
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text())


def make_client(handler):
    return MuseClient(transport=httpx.MockTransport(handler))


def test_search_vibe_returns_candidate_list():
    fixture = load_fixture("search_vibe")

    def handler(request):
        assert request.url.path == "/api/library/search/vibe"
        return httpx.Response(200, json=fixture)

    client = make_client(handler)
    results = client.search_vibe("chill", n=5)

    assert isinstance(results, list)
    assert results
    for item in results:
        assert "track_rowid" in item
        assert "score" in item
        assert "track" in item
        track = item["track"]
        assert "track_name" in track
        assert "artist_name" in track
        assert "duration_ms" in track
        assert "playable" in track


def test_search_text_returns_tracks():
    fixture = load_fixture("search_text")

    def handler(request):
        assert request.url.path == "/api/library/search"
        return httpx.Response(200, json=fixture)

    client = make_client(handler)
    results = client.search_text("bieber", limit=5)

    assert isinstance(results, list)
    assert results
    for track in results:
        assert "track_name" in track
        assert "artist_name" in track
        assert "duration_ms" in track
        assert "playable" in track


def test_recommend_next_returns_seed_and_results():
    fixture = load_fixture("recommend_next")

    def handler(request):
        assert request.url.path == "/api/recommend/123458861"
        return httpx.Response(200, json=fixture)

    client = make_client(handler)
    result = client.recommend_next(123458861, n=5)

    assert "seed" in result
    assert "results" in result
    assert result["seed"] == 123458861


def test_play_returns_proxy_url():
    calls = []

    def handler(request):
        calls.append(request)
        raise AssertionError("play() must not perform any HTTP request")

    client = make_client(handler)
    url = client.play(123458861)

    assert url == "http://ianshomeserver:8765/play/123458861"
    assert calls == []


def test_get_player_state_has_queue_keys():
    fixture = load_fixture("player_state")

    def handler(request):
        assert request.url.path == "/api/player/state"
        return httpx.Response(200, json=fixture)

    client = make_client(handler)
    state = client.get_player_state()

    for key in ("queue", "queue_index", "position_ms", "shuffle", "repeat_mode"):
        assert key in state


def test_set_player_state_sends_required_fields():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler)
    client.set_player_state(queue=[43204, 152835], client_state="playing")

    assert "queue" in captured["body"]
    assert "client_state" in captured["body"]

    def bad_handler(request):
        raise AssertionError("no request should be sent for an invalid client_state")

    bad_client = make_client(bad_handler)
    with pytest.raises(ValueError):
        bad_client.set_player_state(queue=[43204], client_state="stopped")


def test_get_dashboard_has_sections():
    fixture = load_fixture("dashboard")

    def handler(request):
        assert request.url.path == "/api/dashboard"
        return httpx.Response(200, json=fixture)

    client = make_client(handler)
    dashboard = client.get_dashboard()

    for key in ("resume", "mixes", "recent_albums", "never_played", "forgotten"):
        assert key in dashboard


def test_rate_accepts_only_valid_ratings():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler)

    client.rate(123458861, 1)
    assert captured["body"] == {"track_rowid": 123458861, "rating": 1}

    client.rate(123458861, -1)
    assert captured["body"] == {"track_rowid": 123458861, "rating": -1}

    client.rate(123458861, None)
    assert captured["body"] == {"track_rowid": 123458861, "rating": None}

    def bad_handler(request):
        raise AssertionError("no request should be sent for an invalid rating")

    bad_client = make_client(bad_handler)
    with pytest.raises(ValueError):
        bad_client.rate(123458861, 5)


def test_unreachable_muse_raises_museunavailable():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("connection refused", request=request)

    client = make_client(handler)

    with pytest.raises(MuseUnavailable):
        client.get_player_state()

    assert len(calls) == 1
