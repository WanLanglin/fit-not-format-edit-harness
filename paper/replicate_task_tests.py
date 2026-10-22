#!/usr/bin/env python3
"""Paired comparisons of Table 3: for each task, which arm did better over its two runs (tasks where the arms
tie are left out), with a two-sided sign test across tasks. A run without a targeted edit counts as not accepted."""
import math, numpy as np
exec(open("replication_table.py").read().rsplit("rng = np.random.default_rng(0); B = 2000", 1)[0])


def sign_p(pos, neg):
    m = pos + neg; return 1.0 if not m else min(1.0, 2 * sum(math.comb(m, i) for i in range(min(pos, neg) + 1)) / 2 ** m)


for bench, models in R.items():
    for model, arms in models.items():
        data = {a: [load(bench, d, x) for d, x in reps] for a, reps in arms.items()}
        common = sorted(set.intersection(*(set(r) for reps in data.values() for r in reps)))
        def val(a, k, t, key):
            r = data[a][k][t]
            if key == "broken": return 1 if r["broken"] is True else 0
            return 1 if r[key] else 0
        for a, b, key in (("ref", "text", "first"), ("lines", "ref", "broken"), ("ref", "lines", "passed"), ("ref", "text", "passed")):
            d = [sum(val(a, k, t, key) - val(b, k, t, key) for k in (0, 1)) for t in common]
            pos = sum(x > 0 for x in d); neg = sum(x < 0 for x in d)
            print(f"{bench:15s} {model:14s} {key:6s} {a} vs {b}: tasks favouring {a} {pos}, favouring {b} {neg}, task-level sign test p={sign_p(pos, neg):.4f}")
