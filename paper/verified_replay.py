#!/usr/bin/env python3
"""Boundary helpers for the alignment replay (aligned_replay.py): snap moves a quoted boundary to the
nearest line within +-3 whose text equals the quote (blank lines count as distance) and refuses
when no line, or more than one equally near line, matches."""
import ast, collections, sys
exec(open("verified_refusals.py").read().split('if __name__ == "__main__":')[0])
def parses(t):
    try: ast.parse(t); return True
    except Exception: return False
def snap(L, n, quote, lo=1):
    if 0 < n <= len(L) and L[n - 1] == quote: return n
    hits = [x for x in range(max(lo, n - 3), min(len(L), n + 3) + 1) if L[x - 1] == quote]
    if not hits: return None
    best = min(abs(x - n) for x in hits); near = [x for x in hits if abs(x - n) == best]
    return near[0] if len(near) == 1 else None
def resolve(L, e):
    s = snap(L, e["start_line"], norm(e.get("first_line")))
    if s is None: return None
    t = snap(L, e["end_line"], norm(e.get("last_line")), lo=s)
    return None if t is None else (s, t)
