#!/usr/bin/env python3
"""Guided wake/command labelling; writes labels-<ms>.jsonl for the bench loaders.

Run from harness/. See docs/specs/2026-10-06-speaker-firmware-wake.md.
"""
import argparse
import json
import os
import time

COMMANDS = [
    "what's playing",
    "turn it up",
    "turn it down",
    "pause the music",
    "resume the music",
    "skip this song",
    "play something chill",
    "play some jazz",
    "I like this song",
    "who sings this",
    "make it quieter",
    "mute the speaker",
    "unmute the speaker",
    "play the next track",
    "what album is this",
    "tell me a joke",
    "play something upbeat",
    "go back to the previous song",
    "stop the music",
    "how are you today",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.environ.get("CADENCE_BENCH_RECORD_DIR", "bench_audio"))
    ap.add_argument("--block", required=True, choices=["wake", "commands"])
    ap.add_argument("--reps", type=int, default=10)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    dry = args.dry_run

    f = None
    if not dry:
        os.makedirs(args.dir, exist_ok=True)
        f = open(os.path.join(args.dir, f"labels-{int(time.time() * 1000)}.jsonl"), "w")

    def write(obj):
        if f:
            f.write(json.dumps(obj) + "\n")
            f.flush()

    def ready(prompt):
        if dry:
            print("READY: " + prompt)
        else:
            input(prompt)

    def sleep(s):
        if not dry:
            time.sleep(s)

    try:
        write({"kind": "session_start", "t": time.time(), "block": args.block})
        if args.block == "wake":
            for condition in ("quiet", "music"):
                for distance in (1, 3, 5):
                    extra = "; start music at normal listening volume first" if condition == "music" else ""
                    ready(f"Stand {distance} m from the speaker ({condition}{extra}). Press Enter when ready: ")
                    for i in range(1, args.reps + 1):
                        print(f"[{i}/{args.reps}] Say 'hey jarvis' now")
                        write({"kind": "wake", "t": time.time(), "distance_m": distance, "condition": condition})
                        sleep(6.0)  # matches cadence.wakebench.POSITIVE_WINDOW_S
                        sleep(2.0)
        else:
            ready("Stand 3 m from the speaker, music off. Press Enter when ready: ")
            for cmd in COMMANDS:
                print(f"Say: 'hey jarvis', pause one second, then '{cmd}'")
                write({"kind": "command", "t": time.time(), "text": cmd})
                sleep(15.0)  # matches COMMAND_WINDOW_S
    finally:
        write({"kind": "session_end", "t": time.time()})
        if f:
            f.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
