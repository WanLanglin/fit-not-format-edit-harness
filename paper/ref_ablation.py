#!/usr/bin/env python3
"""@@ref ablation. For each model and benchmark, on the tasks valid in every arm: the three baseline
interfaces, the verified selection without @@ref (bin/9a01fe5, 'aligned') and with it (bin/6a13cf6,
'ref'). Per arm: runs that used @@ref, task success, first targeted edit accepted, applied first edits
that leave unparsable Python (replayed with the executor's placement and @@ref expansion, and checked
against the final workspace), output tokens and dollars per task, efficiency vs search/replace; then
ref vs aligned directly (exact McNemar on success, paired bootstrap on efficiency)."""
import ast, glob, json, os, re
from math import comb
import numpy as np, pandas as pd
exec(open("aligned_replay.py").read().split('if __name__ == "__main__":')[0])   # place, snap, norm, _apply, parses, original, dec, cie, ref
MARK = re.compile(r"^(\s*)@@ref\s+(\d+)\s*-\s*(\d+)\s*@@\s*$")
ER = "../editbench/runs"
def shift_of(L, e):
    s0, t0 = e["start_line"], e["end_line"]
    qs = snap(L, s0, norm(e.get("first_line"))); qt = None if qs is None else snap(L, t0, norm(e.get("last_line")), lo=qs)
    return qs - s0 if qs is not None and qt is not None and qs - s0 == qt - t0 else 0
def expand(R, sel, text):
    out = []
    for piece in text.split("\n"):
        m = MARK.match(piece)
        if not m: out.append(piece); continue
        a, b = int(m.group(2)), int(m.group(3))
        ps, pe, sh = next(v for (f, l), v in sel.items() if f <= a <= b <= l)
        block = R[a + sh - 1:b + sh]; ws = [x[:len(x) - len(x.lstrip())] for x in block if x.strip()]
        base = min(ws, key=len) if ws else ""
        out.extend(m.group(1) + x[len(base):] if x.strip() else "" for x in block)
    return "\n".join(out)
def workspace_file(bench, task):
    return cie.load(task).fixture["path"] if bench == "canitedit" else ref.task_files(ref.TASKS / task)[0].name
def run_record(run, bench, verified):
    try: r = json.load(open(run + "/run.json"))
    except Exception: return None
    if r.get("invalid_reasons"): return None
    prefix = "canitedit__" if bench == "canitedit" else "aider-refactor__"
    task = os.path.basename(run)[len(prefix):].rsplit("__", 3)[0]
    out = cost = 0
    for l in open(run + "/model_calls.jsonl", errors="replace"):
        try: c = json.loads(l)
        except Exception: continue
        u = c.get("usage") or {}
        cost += c.get("cost_usd") or 0
        if c.get("status") == 200 and u: out += u.get("completion_tokens") or 0
    rec = dict(task=task, passed=bool(r.get("passed")), out=out, cost=cost, first=None, broken=None, used_ref=False)
    cur = original(bench, task)
    for line in open(run + "/events.jsonl", errors="replace"):
        if '"experiment.tool_call"' not in line: continue
        try: p = json.loads(line)["payload"]
        except Exception: continue
        if p["tool"] != "apply_patch": continue
        err = dec(p.get("error")); raw = dec(p.get("arguments"))
        rec["used_ref"] |= "@@ref " in raw
        try: a = json.loads(raw)
        except Exception:
            if rec["first"] is None: rec["first"] = False
            continue
        files = [f for f in (a.get("files") if isinstance(a.get("files"), list) else []) if isinstance(f, dict)]
        es = [e for f in files for e in (f.get("edits") or []) if isinstance(e, dict)]
        content = [f["content"] for f in files if isinstance(f.get("content"), str)]
        targeted = bool(es) or isinstance(a.get("patch"), str)
        if rec["first"] is None and (targeted or not content): rec["first"] = not err
        new = None
        if not err and es:
            line_form = all(isinstance(e.get("start_line"), int) and isinstance(e.get("end_line"), int) for e in es)
            placed = es
            if line_form and verified:
                R0 = cur.split("\n"); L0 = [x.strip() for x in R0]; pl = [place(R0, e) for e in es]
                if all(x is not None for x in pl):
                    sel = {(e["start_line"], e["end_line"]): (x[0], x[1], shift_of(L0, e)) for e, x in zip(es, pl)}
                    try: placed = [dict(e, start_line=s, end_line=t, new_text=expand(R0, sel, e.get("new_text") or "")) for e, (s, t) in zip(es, pl)]
                    except StopIteration: pass
            try: new = _apply(cur, "lines" if line_form else "text", placed)
            except Exception: new = None
            if rec["broken"] is None and rec["first"] is not None and new is not None and targeted and rec["first"]:
                rec["broken"] = parses(cur) and not parses(new)
        if not err:
            if content: cur = content[0]
            elif new is not None: cur = new
    ws = os.path.join(run, "workspace", workspace_file(bench, task))
    rec["replay_ok"] = os.path.exists(ws) and open(ws, errors="replace").read() == cur
    return rec
SETS = {("canitedit", "GPT-5.6-luna"): {"text": "canitedit-luna-4arms", "patch": "canitedit-luna-4arms", "lines": "canitedit-luna-4arms", "aligned": "canitedit-luna-aligned", "ref": "canitedit-luna-ref"},
        ("canitedit", "MiMo-v2.5-Pro"): {"text": "canitedit-mimo-7arms", "patch": "canitedit-mimo-7arms", "lines": "canitedit-mimo-7arms", "aligned": "canitedit-mimo-aligned", "ref": "canitedit-mimo-ref"},
        ("aider-refactor", "GPT-5.6-luna"): {"text": "refactor-luna-5arms", "patch": "refactor-luna-5arms", "lines": "refactor-luna-5arms", "aligned": "refactor-luna-aligned", "ref": "refactor-luna-ref"},
        ("aider-refactor", "MiMo-v2.5-Pro"): {"text": "refactor-mimo-3arms", "patch": "refactor-mimo-3arms", "lines": "refactor-mimo-3arms", "aligned": "refactor-mimo-aligned", "ref": "refactor-mimo-ref"},
        ("canitedit", "Claude-Sonnet-5"): {"text": "canitedit-claude-sonnet5-2arms", "lines": "canitedit-claude-sonnet5-2arms", "ref": "canitedit-claude-sonnet5-ref"}}
def load(bench, d, name):
    arm = "lines_anchored" if name in ("aligned", "ref") else name
    prefix = "canitedit" if bench == "canitedit" else "aider-refactor"
    recs = [run_record(r, bench, name in ("aligned", "ref")) for r in glob.glob(f"{ER}/{d}/{prefix}__*__{arm}__r0")]
    return {x["task"]: x for x in recs if x}
def mcnemar(a, b):
    n = a + b
    return min(1.0, 2 * sum(comb(n, k) for k in range(min(a, b) + 1)) / 2 ** n) if n else 1.0
rng = np.random.default_rng(0); B = 2000; summary = []
ONLY = os.environ.get('ONLY')
for (bench, model), arms in SETS.items():
    if ONLY and ONLY not in model: continue
    rng = np.random.default_rng(0)  # one stream per benchmark and model
    data = {name: load(bench, d, name) for name, d in arms.items()}
    common = sorted(set.intersection(*(set(v) for v in data.values())))
    def eff(rs, key, idx): return sum(rs[i]["passed"] for i in idx) / max(sum(rs[i][key] for i in idx), 1e-12)
    rows = {}
    base = [data["text"][t] for t in common]
    for name in [n for n in ("text", "patch", "lines", "aligned", "ref") if n in arms]:
        rs = [data[name][t] for t in common]; full = np.arange(len(rs))
        f = [x["first"] for x in rs if x["first"] is not None]; applied = [x for x in rs if x["first"] and x["broken"] is not None]
        row = {"runs that used @@ref": sum(x["used_ref"] for x in rs) if name == "ref" else "-",
               "task success": f"{np.mean([x['passed'] for x in rs]):.3f}", "first edit accepted": f"{np.mean(f):.2f}",
               "broken applied first edits": f"{sum(x['broken'] for x in applied)} of {len(applied)}",
               "output tokens / task": f"{np.mean([x['out'] for x in rs]) / 1000:.1f}k", "dollars / task": f"{np.mean([x['cost'] for x in rs]):.4f}"}
        for key, lab in (("out", "efficiency vs SR (output)"), ("cost", "efficiency vs SR (dollars)")):
            if name == "text": row[lab] = "1"; continue
            r0 = eff(rs, key, full) / eff(base, key, full)
            bs = np.sort([eff(rs, key, i) / eff(base, key, i) for i in (rng.integers(0, len(rs), len(rs)) for _ in range(B))])
            row[lab] = f"{r0:.2f} [{bs[int(.025 * B)]:.2f},{bs[int(.975 * B)]:.2f}]" + ("*" if bs[int(.025 * B)] > 1 or bs[int(.975 * B)] < 1 else "")
        rows[name] = row
    if "aligned" not in data:  # Claude: no aligned arm; report ref against search/replace only
        print(f"\n=== {bench} / {model}: {len(common)} tasks valid in every arm")
        print(pd.DataFrame(rows).to_string()); continue
    A, Rf = [data["aligned"][t] for t in common], [data["ref"][t] for t in common]
    up = sum(r["passed"] and not a["passed"] for a, r in zip(A, Rf)); dn = sum(a["passed"] and not r["passed"] for a, r in zip(A, Rf))
    ratios = {}
    for key in ("out", "cost"):
        r0 = eff(Rf, key, np.arange(len(Rf))) / eff(A, key, np.arange(len(A)))
        bs = np.sort([eff(Rf, key, i) / eff(A, key, i) for i in (rng.integers(0, len(A), len(A)) for _ in range(B))])
        ratios[key] = f"{r0:.2f} [{bs[int(.025 * B)]:.2f},{bs[int(.975 * B)]:.2f}]"
    replay = {n: f"{sum(data[n][t]['replay_ok'] for t in common)}/{len(common)}" for n in ("aligned", "ref") if n in data}
    print(f"\n=== {bench} / {model}: {len(common)} tasks valid in every arm | replay matches workspace: {replay}")
    print(pd.DataFrame(rows).to_string())
    print(f"  ref vs aligned: success +{up}/-{dn} (p={mcnemar(up, dn):.3f}) | efficiency per output {ratios['out']} | per dollar {ratios['cost']}")
    summary.append(dict(bench=bench, model=model, tasks=len(common), ref_used=rows["ref"]["runs that used @@ref"], **{f"{k}_{n}": rows[n][k] for n in ("aligned", "ref") for k in ("task success", "dollars / task")}, ref_vs_aligned_out=ratios["out"], ref_vs_aligned_cost=ratios["cost"], success_diff=f"+{up}/-{dn}"))
if not ONLY: pd.DataFrame(summary).to_csv("data/ref_ablation.csv", index=False)  # a filtered run must not overwrite the table
