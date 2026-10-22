#!/usr/bin/env python3
"""Per-task tokens split into uncached input, cached input and output, by arm (paired tasks as in ref_ablation.py).
Supports the read-is-cheap / write-is-expensive argument: position addressing reads more and writes less."""
import csv, glob, json, os, collections
import numpy as np
ER = "../editbench/runs"
import ast
_src = open("ref_ablation.py").read()
SETS = {k: {n: v[n] for n in ("text", "lines", "aligned", "ref") if n in v}
        for k, v in ast.literal_eval(_src[_src.index("SETS = {") + 7:_src.index("\ndef load(")]).items()}
def runs(bench, d, name):
    arm = "lines_anchored" if name in ("aligned", "ref") else name
    prefix = "canitedit" if bench == "canitedit" else "aider-refactor"
    out = {}
    for run in glob.glob(f"{ER}/{d}/{prefix}__*__{arm}__r0"):
        try: r = json.load(open(run + "/run.json"))
        except Exception: continue
        if r.get("invalid_reasons"): continue
        task = os.path.basename(run)[len(prefix) + 2:].rsplit("__", 3)[0]
        t = collections.Counter()
        for l in open(run + "/model_calls.jsonl", errors="replace"):
            try: c = json.loads(l)
            except Exception: continue
            u = c.get("usage") or {}
            if c.get("status") != 200 or not u: continue
            cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
            t["uncached"] += (u.get("prompt_tokens") or 0) - cached; t["cached"] += cached
            reasoning = (u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
            t["reasoning"] += reasoning; t["visible"] += (u.get("completion_tokens") or 0) - reasoning
            t["cost"] += c.get("cost_usd") or 0
        out[task] = t
    return out
for (bench, model), arms in SETS.items():
    if not all(os.path.isdir(f"{ER}/{d}") for d in arms.values()): print("missing dirs for", bench, model); continue
    data = {n: runs(bench, d, n) for n, d in arms.items()}
    common = sorted(set.intersection(*(set(v) for v in data.values())))
    print(f"\n{bench} / {model}: {len(common)} paired tasks (means per task, thousands of tokens)")
    print(f"  {'arm':6s} {'uncached in':>11s} {'cached in':>10s} {'cached %':>9s} {'visible out':>12s} {'reasoning':>10s} {'$':>8s}")
    for n in arms:
        m = {k: np.mean([data[n][t][k] for t in common]) for k in ("uncached", "cached", "visible", "reasoning", "cost")}
        print(f"  {n:6s} {m['uncached']/1e3:11.1f} {m['cached']/1e3:10.1f} {m['cached']/(m['cached']+m['uncached']):9.0%} {m['visible']/1e3:12.1f} {m['reasoning']/1e3:10.1f} {m['cost']:8.4f}")
