#!/usr/bin/env python3
"""Cost and menu-ablation numbers, all arms, from data/runs.csv."""
import math, sys
import numpy as np, pandas as pd
sys.path.insert(0, "figures")
from style import MODEL_ORDER, runs  # noqa: E402

everything = runs(None)
def arms_for(model):
    """Single interfaces from the main batch; luna's four menu arms from its contemporaneous ablation batch."""
    m = everything[(everything.model == model) & (everything.benchmark == "canitedit")]
    if model == "GPT-5.6-luna":
        return pd.concat([m[(m.batch == "main") & m.arm.isin(["text", "patch", "lines"])], m[(m.batch == "ablation") & m.arm.isin(["choice", "guided", "tools", "tools_guided"])]])
    return m[m.batch == "main"]
ORDER = ["text", "patch", "lines", "choice", "guided", "tools", "tools_guided"]
print("== CanItEdit, every arm: pass | first edit ok | failed edits/run | model calls | tokens/task | tokens per SOLVED task | x vs search/replace")
for model in MODEL_ORDER:
    f = arms_for(model); arms = [a for a in ORDER if a in set(f.arm)]
    counts = f.groupby("task").arm.nunique(); f = f[f.task.isin(counts[counts == len(arms)].index)]
    base = None
    print(f"\n{model}  (paired tasks {f.task.nunique()})")
    for a in arms:
        s = f[f.arm == a]; tps = s.tokens.sum() / max(s.passed.sum(), 1)
        if a == "text": base = tps
        print(f"   {a:13} pass {s.passed.mean():.3f} | first {s.first_edit_ok.mean():.3f} | fails {s.edit_failures.mean():5.2f} | calls {s.model_calls.mean():5.1f} | tok {s.tokens.mean()/1000:6.1f}k | per solved {tps/1000:6.1f}k | x{tps/base:.2f}")
print("\n== large files")
for model in ("GPT-5.6-luna", "MiMo-v2.5-Pro"):
    f = everything[(everything.model == model) & (everything.benchmark == "aider-refactor") & (everything.batch == "main")]; arms = [a for a in ORDER if a in set(f.arm)]
    counts = f.groupby("task").arm.nunique(); f = f[f.task.isin(counts[counts == len(arms)].index)]; base = None
    print(f"\n{model}  (paired tasks {f.task.nunique()})")
    for a in arms:
        s = f[f.arm == a]; tps = s.tokens.sum() / max(s.passed.sum(), 1); base = base or tps
        print(f"   {a:13} pass {s.passed.mean():.3f} | first {s.first_edit_ok.mean():.3f} | fails {s.edit_failures.mean():5.2f} | calls {s.model_calls.mean():5.1f} | tok {s.tokens.mean()/1000:6.1f}k | per solved {tps/1000:6.1f}k | x{tps/base:.2f}")
print("\n== what a failed first edit costs (same task, single-interface arms: arms whose first targeted edit failed vs arms where it applied)")
main = everything[(everything.batch == "main") & everything.arm.isin(["text", "patch", "lines"])]
for bench in ("canitedit", "aider-refactor"):
    for model in MODEL_ORDER:
        f = main[(main.model == model) & (main.benchmark == bench)].dropna(subset=["first_targeted_ok"])
        if f.empty: continue
        g = f.groupby(["task", "first_targeted_ok"]).agg(tok=("tokens", "mean"), calls=("model_calls", "mean")).unstack()
        g = g.dropna()
        if len(g) < 8: print(f"  {bench:15}{model:23} too few tasks with both ({len(g)})"); continue
        print(f"  {bench:15}{model:23} tasks {len(g):3d} | tokens: applied {g[('tok',1)].mean()/1000:6.1f}k  failed {g[('tok',0)].mean()/1000:6.1f}k  (x{g[('tok',0)].mean()/g[('tok',1)].mean():.2f}) | model calls {g[('calls',1)].mean():.1f} -> {g[('calls',0)].mean():.1f}")
