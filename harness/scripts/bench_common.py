"""Shared tool surface, test set and scoring for the Jev/Needle/Laya benchmark.

Tool schemas for the 8 Muse tools are copied verbatim (name, description,
input_schema) from harness/cadence/muse/mcp_server.py at import time. The
`set_warmth` circadian-light tool is MADE UP for this benchmark.

Gold format: each utterance has `outcomes`, a list of acceptable first-step
results. An outcome is a list of expected calls ([] = "no tool"). A call is
{"name": str, "args": {key: spec}}. spec is a literal (exact match), or
{"any": [substr, ...]} (case-insensitive, string contains any), or
{"between": [lo, hi]}. Keys not listed are not checked. Only the FIRST step is
scored for multi-step requests (e.g. "play something jazzy" -> search_vibe;
`play` needs the search result first).
"""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_muse_defs() -> dict:
    """Import _TOOL_DEFS without needing the `mcp` package installed."""
    src = (ROOT / "cadence" / "muse" / "mcp_server.py").read_text()
    start = src.index("_TOOL_DEFS: dict[str, dict] = {")
    end = src.index("\n}\n", start) + 3
    ns: dict = {}
    exec(src[start:end], ns)  # noqa: S102 - literal dict from our own repo
    return ns["_TOOL_DEFS"]


MUSE_DEFS = _load_muse_defs()

SET_WARMTH = {
    "description": (
        "Set the circadian smart light: colour temperature in kelvin "
        "(1800 = candle-warm, 6500 = cool daylight) and optional brightness."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "kelvin": {"type": "integer", "minimum": 1800, "maximum": 6500},
            "brightness": {"type": "integer", "minimum": 0, "maximum": 100},
        },
        "required": ["kelvin"],
    },
}

ALL_DEFS = {**MUSE_DEFS, "set_warmth": SET_WARMTH}
TOOL_NAMES = list(ALL_DEFS)

# Environment facts given identically to every architecture.
CONTEXT = (
    "Home speaker assistant. Currently playing: track_rowid 3112. "
    "Time: 22:30 (evening). Lights are at 4000K, brightness 80."
)


def ollama_tools(names=None):
    return [
        {"type": "function", "function": {"name": n, "description": d["description"], "parameters": d["input_schema"]}}
        for n, d in ALL_DEFS.items()
        if names is None or n in names
    ]


# Needle-style user-phrased descriptions (per Cactus "designing tools for Needle"
# guide: describe what the user would say). Used only by the *_rewrite variants;
# names/parameters are unchanged. Written by the benchmark author, not the harness.
REWRITE = {
    "search_vibe": "Find music for a mood, vibe, genre or activity, e.g. 'something mellow', 'upbeat', 'jazz', 'focus music'. Put the mood words in query.",
    "search_text": "Look up a specific song, artist or album by name, e.g. 'search for Radiohead'. Put the name in query.",
    "recommend_next": "Suggest tracks that should play after or are similar to a given track number, e.g. 'what should play next', 'something like track 587'.",
    "play": "Play a specific track by its track number, e.g. 'play track 3112'.",
    "get_player_state": "Read what is playing now, whether it is paused, and the position in the song.",
    "set_player_state": "Change playback: pause, resume, skip, seek to a position, shuffle on/off, repeat mode (off, one, all), or replace the queue.",
    "get_dashboard": "Show the music library dashboard and listening statistics.",
    "rate": "Thumbs up (1) or thumbs down (-1) a track, e.g. 'I love this song', 'I hate track 2001'.",
    "set_warmth": "Change the room lights: warmer or cooler colour temperature in kelvin (1800 candle-warm to 6500 daylight) and brightness 0-100, e.g. 'warmer', 'dim to 20%', 'cozy'.",
}


def needle_tools(names=None, rewrite=False):
    return [
        {"name": n, "description": REWRITE[n] if rewrite else d["description"], "parameters": d["input_schema"]}
        for n, d in ALL_DEFS.items()
        if names is None or n in names
    ]


def C(name, **args):
    return {"name": name, "args": args}


# (id, category, utterance, outcomes)
TESTSET = [
    # --- search_vibe
    ("v1", "music_vibe", "play something mellow for dinner", [[C("search_vibe", query={"any": ["mellow", "dinner", "chill", "calm"]})]]),
    ("v2", "music_vibe", "I want some upbeat music to get me going", [[C("search_vibe", query={"any": ["upbeat", "energetic", "energy"]})]]),
    ("v3", "music_vibe", "find me something moody and rainy", [[C("search_vibe", query={"any": ["moody", "rain"]})]]),
    ("v4", "music_vibe", "put on some focus music, five options is plenty", [[C("search_vibe", query={"any": ["focus"]}, n=5)]]),
    ("v5", "music_vibe", "something that feels like a sunday morning", [[C("search_vibe", query={"any": ["sunday", "morning"]})]]),
    # --- search_text
    ("t1", "music_text", "search for Radiohead", [[C("search_text", query={"any": ["radiohead"]})]]),
    ("t2", "music_text", "look up the song Clair de Lune", [[C("search_text", query={"any": ["clair de lune"]})]]),
    ("t3", "music_text", "find songs by Khruangbin, give me 3", [[C("search_text", query={"any": ["khruangbin"]}, limit=3)]]),
    # --- recommend_next
    ("r1", "recommend", "what should play after this one", [[C("recommend_next", track_rowid=3112)]]),
    ("r2", "recommend", "queue up something similar to track 587", [[C("recommend_next", track_rowid=587)]]),
    ("r3", "recommend", "give me 4 tracks that follow this song", [[C("recommend_next", track_rowid=3112, n=4)]]),
    # --- play
    ("p1", "play", "play track 3112", [[C("play", track_rowid=3112)]]),
    ("p2", "play", "play song number 9045 please", [[C("play", track_rowid=9045)]]),
    ("p3", "play", "start track 12", [[C("play", track_rowid=12)]]),
    # --- state reads
    ("s1", "state_read", "what's playing right now?", [[C("get_player_state")]]),
    ("s2", "state_read", "is the music paused?", [[C("get_player_state")]]),
    ("s3", "state_read", "how far into this song are we", [[C("get_player_state")]]),
    # --- state writes
    ("w1", "state_write", "turn shuffle on", [[C("set_player_state", shuffle=True)]]),
    ("w2", "state_write", "set repeat to all", [[C("set_player_state", repeat_mode={"any": ["all"]})]]),
    ("w3", "state_write", "pause the music", [[C("set_player_state", client_state={"any": ["pause"]})]]),
    ("w4", "state_write", "jump back to the start of this song", [[C("set_player_state", position_ms=0)]]),
    # --- dashboard
    ("d1", "dashboard", "show me my library dashboard", [[C("get_dashboard")]]),
    ("d2", "dashboard", "how big is my music library and what have I been listening to", [[C("get_dashboard")]]),
    # --- rate
    ("q1", "rate", "I love this song", [[C("rate", track_rowid=3112, rating=1)]]),
    ("q2", "rate", "thumbs down, skip this trash", [[C("rate", track_rowid=3112, rating=-1)]]),
    ("q3", "rate", "give track 587 a thumbs up", [[C("rate", track_rowid=587, rating=1)]]),
    ("q4", "rate", "I hate track 2001", [[C("rate", track_rowid=2001, rating=-1)]]),
    # --- circadian light (made-up tool)
    ("l1", "light", "make the lights warmer", [[C("set_warmth", kelvin={"between": [1800, 3200]})]]),
    ("l2", "light", "set the light to 2700 kelvin", [[C("set_warmth", kelvin=2700)]]),
    ("l3", "light", "set the lights to 3000K at 40 percent brightness", [[C("set_warmth", kelvin=3000, brightness=40)]]),
    ("l4", "light", "dim the lights to 20%", [[C("set_warmth", brightness=20)]]),
    ("l5", "light", "give me cool daylight white", [[C("set_warmth", kelvin={"between": [5000, 6500]})]]),
    ("l6", "light", "candle glow please, super dim", [[C("set_warmth", kelvin={"between": [1800, 2200]}, brightness={"between": [0, 25]})]]),
    # --- chit-chat / no tool
    ("c1", "chat", "tell me a joke", [[]]),
    ("c2", "chat", "what's the capital of France?", [[]]),
    ("c3", "chat", "thanks, that was great", [[]]),
    ("c4", "chat", "how are you today", [[]]),
    ("c5", "chat", "what's the weather tomorrow", [[]]),
    ("c6", "chat", "set an alarm for 7am", [[]]),
    ("c7", "chat", "who sang Bohemian Rhapsody? just tell me, don't play it", [[]]),
    ("c8", "chat", "I'm bored", [[]]),
    # --- ambiguous / multi-step
    ("a1", "ambiguous", "make it cozy in here", [[C("set_warmth", kelvin={"between": [1800, 3200]})], [C("search_vibe", query={"any": ["cozy"]})], [C("set_warmth", kelvin={"between": [1800, 3200]}), C("search_vibe", query={"any": ["cozy"]})]]),
    ("a2", "ambiguous", "I'm going to bed", [[C("set_warmth", kelvin={"between": [1800, 2700]})], [C("set_player_state", client_state={"any": ["pause", "stop"]})], []]),
    ("a3", "multistep", "warm up the lights and play something chill", [[C("set_warmth", kelvin={"between": [1800, 3200]}), C("search_vibe", query={"any": ["chill", "calm", "relax"]})]]),
    ("a4", "multistep", "play some jazz", [[C("search_vibe", query={"any": ["jazz"]})], [C("search_text", query={"any": ["jazz"]})]]),
    ("a5", "multistep", "like this song and then play whatever should come next", [[C("rate", track_rowid=3112, rating=1), C("recommend_next", track_rowid=3112)], [C("rate", track_rowid=3112, rating=1)]]),
    ("a6", "ambiguous", "not this one", [[C("rate", track_rowid=3112, rating=-1)], [C("set_player_state", client_state={"any": ["skip", "next"]})], [C("recommend_next", track_rowid=3112)]]),
    ("a7", "ambiguous", "it's too bright in here", [[C("set_warmth", brightness={"between": [0, 50]})], [C("set_warmth", kelvin={"between": [1800, 3200]})]]),
]


def _match(spec, val):
    if isinstance(spec, dict):
        if "any" in spec:
            return isinstance(val, str) and any(s.lower() in val.lower() for s in spec["any"])
        if "between" in spec:
            try:
                return spec["between"][0] <= float(val) <= spec["between"][1]
            except (TypeError, ValueError):
                return False
    if isinstance(spec, bool) or isinstance(val, bool):
        return spec is val
    if isinstance(spec, (int, float)):
        try:
            return float(val) == float(spec)
        except (TypeError, ValueError):
            return False
    return spec == val


def score(pred_calls: list[dict], outcomes: list[list[dict]]) -> dict:
    """pred_calls: [{"name","arguments"}]. Returns per-item booleans.

    decision_ok: predicted "some call vs none" agrees with at least one outcome.
    name_ok: multiset of names equals some outcome's multiset.
    args_ok: name_ok AND every checked arg of every call matches (that outcome).
    """
    pn = sorted(c["name"] for c in pred_calls)
    decision_ok = any((len(o) == 0) == (len(pn) == 0) for o in outcomes)
    name_ok = False
    args_ok = False
    for o in outcomes:
        if sorted(c["name"] for c in o) != pn:
            continue
        name_ok = True
        remaining = list(pred_calls)
        all_ok = True
        for g in o:
            hit = None
            for p in remaining:
                if p["name"] == g["name"] and all(_match(s, (p.get("arguments") or {}).get(k)) for k, s in g["args"].items()):
                    hit = p
                    break
            if hit is None:
                all_ok = False
                break
            remaining.remove(hit)
        if all_ok:
            args_ok = True
            break
    return {"decision_ok": decision_ok, "name_ok": name_ok, "args_ok": args_ok}
