#!/usr/bin/env python3
"""RefactorBench analysis on the tasks valid in every arm, with the paper's statistics.

Per arm: task success, first targeted edit accepted, rejected edit calls, output tokens and dollars per task,
and tasks completed per output token and per dollar relative to search/replace (paired bootstrap, 2000
resamples, seed 0). Success and first-edit acceptance against search/replace use the exact McNemar test.
Then the same split by task kind (moves code / does not), and how often @@ref (same file / naming a file) was used.

Usage: rb_analysis.py [RUNS_DIR] [--tasks N]   (N = prefix of refactorbench_order.txt; default all)
"""
from __future__ import annotations

import argparse
import re
import sys
from math import comb
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent / "adapters"))
exec(open(Path(__file__).parent / "rb_pilot_summary.py").read().split("def main")[0])  # run_row
import refactorbench as rb  # noqa: E402

ARMS = ["text", "lines", "patch", "lines_anchored"]
NAMES = {"text": "search/replace", "lines": "line range", "patch": "patch", "lines_anchored": "verified selection"}
MOVES = re.compile(r"\b(move|moving|transfer|relocat|combine|merge|consolidat|extract|encapsulat|take out|shift)", re.I)


def mcnemar(gain: int, loss: int) -> float:
    n = gain + loss
    return min(1.0, 2 * sum(comb(n, k) for k in range(min(gain, loss) + 1)) / 2 ** n) if n else 1.0


def table(data: dict[str, dict[str, dict]], tasks: list[str], label: str) -> None:
    rng = np.random.default_rng(0)
    samples = [rng.integers(0, len(tasks), len(tasks)) for _ in range(2000)]
    sr = [data["text"][t] for t in tasks]

    def eff(rows, key, idx):
        return sum(rows[i]["passed"] for i in idx) / max(sum(rows[i][key] for i in idx), 1e-12)

    def ratio(rows, key, idx):
        base = eff(sr, key, idx)
        return eff(rows, key, idx) / base if base else np.nan

    print(f"\n=== {label}: {len(tasks)} tasks valid in every arm")
    for arm in ARMS:
        rows = [data[arm][t] for t in tasks]
        full = np.arange(len(rows))
        passed = sum(r["passed"] for r in rows)
        firsts = [r["first_accepted"] for r in rows if r["first_accepted"] is not None]
        line = (f"{NAMES[arm]:18s} success {passed:3d} ({passed / len(rows):.2f})  first accepted {sum(firsts)}/{len(firsts)}  "
                f"rejected edit calls {sum(r['failed_edits'] for r in rows)}/{sum(r['edit_calls'] for r in rows)}  "
                f"output/task {np.mean([r['out'] for r in rows]) / 1000:.1f}k  $/task {np.mean([r['cost'] for r in rows]):.4f}")
        if arm != "text":
            g = sum(r["passed"] and not s["passed"] for r, s in zip(rows, sr))
            lo = sum(s["passed"] and not r["passed"] for r, s in zip(rows, sr))
            both = [(r["first_accepted"], s["first_accepted"]) for r, s in zip(rows, sr)
                    if r["first_accepted"] is not None and s["first_accepted"] is not None]
            fg = sum(a and not b for a, b in both); fl = sum(b and not a for a, b in both)
            line += f"\n{'':18s} vs SR: success +{g}/-{lo} p={mcnemar(g, lo):.3f}; first accepted +{fg}/-{fl} p={mcnemar(fg, fl):.3f}"
            for key, name in (("out", "output token"), ("cost", "dollar")):
                r0 = ratio(rows, key, full)
                bs = np.array([ratio(rows, key, i) for i in samples])
                lo_ci, hi_ci = np.nanpercentile(bs, [2.5, 97.5])
                dropped = int(np.isnan(bs).sum())
                line += f"; per {name} {r0:.2f} [{lo_ci:.2f}, {hi_ci:.2f}]" + (f" ({dropped} resamples without an SR success dropped)" if dropped else "")
        print(line)
    ours = [data["lines_anchored"][t] for t in tasks]
    print(f"verified selection runs using @@ref: same file {sum(r['ref_same'] > 0 for r in ours)}, "
          f"naming a file {sum(r['ref_named'] > 0 for r in ours)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", nargs="?", default="runs/refactorbench-luna-4arms")
    parser.add_argument("--tasks", type=int)
    args = parser.parse_args()
    order = [line.strip() for line in open(Path(__file__).parent / "refactorbench_order.txt") if line.strip()]
    order = order[: args.tasks] if args.tasks else order
    data: dict[str, dict[str, dict]] = {arm: {} for arm in ARMS}
    invalid = []
    for directory in sorted(Path(args.runs).iterdir()):
        if not directory.is_dir() or not (row := run_row(directory)) or row["task"] not in order or row["arm"] not in ARMS:
            continue
        if row["invalid"]:
            invalid.append((row["task"], row["arm"], row["invalid"]))
            continue
        data[row["arm"]][row["task"]] = row
    tasks = [t for t in order if all(t in data[arm] for arm in ARMS)]
    missing = [t for t in order if t not in tasks]
    print(f"tasks in order: {len(order)}; valid in every arm: {len(tasks)}; missing or invalid somewhere: {len(missing)}")
    for item in invalid:
        print("invalid:", item)
    table(data, tasks, "all")
    moves = [t for t in tasks if MOVES.search(rb.mapping()[t][2].read_text())]
    table(data, moves, "instructions that move code")
    table(data, [t for t in tasks if t not in moves], "instructions that do not move code")


if __name__ == "__main__":
    main()
