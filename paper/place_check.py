#!/usr/bin/env python3
"""Where did the first targeted edit land, relative to where the reference solution edits?

For every run's first targeted edit (same selection as region_law.py), locate the region
it addresses in the ORIGINAL file as a line interval, and compare it with the reference:
  canitedit      lines changed by the before->after diff (inserts count their boundary line)
  aider-refactor the span of the method the task asks to move (found by ast)
Writes data/place_check.csv.  `near` = the two intervals touch or are within 1 line.
"""
import ast, difflib, importlib.util, json, re, sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, "figures")
from style import runs
RUNS = Path("../editbench/runs"); EB = Path("../editbench")
def dec(o): return bytes.fromhex(o["hex"]).decode(errors="replace") if isinstance(o, dict) and "hex" in o else (o or "")
def load(name):
    spec = importlib.util.spec_from_file_location(name, EB / "adapters" / f"{name}.py"); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
cie, ref = load("canitedit"), load("aider_refactor")
_orig, _ref = {}, {}
def original(bench, task):
    if (bench, task) not in _orig:
        _orig[(bench, task)] = cie.load(task).fixture["before"] if bench == "canitedit" else ref.task_files(ref.TASKS / task)[0].read_text(errors="replace")
    return _orig[(bench, task)]
def ref_region(bench, task):
    """1-based inclusive line interval(s) of the original file that the reference touches."""
    if (bench, task) in _ref: return _ref[(bench, task)]
    src = original(bench, task); out = []
    if bench == "canitedit":
        after = cie.load(task).fixture["after"]
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, src.split("\n"), after.split("\n")).get_opcodes():
            if tag == "equal": continue
            out.append((i1 + 1, i2) if i2 > i1 else (max(i1, 1), min(i1 + 1, src.count("\n") + 1)))   # insert: boundary lines
    else:
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for f in node.body:
                    if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and task.endswith(f"{node.name}_{f.name}"):
                        out.append((f.lineno, f.end_lineno))
    _ref[(bench, task)] = out; return out
def line_of(content, off): return content.count("\n", 0, off) + 1
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
def near(a, regions, tol=1):
    return any(a[0] <= r[1] + tol and r[0] <= a[1] + tol for r in regions)
def _apply(src, form, edits):
    if form == "lines":
        content = src
        for e in sorted(edits, key=lambda e: -e["start_line"]):
            starts = [0] + [i + 1 for i, ch in enumerate(content) if ch == "\n"]
            nn = len(starts) - 1 if content.endswith("\n") else len(starts)
            s, t = e["start_line"], e["end_line"]
            if s < 1 or t < s or t > nn: raise ValueError
            a_ = starts[s - 1]; b_ = starts[t] if t < len(starts) else len(content)
            rep = e.get("new_text") or ""
            if content[a_:b_].endswith("\n") and rep and not rep.endswith("\n"): rep += "\n"
            content = content[:a_] + rep + content[b_:]
        return content
    content = src
    for e in edits:
        old, new = e["old_text"], e.get("new_text") or ""
        hits = [m.start() for m in re.finditer(re.escape(old), content) if form != "patch" or m.start() == 0 or content[m.start() - 1] == "\n"]
        if len(hits) != 1: raise ValueError
        content = content[:hits[0]] + new + content[hits[0] + len(old):]
    return content
rows = []
# Claude Sonnet 5 joined after the main study; the RQ2 replay analyses cover the main study.
frame = runs(None); frame = frame[frame.batch != "claude"]
for r in frame.itertuples():
    hits = list((RUNS / r.source).glob(f"*__{r.task}__*__{r.arm}__r0/events.jsonl"))
    if not hits: continue
    src = original(r.benchmark, r.task); refs = ref_region(r.benchmark, r.task)
    if not refs: continue
    for line in hits[0].read_text(errors="replace").splitlines():
        if '"experiment.tool_call"' not in line: continue
        p = json.loads(line)["payload"]
        if p["tool"] not in ("apply_patch", "edit_text", "edit_lines"): continue
        try: a = json.loads(dec(p["arguments"]))
        except Exception: break
        err = dec(p.get("error")); form = edits = None
        if isinstance(a.get("patch"), str): form, edits = "patch", parse_patch(a["patch"])
        else:
            files = a.get("files") if isinstance(a.get("files"), list) else ([a] if isinstance(a.get("edits"), list) else [])
            es = [e for f in files if isinstance(f, dict) for e in (f.get("edits") or []) if isinstance(e, dict)]
            if es and all(isinstance(e.get("old_text"), str) for e in es): form, edits = "text", es
            elif es and all(isinstance(e.get("start_line"), int) and isinstance(e.get("end_line"), int) for e in es): form, edits = "lines", es
            elif any(isinstance(f, dict) and f.get("content") is not None for f in files) or a.get("content") is not None: continue
        if not edits: break
        if err and any(k in err for k in SKIP) and "must match exactly once" not in err and "line edit range" not in err and "overlap" not in err: break
        if err: break                      # only applied first edits are of interest here
        e = edits[0]
        if form == "lines": region = (e["start_line"], e["end_line"])
        else:
            m = [x.start() for x in re.finditer(re.escape(e["old_text"]), src) if form != "patch" or x.start() == 0 or src[x.start() - 1] == "\n"]
            if len(m) != 1: break
            region = (line_of(src, m[0]), line_of(src, m[0] + max(len(e["old_text"]) - 1, 0)))
        n = src.count("\n") + 1
        region = (max(1, region[0]), min(n, region[1]))
        try: ast.parse(_apply(src, form, edits)); syntax = 1
        except SyntaxError: syntax = 0
        except Exception: syntax = None
        rows.append(dict(model=r.model, bench=r.benchmark, arm=r.arm, task=r.task, form=form, passed=int(r.passed),
                         start=region[0], end=region[1], region_lines=region[1] - region[0] + 1, file_lines=n,
                         ref_start=refs[0][0], ref_end=refs[-1][1], near=int(near(region, refs)), syntax_ok=syntax))
        break
d = pd.DataFrame(rows); d.to_csv("data/place_check.csv", index=False)
print("applied first edits with a locatable region:", len(d))
for bench, g in d.groupby("bench"):
    print(f"\n== {bench} ==")
    t = g.groupby("form").agg(n=("near", "size"), near=("near", "mean"), passed=("passed", "mean")).round(3)
    t["far_and_failed"] = g.assign(ff=(g.near == 0) & (g.passed == 0)).groupby("form").ff.mean().round(3)
    t["far_and_passed"] = g.assign(fp=(g.near == 0) & (g.passed == 1)).groupby("form").fp.mean().round(3)
    print(t.to_string())
