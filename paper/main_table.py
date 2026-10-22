#!/usr/bin/env python3
"""Table 2 (main comparison) from data/runs.csv -> data/main_table.txt (printed).

Per model and benchmark, on the tasks with a valid run in every single-interface arm: task success,
Cochran's Q on success across the three arms (exact McNemar when a model has two arms), first targeted
edit accepted (among runs that made a targeted edit), and output tokens per task (reasoning included)."""
import math, sys
import numpy as np
sys.path.insert(0, "figures")
from style import paired, runs

ROWS = [("canitedit", "GPT-5.6-luna", "main"), ("canitedit", "GLM-5.3", "main"), ("canitedit", "DeepSeek-V4-Flash", "main"),
        ("canitedit", "MiMo-v2.5-Pro", "main"), ("canitedit", "Qwen3.8-Flash", "main"), ("canitedit", "Claude-Sonnet-5", "claude"),
        ("aider-refactor", "GPT-5.6-luna", "main"), ("aider-refactor", "MiMo-v2.5-Pro", "main")]


def chi2_sf(x, k):
    """Upper tail of chi-square with k degrees of freedom (k = 1 or 2 here)."""
    if k == 2:
        return math.exp(-x / 2)
    if k == 1:
        return math.erfc(math.sqrt(x / 2))
    raise ValueError(k)


def cochran_q(m):
    """m: tasks x arms 0/1 matrix."""
    k = m.shape[1]; col = m.sum(0); row = m.sum(1); n = m.sum()
    den = k * n - (row ** 2).sum()
    if den == 0:
        return 1.0
    q = (k - 1) * (k * (col ** 2).sum() - n ** 2) / den
    return chi2_sf(q, k - 1)


def mcnemar(a, b):
    g = int(((a == 1) & (b == 0)).sum()); l = int(((a == 0) & (b == 1)).sum()); m = g + l
    return 1.0 if not m else min(1.0, 2 * sum(math.comb(m, i) for i in range(min(g, l) + 1)) / 2 ** m)


R = runs(None)
for bench, model, batch in ROWS:
    sub = R[(R.benchmark == bench) & (R.model == model) & (R.batch == batch)]
    arms = [a for a in ("text", "patch", "lines") if a in set(sub.arm)]
    P = paired(sub, arms)
    w = P.pivot(index="task", columns="arm")
    succ = w["passed"][arms].astype(int).to_numpy()
    p = cochran_q(succ) if len(arms) == 3 else mcnemar(succ[:, 1], succ[:, 0])
    fmt = lambda col, f: " / ".join(f(w[col][a]) if a in arms else "--" for a in ("text", "patch", "lines"))
    first = lambda s: f"{s.dropna().astype(float).mean():.2f}"
    print(f"{bench:15s} {model:18s} tasks {len(w):3d} | success {fmt('passed', lambda s: f'{s.astype(float).mean():.3f}')} "
          f"| p {p:.3f}{'' if len(arms) == 3 else ' (McNemar)'} | first edit {fmt('first_targeted_ok', first)} "
          f"| output/task (k) {fmt('output_tokens', lambda s: f'{s.astype(float).mean() / 1000:.1f}')}")

import json
manifest = json.load(open("data/manifest.json"))
total = invalid = 0
for entry in manifest:
    if entry["batch"] not in ("main", "claude") or not entry["directory"].startswith(("canitedit-", "refactor-")):
        continue
    for arm in ("text", "patch", "lines"):
        total += entry["valid_runs"].get(arm, 0) + entry["excluded_invalid"].get(arm, 0)
        invalid += entry["excluded_invalid"].get(arm, 0)
print(f"runs behind this table: {total}, of which invalid (provider or harness failure): {invalid}")

