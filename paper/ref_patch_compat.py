#!/usr/bin/env python3
"""Would the reference apply_patch accept the first patches our harness rejected?

For every CanItEdit patch-arm run in the main batch, take the first targeted patch call. If our harness
rejected it, replay its patch text with the reference implementation (the Codex CLI binary run as
`apply_patch`) on the original file, and record whether the reference applies it. First-edit
acceptance under the reference = (accepted by us + rejected by us but applied by the reference) / runs.
Writes data/ref_patch_compat.txt and data/ref_patch_compat.csv.
"""
import collections, csv, glob, json, os, re, subprocess, sys, tempfile
import pandas as pd
sys.path.insert(0, "figures")
from style import calls, runs, paired
exec(open("place_check.py").read().split("rows = []")[0])   # original(), dec()

REF = os.environ.get("CODEX_BIN")   # the native codex-cli 0.156.0 binary, run as `apply_patch` via argv[0]
if not REF:
    sys.exit("set CODEX_BIN to the codex binary (codex-cli 0.156.0) to replay patches through the reference apply_patch")
BIN = tempfile.mkdtemp(prefix="refpatch-bin-"); os.symlink(REF, os.path.join(BIN, "apply_patch"))
ver = subprocess.run([REF, "--version"], capture_output=True, text=True).stdout.strip()


def call_args(source, task, position):
    """Arguments of the position-th edit call of one run, or None."""
    hits = glob.glob(f"../editbench/runs/{source}/canitedit__{task}__*__patch__r0")
    if not hits: return None
    k = -1
    for line in open(hits[0] + "/events.jsonl", errors="replace"):
        if '"experiment.tool_call"' not in line: continue
        p = json.loads(line)["payload"]
        if p["tool"] != "apply_patch": continue
        k += 1
        if k == position: return dec(p["arguments"])
    return None


def reference_applies(patch, before):
    """Run the reference apply_patch in a scratch directory holding the original file(s)."""
    d = tempfile.mkdtemp(prefix="refpatch-")
    targets = re.findall(r"^\*\*\* (?:Update|Delete) File: (.+?)\s*$", patch, re.M) or ["solution.py"]
    for t in set(targets):
        path = os.path.join(d, t.lstrip("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").write(before)
    r = subprocess.run([os.path.join(BIN, "apply_patch"), patch], cwd=d, capture_output=True, text=True, timeout=60)
    return r.returncode == 0, (r.stdout + r.stderr).strip().split("\n")[0][:140]


C = calls(); C = C[(C.benchmark == "canitedit") & (C.arm == "patch")]
first = C[C.form == "patch"].sort_values("position").groupby(["model", "task"]).head(1).set_index(["model", "task"])
R = runs(); R = R[(R.benchmark == "canitedit") & R.arm.isin(["text", "patch", "lines"])]
rows, out = [], [f"reference: {ver}"]
for m in sorted(R.model.unique()):
    sub = paired(R[R.model == m], ["text", "patch", "lines"]); P = sub[sub.arm == "patch"].set_index("task")
    n = int(P.first_targeted_ok.notna().sum()); ours = int((P.first_targeted_ok == 1).sum())
    ref_extra = 0; by_class = collections.Counter(); ref_by_class = collections.Counter(); skipped = 0
    for task, r in P.iterrows():
        if pd.isna(r.first_targeted_ok) or r.first_targeted_ok == 1: continue
        if (m, task) not in first.index: skipped += 1; continue
        c = first.loc[(m, task)]
        raw = call_args(c.source, task, int(c.position))
        try: patch = json.loads(raw).get("patch") if raw else None
        except Exception:
            mm = re.search(r'"patch"\s*:\s*"((?:[^"\\]|\\.)*)"', raw or ""); patch = json.loads('"' + mm.group(1) + '"') if mm else None
        if not isinstance(patch, str):
            ok, msg = False, "no patch text in the call"
        else:
            ok, msg = reference_applies(patch, original("canitedit", task))
        by_class[c.error_class] += 1; ref_by_class[c.error_class] += ok; ref_extra += ok
        rows.append(dict(model=m, task=task, our_error=c.error_class, reference_applies=int(ok), reference_message=msg))
    line = (f"{m:18s} runs {n:3d} | first patch accepted by us {ours:3d} ({ours / n:.2f}) | rejected by us {n - ours:3d}, "
            f"of which the reference applies {ref_extra:3d} -> reference acceptance {(ours + ref_extra) / n:.2f}")
    print(line); out.append(line)
    for k, v in by_class.most_common():
        s = f"      {k:52s} rejected by us {v:3d} | reference applies {ref_by_class[k]:3d}"; print(s); out.append(s)
open("data/ref_patch_compat.txt", "w").write("\n".join(out) + "\n")
with open("data/ref_patch_compat.csv", "w", newline="") as h:
    w = csv.DictWriter(h, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
