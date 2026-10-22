#!/usr/bin/env python3
"""Token efficiency of each edit interface, within a model, on paired tasks.
efficiency = tasks solved / output tokens spent (and / dollars billed), relative to
search/replace. Also output tokens per task and pass rate for the three single interfaces.
Writes data/efficiency.csv (relative efficiency with paired bootstrap 95% intervals) and
data/output_per_task.csv."""
import sys
import numpy as np, pandas as pd
sys.path.insert(0, "figures")
from style import runs, MODEL_ORDER
B = 2000
R = runs(None).copy()
R["output_tokens"] = pd.to_numeric(R.output_tokens, errors="coerce").fillna(0)
ORDER = [("canitedit", m) for m in MODEL_ORDER] + [("aider-refactor", "GPT-5.6-luna"), ("aider-refactor", "MiMo-v2.5-Pro")]
eff, per = [], []
for bench, model in ORDER:
    g = R[(R.benchmark == bench) & (R.model == model)]
    three = g[g.arm.isin(["text", "patch", "lines"]) & (g.batch == "main")]
    p = three.pivot_table(index="task", columns="arm", values=["passed", "output_tokens", "cost_usd"], aggfunc="first").dropna()
    row = dict(bench=bench, model=model, tasks=len(p))
    for arm in ("text", "patch", "lines"):
        row[f"{arm}_pass"] = p["passed"][arm].mean(); row[f"{arm}_out_k"] = p["output_tokens"][arm].mean() / 1000
    per.append(row)
    for arm in [a for a in ["patch", "lines", "choice", "guided", "tools", "tools_guided"] if a in set(g.arm)]:
        q = g[g.arm.isin(["text", arm])].pivot_table(index="task", columns="arm", values=["passed", "output_tokens", "cost_usd"], aggfunc="first").dropna()
        if len(q) < 20: continue
        def e(idx, a, k): return q["passed"][a].iloc[idx].sum() / q[k][a].iloc[idx].sum()
        full = np.arange(len(q)); rng = np.random.default_rng(0)
        for k, name in (("output_tokens", "output"), ("cost_usd", "dollar")):
            r0 = e(full, arm, k) / e(full, "text", k)
            bs = np.sort([e(i, arm, k) / e(i, "text", k) for i in (rng.integers(0, len(q), len(q)) for _ in range(B))])
            eff.append(dict(bench=bench, model=model, arm=arm, per=name, n=len(q), rel=r0, lo=bs[int(.025 * B)], hi=bs[int(.975 * B)]))
E = pd.DataFrame(eff); E.to_csv("data/efficiency.csv", index=False)
P = pd.DataFrame(per); P.to_csv("data/output_per_task.csv", index=False)
pd.set_option("display.width", 220)
print(P.round(3).to_string(index=False))
for per_ in ("output", "dollar"):
    x = E[(E.per == per_) & E.arm.isin(["patch", "lines"])].copy()
    x["cell"] = x.apply(lambda r: f"{r.rel:.2f} [{r.lo:.2f},{r.hi:.2f}]" + (" *" if r.lo > 1 or r.hi < 1 else ""), axis=1)
    print(f"\n== efficiency per {per_}, relative to search/replace (higher = better) ==")
    print(x.pivot_table(index=["bench", "model"], columns="arm", values="cell", aggfunc="first").to_string())
