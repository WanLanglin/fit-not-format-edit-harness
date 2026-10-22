#!/usr/bin/env python3
"""Summarize a pilot directory: run records joined with proxy call and generation logs.

Writes runs.csv, with one row per planned run, and prints a table grouped by
benchmark × model × arm. The table covers pass rate over valid runs, cost
from the proxy's recorded usage, elapsed time, model calls, edit failures,
upstream errors, length-truncated responses, and which providers actually
served the calls.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def run_row(run: dict[str, Any]) -> dict[str, Any]:
    directory = Path(run["output"])
    record_path = directory / "run.json"
    record = json.loads(record_path.read_text()) if record_path.is_file() else None
    calls = read_jsonl(directory / "model_calls.jsonl")
    generations = read_jsonl(directory / "generations.jsonl")
    # A stream S-Code abandons (for example at its timeout) has no final usage
    # chunk, so the call records no cost although OpenRouter bills it. Fall
    # back to the generation's total_cost for those calls.
    generation_cost = {g.get("generation_id"): g.get("total_cost") for g in generations}
    for call in calls:
        if not call.get("cost_usd") and isinstance(generation_cost.get(call.get("generation_id")), (int, float)):
            call["cost_usd"] = generation_cost[call["generation_id"]]
            call["cost_source"] = "generation"
    usages = [call.get("usage") for call in calls if isinstance(call.get("usage"), dict)]

    def usage_sum(*path: str) -> int:
        total = 0
        for usage in usages:
            value: Any = usage
            for key in path:
                value = value.get(key) if isinstance(value, dict) else None
            total += int(value or 0)
        return total

    row: dict[str, Any] = {
        "benchmark": run["benchmark"],
        "task": run["task"],
        "model": run["model"],
        "arm": run["arm"],
        "repeat": run["repeat"],
        "recorded": record is not None,
        "cost_usd": round(sum(call.get("cost_usd") or 0 for call in calls), 6),
        "prompt_tokens": usage_sum("prompt_tokens"),
        "completion_tokens": usage_sum("completion_tokens"),
        "cached_prompt_tokens": usage_sum("prompt_tokens_details", "cached_tokens"),
        "reasoning_tokens": usage_sum("completion_tokens_details", "reasoning_tokens"),
        "proxy_calls": len(calls),
        "upstream_errors": sum(1 for call in calls if call.get("status") != 200),
        "length_truncated": sum(1 for call in calls if call.get("finish_reason") == "length"),
        "providers": ";".join(sorted({str(g.get("provider_name")) for g in generations if g.get("provider_name")})),
        "dropped_parameters": ";".join(sorted({name for call in calls for name in call.get("dropped_parameters") or []})),
    }
    if record is None:
        return row
    usage = record.get("usage") or {}
    edits = record.get("edits") or {}
    row.update(
        {
            # An upstream HTTP error at the proxy is an infrastructure failure,
            # not a task outcome, even when S-Code recorded a finished turn.
            "valid": bool(record.get("arm_verified"))
            and not record.get("invalid_reasons")
            and row["upstream_errors"] == 0,
            "invalid_reasons": ";".join(
                (record.get("invalid_reasons") or [])
                + ([f"{row['upstream_errors']} upstream HTTP errors"] if row["upstream_errors"] else [])
            ),
            "passed": bool(record.get("passed")),
            "turn_status": (record.get("turn") or {}).get("status"),
            "elapsed_seconds": (record.get("process") or {}).get("elapsed_seconds"),
            "model_calls": usage.get("model_calls"),
            "input_units": usage.get("input_units"),
            "output_units": usage.get("output_units"),
            "tool_calls": edits.get("tool_calls"),
            "edit_calls": edits.get("edit_calls"),
            "edit_failures": edits.get("edit_failures"),
            "first_edit_succeeded": edits.get("first_edit_succeeded"),
            "content_bypass_calls": edits.get("content_bypass_calls"),
            # A run that wrote any whole file through `content` did not use its
            # arm's edit form alone; pure-form pass rates exclude these runs.
            "used_content": bool(edits.get("content_bypass_calls")),
            # Edit forms per call shape, e.g. {"text": 2, "content": 1}; for the
            # choice arm this is what the model picked.
            "edit_forms": json.dumps(edits.get("edit_forms") or {}, sort_keys=True),
            "first_call_prompt_tokens": next(
                (int((call.get("usage") or {}).get("prompt_tokens") or 0) for call in calls if isinstance(call.get("usage"), dict)),
                None,
            ),
            "scode_aborted_calls": (record.get("proxy_calls") or {}).get("scode_aborted_calls"),
            "ghost_run": record.get("ghost_run"),
        }
    )
    return row


def group_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["benchmark"], row["model"], row["arm"])].append(row)
    table = []
    for (benchmark, model, arm), members in sorted(groups.items()):
        recorded = [row for row in members if row["recorded"]]
        valid = [row for row in recorded if row.get("valid")]
        elapsed = [row["elapsed_seconds"] for row in recorded if row.get("elapsed_seconds") is not None]
        passed = sum(1 for row in valid if row["passed"])
        pure = [row for row in valid if not row.get("used_content")]
        valid_cost = sum(row["cost_usd"] for row in valid)
        valid_tokens = sum(row["prompt_tokens"] + row["completion_tokens"] for row in valid)
        prompt_tokens = sum(row["prompt_tokens"] for row in valid)

        def mean(key: str) -> float | None:
            return round(statistics.mean(row[key] for row in valid), 1) if valid else None

        efficiency = {
            # Per valid run, from the proxy's provider usage.
            "mean_cost_usd": round(valid_cost / len(valid), 5) if valid else None,
            "mean_prompt_tokens": mean("prompt_tokens"),
            "mean_completion_tokens": mean("completion_tokens"),
            "mean_reasoning_tokens": mean("reasoning_tokens"),
            "cache_hit_share": round(sum(row["cached_prompt_tokens"] for row in valid) / prompt_tokens, 3) if prompt_tokens else None,
            # Token efficiency: resources spent per solved task.
            "cost_per_pass_usd": round(valid_cost / passed, 5) if passed else None,
            "tokens_per_pass": round(valid_tokens / passed) if passed else None,
        }
        table.append(
            {
                "benchmark": benchmark,
                "model": model,
                "arm": arm,
                "planned": len(members),
                "recorded": len(recorded),
                "valid": len(valid),
                "passed": sum(1 for row in valid if row["passed"]),
                "pass_rate": round(sum(1 for row in valid if row["passed"]) / len(valid), 3) if valid else None,
                "content_run_share": round((len(valid) - len(pure)) / len(valid), 3) if valid else None,
                "pure_form_valid": len(pure),
                "pure_form_pass_rate": round(sum(1 for row in pure if row["passed"]) / len(pure), 3) if pure else None,
                "scode_aborted_calls": sum(row.get("scode_aborted_calls") or 0 for row in recorded),
                "cost_usd": round(sum(row["cost_usd"] for row in members), 4),
                **efficiency,
                "median_elapsed_s": round(statistics.median(elapsed), 1) if elapsed else None,
                "mean_model_calls": round(statistics.mean(row.get("model_calls") or 0 for row in recorded), 1) if recorded else None,
                "edit_failures": sum(row.get("edit_failures") or 0 for row in recorded),
                "upstream_errors": sum(row["upstream_errors"] for row in members),
                "length_truncated": sum(row["length_truncated"] for row in members),
                "ghost_runs": sum(1 for row in recorded if row.get("ghost_run")),
                "providers": ";".join(sorted({p for row in members for p in row["providers"].split(";") if p})),
                "invalid_reasons": dict(Counter(row.get("invalid_reasons") for row in recorded if not row.get("valid"))),
            }
        )
    return table


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pilot_dir", type=Path)
    args = parser.parse_args()
    plan = json.loads((args.pilot_dir / "plan.json").read_text())
    rows = [run_row(run) for run in plan["runs"]]
    fields = sorted({key for row in rows for key in row})
    with (args.pilot_dir / "runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    table = group_table(rows)
    (args.pilot_dir / "groups.json").write_text(json.dumps(table, indent=1) + "\n")
    print(f"runs planned {len(rows)}, recorded {sum(r['recorded'] for r in rows)}, total cost ${sum(r['cost_usd'] for r in rows):.4f}")
    for group in table:
        print(json.dumps(group, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
