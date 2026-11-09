#!/usr/bin/env python3
"""Five live turns through the running harness; prints two markdown tables.

Run from harness/ with the server up on /peer, port 8770 (ws://127.0.0.1:8770/peer).
See docs/preflight/e2e-v1.md.
"""
import asyncio
import json
import os
import sys
import time

import websockets

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cadence.decisionlog import DecisionLog  # noqa: E402
from cadence.protocol import hello  # noqa: E402

URL = "ws://127.0.0.1:8770/peer"
UTTERANCES = [
    "play something chill",
    "what's playing",
    "pause the music",
    "tell me a joke",
    "no, I meant something upbeat",
]
TURN_TIMEOUT = 120


def cell(value, limit=200):
    return str(value).replace("|", "/").replace("\n", " ")[:limit]


async def turn(ws, text):
    t = time.perf_counter()
    await ws.send(json.dumps({"type": "event", "kind": "utterance", "payload": {"text": text}}))
    texts = []
    while True:
        msg = await asyncio.wait_for(ws.recv(), TURN_TIMEOUT)
        frame = json.loads(msg)
        if frame.get("type") == "turn_end":
            break
        if frame.get("type") == "say":
            texts.append(f"say: {frame['text']}")
        elif frame.get("type") == "error":
            texts.append(f"error: {frame.get('text') or frame.get('message')}")
    return (time.perf_counter() - t), texts


async def main():
    rows = []
    async with websockets.connect(URL, max_size=None) as ws:
        await ws.send(json.dumps(hello("smoke", "device", "text", None, ["text_out"], [])))
        welcome = json.loads(await ws.recv())
        if welcome.get("type") != "welcome":
            raise SystemExit(f"expected welcome, got {welcome}")
        for text in UTTERANCES:
            try:
                wall, texts = await turn(ws, text)
                rows.append((text, f"{wall:.2f}", "; ".join(texts)))
            except Exception as exc:  # record, keep going
                rows.append((text, "n/a", f"EXC {type(exc).__name__}: {exc}"))
    print("## Turns\n")
    print("| utterance | wall s | say/error frames |")
    print("|---|---|---|")
    for text, wall, extra in rows:
        print(f"| {cell(text)} | {wall} | {cell(extra)} |")
    print("\n## Decision log (last 5)\n")
    print("| text | route | decider | escalation | calls | outcome | latency_ms | labels |")
    print("|---|---|---|---|---|---|---|---|")
    for r in DecisionLog("cadence.sqlite3").export()[-5:]:
        print(f"| {cell(r['text'])} | {cell(r['route'])} | {cell(r['decider'])} | "
              f"{cell(r['escalation'])} | {cell(json.dumps(r['calls']))} | {cell(r['outcome'])} | "
              f"{cell(json.dumps(r['latency_ms']))} | {cell(json.dumps(r.get('labels')))} |")


if __name__ == "__main__":
    asyncio.run(main())
