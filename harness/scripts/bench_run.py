"""Run one architecture over the test set and dump raw per-call records as JSON.

Usage (needs a venv with `cactus-needle`, `laya`, `torch`, `httpx`):
  NEEDLE_TELEMETRY=0 python bench_run.py --arch needle --reps 3 --out ../../docs/research/data/needle.json

arch:
  cloud       single LLM (ollama gemma4:31b-cloud) decides + calls tools (baseline A; mirrors cadence/llm.py)
  needle      Needle 3 alone, all 9 tools (D)
  laya_gate   Laya noul "needs a tool?" gate -> Needle with all 9 tools (C1)
  needle_rewrite / laya_route_rewrite  same but with user-phrased tool descriptions (bench_common.REWRITE)
  laya_route  Laya choice over tools (+none) -> Needle given only the shortlisted tools (C2)
  (Laya alone = stage 1 of laya_route, scored on decision + tool name only)
  jev_gate / jev_route / jev_route_rewrite  same as laya_* but stage 1 is the hosted TypeSafe Jev API.
The Jev key is read at runtime from ~/.config/cadence/typesafe.env and is never printed or saved; a 4xx/429/529 stops the run.

Each record is a decision log entry (what the finetuning path would need):
utterance, context, stage outputs incl. probabilities/confidence, final calls, latencies.
"""
import argparse
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("NEEDLE_TELEMETRY", "0")
os.environ.setdefault("DO_NOT_TRACK", "1")
from bench_common import ALL_DEFS, CONTEXT, TESTSET, needle_tools, ollama_tools, score  # noqa: E402


def rss_hwm_mb() -> float:
    for line in open("/proc/self/status"):
        if line.startswith("VmHWM"):
            return int(line.split()[1]) / 1024
    return float("nan")


def rss_mb() -> float:
    for line in open("/proc/self/status"):
        if line.startswith("VmRSS"):
            return int(line.split()[1]) / 1024
    return float("nan")


# ---------------------------------------------------------------- cloud
class Cloud:
    name = "cloud"

    def __init__(self):
        import httpx

        self.httpx = httpx
        self.tools = ollama_tools()

    def run(self, utt):
        t = time.perf_counter()
        r = self.httpx.post(
            "http://localhost:11434/api/chat",
            json={
                "model": "gemma4:31b-cloud",
                "messages": [{"role": "system", "content": CONTEXT}, {"role": "user", "content": utt}],
                "tools": self.tools,
                "stream": False,
                "think": False,
            },
            timeout=120,
        )
        dt = time.perf_counter() - t
        m = r.json()["message"]
        calls = [{"name": c["function"]["name"], "arguments": c["function"].get("arguments") or {}} for c in m.get("tool_calls") or []]
        return calls, {"stage_ms": {"llm": dt * 1000}, "text": m.get("content", ""), "http": r.status_code}, dt


# ---------------------------------------------------------------- needle
class NeedleArch:
    name = "needle"
    rewrite = False

    def __init__(self):
        import needle

        self.needle = needle
        t = time.perf_counter()
        self.agents = {}
        self.get_agent(None)
        self.load_s = time.perf_counter() - t

    def get_agent(self, names):
        key = None if names is None else tuple(sorted(names))
        if key not in self.agents:
            self.agents[key] = self.needle.Needle(tools=needle_tools(names, self.rewrite), system=CONTEXT)
        return self.agents[key]

    def call(self, utt, names=None):
        t0 = time.perf_counter()
        a = self.get_agent(names)
        t1 = time.perf_counter()
        a.reset()
        out = a.complete(utt)
        t2 = time.perf_counter()
        calls = [{"name": c["name"], "arguments": c.get("arguments") or {}} for c in out.get("function_calls") or []]
        info = {
            "confidence": out.get("confidence"),
            "suppressed": out.get("suppressed_calls"),
            "reasoning": out.get("reasoning"),
            "validation": out.get("validation"),
            "engine_peak_ram_mb": out.get("peak_ram_mb"),
            "decode_tps": out.get("decode_tps"),
            "tools_offered": names or list(ALL_DEFS),
        }
        return calls, info, {"agent_get_ms": (t1 - t0) * 1000, "needle_ms": (t2 - t1) * 1000}

    def run(self, utt):
        calls, info, tm = self.call(utt)
        info["stage_ms"] = {"needle": tm["needle_ms"]}
        return calls, info, tm["needle_ms"] / 1000


# ---------------------------------------------------------------- laya
class NeedleRewrite(NeedleArch):
    name = "needle_rewrite"
    rewrite = True


class LayaBase(NeedleArch):
    def __init__(self):
        super().__init__()
        from laya import Router

        t = time.perf_counter()
        self.router = Router()
        # force-load the English checkpoint now (load cost reported separately)
        self.router.predict("warmup", {"x": {"type": "noul", "instructions": "Is this a greeting?"}}, model="english")
        self.laya_load_s = time.perf_counter() - t

    def laya(self, questions, utt):
        t = time.perf_counter()
        r = self.router.predict(f"{CONTEXT}\nUser said: {utt}", questions, model="english")
        return r["answers"], (time.perf_counter() - t) * 1000


GATE_Q = {
    "needs_tool": {
        "type": "noul",
        "instructions": (
            "The user asks the device to DO something with music playback, the music library, "
            "track ratings, or the room lighting (colour temperature or brightness). "
            "Chit-chat, general questions, thanks, or requests the device cannot perform do not count."
        ),
    }
}

ROUTE_CRITERIA = {
    "search_vibe": "wants music matching a mood, vibe, genre, feeling, or activity",
    "search_text": "wants to find a specific song, artist, or album by name",
    "recommend_next": "asks what should play next, or for tracks similar to or following a given track",
    "play": "asks to play a specific track by its number",
    "get_player_state": "asks what is playing, whether music is paused, or the playback position",
    "set_player_state": "wants to pause, resume, skip, seek, shuffle, repeat, or change the queue",
    "get_dashboard": "asks for the library dashboard or statistics",
    "rate": "likes or dislikes a track and wants it rated (thumbs up or down)",
    "set_warmth": "wants the lights warmer, cooler, dimmer, brighter, or a specific colour temperature",
    "none": "chit-chat, a general question, thanks, or a request no listed function can perform",
}
ROUTE_Q = {"tool": {"type": "choice", "instructions": "Which single device function best serves the user's request?", "criteria": ROUTE_CRITERIA}}


class LayaGate(LayaBase):
    name = "laya_gate"

    def run(self, utt):
        ans, laya_ms = self.laya(GATE_Q, utt)
        p = ans["needs_tool"]["noul"]
        info = {"laya": {"needs_tool_p": p, "raw": ans["needs_tool"]}, "stage_ms": {"laya": laya_ms}}
        if p < 0.5:
            info["stage_ms"]["needle"] = 0.0
            return [], info, laya_ms / 1000
        calls, ninfo, tm = self.call(utt)
        info["needle"] = ninfo
        info["stage_ms"]["needle"] = tm["needle_ms"]
        return calls, info, (laya_ms + tm["needle_ms"]) / 1000


class LayaRoute(LayaBase):
    name = "laya_route"

    def run(self, utt):
        ans, laya_ms = self.laya(ROUTE_Q, utt)
        probs = ans["tool"]["probabilities"]
        top = ans["tool"]["choice"]
        info = {"laya": {"choice": top, "probabilities": probs, "confidence": ans["tool"].get("confidence")}, "stage_ms": {"laya": laya_ms}}
        if top == "none":
            info["stage_ms"]["needle"] = 0.0
            return [], info, laya_ms / 1000
        short = [k for k, v in sorted(probs.items(), key=lambda kv: -kv[1]) if k != "none" and v >= 0.25][:2] or [top]
        info["shortlist"] = short
        calls, ninfo, tm = self.call(utt, short)
        info["needle"] = ninfo
        info["stage_ms"]["needle"] = tm["needle_ms"]
        info["stage_ms"]["agent_get"] = tm["agent_get_ms"]
        return calls, info, (laya_ms + tm["needle_ms"] + tm["agent_get_ms"]) / 1000


class LayaRouteRewrite(LayaRoute):
    name = "laya_route_rewrite"
    rewrite = True


# ---------------------------------------------------------------- jev (hosted, TypeSafe)
def _typesafe_key() -> str:
    """Read the key at runtime from ~/.config/cadence/typesafe.env. Never printed or saved."""
    for line in open(os.path.expanduser("~/.config/cadence/typesafe.env")):
        if line.startswith("TYPESAFE_API_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"")
    raise SystemExit("TYPESAFE_API_KEY not found in ~/.config/cadence/typesafe.env")


class JevStop(Exception):
    pass


class JevMixin:
    def jev_init(self):
        import httpx

        self._key = _typesafe_key()
        self.client = httpx.Client(timeout=60)
        self.api_calls = 0

    def jev(self, questions, utt):
        t = time.perf_counter()
        try:
            r = self.client.post(
                "https://api.typesafe.ai/v1/systemone",
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json={"state": f"{CONTEXT}\nUser said: {utt}", "model": "jev-latest", "questions": questions},
            )
        except Exception as e:  # message only, never headers
            raise JevStop(f"jev transport error: {type(e).__name__}") from None
        dt = (time.perf_counter() - t) * 1000
        self.api_calls += 1
        if r.status_code in (429, 529) or r.status_code >= 400:
            raise JevStop(f"jev HTTP {r.status_code} after {self.api_calls} calls (stopping, not retrying): {r.text[:200]}")
        j = r.json()
        return j["answers"], dt, {"model": j.get("model"), "usage": j.get("usage")}


class JevGate(NeedleArch, JevMixin):
    name = "jev_gate"

    def __init__(self):
        NeedleArch.__init__(self)
        self.jev_init()

    def run(self, utt):
        ans, ms, meta = self.jev(GATE_Q, utt)
        p = ans["needs_tool"]["noul"]
        info = {"jev": {"needs_tool_p": p, **meta}, "stage_ms": {"jev": ms}}
        if p < 0.5:
            info["stage_ms"]["needle"] = 0.0
            return [], info, ms / 1000
        calls, ninfo, tm = self.call(utt)
        info["needle"] = ninfo
        info["stage_ms"]["needle"] = tm["needle_ms"]
        return calls, info, (ms + tm["needle_ms"]) / 1000


class JevRoute(NeedleArch, JevMixin):
    name = "jev_route"

    def __init__(self):
        NeedleArch.__init__(self)
        self.jev_init()

    def run(self, utt):
        ans, ms, meta = self.jev(ROUTE_Q, utt)
        a = ans["tool"]
        probs = a["probabilities"]
        top = a["choice"]
        info = {"jev": {"choice": top, "probabilities": probs, "confidence": a.get("confidence"), **meta}, "stage_ms": {"jev": ms}}
        if top == "none":
            info["stage_ms"]["needle"] = 0.0
            return [], info, ms / 1000
        short = [k for k, v in sorted(probs.items(), key=lambda kv: -kv[1]) if k != "none" and v >= 0.25][:2] or [top]
        info["shortlist"] = short
        calls, ninfo, tm = self.call(utt, short)
        info["needle"] = ninfo
        info["stage_ms"]["needle"] = tm["needle_ms"]
        info["stage_ms"]["agent_get"] = tm["agent_get_ms"]
        return calls, info, (ms + tm["needle_ms"] + tm["agent_get_ms"]) / 1000


class JevRouteRewrite(JevRoute):
    name = "jev_route_rewrite"
    rewrite = True



ARCHES = {"jev_gate": JevGate, "jev_route": JevRoute, "jev_route_rewrite": JevRouteRewrite, "cloud": Cloud, "needle": NeedleArch, "needle_rewrite": NeedleRewrite, "laya_route_rewrite": LayaRouteRewrite, "laya_gate": LayaGate, "laya_route": LayaRoute}


def pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arch", required=True, choices=list(ARCHES))
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    rss0 = rss_mb()
    t = time.perf_counter()
    arch = ARCHES[a.arch]()
    init_s = time.perf_counter() - t
    rss_loaded = rss_mb()
    records = []
    first = True
    for rep in range(a.reps):
        for uid, cat, utt, outcomes in TESTSET:
            try:
                calls, info, lat = arch.run(utt)
            except Exception as e:
                if type(e).__name__ == "JevStop":
                    print("STOPPED:", e)
                    json.dump({"arch": a.arch, "stopped": str(e)[:300], "records_done": len(records)}, open(a.out + ".stopped", "w"))
                    sys.exit(3)
                raise
            sc = score(calls, outcomes)
            records.append(
                {
                    "rep": rep,
                    "id": uid,
                    "category": cat,
                    "utterance": utt,
                    "gold_outcomes": outcomes,
                    "pred_calls": calls,
                    "latency_ms": lat * 1000,
                    "is_first_call_of_process": first,
                    "info": info,
                    **sc,
                }
            )
            first = False
    out = {
        "arch": a.arch,
        "reps": a.reps,
        "n_items": len(TESTSET),
        "init_s": init_s,
        "rss_before_mb": rss0,
        "rss_after_load_mb": rss_loaded,
        "rss_peak_mb": rss_hwm_mb(),
        "cpu_count": os.cpu_count(),
        "records": records,
    }
    json.dump(out, open(a.out, "w"), indent=1, default=str)
    lat = [r["latency_ms"] for r in records]
    warm = [r["latency_ms"] for r in records if not r["is_first_call_of_process"]]
    print(a.arch, "n=", len(records), "decision", statistics.mean(r["decision_ok"] for r in records if r["rep"] == 0),
          "name", statistics.mean(r["name_ok"] for r in records if r["rep"] == 0),
          "args", statistics.mean(r["args_ok"] for r in records if r["rep"] == 0),
          "p50/p95 warm", pct(warm, 50), pct(warm, 95), "first", records[0]["latency_ms"], "rss_peak", rss_hwm_mb())


if __name__ == "__main__":
    main()
