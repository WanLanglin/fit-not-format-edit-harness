#!/usr/bin/env python3
"""Supporting statistics quoted in the paper, all from data/*.csv."""
import math, sys
import numpy as np, pandas as pd
sys.path.insert(0, "figures")
from style import MODEL_ORDER, calls, paired, runs  # noqa: E402

ARMS = ["text", "patch", "lines"]; frame = runs(); everything = runs(None)
def mcnemar(a, b):
    g = int(((a == 1) & (b == 0)).sum()); l = int(((a == 0) & (b == 1)).sum()); m = g + l
    p = 1.0 if not m else min(1.0, 2 * sum(math.comb(m, i) for i in range(min(g, l) + 1)) / 2 ** m)
    return g, l, p
print("== first targeted edit, exact McNemar (tasks where both arms made a targeted edit)")
for bench in ("canitedit", "aider-refactor"):
    for model in MODEL_ORDER:
        sub = paired(frame[(frame.model == model) & (frame.benchmark == bench)], ARMS)
        if sub.empty: continue
        w = sub.pivot(index="task", columns="arm", values="first_targeted_ok")
        out = []
        for x, y in (("lines", "text"), ("lines", "patch"), ("text", "patch")):
            d = w[[x, y]].dropna(); g, l, p = mcnemar(d[x], d[y]); out.append(f"{x}>{y} +{g}/-{l} p={p:.4f}")
        print(f"  {bench:15}{model:23}" + " | ".join(out))
print("\n== tokens relative to search/replace (ratio of means, paired bootstrap 95%)")
rng = np.random.default_rng(1)
for bench in ("canitedit", "aider-refactor"):
    for model in MODEL_ORDER:
        sub = paired(frame[(frame.model == model) & (frame.benchmark == bench)], ARMS)
        if sub.empty: continue
        w = sub.pivot(index="task", columns="arm", values="tokens").dropna(); idx = rng.integers(0, len(w), (4000, len(w))); out = []
        for arm in ("patch", "lines"):
            b = w[arm].to_numpy()[idx].mean(1) / w["text"].to_numpy()[idx].mean(1); lo, hi = np.percentile(b, [2.5, 97.5])
            out.append(f"{arm} x{w[arm].mean()/w['text'].mean():.2f} [{lo:.2f}, {hi:.2f}]")
        print(f"  {bench:15}{model:23}" + " | ".join(out))
print("\n== failed patch calls attributable to the harness being stricter than the reference (CanItEdit, patch arm)")
c = calls(); c = c[(c.benchmark == "canitedit") & (c.arm == "patch") & (c.ok == 0)]
for model in MODEL_ORDER:
    s = c[c.model == model]; strict = ((s.error_class == "patch: context-only hunk") | ((s.error_class == "patch: non-bare @@ header") & (s.header_style == "codex-style"))).sum()
    contract = s.error_class.isin(["patch: sent without revisions", "stale revision"]).sum()
    print(f"  {model:23} failed {len(s):5d} | harness stricter {strict:4d} ({strict/max(len(s),1):.0%}) | revision contract {contract:4d} ({contract/max(len(s),1):.0%}) | rest (reference rejects too) {len(s)-strict-contract:5d} ({(len(s)-strict-contract)/max(len(s),1):.0%})")
print("\n== position lift in the three-tool arm: P(pick f | f listed first) - P(pick f | listed later)")
tool_form = {"edit_lines": "lines", "edit_text": "text", "apply_patch": "patch"}
main = everything[(everything.batch == "main") | ((everything.batch == "ablation") & (everything.model == "GPT-5.6-luna"))]
for model in ("GPT-5.6-luna", "Qwen3.8-Flash", "MiMo-v2.5-Pro"):
    s = main[(main.model == model) & (main.arm == "tools") & (main.benchmark == "canitedit") & main.first_tool.notna()]
    picked = s.first_tool.map(tool_form).where(s.first_form != "content", "content"); out = []
    for f in ("lines", "text", "patch"):
        first = s.choice_order.str.startswith(f); out.append(f"{f} {(picked[first]==f).mean() - (picked[~first]==f).mean():+.2f}")
    share = picked.value_counts(normalize=True).round(2).to_dict()
    print(f"  {model:23}" + "  ".join(out) + f"   overall first pick {share}")
print("\n== whole-file rewrites (runs that used content at least once), single-interface arms")
for bench in ("canitedit", "aider-refactor"):
    for model in MODEL_ORDER:
        s = frame[(frame.model == model) & (frame.benchmark == bench) & frame.arm.isin(ARMS)]
        if s.empty: continue
        print(f"  {bench:15}{model:23}" + "  ".join(f"{a} {s[s.arm==a].content_any.mean():.0%}" for a in ARMS))
