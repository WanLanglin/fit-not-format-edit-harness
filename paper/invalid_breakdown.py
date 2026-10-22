#!/usr/bin/env python3
"""Classify the applied-but-invalid first LINE-RANGE edits (same selection as region_law.py).
boundary : shifting start and/or end by one line makes the result parse
new_text : the new text alone (dedented) does not parse as a block, and no shift fixes it
other    : neither (includes intermediate states of a multi-step refactor)
Also reports the two signatures used in the paper and their overlap, overall and for >=200 tokens."""
import ast, json, re, sys, textwrap
from pathlib import Path
import pandas as pd
sys.path.insert(0, "figures")
exec(open("place_check.py").read().split("rows = []")[0])          # reuse loaders and helpers
def apply_lines(src, edits):
    try: return _apply(src, "lines", edits)
    except Exception: return None
def parses(t):
    try: ast.parse(t); return True
    except Exception: return False
rows = []
frame = runs(None)
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
        if isinstance(a.get("patch"), str): break
        files = a.get("files") if isinstance(a.get("files"), list) else ([a] if isinstance(a.get("edits"), list) else [])
        es = [e for f in files if isinstance(f, dict) for e in (f.get("edits") or []) if isinstance(e, dict)]
        if not (es and all(isinstance(e.get("start_line"), int) and isinstance(e.get("end_line"), int) for e in es)):
            if any(isinstance(f, dict) and f.get("content") is not None for f in files) or a.get("content") is not None: continue
            break
        if err: break
        out = apply_lines(src, es)
        if out is None or parses(out): break
        L = src.split("\n")
        region = sum(len("\n".join(L[max(e["start_line"],1)-1:e["end_line"]])) for e in es) / 4
        # signatures used in the paper
        dup = any((e.get("new_text") or "").split("\n")[0].strip() and ((e["start_line"] >= 2 and (e.get("new_text") or "").split("\n")[0].strip() == L[e["start_line"]-2].strip())
                  or (e["end_line"] < len(L) and (e.get("new_text") or "").rstrip("\n").split("\n")[-1].strip() == L[e["end_line"]].strip())) for e in es)
        try: ast.parse(out); nobody = False
        except SyntaxError as ex: nobody = "expected an indented block" in str(ex)
        # where is the parse error: inside text the model wrote, or in original code around it?
        spans=[]; delta=0
        for e in sorted(es, key=lambda e: e["start_line"]):
            nl=len((e.get("new_text") or "").rstrip("\n").split("\n")) if (e.get("new_text") or "") else 0
            st=e["start_line"]+delta; spans.append((st, st+nl-1)); delta+=nl-(e["end_line"]-e["start_line"]+1)
        try: ast.parse(out); errline=None
        except SyntaxError as ex: errline=ex.lineno
        inside = errline is not None and any(a_-1 <= errline <= b_+1 for a_,b_ in spans)
        # boundary: shifting one edit's start or end by one line (others fixed) makes it parse
        fixed=False
        for i,e in enumerate(es):
            for ds,de in ((-1,0),(1,0),(0,-1),(0,1),(-1,-1),(1,1)):
                f=[dict(x) for x in es]; f[i]["start_line"]+=ds; f[i]["end_line"]+=de
                o=apply_lines(src,f)
                if o is not None and parses(o): fixed=True; break
            if fixed: break
        cls = "boundary_fixable" if fixed else ("error_in_written_text" if inside else "error_in_surrounding_code")
        rows.append(dict(model=r.model, bench=r.benchmark, task=r.task, region=region, n_edits=len(es), dup=int(dup), nobody=int(nobody), cls=cls))
        break
d = pd.DataFrame(rows); d.to_csv("data/invalid_breakdown.csv", index=False)
for name, g in [("all sizes", d), (">=200 tokens", d[d.region >= 200])]:
    print(f"== {name}: n={len(g)}  (refactor {int((g.bench=='aider-refactor').sum())})")
    print("  dup boundary line:", int(g.dup.sum()), " def/class without body:", int(g.nobody.sum()), " both:", int((g.dup & g.nobody).sum()), " neither:", int(((g.dup==0)&(g.nobody==0)).sum()))
    print("  class:", g.cls.value_counts().to_dict())
    print("  class x bench:", g.groupby(["bench","cls"]).size().to_dict())
