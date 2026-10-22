#!/usr/bin/env python3
"""Where the money goes (RQ2): per-task cost of GPT-5.6-luna and MiMo-v2.5-Pro under perfect prefix caching
(Equation 4), split into re-read context, newly read input and output, for search/replace, line ranges and
verified selection on the tasks valid in all three. Per-token prices are fitted by least squares on per-call
billed cost, as in cache_neutral.py."""
import numpy as np
src = open("cache_neutral.py").read()
exec(src.split("for (bench, model), arms in SETS.items():")[0])   # SETS, load()
for key in (("aider-refactor", "GPT-5.6-luna"), ("aider-refactor", "MiMo-v2.5-Pro"), ("canitedit", "GPT-5.6-luna"), ("canitedit", "MiMo-v2.5-Pro")):
    bench, model = key; arms = SETS[key]; names = ["text", "lines", "ref"]
    data = {n: load(bench, arms[n], n) for n in names}
    common = sorted(set.intersection(*(set(v) for v in data.values())))
    X = np.array([c[:3] for n in names for t in common for c in data[n][t]["calls"]], float)
    Y = np.array([c[3] for n in names for t in common for c in data[n][t]["calls"]], float)
    pu, pc, po = np.linalg.lstsq(X, Y, rcond=None)[0]
    print(f"{bench} / {model} ({len(common)} tasks): per task under ideal prefix caching")
    for n in names:
        reread = sum(c[4] for t in common for c in data[n][t]["calls"]) * pc / len(common)
        new = sum(c[0] + c[1] - c[4] for t in common for c in data[n][t]["calls"]) * pu / len(common)
        out = sum(c[2] for t in common for c in data[n][t]["calls"]) * po / len(common)
        ncalls = np.mean([len(data[n][t]["calls"]) for t in common]); ctx = np.mean([c[0] + c[1] for t in common for c in data[n][t]["calls"]])
        tot = reread + new + out
        print(f"  {n:5s} model calls/task {ncalls:5.1f}, mean context {ctx / 1e3:5.1f}k | ${tot:.4f} = re-read {reread / tot:4.0%} + new input {new / tot:4.0%} + output {out / tot:4.0%}")
