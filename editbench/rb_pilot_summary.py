#!/usr/bin/env python3
"""Summarize a RefactorBench batch: per run and per arm, task success, cost, calls, edits and @@ref use.

Usage: rb_pilot_summary.py RUNS_DIR [--project N]
Edit calls are read from the experiment.tool_call events (arguments are hex-encoded there).
"First edit accepted" is the first apply_patch call carrying targeted edits (edits or patch).
@@ref lines are counted in edit new_text and file content: same-file (`@@ref A-B@@`) and
naming a file (`@@ref path:A-B@@`). --project N multiplies the mean cost per run by N runs.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

SAME = re.compile(r"^\s*@@ref\s+\d+\s*-\s*\d+\s*@@\s*$", re.M)
NAMED = re.compile(r"^\s*@@ref\s+\S[^\n]*:\s*\d+\s*-\s*\d+\s*@@\s*$", re.M)


def decode(value) -> str:
    if isinstance(value, dict) and "hex" in value:
        return bytes.fromhex(value["hex"]).decode("utf-8", "replace")
    return value if isinstance(value, str) else ("" if value is None else json.dumps(value))


def run_row(directory: Path) -> dict | None:
    record_path = directory / "run.json"
    if not record_path.is_file():
        return None
    r = json.loads(record_path.read_text())
    cost = out = 0.0
    for line in (directory / "model_calls.jsonl").read_text(errors="replace").splitlines():
        try:
            call = json.loads(line)
        except json.JSONDecodeError:
            continue
        cost += call.get("cost_usd") or 0
        if call.get("status") == 200 and call.get("usage"):
            out += call["usage"].get("completion_tokens") or 0
    edits = failed = same = named = files_edited = 0
    first = None
    for line in (directory / "events.jsonl").read_text(errors="replace").splitlines():
        if '"experiment.tool_call"' not in line:
            continue
        payload = json.loads(line)["payload"]
        if payload["tool"] != "apply_patch":
            continue
        edits += 1
        error = decode(payload.get("error"))
        failed += bool(error)
        raw = decode(payload.get("arguments"))
        try:
            arguments = json.loads(raw)
        except json.JSONDecodeError:
            arguments = {}
        targets = arguments.get("files") if isinstance(arguments.get("files"), list) else []
        targeted = any(isinstance(f, dict) and f.get("edits") for f in targets) or isinstance(arguments.get("patch"), str)
        if first is None and targeted:
            first = not error
        if not error:
            files_edited += len(targets) or 1
        texts = [e.get("new_text", "") for f in targets if isinstance(f, dict) for e in (f.get("edits") or []) if isinstance(e, dict)]
        texts += [f.get("content", "") for f in targets if isinstance(f, dict) and isinstance(f.get("content"), str)]
        for text in texts:
            same += len(SAME.findall(text or ""))
            named += len(NAMED.findall(text or ""))
    grade = r.get("grade") or {}
    usage = r.get("usage") or {}
    return {
        "task": r["task_id"], "arm": r["arm"], "passed": bool(r.get("passed")), "invalid": r.get("invalid_reasons") or [],
        "turn": (r.get("turn") or {}).get("status"), "cost": cost, "out": out,
        "model_calls": usage.get("model_calls"), "tool_calls": usage.get("tool_calls"), "input": usage.get("input_units"),
        "edit_calls": edits, "failed_edits": failed, "first_accepted": first, "files_written": files_edited,
        "ref_same": same, "ref_named": named, "tests": f'{grade.get("tests_run", "?")} run, failed: {grade.get("failed") or "-"}',
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs")
    parser.add_argument("--project", type=int)
    args = parser.parse_args()
    rows = [row for d in sorted(Path(args.runs).iterdir()) if d.is_dir() and (row := run_row(d))]
    for row in rows:
        print(f'{row["task"][:34]:34s} {row["arm"]:15s} pass={row["passed"]!s:5s} ${row["cost"]:.3f} out={row["out"]:>6.0f} '
              f'calls={row["model_calls"]}/{row["tool_calls"]} edits={row["edit_calls"]} fail={row["failed_edits"]} '
              f'first={row["first_accepted"]} ref(same/named)={row["ref_same"]}/{row["ref_named"]} turn={row["turn"]} '
              f'{"INVALID " + str(row["invalid"]) if row["invalid"] else ""} [{row["tests"]}]')
    by = defaultdict(list)
    for row in rows:
        by[row["arm"]].append(row)
    print()
    for arm, rs in sorted(by.items()):
        firsts = [r["first_accepted"] for r in rs if r["first_accepted"] is not None]
        print(f'{arm:15s} runs={len(rs)} passed={sum(r["passed"] for r in rs)} '
              f'first accepted={sum(firsts)}/{len(firsts)} mean ${statistics.mean(r["cost"] for r in rs):.3f} '
              f'max ${max(r["cost"] for r in rs):.3f} mean output {statistics.mean(r["out"] for r in rs):.0f} '
              f'runs using @@ref path:={sum(r["ref_named"] > 0 for r in rs)}')
    costs = [r["cost"] for r in rows]
    print(f'\ntotal ${sum(costs):.2f} over {len(rows)} runs; mean ${statistics.mean(costs):.3f}/run')
    if args.project:
        print(f'projection: {args.project} runs x mean = ${args.project * statistics.mean(costs):.2f}')


if __name__ == "__main__":
    main()
