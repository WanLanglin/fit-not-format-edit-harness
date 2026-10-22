#!/usr/bin/env python3
"""Dollar efficiency with caching held fixed. Cache hit rates are set by the provider and differ between run
dates (the method arms ran later than the baselines), so billed dollars mix interface effects with cache luck.
Per model, list prices are recovered by least squares on per-call billed cost ~ uncached + cached + completion,
then every run is repriced two ways that do not depend on the provider's cache luck:
  neutral: all input at the uncached price (no cache);
  ideal:   perfect prefix caching - the agent context is append-only, so in call i the tokens of call i-1's prompt
           are a cached prefix and only the rest is new (a lower bound on what an ideal prefix cache reuses)."""
import ast, glob, json, os, collections
import numpy as np
ER = "../editbench/runs"
_src = open("ref_ablation.py").read()
SETS = ast.literal_eval(_src[_src.index("SETS = {") + 7:_src.index("\ndef load(")])
def calls(run):
    prev = 0
    for l in open(run + "/model_calls.jsonl", errors="replace"):
        try: c = json.loads(l)
        except Exception: continue
        u = c.get("usage") or {}
        if c.get("status") != 200 or not u: continue
        cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        prompt = u.get("prompt_tokens") or 0; reusable = min(prompt, prev); prev = prompt
        yield prompt - cached, cached, u.get("completion_tokens") or 0, c.get("cost_usd") or 0, reusable
def load(bench, d, name):
    arm = "lines_anchored" if name in ("aligned", "ref") else name
    prefix = "canitedit" if bench == "canitedit" else "aider-refactor"
    out = {}
    for run in glob.glob(f"{ER}/{d}/{prefix}__*__{arm}__r0"):
        try: r = json.load(open(run + "/run.json"))
        except Exception: continue
        if r.get("invalid_reasons"): continue
        out[os.path.basename(run)[len(prefix) + 2:].rsplit("__", 3)[0]] = dict(passed=bool(r.get("passed")), calls=list(calls(run)))
    return out
rng = np.random.default_rng(0); B = 2000
for (bench, model), arms in SETS.items():
    rng = np.random.default_rng(0)  # one stream per benchmark and model
    names = [n for n in ("text", "lines", "aligned", "ref") if n in arms]
    data = {n: load(bench, arms[n], n) for n in names}
    common = sorted(set.intersection(*(set(v) for v in data.values())))
    if "Claude" in model:
        p_unc, p_cache, p_out = 2.0e-6, 0.2e-6, 10.0e-6  # OpenRouter list prices; its runs had no cache hits, so a fit cannot recover the cached price
    else:
        X = np.array([c[:3] for n in names for t in common for c in data[n][t]["calls"]], float)
        y = np.array([c[3] for n in names for t in common for c in data[n][t]["calls"]], float)
        p_unc, p_cache, p_out = np.linalg.lstsq(X, y, rcond=None)[0]
    def cost(rec, mode):
        total = 0.0
        for u, ca, o, _, reuse in rec["calls"]:
            if mode == "neutral": total += (u + ca) * p_unc + o * p_out
            elif mode == "ideal": total += reuse * p_cache + (u + ca - reuse) * p_unc + o * p_out
            else: total += u * p_unc + ca * p_cache + o * p_out
        return total
    def eff(rs, key, idx): return sum(rs[i]["passed"] for i in idx) / sum(rs[i][key] for i in idx)
    rows = {n: [dict(passed=data[n][t]["passed"], billed=cost(data[n][t], "billed"), neutral=cost(data[n][t], "neutral"), ideal=cost(data[n][t], "ideal")) for t in common] for n in names}
    share = {n: sum(c[4] for t in common for c in data[n][t]["calls"]) / max(1, sum(c[0] + c[1] for t in common for c in data[n][t]["calls"])) for n in names}
    billed_share = {n: sum(c[1] for t in common for c in data[n][t]["calls"]) / max(1, sum(c[0] + c[1] for t in common for c in data[n][t]["calls"])) for n in names}
    print(f"\n{bench} / {model}: {len(common)} tasks | prices $/M uncached {p_unc*1e6:.3f} cached {p_cache*1e6:.3f} output {p_out*1e6:.3f}")
    for n in names[1:]:
        out = []
        for key in ("billed", "neutral", "ideal"):
            full = np.arange(len(common)); r0 = eff(rows[n], key, full) / eff(rows["text"], key, full)
            bs = np.sort([eff(rows[n], key, i) / eff(rows["text"], key, i) for i in (rng.integers(0, len(common), len(common)) for _ in range(B))])
            star = "*" if bs[50] > 1 or bs[1949] < 1 else ""
            out.append(f"{key} {r0:.2f} [{bs[50]:.2f},{bs[1949]:.2f}]{star}")
        print(f"  {n:8s} vs SR dollar efficiency: " + " | ".join(out))
    print("  input share cached: billed " + ", ".join(f"{n} {billed_share[n]:.0%}" for n in names) + " | reusable prefix (ideal) " + ", ".join(f"{n} {share[n]:.0%}" for n in names))
