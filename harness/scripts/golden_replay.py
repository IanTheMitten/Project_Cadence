#!/usr/bin/env python3
"""Replay harness/tests/golden/utterances.json against live Jev (closed args on) and score it.

Writes docs/research/data/jev_v1_golden.json and docs/preflight/jev-v1-golden.md. Sequential, no retries,
stops on the first DeciderUnavailable. The API key is never printed or saved.
"""
import asyncio
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(ROOT)
sys.path.insert(0, ROOT)

from cadence.catalogue import Catalogue  # noqa: E402
from cadence.deciders.base import DeciderUnavailable  # noqa: E402
from cadence.deciders.jev import JevDecider, load_api_key  # noqa: E402
from cadence.events import utterance  # noqa: E402
from cadence.plugins.music import MusicPlugin  # noqa: E402
from cadence.plugins.speaker import SpeakerPlugin  # noqa: E402

CONTEXT = {"time": "22:30", "weekday": "Tuesday", "room": "bedroom",
           "now_playing": {"track_name": "Weightless", "artist_name": "Marconi Union", "paused": False},
           "recent": []}
THRESHOLDS = (0.3, 0.5, 0.7, 0.9)


def pct(xs):
    return f"{100 * sum(xs) / len(xs):.1f}% ({sum(xs)}/{len(xs)})" if xs else "n/a"


def quantile(vals, q):
    s = sorted(vals)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))] if s else float("nan")


async def main():
    items = json.load(open(os.path.join(ROOT, "tests/golden/utterances.json")))["items"]
    caps = Catalogue([MusicPlugin(object()), SpeakerPlugin()]).available()
    jev = JevDecider(load_api_key())
    records, stopped = [], None
    for it in items:
        ev = utterance("golden", "bedroom", it["utterance"])
        t = time.perf_counter()
        try:
            d = await jev.decide(ev, CONTEXT, caps)
        except DeciderUnavailable as e:
            stopped = {"at_id": it["id"], "reason": str(e)}
            break
        ms = (time.perf_counter() - t) * 1000
        args = d.calls[0].args if d.calls else {}
        records.append({"id": it["id"], "utterance": it["utterance"], "routes": it["routes"],
                        "expected_args": it["args"], "route": d.route, "confidence": d.confidence,
                        "probabilities": d.candidates, "args": args, "latency_ms": round(ms, 1)})
    for r in records:
        r["route_ok"] = r["route"] in r["routes"]
        r["arg_scored"] = r["route"] == r["routes"][0] and bool(r["expected_args"])
        r["arg_ok"] = r["arg_scored"] and all(r["args"].get(k) == v for k, v in r["expected_args"].items())
    json.dump({"context": CONTEXT, "total_items": len(items), "stopped": stopped, "records": records},
              open(os.path.join(REPO, "docs/research/data/jev_v1_golden.json"), "w"), indent=1)

    L = ["# Jev v1 golden replay", "",
         f"Items replayed: {len(records)}/{len(items)}" + (f"; stopped at {stopped['at_id']}: {stopped['reason']}" if stopped else ""),
         "", f"Overall route accuracy: {pct([r['route_ok'] for r in records])}", "",
         "## Per-route accuracy (by expected first route)", "", "| route | accuracy |", "|---|---|"]
    for route in sorted({r["routes"][0] for r in records}):
        L.append(f"| {route} | {pct([r['route_ok'] for r in records if r['routes'][0] == route])} |")
    sc = [r for r in records if r["arg_scored"]]
    lat = [r["latency_ms"] for r in records]
    L += ["", f"Closed-arg accuracy: {pct([r['arg_ok'] for r in sc])}", "",
          f"Latency ms: p50 {quantile(lat, .5):.0f}, p95 {quantile(lat, .95):.0f}", "",
          "## Confidence thresholds", "",
          "| conf >= | route accuracy of kept | kept | escalated |", "|---|---|---|---|"]
    for th in THRESHOLDS:
        kept = [r for r in records if r["confidence"] is not None and r["confidence"] >= th]
        L.append(f"| {th} | {pct([r['route_ok'] for r in kept])} | {len(kept)} | "
                 f"{100 * (len(records) - len(kept)) / max(1, len(records)):.1f}% |")
    wrong = [r for r in records if not r["route_ok"]]
    L += ["", "## Misrouted", "", "| id | utterance | expected | got | conf |", "|---|---|---|---|---|"]
    L += [f"| {r['id']} | {r['utterance']} | {','.join(r['routes'])} | {r['route']} | {r['confidence']} |" for r in wrong]
    L += ["", "## Recommendation", "", "RECOMMENDATION_PLACEHOLDER", ""]
    open(os.path.join(REPO, "docs/preflight/jev-v1-golden.md"), "w").write("\n".join(L))
    print("\n".join(L))


asyncio.run(main())
