#!/usr/bin/env python3
"""Per-edit dose-response from existing search/replace calls -> data/edits_text.csv

One row per search/replace edit whose fate is known: in a call that applied, every
edit matched; in a call rejected with 'edit N old_text must match exactly once,
but matched K times', edits 1..N-1 matched and edit N did not (later edits unknown).
Calls rejected for argument shape, revisions etc. say nothing about matching and are skipped.
"""
import importlib.util, json, re, sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, "figures")
from style import runs

RUNS = Path("../editbench/runs"); EB = Path("../editbench")
def dec(o): return bytes.fromhex(o["hex"]).decode(errors="replace") if isinstance(o, dict) and "hex" in o else (o or "")
def load(name):
    spec = importlib.util.spec_from_file_location(name, EB / "adapters" / f"{name}.py"); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
cie, ref = load("canitedit"), load("aider_refactor")
file_lines = {}
def flen(bench, task):
    key = (bench, task)
    if key not in file_lines:
        if bench == "canitedit": file_lines[key] = len(cie.load(task).fixture["before"].splitlines())
        else: file_lines[key] = len(ref.task_files(ref.TASKS / task)[0].read_text(errors="replace").splitlines())
    return file_lines[key]
frame = runs(None); rows = []
for r in frame.itertuples():
    hits = list((RUNS / r.source).glob(f"*__{r.task}__*__{r.arm}__r0/events.jsonl"))
    if not hits: continue
    for line in hits[0].read_text(errors="replace").splitlines():
        if '"experiment.tool_call"' not in line: continue
        p = json.loads(line)["payload"]
        if p["tool"] not in ("apply_patch", "edit_text"): continue
        try: a = json.loads(dec(p["arguments"]))
        except Exception: continue
        files = a.get("files") if isinstance(a.get("files"), list) else ([a] if isinstance(a.get("edits"), list) else [])
        edits = [e for f in files if isinstance(f, dict) for e in (f.get("edits") or []) if isinstance(e, dict) and isinstance(e.get("old_text"), str)]
        if not edits: continue
        err = dec(p.get("error")); m = re.search(r"edit (\d+) old_text must match exactly once, but matched (\d+) times", err)
        if err and not m: continue
        upto = int(m.group(1)) if m else len(edits)
        for i, e in enumerate(edits[:upto], 1):
            matched = 1 if (not m or i < upto) else int(m.group(2))
            rows.append(dict(model=r.model, bench=r.benchmark, arm=r.arm, batch=r.batch, task=r.task, old_chars=len(e["old_text"]), old_lines=e["old_text"].count("\n") + 1, new_chars=len(e.get("new_text") or ""), file_lines=flen(r.benchmark, r.task), matches=matched))
# Claude Sonnet 5 joined after the main study; the RQ2 replay analyses cover the main study.
d = pd.DataFrame(rows); d = d[d.batch != "claude"]
d.to_csv("data/edits_text.csv", index=False)
print("edits with a known fate:", len(d), "| matched once", (d.matches == 1).sum(), "| matched 0 times", (d.matches == 0).sum(), "| matched 2+ times", (d.matches >= 2).sum())
print(d.groupby(["bench", "model"]).size().unstack(0).fillna(0).astype(int).to_string())
