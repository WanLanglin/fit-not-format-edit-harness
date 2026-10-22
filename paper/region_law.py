#!/usr/bin/env python3
"""First targeted edit call of every run, replayed on the original file -> data/first_calls.csv

For each run: take the first edit call that uses an addressing form (not a whole-file
write), skip calls rejected for reasons that say nothing about addressing (argument
shape, patch grammar, revisions), and record
  region_tokens : size of the code the call replaces (old_text / context+removed lines /
                  the addressed line ranges), chars/4
  applied       : the harness applied it
  syntax_ok     : the replayed result still parses as Python (None if not applied / replay differs)
"""
import ast, importlib.util, json, re, sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, "figures")
from style import runs

RUNS = Path("../editbench/runs"); EB = Path("../editbench")
def dec(o): return bytes.fromhex(o["hex"]).decode(errors="replace") if isinstance(o, dict) and "hex" in o else (o or "")
def load(name):
    spec = importlib.util.spec_from_file_location(name, EB / "adapters" / f"{name}.py"); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
cie, ref = load("canitedit"), load("aider_refactor"); originals = {}
def original(bench, task):
    if (bench, task) not in originals:
        originals[(bench, task)] = cie.load(task).fixture["before"] if bench == "canitedit" else ref.task_files(ref.TASKS / task)[0].read_text(errors="replace")
    return originals[(bench, task)]

def replay_text(content, edits, line_start=False):
    for e in edits:
        old, new = e["old_text"], e.get("new_text") or ""
        hits = [m.start() for m in re.finditer(re.escape(old), content) if not line_start or m.start() == 0 or content[m.start() - 1] == "\n"]
        if len(hits) != 1: return None
        content = content[:hits[0]] + new + content[hits[0] + len(old):]
    return content
def replay_lines(content, edits):
    for e in sorted(edits, key=lambda e: -e["start_line"]):
        starts = [0] + [i + 1 for i, ch in enumerate(content) if ch == "\n"]
        n = len(starts) - 1 if content.endswith("\n") else len(starts)
        s, t = e["start_line"], e["end_line"]
        if s < 1 or t < s or t > n: return None
        a = starts[s - 1]; b = starts[t] if t < len(starts) else len(content)
        rep = e.get("new_text") or ""
        if content[a:b].endswith("\n") and rep and not rep.endswith("\n"): rep += "\n"
        content = content[:a] + rep + content[b:]
    return content
def parse_patch(patch):
    lines = patch.split("\n"); hunks, cur = [], None
    for ln in lines[1:]:
        if ln.startswith("*** "): cur = None; continue
        if ln.strip() == "@@": cur = {"old_text": "", "new_text": ""}; hunks.append(cur); continue
        if cur is None or not ln: continue
        tag, text = ln[0], ln[1:] + "\n"
        if tag in " -": cur["old_text"] += text
        if tag in " +": cur["new_text"] += text
    return [h for h in hunks if h["old_text"]]
SKIP = ("unknown field", "exactly one", "cannot be combined", "invalid type", "accepts only", "missing field", "Begin Patch", "requires bare @@", "patch requires only", "supported patch operations", "each update hunk needs", "patch lines require", "expected_revision", "expected hash", "editing paths", "revision", "one mode consistently", "update hunk")
rows = []
# Claude Sonnet 5 joined after the main study; the RQ2 replay analyses cover the main study.
frame = runs(None); frame = frame[frame.batch != "claude"]
for r in frame.itertuples():
    hits = list((RUNS / r.source).glob(f"*__{r.task}__*__{r.arm}__r0/events.jsonl"))
    if not hits: continue
    src = original(r.benchmark, r.task)
    for line in hits[0].read_text(errors="replace").splitlines():
        if '"experiment.tool_call"' not in line: continue
        p = json.loads(line)["payload"]
        if p["tool"] not in ("apply_patch", "edit_text", "edit_lines"): continue
        try: a = json.loads(dec(p["arguments"]))
        except Exception: break
        err = dec(p.get("error"))
        form = edits = None
        if isinstance(a.get("patch"), str):
            form, edits = "patch", parse_patch(a["patch"])
        else:
            files = a.get("files") if isinstance(a.get("files"), list) else ([a] if isinstance(a.get("edits"), list) else [])
            es = [e for f in files if isinstance(f, dict) for e in (f.get("edits") or []) if isinstance(e, dict)]
            if es and all(isinstance(e.get("old_text"), str) for e in es): form, edits = "text", es
            elif es and all(isinstance(e.get("start_line"), int) and isinstance(e.get("end_line"), int) for e in es): form, edits = "lines", es
            elif any(isinstance(f, dict) and f.get("content") is not None for f in files) or a.get("content") is not None: continue   # whole-file write: look at the next call
        if not edits: break
        if err and any(k in err for k in SKIP) and "must match exactly once" not in err and "line edit range" not in err and "overlap" not in err: break
        if form == "lines":
            orig_lines = src.split("\n"); region = sum(len("\n".join(orig_lines[max(e["start_line"], 1) - 1: e["end_line"]])) for e in edits if e["end_line"] >= e["start_line"])
            result = None if err else replay_lines(src, edits)
        else:
            region = sum(len(e["old_text"]) for e in edits); result = None if err else replay_text(src, edits, line_start=(form == "patch"))
        syntax = None
        if result is not None:
            try: ast.parse(result); syntax = 1
            except SyntaxError: syntax = 0
        rows.append(dict(model=r.model, bench=r.benchmark, arm=r.arm, batch=r.batch, source=r.source, task=r.task, form=form, n_edits=len(edits), region_tokens=region / 4.0, file_lines=src.count("\n") + 1,
                         applied=int(not err), replayed=int(result is not None), syntax_ok=syntax, error=("no match" if "matched 0" in err else "ambiguous" if "matched" in err else "range" if err else "")))
        break
d = pd.DataFrame(rows); d.to_csv("data/first_calls.csv", index=False)
print("first targeted edit calls:", len(d)); print(d.groupby("form").agg(n=("applied", "size"), applied=("applied", "mean"), replayed=("replayed", "mean"), syntax_ok=("syntax_ok", "mean")).round(3).to_string())
print("\nreplay agrees with the harness (applied but replay failed):", int(((d.applied == 1) & (d.replayed == 0)).sum()), "calls")
