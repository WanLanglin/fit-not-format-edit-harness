#!/usr/bin/env python3
"""Table 3 (RQ4), with dollars under ideal prefix caching: plain line-range, verified line-range (strict boundary check) and verified line-range with
boundary alignment, with and without @@ref, on the Aider refactor tasks valid in every arm (search/replace is the
efficiency baseline). Per run: task success; the first targeted edit (a call with edits or a patch;
a call with neither edits nor content counts as a failure, whole-file writes are skipped) - accepted,
and if applied, whether the file still parses (replayed on the file as it stood, with the aligned
placement for the aligned arm); whether any boundary refusal occurred; output tokens (completion
tokens of successful model calls) and billed dollars. Efficiency = solved / output tokens (or
dollars), relative to search/replace on the same tasks, paired bootstrap 95% interval."""
import glob, json, os, re, sys
import numpy as np, pandas as pd
exec(open("aligned_replay.py").read().split('if __name__ == "__main__":')[0])   # place, _apply, parses, original, dec
ER = "../editbench/runs"
SETS = {"GPT-5.6-luna": [("text", "refactor-luna-5arms", "text"), ("lines", "refactor-luna-5arms", "lines"),
                         ("verified", "refactor-luna-anchored", "lines_anchored"), ("aligned", "refactor-luna-aligned", "lines_anchored"),
                         ("ref", "refactor-luna-ref", "lines_anchored")],
        "MiMo-v2.5-Pro": [("text", "refactor-mimo-3arms", "text"), ("lines", "refactor-mimo-3arms", "lines"),
                          ("verified", "refactor-mimo-anchored", "lines_anchored"), ("aligned", "refactor-mimo-aligned", "lines_anchored"),
                          ("ref", "refactor-mimo-ref", "lines_anchored")]}
MARK = re.compile(r"^(\s*)@@ref\s+(\d+)\s*-\s*(\d+)\s*@@\s*$")
def shift_of(L, e):
    s0, t0 = e["start_line"], e["end_line"]
    qs = snap(L, s0, norm(e.get("first_line"))); qt = None if qs is None else snap(L, t0, norm(e.get("last_line")), lo=qs)
    return qs - s0 if qs is not None and qt is not None and qs - s0 == qt - t0 else 0
def expand(R, sel, text):
    """Same rules as the @@ref expansion in the harness (build 6a13cf6)."""
    out = []
    for piece in text.split("\n"):
        m = MARK.match(piece)
        if not m: out.append(piece); continue
        a, b = int(m.group(2)), int(m.group(3))
        ps, pe, sh = next(v for (f, l), v in sel.items() if f <= a <= b <= l)
        block = R[a + sh - 1:b + sh]
        ws = [x[:len(x) - len(x.lstrip())] for x in block if x.strip()]
        base = min(ws, key=len) if ws else ""
        out.extend(m.group(1) + x[len(base):] if x.strip() else "" for x in block)
    return "\n".join(out)
def run_record(run, aligned):
    try: r = json.load(open(run + "/run.json"))
    except Exception: return None
    if r.get("invalid_reasons"): return None
    task = os.path.basename(run)[len("aider-refactor__"):].rsplit("__", 3)[0]
    out = cost = 0; parts = []; prev = 0
    for l in open(run + "/model_calls.jsonl", errors="replace"):
        try: c = json.loads(l)
        except Exception: continue
        cost += c.get("cost_usd") or 0
        u = c.get("usage") or {}
        if c.get("status") == 200 and u:
            out += u.get("completion_tokens") or 0
            prompt = u.get("prompt_tokens") or 0; cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
            parts.append((prompt - cached, cached, u.get("completion_tokens") or 0, c.get("cost_usd") or 0, min(prompt, prev))); prev = prompt
    rec = dict(task=task, passed=bool(r.get("passed")), out=out, cost=cost, parts=parts, first=None, broken=None, refusals=0, used_ref=False)
    cur = original("aider-refactor", task)
    for line in open(run + "/events.jsonl", errors="replace"):
        if '"experiment.tool_call"' not in line: continue
        p = json.loads(line)["payload"]
        if p["tool"] != "apply_patch": continue
        err = dec(p.get("error"))
        rec["refusals"] += "does not match line" in err
        rec["used_ref"] |= "@@ref " in dec(p["arguments"])
        if rec["first"] is not None: continue
        try: a = json.loads(dec(p["arguments"]))
        except Exception: rec["first"] = False; continue
        files = [f for f in (a.get("files") if isinstance(a.get("files"), list) else []) if isinstance(f, dict)]
        es = [e for f in files for e in (f.get("edits") or []) if isinstance(e, dict)]
        content = [f["content"] for f in files if f.get("content") is not None] or ([a["content"]] if isinstance(a.get("content"), str) else [])
        if es or isinstance(a.get("patch"), str):
            rec["first"] = not err
            if not err and es:
                lines_form = all(isinstance(e.get("start_line"), int) for e in es)
                placed = es
                if lines_form and aligned:
                    R0 = cur.split("\n"); L0 = [x.strip() for x in R0]
                    pl = [place(R0, e) for e in es]
                    if all(x is not None for x in pl):
                        sel = {(e["start_line"], e["end_line"]): (x[0], x[1], shift_of(L0, e)) for e, x in zip(es, pl)}
                        try: placed = [dict(e, start_line=s, end_line=t, new_text=expand(R0, sel, e.get("new_text") or "")) for e, (s, t) in zip(es, pl)]
                        except StopIteration: placed = es
                try: rec["broken"] = not parses(_apply(cur, "lines" if lines_form else "text", placed))
                except Exception: pass
            continue
        if content:
            if not err: cur = content[0]
            continue
        rec["first"] = False                                  # neither edits nor content: malformed
    return rec
def load(d, arm, aligned):
    recs = [run_record(r, aligned) for r in glob.glob(f"{ER}/{d}/aider-refactor__*__{arm}__r0")]
    return {r["task"]: r for r in recs if r}
rng = np.random.default_rng(0); B = 2000
for model, arms in SETS.items():
    data = {name: load(d, arm, name in ("aligned", "ref")) for name, d, arm in arms}
    X = np.array([p[:3] for v in data.values() for r in v.values() for p in r["parts"]], float); Y = np.array([p[3] for v in data.values() for r in v.values() for p in r["parts"]], float)
    pu, pc, po = np.linalg.lstsq(X, Y, rcond=None)[0]
    for v in data.values():
        for r in v.values(): r["ideal"] = sum(re_ * pc + (u + ca - re_) * pu + o * po for u, ca, o, _, re_ in r["parts"])
    print(f"fitted $/M: uncached {pu*1e6:.3f} cached {pc*1e6:.3f} output {po*1e6:.3f}")
    common = sorted(set.intersection(*(set(v) for v in data.values())))
    print(f"\n=== {model}: {len(common)} tasks valid in every arm (per arm valid: {', '.join(f'{k} {len(v)}' for k, v in data.items())})")
    base = [data["text"][t] for t in common]
    def eff(rs, key, idx): return sum(rs[i]["passed"] for i in idx) / sum(rs[i][key] for i in idx)
    rows = {}
    for name in ("text", "lines", "verified", "aligned", "ref"):
        rs = [data[name][t] for t in common]; full = np.arange(len(rs))
        f = [r["first"] for r in rs if r["first"] is not None]
        applied = [r for r in rs if r["first"] and r["broken"] is not None]
        row = {"first edit accepted": f"{np.mean(f):.2f}",
               "runs that used @@ref": sum(r["used_ref"] for r in rs) if name == "ref" else "-",
               "runs with a boundary refusal": sum(r["refusals"] > 0 for r in rs) if name in ("verified", "aligned", "ref") else "-",
               "broken applied first edits": f"{sum(r['broken'] for r in applied)} of {len(applied)}",
               "clean first edit": f"{sum(bool(r['first']) and r['broken'] is False for r in rs) / len(rs):.2f}",
               "task success": f"{np.mean([r['passed'] for r in rs]):.3f}",
               "output tokens / task": f"{np.mean([r['out'] for r in rs]) / 1000:.1f}k",
               "dollars / task": f"{np.mean([r['cost'] for r in rs]):.4f}"}
        for key, lab in (("out", "efficiency vs SR (output)"), ("cost", "efficiency vs SR (billed $)"), ("ideal", "efficiency vs SR (ideal-cache $)")):
            if name == "text": row[lab] = "1"; continue
            r0 = eff(rs, key, full) / eff(base, key, full)
            bs = np.sort([eff(rs, key, i) / eff(base, key, i) for i in (rng.integers(0, len(rs), len(rs)) for _ in range(B))])
            lo, hi = bs[int(.025 * B)], bs[int(.975 * B)]
            row[lab] = f"{r0:.2f} [{lo:.2f},{hi:.2f}]" + ("*" if lo > 1 or hi < 1 else "")
        rows[name] = row
    print(pd.DataFrame(rows).to_string())
    A, P = [data["aligned"][t] for t in common], [data["ref"][t] for t in common]
    for key, lab in (("out", "output"), ("cost", "billed dollars"), ("ideal", "ideal-cache dollars")):
        e = lambda rs, i: sum(rs[j]["passed"] for j in i) / sum(rs[j][key] for j in i)
        r0 = e(P, np.arange(len(P))) / e(A, np.arange(len(A)))
        bs = np.sort([e(P, i) / e(A, i) for i in (rng.integers(0, len(P), len(P)) for _ in range(B))])
        print(f"  ref vs aligned, efficiency per {lab}: {r0:.2f} [{bs[int(.025 * B)]:.2f}, {bs[int(.975 * B)]:.2f}]")
    for a, b in (("ref", "aligned"), ("aligned", "verified"), ("verified", "lines"), ("ref", "lines"), ("ref", "text")):
        up = sum(data[a][t]["passed"] and not data[b][t]["passed"] for t in common); dn = sum(data[b][t]["passed"] and not data[a][t]["passed"] for t in common)
        n = up + dn; from math import comb
        p = min(1.0, 2 * sum(comb(n, k) for k in range(min(up, dn) + 1)) / 2 ** n) if n else 1.0
        print(f"  success {a} vs {b}: +{up}/-{dn} (exact McNemar p={p:.3f})")

    for a, b in (("ref", "text"), ("ref", "lines")):
        fa = {t: bool(data[a][t]["first"]) for t in common}; fb = {t: bool(data[b][t]["first"]) for t in common}
        up = sum(fa[t] and not fb[t] for t in common); dn = sum(fb[t] and not fa[t] for t in common); n = up + dn
        p = min(1.0, 2 * sum(comb(n, k) for k in range(min(up, dn) + 1)) / 2 ** n) if n else 1.0
        ca = {t: bool(data[a][t]["first"]) and data[a][t]["broken"] is False for t in common}; cb = {t: bool(data[b][t]["first"]) and data[b][t]["broken"] is False for t in common}
        up2 = sum(ca[t] and not cb[t] for t in common); dn2 = sum(cb[t] and not ca[t] for t in common); n2 = up2 + dn2
        p2 = min(1.0, 2 * sum(comb(n2, k) for k in range(min(up2, dn2) + 1)) / 2 ** n2) if n2 else 1.0
        print(f"  first edit accepted {a} vs {b}: +{up}/-{dn} (p={p:.3f}) | clean first edit: +{up2}/-{dn2} (p={p2:.3f})")
