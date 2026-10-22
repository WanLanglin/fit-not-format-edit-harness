#!/usr/bin/env python3
"""Saturation pilot: sample tasks per benchmark and run them across models and arms.

The plan is expanded deterministically from --seed:
- for each benchmark, take the first --per-benchmark tasks by sha256(seed, task);
- cross them with every model and arm, and with repeat indices.

Each run is one runner.py invocation in its own directory. Existing run.json
files are skipped, so an interrupted pilot resumes. --dry-run prints the plan
without running anything. The summary groups pass rates by benchmark × model ×
arm and excludes runs whose arm could not be verified or that were invalid.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

EDITBENCH = Path(__file__).resolve().parent
BENCHMARKS = ("aider-refactor", "canitedit", "refactorbench")
# Cyclic Latin square over the order of the three format sections in the
# `choice` prompt. A plain `choice` arm takes row (task position + repeat) % 3,
# so orders are balanced across tasks and, with 3 repeats, every task sees all three.
CHOICE_ORDERS = ("lines,text,patch", "text,patch,lines", "patch,lines,text")


def adapter_task_ids(benchmark: str) -> list[str]:
    path = EDITBENCH / "adapters" / f"{benchmark.replace('-', '_')}.py"
    spec = importlib.util.spec_from_file_location(f"pilot_adapter_{benchmark}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.task_ids()


def sample(benchmark: str, count: int, seed: str) -> list[str]:
    ids = adapter_task_ids(benchmark)
    ranked = sorted(ids, key=lambda task_id: hashlib.sha256(f"{seed}:{benchmark}:{task_id}".encode()).hexdigest())
    return ranked[:count]


def safe(value: str) -> str:
    return "".join(character if character.isalnum() or character in "-_." else "_" for character in value)


def plan(args: argparse.Namespace) -> list[dict[str, Any]]:
    runs = []
    for benchmark in args.benchmarks:
        if args.tasks:
            available = set(adapter_task_ids(benchmark))
            task_ids = [task_id for task_id in args.tasks if task_id in available]
        else:
            task_ids = sample(benchmark, args.per_benchmark, args.seed)
        for position, task_id in enumerate(task_ids):
            for model in args.models:
                for arm in args.arms:
                    for repeat in range(args.repeats):
                        name = f"{safe(benchmark)}__{safe(task_id)}__{safe(model)}__{safe(arm)}__r{repeat}"
                        run = {
                            "benchmark": benchmark,
                            "task": task_id,
                            "model": model,
                            "arm": arm,
                            "repeat": repeat,
                            "output": str(Path(args.output) / name),
                        }
                        if arm in ("choice", "guided", "tools", "tools_guided") and not args.fixed_choice_order:
                            run["runner_arm"] = f"{arm}:{CHOICE_ORDERS[(position + repeat) % len(CHOICE_ORDERS)]}"
                        runs.append(run)
    return runs


def record_is_final(output: Path) -> bool:
    """A recorded run is done unless it failed for infrastructure reasons.

    Invalid records (unverified arm or limits, ghost run, upstream failure, a
    failed model call S-Code did not abandon itself) and runs with an upstream
    HTTP error at the proxy are retried. Everything else is a final outcome:
    a task the model failed, and a call S-Code abandoned at its own stream
    event, idle or elapsed limit (runner.py decides which failures those are).
    """
    try:
        record = json.loads((output / "run.json").read_text())
    except json.JSONDecodeError:
        # The batch was stopped while the record was being written.
        return False
    if record.get("invalid_reasons"):
        return False
    calls = output / "model_calls.jsonl"
    if calls.is_file():
        for line in calls.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                if json.loads(line).get("status") != 200:
                    return False
            except json.JSONDecodeError:
                continue
    return True


def counted_attempts(output: Path) -> int:
    """Earlier attempts that count toward --max-attempts.

    An attempt directory without a readable run.json (the batch was stopped) or whose
    proxy log shows the request was refused for billing (402 credits, 403 key
    limit, 429 experiment budget) never reached the model, so it does not count.
    """
    count = 0
    for attempt in output.parent.glob(f"{output.name}.attempt-*"):
        if not (attempt / "run.json").is_file():
            continue
        try:
            json.loads((attempt / "run.json").read_text())
        except json.JSONDecodeError:
            continue
        calls = attempt / "model_calls.jsonl"
        refused = False
        if calls.is_file():
            for line in calls.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    call = json.loads(line)
                except json.JSONDecodeError:
                    continue
                status = call.get("status")
                # OpenRouter answers an exhausted per-key limit with 403, not 402.
                key_limit = status == 403 and "limit" in str(call.get("error_body")).lower()
                refused = refused or status in (402, 429) or key_limit
        if refused:
            continue
        count += 1
    return count


def retire(output: Path) -> Path:
    """Keep a failed attempt as evidence beside the run directory."""
    attempt = 1
    while (target := output.with_name(f"{output.name}.attempt-{attempt}")).exists():
        attempt += 1
    output.rename(target)
    return target


def execute(run: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    output = Path(run["output"])
    record_path = output / "run.json"
    retired = None
    if record_path.is_file():
        if record_is_final(output):
            return {**run, "status": "skipped-existing"}
        attempts = counted_attempts(output) + 1
        if attempts >= args.max_attempts:
            # Capped so repeated infrastructure trouble cannot resample one
            # arm's outcomes indefinitely; the invalid record stays reported.
            return {**run, "status": "attempts-exhausted"}
        retired = retire(output)
    elif output.exists():
        retired = retire(output)
    command = [
        sys.executable, str(EDITBENCH / "runner.py"),
        "--benchmark", run["benchmark"], "--task", run["task"], "--arm", run.get("runner_arm", run["arm"]),
        "--model", run["model"], "--s-code", args.s_code, "--output", run["output"],
        "--tool-set", args.tool_set, "--timeout", str(args.timeout),
    ]
    if args.temperature is not None:
        command += ["--temperature", repr(args.temperature)]
    if args.max_stream_events is not None:
        command += ["--max-stream-events", str(args.max_stream_events)]
    if args.cross_file_ref:
        command += ["--cross-file-ref"]
    if args.max_tool_calls is not None:
        command += ["--max-tool-calls", str(args.max_tool_calls)]
    if args.max_model_calls is not None:
        command += ["--max-model-calls", str(args.max_model_calls)]
    if args.max_total_tokens is not None:
        command += ["--max-total-tokens", str(args.max_total_tokens)]
    if args.detailed_tool_results is not None:
        command += ["--detailed-tool-results", str(args.detailed_tool_results)]
    command += ["--fixture-form", args.fixture_form] if args.fixture_form else ["--base-url", args.base_url]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=args.timeout + 600)
    previous = {"retired_attempt": str(retired)} if retired else {}
    if not record_path.is_file():
        return {**run, **previous, "status": "no-record", "detail": (completed.stderr or completed.stdout)[-1000:]}
    return {**run, **previous, "status": "done"}


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(
        lambda: {"runs": 0, "valid": 0, "passed": 0, "ghost": 0, "edit_calls": 0, "edit_failures": 0, "output_units": 0}
    )
    for run in runs:
        record_path = Path(run["output"]) / "run.json"
        if not record_path.is_file():
            continue
        record = json.loads(record_path.read_text())
        group = groups[(run["benchmark"], run["model"], run["arm"])]
        group["runs"] += 1
        group["ghost"] += int(bool(record.get("ghost_run")))
        if not record.get("arm_verified") or record.get("invalid_reasons"):
            continue
        group["valid"] += 1
        group["passed"] += int(bool(record.get("passed")))
        group["edit_calls"] += record["edits"]["edit_calls"]
        group["edit_failures"] += record["edits"]["edit_failures"]
        usage = record.get("usage") or {}
        group["output_units"] += int(usage.get("output_units") or 0)
    rows = []
    for (benchmark, model, arm), group in sorted(groups.items()):
        rows.append(
            {
                "benchmark": benchmark,
                "model": model,
                "arm": arm,
                **group,
                "pass_rate": round(group["passed"] / group["valid"], 3) if group["valid"] else None,
            }
        )
    return {"groups": rows}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    result.add_argument("--output", required=True)
    result.add_argument("--s-code", required=True)
    result.add_argument("--benchmarks", nargs="+", default=list(BENCHMARKS), choices=BENCHMARKS)
    result.add_argument("--models", nargs="+", required=True)
    result.add_argument("--arms", nargs="+", default=["text"])
    result.add_argument("--per-benchmark", type=int, default=10)
    result.add_argument("--repeats", type=int, default=1)
    result.add_argument("--seed", default="editbench-pilot-2026-09")
    result.add_argument("--tasks", nargs="+", help="explicit task ids instead of a seeded sample")
    result.add_argument("--temperature", type=float)
    result.add_argument("--fixed-choice-order", action="store_true", help="keep runner's default choice order instead of rotating it")
    result.add_argument("--max-stream-events", type=int, help="passed to runner.py (its default applies when omitted)")
    result.add_argument("--cross-file-ref", action="store_true", help="passed to runner.py")
    result.add_argument("--max-tool-calls", type=int, help="passed to runner.py")
    result.add_argument("--max-model-calls", type=int, help="passed to runner.py")
    result.add_argument("--max-total-tokens", type=int, help="passed to runner.py")
    result.add_argument("--detailed-tool-results", type=int, help="passed to runner.py")
    result.add_argument("--max-attempts", type=int, default=2, help="total attempts per run before an invalid record is kept")
    result.add_argument("--tool-set", default="edit")
    result.add_argument("--timeout", type=int, default=1800)
    result.add_argument("--concurrency", type=int, default=3)
    endpoint = result.add_mutually_exclusive_group(required=True)
    endpoint.add_argument("--base-url")
    endpoint.add_argument("--fixture-form", choices=("lines", "text", "patch", "lines_anchored"))
    result.add_argument("--dry-run", action="store_true")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    runs = plan(args)
    Path(args.output).mkdir(parents=True, exist_ok=True)
    (Path(args.output) / "plan.json").write_text(json.dumps({"args": vars(args), "runs": runs}, indent=1) + "\n")
    if args.dry_run:
        print(json.dumps({"runs": len(runs), "first": runs[:3]}, indent=1))
        return 0
    statuses = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(execute, run, args) for run in runs]
        for future in as_completed(futures):
            result = future.result()
            statuses.append(result)
            print(json.dumps({key: result.get(key) for key in ("benchmark", "task", "model", "arm", "repeat", "status")}), flush=True)
    summary = {"statuses": statuses, **summarize(runs)}
    (Path(args.output) / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary["groups"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
