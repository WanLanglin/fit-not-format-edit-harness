#!/usr/bin/env python3
"""How often are the line numbers of a first edit wrong, judged by the model's own quoted boundaries?

In the verified-selection arms every line edit carries start/end line numbers AND the quoted first and
last line of the span. For each run's first targeted edit call, compare the quotes with the file the
model was editing:
  exact      both quotes equal the lines at the stated numbers
  blank edge the range only includes one extra blank line at an edge (whitespace, not code, would change)
  shifted    both quotes match at one common offset of 1-3 lines (the numbers are off, the intent is clear)
  one end    one quote matches at its stated line, the other within 1-3 lines (one boundary off)
  other      anything else (misquoted text, or the quoted line is not near the range)
Then replay every misaddressed call (shifted or one end) as a bare line range, i.e. at the stated numbers
without the check, and parse the result: this splits misaddressed edits into those a parse check would
catch and those that would apply as valid code at the wrong lines.
Writes data/misaddress.txt.
"""
import ast, collections, glob, json, os, sys
sys.path.insert(0, "figures")
exec(open("place_check.py").read().split("rows = []")[0])   # original(), dec(), _apply()

ARMS = [("refactor", "luna", "P1", "refactor-luna-anchored"), ("refactor", "luna", "P1+P2", "refactor-luna-aligned"),
        ("refactor", "luna", "ours", "refactor-luna-ref"), ("refactor", "luna", "ours rep", "refactor-luna-ref-rep1"),
        ("refactor", "MiMo", "P1", "refactor-mimo-anchored"), ("refactor", "MiMo", "P1+P2", "refactor-mimo-aligned"),
        ("refactor", "MiMo", "ours", "refactor-mimo-ref"), ("refactor", "MiMo", "ours rep", "refactor-mimo-ref-rep1"),
        ("canitedit", "luna", "ours", "canitedit-luna-ref"), ("canitedit", "luna", "ours rep", "canitedit-luna-ref-rep1"),
        ("canitedit", "MiMo", "ours", "canitedit-mimo-ref"), ("canitedit", "Claude", "ours", "canitedit-claude-sonnet5-ref")]
BENCH = {"refactor": ("aider-refactor", "aider-refactor__"), "canitedit": ("canitedit", "canitedit__")}


def norm(s):
    s = (s or "").strip()
    if ": " in s and s.split(": ", 1)[0].isdigit(): s = s.split(": ", 1)[1].strip()
    return s


def first_call(run, bench, prefix):
    """(file before the call, edits) for the run's first targeted line-edit call, or None."""
    task = os.path.basename(run)[len(prefix):].rsplit("__", 3)[0]
    cur = original(bench, task)
    for line in open(run + "/events.jsonl", errors="replace"):
        if '"experiment.tool_call"' not in line: continue
        p = json.loads(line)["payload"]
        if p["tool"] != "apply_patch": continue
        try: a = json.loads(dec(p["arguments"]))
        except Exception: continue
        files = a.get("files") if isinstance(a.get("files"), list) else []
        es = [e for f in files if isinstance(f, dict) for e in (f.get("edits") or []) if isinstance(e, dict)]
        content = [f.get("content") for f in files if isinstance(f, dict) and f.get("content") is not None]
        if es and all(isinstance(e.get("start_line"), int) and isinstance(e.get("end_line"), int) for e in es):
            return cur, es
        if content and not dec(p.get("error")): cur = content[0]
    return None


def classify(L, e):
    s, t = e["start_line"], e["end_line"]; fa, la = norm(e.get("first_line")), norm(e.get("last_line"))
    at = lambda i, q: 0 < i <= len(L) and L[i - 1] == q
    if at(s, fa) and at(t, la): return "exact"
    # the range only gains or loses a blank line at an edge: bare replacement would change whitespace, not code
    end_blank = at(s, fa) and 0 < t <= len(L) and L[t - 1] == "" and at(t - 1, la)
    start_blank = at(t, la) and 0 < s <= len(L) and L[s - 1] == "" and at(s + 1, fa)
    if end_blank or start_blank: return "blank edge"
    if any(at(s + k, fa) and at(t + k, la) for k in (-3, -2, -1, 1, 2, 3)): return "shifted"
    if (at(s, fa) and any(at(t + k, la) for k in (-3, -2, -1, 1, 2, 3))) or \
       (at(t, la) and any(at(s + k, fa) for k in (-3, -2, -1, 1, 2, 3))): return "one end"
    return "other"


def parses(src):
    try: ast.parse(src); return True
    except Exception: return False


out = []
tot = {}
for bench_key, model, arm, d in ARMS:
    bench, prefix = BENCH[bench_key]
    C = collections.Counter()
    for run in sorted(glob.glob(f"../editbench/runs/{d}/{prefix}*__lines_anchored__r0")):
        fc = first_call(run, bench, prefix)
        if fc is None: continue
        cur, es = fc
        L = [x.strip() for x in cur.split("\n")]
        cls = [classify(L, e) for e in es]
        if all(c == "exact" for c in cls): C["exact"] += 1; continue
        if all(c in ("exact", "blank edge") for c in cls): C["blank edge"] += 1; continue
        if any(c == "other" for c in cls): C["other"] += 1; continue
        C["misaddressed"] += 1
        try: replay = _apply(cur, "lines", es)
        except Exception: C["misaddressed: replay n/a"] += 1; continue
        C["misaddressed: would parse" if parses(replay) else "misaddressed: would break"] += 1
    n = C["exact"] + C["blank edge"] + C["misaddressed"] + C["other"]
    row = (f"{bench_key:9s} {model:6s} {arm:8s} first calls {n:3d} | exact {C['exact']:3d} | blank edge {C['blank edge']:2d} | misaddressed {C['misaddressed']:3d}"
           f" ({C['misaddressed'] / max(n, 1):.1%}): would parse {C['misaddressed: would parse']:3d}, would break"
           f" {C['misaddressed: would break']:3d}, n/a {C['misaddressed: replay n/a']} | other {C['other']:3d}")
    print(row); out.append(row)
    tot[bench_key] = tot.get(bench_key, collections.Counter()) + C
for b, T in tot.items():
    n = T["exact"] + T["blank edge"] + T["misaddressed"] + T["other"]
    row = (f"{b.upper()} TOTAL first calls {n} | blank edge {T['blank edge']} | misaddressed {T['misaddressed']} ({T['misaddressed'] / n:.1%})"
           f" | would parse {T['misaddressed: would parse']} | would break {T['misaddressed: would break']} | n/a {T['misaddressed: replay n/a']}")
    print(row); out.append(row)
open("data/misaddress.txt", "w").write("\n".join(out) + "\n")
raise SystemExit
n = tot["exact"] + tot["misaddressed"] + tot["other"]
row = (f"REFACTOR TOTAL first calls {n} | misaddressed {tot['misaddressed']} ({tot['misaddressed'] / n:.1%}) | would parse "
       f"{tot['misaddressed: would parse']} | would break {tot['misaddressed: would break']} | n/a {tot['misaddressed: replay n/a']}")
print(row); out.append(row)
open("data/misaddress.txt", "w").write("\n".join(out) + "\n")
