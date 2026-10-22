#!/usr/bin/env python3
"""RQ3 menu arms on CanItEdit: which form a model picks first when one tool accepts all three forms, how often
each single form's first edit is accepted, and one tool with three argument shapes against three named tools."""
import math, sys
sys.path.insert(0, "figures")
from style import canitedit_arms, paired, MODEL_ORDER


def mcnemar(g, l):
    m = g + l
    return 1.0 if not m else min(1.0, 2 * sum(math.comb(m, i) for i in range(min(g, l) + 1)) / 2 ** m)


for model in MODEL_ORDER:
    F = canitedit_arms(model)
    for arm in ("choice", "tools"):
        A = F[F.arm == arm]
        if A.empty:
            continue
        share = A.first_form.value_counts(normalize=True).round(2).to_dict()
        print(f"{model:18s} {arm:6s} runs {len(A)} | first form picked {share}")
    singles = paired(F, ["text", "patch", "lines"])
    acc = singles.groupby("arm").first_targeted_ok.mean().round(2).to_dict()
    print(f"{model:18s} single-form first edit accepted {acc}")
    if {"choice", "tools"} <= set(F.arm):
        P = paired(F, ["choice", "tools"]).pivot(index="task", columns="arm", values="first_targeted_ok").fillna(0).astype(int)
        g = int(((P.tools == 1) & (P.choice == 0)).sum()); l = int(((P.tools == 0) & (P.choice == 1)).sum())
        print(f"{model:18s} first edit accepted, three tools vs one tool: {P.choice.mean():.3f} -> {P.tools.mean():.3f} "
              f"({100 * (P.tools.mean() - P.choice.mean()):+.1f} points, +{g}/-{l}, exact McNemar p={mcnemar(g, l):.3f})")

# Advice on when to use each form: guided vs choice (one tool) and tools_guided vs tools (three tools), per model.
import pandas as pd
eff = pd.read_csv("data/efficiency.csv")   # written by efficiency.py: tasks solved per output token relative to search/replace
eff = eff[(eff.bench == "canitedit") & (eff.per == "output")].set_index(["model", "arm"]).rel
up = down = n = 0
for model in MODEL_ORDER:
    F = canitedit_arms(model)
    for plain, advised in (("choice", "guided"), ("tools", "tools_guided")):
        if not {plain, advised} <= set(F.arm):
            continue
        P = paired(F, [plain, advised]).groupby("arm").first_targeted_ok.mean()
        n += 1; up += P[advised] > P[plain]; down += eff[(model, advised)] < eff[(model, plain)]
        print(f"{model:18s} {plain} -> {advised}: first edit accepted {P[plain]:.3f} -> {P[advised]:.3f}, "
              f"output efficiency vs SR {eff[(model, plain)]:.2f} -> {eff[(model, advised)]:.2f}")
print(f"advice raises first-edit acceptance in {up} of {n} comparisons and lowers output efficiency in {down}")
