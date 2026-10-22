#!/usr/bin/env python3
"""Within-model cost of each interface relative to search/replace, on paired tasks.
Two measures per solved task: billed cost (input + output at the provider's prices, cache
included) and output tokens (reasoning included). Also the price of a failed first edit:
on the same task, arms whose first targeted edit failed vs arms where it applied.
Writes data/cost_ratios.csv and data/failed_first_edit.csv."""
import random, sys
import numpy as np, pandas as pd
sys.path.insert(0, "figures")
from style import runs, MODEL_ORDER
random.seed(0); B = 2000
R = runs(None).copy()
R["output_tokens"] = pd.to_numeric(R.output_tokens, errors="coerce").fillna(0)
rows = []
for (bench, model), g in R.groupby(["benchmark", "model"]):
    arms = [a for a in ["patch", "lines", "choice", "guided", "tools", "tools_guided"] if a in set(g.arm)]
    for arm in arms:
        p = g[g.arm.isin(["text", arm])].pivot_table(index="task", columns="arm", values=["passed", "cost_usd", "output_tokens"], aggfunc="first").dropna()
        if len(p) < 20: continue
        def per_solved(idx, a, k): return p[k][a].iloc[idx].sum() / max(p["passed"][a].iloc[idx].sum(), 1)
        full = np.arange(len(p))
        for k, name in (("cost_usd", "cost"), ("output_tokens", "output")):
            r0 = per_solved(full, arm, k) / per_solved(full, "text", k)
            bs = sorted(per_solved(i, arm, k) / per_solved(i, "text", k) for i in (np.random.default_rng(s).integers(0, len(p), len(p)) for s in range(B)))
            rows.append(dict(bench=bench, model=model, arm=arm, measure=name, n=len(p), ratio=r0, lo=bs[int(.025 * B)], hi=bs[int(.975 * B)]))
cr = pd.DataFrame(rows); cr.to_csv("data/cost_ratios.csv", index=False)
fr = []
main = R[R.arm.isin(["text", "patch", "lines"]) & (R.batch == "main")].copy()
main = main[main.first_targeted_ok.astype(str).isin(["0", "1", "0.0", "1.0"])]
main["ok"] = main.first_targeted_ok.astype(float).astype(int)
for (bench, model), g in main.groupby(["benchmark", "model"]):
    for k, name in (("cost_usd", "cost"), ("output_tokens", "output")):
        t = g.groupby(["task", "ok"])[k].mean().unstack().dropna()
        if len(t) < 5: continue
        fr.append(dict(bench=bench, model=model, measure=name, tasks=len(t), ratio=t[0].mean() / t[1].mean()))
ff = pd.DataFrame(fr); ff.to_csv("data/failed_first_edit.csv", index=False)
pd.set_option("display.width", 200)
for m in ("cost", "output"):
    print(f"\n== per solved task, relative to search/replace: {m} ==")
    x = cr[(cr.measure == m) & cr.arm.isin(["patch", "lines", "tools"])].copy()
    x["cell"] = x.apply(lambda r: f"{r.ratio:.2f} [{r.lo:.2f},{r.hi:.2f}]" + (" *" if r.hi < 1 or r.lo > 1 else ""), axis=1)
    print(x.pivot_table(index=["bench", "model"], columns="arm", values="cell", aggfunc="first").to_string())
print("\n== failed first targeted edit vs applied, same tasks ==")
print(ff.pivot_table(index=["bench", "model"], columns="measure", values="ratio").round(2).to_string())
