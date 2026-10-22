#!/usr/bin/env python3
"""RQ2 numbers from the replayed first targeted edits (data/first_calls.csv, written by region_law.py) and the
search/replace edits with a known match outcome (data/edits_text.csv, written by copy_law.py).

Small regions (< 200 token-equivalents): edits that apply and leave a file that parses. Large regions (>= 200):
edits rejected by the harness and edits applied after which the file no longer parses, per interface."""
import pandas as pd

d = pd.read_csv("data/first_calls.csv")
e = pd.read_csv("data/edits_text.csv")
print(f"replayed first targeted calls {len(d)} | replay disagrees with the harness on {int((d.replayed != d.applied).sum())}")
print(f"search/replace edits with a known match outcome {len(e)}")
d["clean"] = (d.applied == 1) & (d.syntax_ok == 1)
d["broken"] = (d.applied == 1) & (d.syntax_ok == 0)
for form in ("text", "patch", "lines"):
    small = d[(d.form == form) & (d.region_tokens < 200)]
    large = d[(d.form == form) & (d.region_tokens >= 200)]
    print(f"{form:6s} < 200: clean {int(small.clean.sum())} of {len(small)} ({small.clean.mean():.3f}) | "
          f">= 200 ({len(large)}): rejected {100 * (large.applied == 0).mean():.1f}%, applied and broken {100 * large.broken.mean():.1f}%")
print(f"broken first line-range edits, all sizes: {int(d[d.form == 'lines'].broken.sum())}")
