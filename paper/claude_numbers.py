#!/usr/bin/env python3
"""Claude Sonnet 5 on CanItEdit, search/replace against line ranges (its main-comparison arms), on paired tasks:
task success and first targeted edit accepted (exact McNemar), output tokens per task, and efficiency per output
token and per billed dollar with a paired bootstrap."""
import math, sys
import numpy as np, pandas as pd
sys.path.insert(0, "figures")
from style import calls, paired, runs

R = runs(None); C = R[(R.batch == "claude") & (R.model == "Claude-Sonnet-5")]
P = paired(C, ["text", "lines"])
w = P.pivot(index="task", columns="arm", values=["passed", "first_targeted_ok", "output_tokens", "cost_usd"])
print("paired tasks", len(w))


def mcn(a, b):
    g = int(((a == 1) & (b == 0)).sum()); l = int(((a == 0) & (b == 1)).sum()); m = g + l
    return g, l, (1.0 if not m else min(1.0, 2 * sum(math.comb(m, i) for i in range(min(g, l) + 1)) / 2 ** m))


for col in ("passed", "first_targeted_ok"):
    d = w[col].dropna(); g, l, p = mcn(d["lines"], d["text"])
    print(f"{col:18s} SR {d['text'].mean():.3f}  lines {d['lines'].mean():.3f}  lines vs SR +{g}/-{l} p={p:.3f}  (n={len(d)})")
out = pd.to_numeric(w["output_tokens"].stack(), errors="coerce").unstack()
print(f"output/task (k): SR {out['text'].mean() / 1000:.1f} lines {out['lines'].mean() / 1000:.1f}")
rng = np.random.default_rng(0); B = 2000
for k, name in (("output_tokens", "output"), ("cost_usd", "dollar")):
    q = w[["passed", k]].copy(); q.columns = [f"{a}_{b}" for a, b in q.columns]
    q = q.apply(pd.to_numeric, errors="coerce").dropna()
    def e(idx, arm): return q[f"passed_{arm}"].iloc[idx].sum() / q[f"{k}_{arm}"].iloc[idx].sum()
    full = np.arange(len(q)); r0 = e(full, "lines") / e(full, "text")
    bs = np.sort([e(i, "lines") / e(i, "text") for i in (rng.integers(0, len(q), len(q)) for _ in range(B))])
    print(f"lines vs SR efficiency per {name}: {r0:.2f} [{bs[50]:.2f}, {bs[1949]:.2f}]")
E = calls(None); print("Claude edit calls", len(E[E.batch == "claude"]))

# Verified selection against search/replace (RQ4), on the tasks valid in both; a run whose first edit call is a
# whole-file write has no targeted first edit and counts as not accepted.
src = open("ref_ablation.py").read()
ns = {}; exec(src.split("rng = np.random.default_rng(0); B = 2000")[0], ns)
arms = ns["SETS"][("canitedit", "Claude-Sonnet-5")]
data = {n: ns["load"]("canitedit", arms[n], n) for n in ("text", "ref")}
common = sorted(set(data["text"]) & set(data["ref"]))
for n in ("text", "ref"):
    firsts = [data[n][t]["first"] for t in common]
    print(f"{n:4s} first edit: accepted targeted {firsts.count(True)} of {len(common)}, rejected {firsts.count(False)}, "
          f"whole-file write first {firsts.count(None)}")
for key in ("first", "passed"):
    a = [int(data["ref"][t][key] is True) for t in common]; b = [int(data["text"][t][key] is True) for t in common]
    g, l, p = mcn(pd.Series(a), pd.Series(b))
    print(f"{key:6s} verified selection vs SR: {np.mean(a):.3f} vs {np.mean(b):.3f}, +{g}/-{l}, exact McNemar p={p:.3f}")
