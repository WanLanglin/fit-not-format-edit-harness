#!/usr/bin/env python3
"""Offline replay of boundary alignment on the recorded lines_anchored edits, with the same rules as
place_line_edit in the experiment executor: a quoted boundary line is looked for within +-3 lines
(nearest, no ties); the range moves only if both boundaries move alike or a boundary crosses blank
lines only; a new-text edge line identical (indentation included) to the non-blank line just
outside the range takes that line in, unless it also repeats the line inside."""
import collections, glob, json, os
exec(open("verified_replay.py").read().split('for model, d in')[0])
def place(R, e):
    L = [x.strip() for x in R]; s0, t0 = e["start_line"], e["end_line"]
    s = snap(L, s0, norm(e.get("first_line")))
    t = None if s is None else snap(L, t0, norm(e.get("last_line")), lo=s)
    if s is None or t is None or t < s: return None
    def blank_only(a, b):
        lo, hi = min(a, b), max(a, b)
        return a == b or (all(L[x - 1] == "" for x in range(lo + 1, hi)) and (L[lo - 1] == "" or L[hi - 1] == ""))
    even = abs(s - s0) == abs(t - t0) and (s >= s0) == (t >= t0)
    if not (even or (blank_only(s0, s) and blank_only(t0, t))): return None
    nl = [x.rstrip() for x in (e.get("new_text") or "").rstrip("\n").split("\n")]
    def restates(out, inside, line):
        o = R[out - 1].rstrip() if 1 <= out <= len(R) else ""
        return o.strip() != "" and o == line and R[inside - 1].rstrip() != o
    top = s >= 2 and restates(s - 1, s, nl[0]); bot = t < len(R) and restates(t + 1, t, nl[-1])
    if not (top and bot and len(nl) == 1): s, t = s - top, t + bot
    return s, t
def valid(d, arm):
    out = set()
    for run in glob.glob(f"../editbench/runs/{d}/aider-refactor__*__{arm}__r0"):
        try: r = json.load(open(run + "/run.json"))
        except Exception: continue
        if not r.get("invalid_reasons"): out.add(os.path.basename(run)[len("aider-refactor__"):].rsplit("__", 3)[0])
    return out
def outcome(cur, es):
    try: return "clean" if parses(_apply(cur, "lines", es)) else "broken"
    except Exception: return "refused"
