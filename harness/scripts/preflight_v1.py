#!/usr/bin/env python3
"""v1 runtime preflight: does each live dependency load/answer on this host.

Prints one markdown row per check: check | ok | detail | ms. Every check's
exceptions are caught and recorded. See docs/preflight/runtime-v1.md.
"""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MUSE_BASE = os.environ.get("CADENCE_MUSE_BASE_URL", "http://ianshomeserver:8080")
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


def _typesafe_key() -> str:
    """Read the key at runtime from ~/.config/cadence/typesafe.env. Never printed or saved."""
    for line in open(os.path.expanduser("~/.config/cadence/typesafe.env")):
        if line.startswith("TYPESAFE_API_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"")
    raise RuntimeError("TYPESAFE_API_KEY not found in ~/.config/cadence/typesafe.env")


def row(check, ok, detail, ms):
    detail = str(detail).replace("|", "/").replace("\n", " ")[:200]
    print(f"| {check} | {ok} | {detail} | {ms:.0f} |", flush=True)


def ms_since(t):
    return (time.perf_counter() - t) * 1000


def run(check, fn):
    t = time.perf_counter()
    try:
        detail = fn()
        row(check, "yes", detail, ms_since(t))
    except Exception as e:  # noqa: BLE001 - record, never abort
        row(check, "no", f"{type(e).__name__}: {e}", ms_since(t))


def asr():
    from cadence.audio.asr import Asr

    t = time.perf_counter()
    a = Asr()
    load = ms_since(t)
    row("asr load", "yes", "faster-whisper small.en", load)
    t = time.perf_counter()
    text = a.transcribe(bytes(32000))
    return f"transcribe 1s silence -> {text!r}"


def tts():
    from cadence.audio.tts import Tts

    t = time.perf_counter()
    k = Tts()
    row("tts load", "yes", "kokoro", ms_since(t))
    t = time.perf_counter()
    out = k.speak("Playing Weightless by Marconi Union.")
    return f"speak -> {len(out)} bytes"


def wake():
    import openwakeword
    from openwakeword.model import Model

    t = time.perf_counter()
    openwakeword.utils.download_models(model_names=["hey_jarvis_v0.1"])
    row("openwakeword download", "yes", "hey_jarvis_v0.1", ms_since(t))
    t = time.perf_counter()
    m = Model(wakeword_models=["hey_jarvis_v0.1"], inference_framework="onnx")
    row("openwakeword load", "yes", "onnx", ms_since(t))
    frame = np.zeros(1280, dtype=np.int16)
    t = time.perf_counter()
    for _ in range(50):
        m.predict(frame)
    return f"50 frames predict, {ms_since(t) / 50:.1f} ms/frame"


def jev():
    import httpx

    key = _typesafe_key()
    def q(instr, opts):
        return {"type": "choice", "instructions": instr, "criteria": {o: f"the answer is {o}" for o in opts}}

    questions = {
        "route": q("Which function best serves the request?", ["search_text", "set_player_state", "none"]),
        "arg:kind": q("Is the request for a track or an artist?", ["track", "artist"]),
        "arg:when": q("Should it happen now or later?", ["now", "later"]),
        "arg:loud": q("Is the user asking for louder or quieter?", ["louder", "quieter"]),
    }
    body = {"state": "User said: play weightless by marconi union", "model": "jev-latest",
            "questions": questions}
    try:
        r = httpx.post("https://api.typesafe.ai/v1/systemone",
                       headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                       json=body, timeout=60)
    except Exception as e:
        raise RuntimeError(f"transport error: {type(e).__name__}") from None
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:150]}")
    j = r.json()
    answers = j.get("answers")
    keys = list(questions)
    got = sum(1 for k in keys if isinstance(answers, dict) and k in answers)
    shape = type(answers).__name__
    return f"model={j.get('model')} answers_type={shape} keys_back={got}/4 all={got == 4}"


def ollama():
    import httpx

    r = httpx.post(f"{OLLAMA_URL}/api/chat", timeout=120, json={
        "model": "gemma4:31b-cloud", "stream": False,
        "messages": [{"role": "user", "content": "Say hi in one word."}]})
    r.raise_for_status()
    return f"reply={r.json().get('message', {}).get('content', '')[:60]!r}"


def muse():
    import httpx

    r = httpx.get(f"{MUSE_BASE}/api/health", timeout=10)
    return f"GET {MUSE_BASE}/api/health -> HTTP {r.status_code}"


def main():
    print("| check | ok | detail | ms |")
    print("|---|---|---|---|")
    run("asr transcribe", asr)
    run("tts speak", tts)
    run("openwakeword predict", wake)
    run("jev multi-question", jev)
    run("ollama gemma4:31b-cloud", ollama)
    run("muse health", muse)


if __name__ == "__main__":
    main()
