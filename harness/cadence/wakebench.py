"""Pure scoring library for the wake/ASR bench: detection, sweep, win rule, WER, loaders."""

import glob
import json
import math
import os
import re
from dataclasses import dataclass

REFRACTORY_S = 2.0
POSITIVE_WINDOW_S = 6.0
COMMAND_WINDOW_S = 15.0
FW_TARGET_PER_HOUR = 1 / 8
HIT_MARGIN = 0.10
ASR_WER_MARGIN = 0.02
EPS = 1e-9
THRESHOLD_GRID = tuple(round(i / 100, 2) for i in range(1, 100)) + tuple(
    round(0.99 + i / 1000, 3) for i in range(1, 10))

_BYTES_PER_SECOND = 32000  # 16 kHz s16le mono


@dataclass(frozen=True)
class Recording:
    pcm_path: str
    start_wall: float
    seconds: float


@dataclass(frozen=True)
class EngineResult:
    threshold: float
    hit_rate: float
    false_wakes: int
    fw_per_hour: float
    target_met: bool


@dataclass(frozen=True)
class AsrResult:
    name: str
    wer: float
    median_ms: float


def detections(trace, threshold, refractory_s=REFRACTORY_S):
    events = []
    for t, score in trace:
        if score >= threshold and (not events or t >= events[-1] + refractory_s):
            events.append(t)
    return events


def hit_rate(events, label_times, window_s=POSITIVE_WINDOW_S):
    if not label_times:
        return 0.0
    hits = sum(1 for lt in label_times if any(lt <= e <= lt + window_s for e in events))
    return hits / len(label_times)


def evaluate(traces, label_times, guided, background_s, threshold):
    if background_s <= 0:
        raise ValueError("no background audio")
    events = [e for trace in traces for e in detections(trace, threshold)]
    fw = sum(1 for e in events if not any(start <= e <= end for start, end in guided))
    per_hour = fw / (background_s / 3600)
    return EngineResult(threshold, hit_rate(events, label_times), fw, per_hour,
                        per_hour <= FW_TARGET_PER_HOUR + EPS)


def sweep(traces, label_times, guided, background_s, grid=THRESHOLD_GRID):
    results = [evaluate(traces, label_times, guided, background_s, th) for th in grid]
    met = [r for r in results if r.target_met]
    if met:
        return min(met, key=lambda r: (-r.hit_rate, r.threshold))
    return min(results, key=lambda r: (r.false_wakes, -r.hit_rate, r.threshold))


def board_wins(board, server):
    if server.hit_rate - board.hit_rate >= HIT_MARGIN - EPS:
        return False
    if board.false_wakes >= 2 * max(server.false_wakes, 1):
        return False
    return True


def normalize(text):
    return re.sub(r"[^a-z0-9' ]", " ", text.lower()).split()


def _edit_distance(ref, hyp):
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h)))
        prev = cur
    return prev[-1]


def wer(refs, hyps):
    if len(refs) != len(hyps):
        raise ValueError("refs and hyps differ in length")
    total = 0
    errors = 0
    for ref, hyp in zip(refs, hyps):
        r = normalize(ref)
        total += len(r)
        errors += _edit_distance(r, normalize(hyp))
    if total == 0:
        raise ValueError("no reference words")
    return errors / total


def pick_asr(results, baseline):
    base = next(r for r in results if r.name == baseline)
    ok = [r for r in results if r.wer <= base.wer + ASR_WER_MARGIN + EPS]
    return min(ok, key=lambda r: r.median_ms)


def load_recordings(directory):
    recs = []
    for meta_path in glob.glob(os.path.join(directory, "*.json")):
        if os.path.basename(meta_path).startswith("labels-"):
            continue
        pcm = meta_path[:-len(".json")] + ".pcm"
        if not os.path.exists(pcm):
            continue
        with open(meta_path) as f:
            meta = json.load(f)
        recs.append(Recording(pcm, meta["start_wall"], os.path.getsize(pcm) / _BYTES_PER_SECOND))
    return sorted(recs, key=lambda r: r.start_wall)


def load_labels(directory):
    labels = []
    for path in glob.glob(os.path.join(directory, "labels-*.jsonl")):
        with open(path) as f:
            labels.extend(json.loads(line) for line in f if line.strip())
    return sorted(labels, key=lambda d: d["t"])


def guided_spans(labels):
    spans = []
    start = None
    for lab in labels:
        if lab["kind"] == "session_start" and start is None:
            start = lab["t"]
        elif lab["kind"] == "session_end" and start is not None:
            spans.append((start, lab["t"]))
            start = None
    if start is not None:
        spans.append((start, math.inf))
    return spans


def background_seconds(recordings, spans):
    total = 0.0
    for rec in recordings:
        lo, hi = rec.start_wall, rec.start_wall + rec.seconds
        total += rec.seconds
        for s, e in spans:
            total -= max(0.0, min(hi, e) - max(lo, s))
    return total


def load_utterances(directory):
    utts = []
    for path in glob.glob(os.path.join(directory, "utt-*.pcm")):
        stem = os.path.basename(path)[:-len(".pcm")]
        utts.append((int(stem.rsplit("-", 1)[1]) / 1000, path))
    return sorted(utts)


def pair_commands(labels, utterances, window_s=COMMAND_WINDOW_S):
    used = set()
    pairs = []
    for lab in labels:
        if lab["kind"] != "command":
            continue
        for i, (wall, path) in enumerate(utterances):
            if i not in used and lab["t"] <= wall <= lab["t"] + window_s:
                used.add(i)
                pairs.append((lab["text"], path))
                break
    return pairs
