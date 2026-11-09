#!/usr/bin/env python3
"""Wake bench preflight: do microWakeWord, openWakeWord and the Whisper models load.

Prints one markdown row per check: check | ok | detail | ms. Every check's
exceptions are caught and recorded. See docs/preflight/wake-bench-preflight.md.
"""
import hashlib
import os
import sys
import time
from datetime import date

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cadence_speaker.config import WAKE_MODEL  # noqa: E402

MWW_SHA256 = "21a7976add39ee24ec96c63d96b7aaa18e24d1d9824b963e451da8feb4b78b77"


def row(check, ok, detail, ms):
    detail = str(detail).replace("|", "/").replace("\n", " ")[:200]
    print(f"| {check} | {ok} | {detail} | {ms:.0f} |", flush=True)


def ms_since(t):
    return (time.perf_counter() - t) * 1000


def run(check, fn):
    t = time.perf_counter()
    try:
        ok, detail = fn()
        row(check, ok, detail, ms_since(t))
        return ok
    except Exception as e:  # noqa: BLE001 - record, never abort
        row(check, False, f"{type(e).__name__}: {e}", ms_since(t))
        return False


def mww():
    from pymicro_wakeword import MicroWakeWord, MicroWakeWordFeatures, Model

    m = MicroWakeWord.from_builtin(Model.HEY_JARVIS)
    path = m.model_path.decode() if isinstance(m.model_path, bytes) else m.model_path
    sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
    feats = MicroWakeWordFeatures()
    fired = any(
        m.process_streaming(f) is True for f in feats.process_streaming(bytes(32000))
    )
    ok = m.probability_cutoff == 0.97 and sha == MWW_SHA256 and not fired
    return ok, f"cutoff={m.probability_cutoff} sha256={sha[:12]} silence_fired={fired}"


def oww():
    from openwakeword.model import Model

    m = Model(wakeword_models=[WAKE_MODEL], inference_framework="onnx")
    out = m.predict(np.zeros(1280, np.int16))
    return WAKE_MODEL in out, f"keys={list(out)}"


def whisper(name):
    def go():
        from faster_whisper import WhisperModel

        model = WhisperModel(name, device="cpu", compute_type="int8")
        segs = list(
            model.transcribe(np.zeros(16000, np.float32), beam_size=1, vad_filter=True)[0]
        )
        return True, f"loaded, {len(segs)} segments on 1s silence"

    return go


def main() -> int:
    print(f"# Wake bench preflight ({date.today().isoformat()})")
    print()
    print("| check | ok | detail | ms |")
    print("|---|---|---|---|")
    results = [
        run("mww hey_jarvis", mww),
        run(f"oww {WAKE_MODEL}", oww),
    ]
    for name in ("small.en", "base.en", "distil-small.en"):
        results.append(run(f"whisper {name}", whisper(name)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
