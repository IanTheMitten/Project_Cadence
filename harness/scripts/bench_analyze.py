"""Aggregate docs/research/data/*.json (from bench_run.py) into summary.json + a printed table.

Post-hoc variants computed from the raw logs, no re-running:
  *+suppressed   Needle calls withheld below its 0.1 confidence floor are treated as emitted
  laya_alone     stage 1 of laya_route only (decision + tool-name, no args possible)
"""
import json
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from bench_common import score  # noqa: E402

D = pathlib.Path(__file__).resolve().parents[2] / "docs" / "research" / "data"


def pct(xs, p):
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def acc(scores, key):
    return sum(s[key] for s in scores) / len(scores)


def summarize(name, recs, meta):
    r0 = [r for r in recs if r["rep"] == 0]
    sc = r0
    warm = [r["latency_ms"] for r in recs if not r["is_first_call_of_process"]]
    tool_items = [r for r in r0 if any(len(o) for o in r["gold_outcomes"]) and not any(len(o) == 0 for o in r["gold_outcomes"])]
    chat_items = [r for r in r0 if any(len(o) == 0 for o in r["gold_outcomes"]) and all(len(o) == 0 for o in r["gold_outcomes"])]
    cats = {}
    for r in r0:
        cats.setdefault(r["category"], []).append(r)
    out = {
        "n_items": len(r0),
        "decision_acc": acc(sc, "decision_ok"),
        "tool_name_acc": acc(sc, "name_ok"),
        "args_acc": acc(sc, "args_ok"),
        "args_acc_given_name_ok": (sum(r["args_ok"] for r in r0 if r["name_ok"]) / max(1, sum(r["name_ok"] for r in r0))),
        "false_positive_rate_on_chat": sum(bool(r["pred_calls"]) for r in chat_items) / len(chat_items) if chat_items else None,
        "miss_rate_on_tool_items": sum(not r["pred_calls"] for r in tool_items) / len(tool_items) if tool_items else None,
        "latency_ms_warm_p50": pct(warm, 50) if warm else None,
        "latency_ms_warm_p95": pct(warm, 95) if warm else None,
        "latency_ms_first_call": recs[0]["latency_ms"],
        "init_s": meta.get("init_s"),
        "rss_after_load_mb": meta.get("rss_after_load_mb"),
        "rss_peak_mb": meta.get("rss_peak_mb"),
        "n_latency_samples": len(warm),
        "by_category_name_acc": {c: acc(v, "name_ok") for c, v in cats.items()},
    }
    return out


def SK(d):
    return "jev" if d["arch"].startswith("jev") else "laya"


def main():
    summary = {}
    for f in sorted(D.glob("*.json")):
        if f.name == "summary.json":
            continue
        d = json.load(open(f))
        summary[d["arch"]] = summarize(d["arch"], d["records"], d)
        # deterministic-ness check across reps
        by = {}
        for r in d["records"]:
            by.setdefault(r["id"], set()).add(json.dumps(r["pred_calls"], sort_keys=True))
        summary[d["arch"]]["items_with_nondeterministic_output_across_reps"] = sum(len(v) > 1 for v in by.values())
        if d["arch"].startswith(("needle", "laya", "jev")):
            sup = []
            for r in d["records"]:
                if r["rep"] != 0:
                    continue
                ni = r["info"].get("needle", r["info"])
                calls = r["pred_calls"] or [{"name": c["name"], "arguments": c.get("arguments") or {}} for c in (ni.get("suppressed") or [])]
                sup.append({"conf": r["info"].get("confidence"), **score(calls, r["gold_outcomes"])})
            summary[d["arch"] + "+suppressed(post-hoc, Needle-withheld calls counted as emitted; for laya_* only rows where Laya passed to Needle)"] = {
                "decision_acc": acc(sup, "decision_ok"),
                "tool_name_acc": acc(sup, "name_ok"),
                "args_acc": acc(sup, "args_ok"),
            }
        if d["arch"].startswith(("laya_route", "jev_route")):
            alone = []
            for r in d["records"]:
                if r["rep"] != 0:
                    continue
                ch = r["info"][SK(d)]["choice"]
                calls = [] if ch == "none" else [{"name": ch, "arguments": {}}]
                # names only: args spec ignored by building name-only gold
                s = score(calls, [[{"name": c["name"], "args": {}} for c in o] for o in r["gold_outcomes"]])
                alone.append(s)
            summary[d["arch"] + "_stage1_alone"] = {
                "decision_acc": acc(alone, "decision_ok"),
                "tool_name_acc_single_tool_only": acc(alone, "name_ok"),
                "latency_ms_p50": pct([r["info"]["stage_ms"][SK(d)] for r in d["records"]], 50),
                "latency_ms_p95": pct([r["info"]["stage_ms"][SK(d)] for r in d["records"]], 95),
            }
        if d["arch"] in ("laya_gate", "jev_gate"):
            g = [(r["info"][SK(d)]["needs_tool_p"], any(len(o) for o in r["gold_outcomes"]) and not any(len(o) == 0 for o in r["gold_outcomes"]), all(len(o) == 0 for o in r["gold_outcomes"])) for r in d["records"] if r["rep"] == 0]
            summary[d["arch"] + "_stage1"] = {
                "mean_p_on_tool_items": statistics.mean(p for p, t, c in g if t),
                "mean_p_on_chat_items": statistics.mean(p for p, t, c in g if c),
            }
    json.dump(summary, open(D / "summary.json", "w"), indent=1)
    for k, v in summary.items():
        print(k, json.dumps({a: (round(b, 3) if isinstance(b, float) else b) for a, b in v.items() if a != "by_category_name_acc"}))


if __name__ == "__main__":
    main()
