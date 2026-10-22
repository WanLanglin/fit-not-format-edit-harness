#!/usr/bin/env python3
"""Two replicates (r0 = original runs, r1 = *-rep1 runs, same builds and settings) for the headline arms:
refactor luna/MiMo (text, lines, ref) and CanItEdit luna (text, patch, lines, ref). Reports each replicate and the
pooled result; pooled efficiency = total solved / total output tokens over both replicates, relative to search/replace,
with a bootstrap that resamples tasks and keeps both replicates of a task together."""
import math, os
import numpy as np
from pathlib import Path
here = os.getcwd()
ns = {}; exec(open("method_table.py").read().split("rng = np.random.default_rng(0); B = 2000")[0], ns)   # refactor loader
ns2 = {}; exec(open("ref_ablation.py").read().split("rng = np.random.default_rng(0); B = 2000")[0], ns2)      # canitedit loader
R = {"refactor": {
        "GPT-5.6-luna": {"text": [("refactor-luna-5arms", "text"), ("refactor-luna-rep1", "text")],
                         "lines": [("refactor-luna-5arms", "lines"), ("refactor-luna-rep1", "lines")],
                         "ref": [("refactor-luna-ref", "lines_anchored"), ("refactor-luna-ref-rep1", "lines_anchored")]},
        "MiMo-v2.5-Pro": {"text": [("refactor-mimo-3arms", "text"), ("refactor-mimo-rep1", "text")],
                          "lines": [("refactor-mimo-3arms", "lines"), ("refactor-mimo-rep1", "lines")],
                          "ref": [("refactor-mimo-ref", "lines_anchored"), ("refactor-mimo-ref-rep1", "lines_anchored")]}},
     "canitedit": {
        "GPT-5.6-luna": {"text": [("canitedit-luna-4arms", "text"), ("canitedit-luna-rep1", "text")],
                         "patch": [("canitedit-luna-4arms", "patch"), ("canitedit-luna-rep1", "patch")],
                         "lines": [("canitedit-luna-4arms", "lines"), ("canitedit-luna-rep1", "lines")],
                         "ref": [("canitedit-luna-ref", "ref"), ("canitedit-luna-ref-rep1", "ref")]}}}
def load(bench, d, arm):
    if bench == "refactor": return ns["load"](d, arm, arm == "lines_anchored")
    return ns2["load"]("canitedit", d, arm)
def mcn(g, l):
    m = g + l; return 1.0 if not m else min(1.0, 2 * sum(math.comb(m, i) for i in range(min(g, l) + 1)) / 2 ** m)
rng = np.random.default_rng(0); B = 2000
for bench, models in R.items():
    for model, arms in models.items():
        data = {a: [load(bench, d, x) for d, x in reps] for a, reps in arms.items()}
        common = sorted(set.intersection(*(set(r) for reps in data.values() for r in reps)))
        print(f"\n=== {bench} / {model}: {len(common)} tasks valid in every arm and both replicates")
        def stat(rs):
            f = [r["first"] for r in rs if r["first"] is not None]; ap = [r for r in rs if r["first"] and r["broken"] is not None]
            return dict(success=np.mean([r["passed"] for r in rs]), first=np.mean(f), broken=(sum(r["broken"] for r in ap), len(ap)),
                        clean=sum(bool(r["first"]) and r["broken"] is False for r in rs) / len(rs), out=np.mean([r["out"] for r in rs]) / 1000)
        for a in arms:
            per = [stat([data[a][k][t] for t in common]) for k in (0, 1)]
            line = " | ".join(f"r{k}: succ {p['success']:.3f} first {p['first']:.2f} broken {p['broken'][0]}/{p['broken'][1]} clean {p['clean']:.2f} out {p['out']:.1f}k" for k, p in enumerate(per))
            print(f"  {a:6s} {line}")
        def eff(a, idx):
            s = sum(data[a][k][common[i]]["passed"] for i in idx for k in (0, 1)); o = sum(data[a][k][common[i]]["out"] for i in idx for k in (0, 1))
            return s / o
        def eff1(a, k, idx): return sum(data[a][k][common[i]]["passed"] for i in idx) / sum(data[a][k][common[i]]["out"] for i in idx)
        full = np.arange(len(common))
        for a in [x for x in arms if x != "text"]:
            per = [eff1(a, k, full) / eff1("text", k, full) for k in (0, 1)]
            r0 = eff(a, full) / eff("text", full)
            bs = np.sort([eff(a, i) / eff("text", i) for i in (rng.integers(0, len(common), len(common)) for _ in range(B))])
            print(f"  {a:6s} vs SR solved per output token: r0 {per[0]:.2f}, r1 {per[1]:.2f}, pooled {r0:.2f} [{bs[int(.025*B)]:.2f}, {bs[int(.975*B)]:.2f}]")
        # pooled paired tests for the headline comparisons
        for a, b, key in (("ref", "text", "first"), ("ref", "lines", "broken"), ("lines", "text", "first"), ("ref", "text", "passed"), ("ref", "lines", "passed")):
            if a not in arms or b not in arms: continue
            if key == "broken":
                g = sum((data[b][k][t]["broken"] is True) and not (data[a][k][t]["broken"] is True) for t in common for k in (0, 1))
                l = sum((data[a][k][t]["broken"] is True) and not (data[b][k][t]["broken"] is True) for t in common for k in (0, 1))
                print(f"  broken first edit, {b} but not {a}: {g} vs {a} but not {b}: {l} (pooled over replicates; sign test p={mcn(g, l):.3f})")
            else:
                g = sum(bool(data[a][k][t][key]) and not data[b][k][t][key] for t in common for k in (0, 1)); l = sum(bool(data[b][k][t][key]) and not data[a][k][t][key] for t in common for k in (0, 1))
                print(f"  {key:6s} {a} vs {b}: +{g}/-{l} pooled over replicates (sign test p={mcn(g, l):.3f})")
