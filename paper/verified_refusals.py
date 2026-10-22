#!/usr/bin/env python3
"""Helpers for the replay scripts: reconstruct the file the model was editing at each line edit of
the lines_anchored runs, and normalise its quoted first and last lines."""
import json, glob, os, sys, collections
sys.path.insert(0, "figures")
exec(open("place_check.py").read().split("rows = []")[0])
def norm(s):
    s = (s or "").strip()
    if ": " in s and s.split(": ", 1)[0].isdigit(): s = s.split(": ", 1)[1].strip()
    return s
def edits_of(d):
    """Yield (model_dir, file lines before the call, edits, error) for every line-edit call, in order."""
    for run in sorted(glob.glob(f"../editbench/runs/{d}/aider-refactor__*__lines_anchored__r0")):
        task = os.path.basename(run)[len("aider-refactor__"):].rsplit("__", 3)[0]
        cur = original("aider-refactor", task)
        for line in open(run + "/events.jsonl", errors="replace"):
            if '"experiment.tool_call"' not in line: continue
            p = json.loads(line)["payload"]
            if p["tool"] != "apply_patch": continue
            err = dec(p.get("error"))
            try: a = json.loads(dec(p["arguments"]))
            except Exception: continue
            files = a.get("files") if isinstance(a.get("files"), list) else []
            es = [e for f in files if isinstance(f, dict) for e in (f.get("edits") or []) if isinstance(e, dict)]
            content = [f.get("content") for f in files if isinstance(f, dict) and f.get("content") is not None]
            if es and all(isinstance(e.get("start_line"), int) and isinstance(e.get("end_line"), int) for e in es):
                yield run, task, cur, es, err
            if not err:
                if content: cur = content[0]
                elif es:
                    try: cur = _apply(cur, "lines", es)
                    except Exception: pass
