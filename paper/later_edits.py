#!/usr/bin/env python3
"""GPT-5.6-luna on the refactors (main batch): edits after the first successful targeted edit.
Per arm: later targeted edit calls and how many were accepted; for line ranges, how many were preceded by a
read_file since the previous edit call, and how many were rejected for a stale revision. Also the mean visible
output tokens of the model call that made the first targeted edit (runs.csv, edit_visible_tokens)."""
import glob, json, sys
sys.path.insert(0, "figures")
from style import paired, runs

R = runs(None); L = R[(R.benchmark == "aider-refactor") & (R.model == "GPT-5.6-luna") & (R.batch == "main")]
P = paired(L, ["text", "patch", "lines"])
for arm in ("text", "patch", "lines"):
    print(f"{arm:6s} first targeted edit call, mean visible output tokens: {P[P.arm == arm].edit_visible_tokens.mean():.0f}")


def targeted(call):
    forms = call.get("edit_forms") or {}
    return call["tool"] == "apply_patch" and any(k != "content" for k in forms)


for arm in ("text", "patch", "lines"):
    later = ok = reread = stale = 0
    for path in sorted(glob.glob(f"../editbench/runs/refactor-luna-5arms/aider-refactor__*__{arm}__r0/run.json")):
        r = json.load(open(path))
        if r.get("invalid_reasons"):
            continue
        seen_ok = False; read_since = False
        for call in r["tool_calls"]:
            if call["tool"] == "read_file":
                read_since = True; continue
            if call["tool"] != "apply_patch":
                continue
            if seen_ok and targeted(call):
                later += 1; ok += call["outcome"] == "completed"; reread += read_since
                stale += "revision" in str(call.get("error") or "").lower()
            if not seen_ok and targeted(call) and call["outcome"] == "completed":
                seen_ok = True
            read_since = False
    print(f"{arm:6s} later targeted edits {later}, accepted {ok} ({ok / max(later, 1):.2f}), preceded by a re-read {reread}, stale-revision rejections {stale}")
