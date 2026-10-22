#!/usr/bin/env python3
"""Run one benchmark task through S-Code under one editing arm and record it.

Each run gets a fresh workspace and an isolated S-Code service, reusing the
PR #56 harness (tests/benchmarks/harness/run.py in the experiment copy). The
runner writes a service config selecting the editing mode, sets the
experiment environment, runs `s-code exec --stream-json`, and then:
- checks from experiment.turn_profile that the arm and tool set took effect;
- decodes experiment.tool_call events;
- grades the workspace;
- writes run.json.

With --fixture-form the scripted fixture model stands in for a real endpoint,
so the whole pipeline can be exercised offline.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.util
import json
import os
import sys
import threading
import time
from collections import Counter
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Callable

EDITBENCH = Path(__file__).resolve().parent
EXPERIMENT_COPY = Path(os.environ.get("EDITBENCH_S_CODE_SOURCE", EDITBENCH.parent / "s-code-exp"))
RUN_SCHEMA = "editbench-run-1"
TOOL_SETS = {
    "edit": ["read_file", "list_files", "search_text", "apply_patch"],
}
DEFAULT_CHOICE_ORDER = "lines,text,patch"
# The three-tool arms offer each form as its own tool. `apply_patch` stays the
# patch form's name; the other two are aliases S-Code maps onto it at execution.
EDIT_TOOL_NAMES = ("edit_lines", "edit_text", "apply_patch")
MENU_MODES = {"choice": "choice", "guided": "choice_guided", "tools": "choice_tools", "tools_guided": "choice_tools_guided"}
THREE_TOOL_MODES = ("choice_tools", "choice_tools_guided")
MAX_ERROR_CHARS = 2000
# The recording proxy appends a call record only when its upstream stream
# ends, so a call S-Code abandoned mid-stream can be recorded seconds or
# minutes later. Wait this long for those records before calling a failed
# model call unexplained.
PROXY_SETTLE_SECONDS = 20.0
# Values every run must report in experiment.turn_profile. The environment
# below sets the adjustable ones; the turn limits are S-Code's defaults.
EXPECTED_MAX_OUTPUT_TOKENS = 32768
EXPECTED_HTTP_TIMEOUTS_SECONDS = [10, 120, 600]
DEFAULT_MAX_STREAM_EVENTS = 131072
EXPECTED_TURN_LIMITS = {
    "max_model_calls": 48,
    "max_tool_calls": 64,
    "max_elapsed_seconds": 1800,
    "model_stream_idle_seconds": 60,
    "max_cost_micros": 5_000_000,
    "max_total_tokens": 1_000_000,
}


@dataclasses.dataclass
class Task:
    benchmark: str
    task_id: str
    prompt: str
    prepare: Callable[[Path], None]
    grade: Callable[[Path], dict[str, Any]]
    fixture: dict[str, str] | None = None


@dataclasses.dataclass(frozen=True)
class Arm:
    name: str
    mode: str
    choice_order: str | None = None


def parse_arm(value: str) -> Arm:
    """`lines`, `text`, `patch`, or a menu arm with an optional `:order`.

    `choice` offers the three forms inside one tool; `guided` adds a paragraph on
    when to use which. `tools` and `tools_guided` are the same two conditions with
    each form offered as its own tool (`edit_lines`, `edit_text`, `apply_patch`),
    where `order` rotates the tools instead of the instruction blocks.
    """
    name, _, order = value.partition(":")
    if name in ("lines", "text", "patch", "lines_anchored") and not order:
        return Arm(value, name)
    if name in MENU_MODES:
        order = order or DEFAULT_CHOICE_ORDER
        forms = order.split(",")
        if sorted(forms) != ["lines", "patch", "text"]:
            raise ValueError(f"choice order must permute lines,text,patch: {order}")
        return Arm(f"{name}:{order}", MENU_MODES[name], order)
    raise ValueError(f"unknown arm {value!r}")


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_harness() -> ModuleType:
    return load_module("s_code_harness_run", EXPERIMENT_COPY / "tests/benchmarks/harness/run.py")


def load_task(benchmark: str, task_id: str) -> Task:
    adapter = load_module(f"editbench_adapter_{benchmark}", EDITBENCH / "adapters" / f"{benchmark.replace('-', '_')}.py")
    return adapter.load(task_id)


def service_config_text(base_url: str, mode: str) -> str:
    if any(character in base_url for character in "\"\\\n"):
        raise ValueError("base_url contains characters that cannot appear in the TOML string")
    return f'[model]\nprovider = "openai_compatible"\nbase_url = "{base_url}"\nediting_mode = "{mode}"\n'


def experiment_environment(
    environment: dict[str, str],
    arm: Arm,
    tool_set: str,
    max_stream_events: int = DEFAULT_MAX_STREAM_EVENTS,
    cross_file_ref: bool = False,
    max_tool_calls: int | None = None,
    max_model_calls: int | None = None,
    max_total_tokens: int | None = None,
    detailed_tool_results: int | None = None,
) -> dict[str, str]:
    environment = dict(environment)
    environment.pop("S_CODE_DATABASE_URL", None)
    for name in [key for key in environment if key.startswith("S_CODE_EXPERIMENT")]:
        environment.pop(name)
    environment["S_CODE_EXPERIMENT"] = "1"
    environment["S_CODE_EXPERIMENT_TOOL_SET"] = tool_set
    # Reasoning models can stream quietly for long stretches; the shipped 45 s
    # read / 180 s total limits would cut them off. turn_profile records these.
    environment["S_CODE_EXPERIMENT_HTTP_READ_SECONDS"] = "120"
    environment["S_CODE_EXPERIMENT_HTTP_TOTAL_SECONDS"] = "600"
    # The shipped 8192-token output limit includes reasoning; a reasoning model
    # can spend all of it on reasoning and emit no tool call.
    environment["S_CODE_EXPERIMENT_MAX_OUTPUT_TOKENS"] = str(EXPECTED_MAX_OUTPUT_TOKENS)
    # The shipped gateway fails a stream after 16,384 parsed events. Z.AI sends
    # GLM-5.3 reasoning one token per event, so long reasoning hit that limit
    # at about 16K tokens, below the output cap above.
    environment["S_CODE_EXPERIMENT_MAX_STREAM_EVENTS"] = str(max_stream_events)
    # RefactorBench build (6a13cf6 + 6a13cf6-refactorbench.patch): the anchored instructions then say
    # @@ref may name another file of the call. Only the prompt hash records it.
    if cross_file_ref:
        environment["S_CODE_EXPERIMENT_CROSS_FILE_REF"] = "1"
    # Repository-scale tasks (RefactorBench) need more reads and searches than
    # the shipped turn allows. Unset keeps S-Code's limits; arm_check asserts them.
    if max_tool_calls is not None:
        environment["S_CODE_EXPERIMENT_MAX_TOOL_CALLS"] = str(max_tool_calls)
    if max_model_calls is not None:
        environment["S_CODE_EXPERIMENT_MAX_MODEL_CALLS"] = str(max_model_calls)
    if max_total_tokens is not None:
        environment["S_CODE_EXPERIMENT_MAX_TOTAL_TOKENS"] = str(max_total_tokens)
    # S-Code keeps the detail of only the six latest tool results; on multi-file
    # tasks the model then re-reads files it has already read. Unset keeps six.
    if detailed_tool_results is not None:
        environment["S_CODE_EXPERIMENT_DETAILED_TOOL_RESULTS"] = str(detailed_tool_results)
    if arm.choice_order:
        environment["S_CODE_EXPERIMENT_CHOICE_ORDER"] = arm.choice_order
    return environment


def read_events(path: Path) -> list[dict[str, Any]]:
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def decode_recorded(value: Any) -> str | None:
    if not isinstance(value, dict) or not isinstance(value.get("hex"), str):
        return None
    return bytes.fromhex(value["hex"]).decode("utf-8", errors="replace")


def experiment_records(rows: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    profile = None
    calls = []
    for row in rows:
        kind = row.get("kind", row.get("type"))
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        if kind == "experiment.turn_profile" and profile is None:
            profile = payload
        elif kind == "experiment.tool_call":
            error = decode_recorded(payload.get("error"))
            calls.append(
                {
                    "tool": payload.get("tool"),
                    "outcome": payload.get("outcome"),
                    "edit_forms": payload.get("edit_forms"),
                    "edit_counts": payload.get("edit_counts"),
                    "arguments_bytes": (payload.get("arguments") or {}).get("bytes"),
                    "arguments_sha256": (payload.get("arguments") or {}).get("sha256"),
                    "error": error[:MAX_ERROR_CHARS] if error else None,
                }
            )
    return profile, calls


def arm_check(
    profile: dict[str, Any] | None,
    arm: Arm,
    tool_set: str,
    max_stream_events: int = DEFAULT_MAX_STREAM_EVENTS,
    max_tool_calls: int | None = None,
    max_model_calls: int | None = None,
    max_total_tokens: int | None = None,
    detailed_tool_results: int | None = None,
) -> list[str]:
    """Reasons the run did not use the requested arm and limits; empty when it did."""
    if profile is None:
        return ["no experiment.turn_profile event"]
    problems = []
    if profile.get("editing_mode") != arm.mode:
        problems.append(f"editing_mode {profile.get('editing_mode')!r} != {arm.mode!r}")
    expected_tools = sorted(set(TOOL_SETS[tool_set]) | (set(EDIT_TOOL_NAMES) if arm.mode in THREE_TOOL_MODES else set()))
    if sorted(profile.get("tools") or []) != expected_tools:
        problems.append(f"tools {sorted(profile.get('tools') or [])} != {expected_tools}")
    if arm.choice_order and ",".join(profile.get("choice_order") or []) != arm.choice_order:
        problems.append(f"choice_order {profile.get('choice_order')} != {arm.choice_order}")
    expected = {
        "max_output_tokens": EXPECTED_MAX_OUTPUT_TOKENS,
        "http_timeouts_seconds": EXPECTED_HTTP_TIMEOUTS_SECONDS,
        "max_stream_events": max_stream_events,
        "turn_limits": {
            **EXPECTED_TURN_LIMITS,
            **({"max_tool_calls": max_tool_calls} if max_tool_calls is not None else {}),
            **({"max_model_calls": max_model_calls} if max_model_calls is not None else {}),
            **({"max_total_tokens": max_total_tokens} if max_total_tokens is not None else {}),
        },
    }
    # Binaries before the override do not report it; absent means S-Code's six.
    if profile.get("detailed_tool_results", 6) != (detailed_tool_results if detailed_tool_results is not None else 6):
        problems.append(f"detailed_tool_results {profile.get('detailed_tool_results')!r} != {detailed_tool_results!r}")
    for key, value in expected.items():
        if profile.get(key) != value:
            problems.append(f"{key} {profile.get(key)!r} != {value!r}")
    return problems


def proxy_call_counts(output: Path) -> dict[str, int] | None:
    """Classify the recording proxy's calls for this run; None without a proxy."""
    path = output / "model_calls.jsonl"
    if not path.is_file():
        return None
    calls = read_events(path)
    return {
        "proxy_calls": len(calls),
        "upstream_failures": sum(1 for call in calls if call.get("status") != 200 or call.get("upstream_stream_error")),
        "scode_aborted_calls": sum(1 for call in calls if call.get("client_disconnected")),
    }


def edit_summary(calls: list[dict[str, Any]]) -> dict[str, Any]:
    edits = [call for call in calls if call["tool"] in EDIT_TOOL_NAMES]
    forms = Counter(form for call in edits for form in (call.get("edit_forms") or []))
    return {
        "tool_calls": len(calls),
        "tool_calls_by_name": dict(Counter(call["tool"] for call in calls)),
        "edit_calls": len(edits),
        "edit_failures": sum(1 for call in edits if call["outcome"] == "failed"),
        "first_edit_succeeded": (edits[0]["outcome"] == "completed") if edits else None,
        "edit_forms": dict(forms),
        "content_bypass_calls": sum(1 for call in edits if "content" in (call.get("edit_forms") or [])),
    }


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def start_fixture_model(task: Task, form: str, log: Path) -> tuple[Any, str]:
    if task.fixture is None:
        raise ValueError(f"{task.benchmark}/{task.task_id} has no fixture script")
    fixture_model = load_module("editbench_fixture_model", EDITBENCH / "fixture_model.py")
    server = fixture_model.serve({**task.fixture, "form": form}, log)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/v1"


def run(args: argparse.Namespace) -> dict[str, Any]:
    harness = load_harness()
    task = load_task(args.benchmark, args.task)
    arm = parse_arm(args.arm)
    binary = Path(args.s_code).resolve()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    workspace = output / harness.ARTIFACTS["workspace"]
    task.prepare(workspace)
    (output / harness.ARTIFACTS["prompt"]).write_text(task.prompt, encoding="utf-8")

    fixture_server = None
    if args.fixture_form:
        fixture_server, base_url = start_fixture_model(task, args.fixture_form, output / "fixture_model.jsonl")
    else:
        base_url = args.base_url.replace("{run_id}", output.name)
    config_path = output / "service-config.toml"
    config_path.write_text(service_config_text(base_url, arm.mode), encoding="utf-8")

    environment, directories, service_config_record = harness.prepare_service(output, harness.service_config(str(config_path)))
    environment = experiment_environment(
        environment, arm, args.tool_set, args.max_stream_events, args.cross_file_ref, args.max_tool_calls, args.max_model_calls,
        args.max_total_tokens, args.detailed_tool_results,
    )
    if args.temperature is not None:
        environment["S_CODE_EXPERIMENT_TEMPERATURE"] = repr(args.temperature)
    agent_args = SimpleNamespace(
        model=args.model,
        permission_mode="workspace",
        timeout=args.timeout,
        grace_seconds=args.grace_seconds,
    )
    run_started = time.time()
    try:
        process = harness.run_agent(binary, workspace, task.prompt, agent_args, output, environment)
    finally:
        service, pid = harness.inspect_service(directories, run_started)
        service["stopped"] = harness.stop_service(pid)
        if fixture_server is not None:
            fixture_server.shutdown()

    rows = read_events(output / harness.ARTIFACTS["events"])
    with (output / harness.ARTIFACTS["events"]).open(encoding="utf-8", errors="replace") as events:
        summary = harness.summarize_events(events)
    profile, calls = experiment_records(rows)
    problems = arm_check(
        profile, arm, args.tool_set, args.max_stream_events,
        args.max_tool_calls, args.max_model_calls, args.max_total_tokens, args.detailed_tool_results,
    )
    if args.temperature is not None and profile is not None and profile.get("temperature") != args.temperature:
        problems.append(f"temperature {profile.get('temperature')!r} != {args.temperature!r}")
    edits = edit_summary(calls)
    try:
        usage = harness.usage_record(summary)
    except Exception as error:  # the usage schema belongs to PR #56; keep the run record
        usage = {"error": f"{type(error).__name__}: {error}"}
    grade = task.grade(workspace)
    (output / harness.ARTIFACTS["grade"]).write_text(json.dumps(grade, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    terminal = (summary.get("lifecycle") or {}).get("terminal") or []
    ghost = edits["tool_calls"] == 0 and not (usage.get("output_units") if isinstance(usage, dict) else 0)
    invalid = list(problems)
    # Running out of the time budget is a performance outcome, not an
    # infrastructure failure: the workspace is graded as it stands. `s-code
    # exec` exits 124 on its own --timeout (CliExitStatus::Timeout).
    budget_exhausted = bool(process.get("timed_out")) or process.get("exit_code") == 124
    if process.get("exit_code") not in (0, 124, None) and not terminal:
        invalid.append(f"s-code exec exited {process.get('exit_code')} without a terminal turn event")
    if ghost:
        # No tool call and no model output: the model never answered (for
        # example an upstream refusal), so this is not a task outcome.
        invalid.append("ghost run: no tool calls and no model output")
    failed_model_calls = sum(
        1
        for row in rows
        if row.get("kind") == "model.call.completed" and (row.get("payload") or {}).get("outcome") == "failed"
    )
    if summary.get("status") == "cancelled":
        # The turn was cancelled rather than finished: the daemon went away
        # mid-turn (seen 2026-09-15 when a cleanup killed live daemons) or the
        # run was stopped. The workspace is half-edited, so this is not a task
        # outcome. Without this check such runs were recorded as valid failures.
        invalid.append("turn was cancelled before finishing")
    proxy = proxy_call_counts(output)
    if proxy is not None and failed_model_calls > proxy["scode_aborted_calls"]:
        # The proxy appends a call record only when its upstream stream ends, so
        # a call S-Code abandoned while the provider kept streaming is recorded
        # after this runner would classify it (seen 2026-09-15: records landing
        # 76 s and 542 s late). Wait briefly for the records to settle before
        # deciding a failure is unexplained.
        deadline = time.time() + PROXY_SETTLE_SECONDS
        while time.time() < deadline:
            time.sleep(1.0)
            settled = proxy_call_counts(output)
            if settled is None:
                break
            proxy = settled
            if failed_model_calls <= proxy["scode_aborted_calls"]:
                break
    if proxy is not None and proxy["upstream_failures"]:
        # The provider answered with an error or broke the stream: infrastructure.
        invalid.append(f"{proxy['upstream_failures']} upstream failures at the proxy")
    unexplained = failed_model_calls - (proxy["scode_aborted_calls"] if proxy is not None else 0)
    if unexplained > 0:
        # A failed call the proxy did not see S-Code abandon never reached or
        # never came back from the provider. Calls S-Code itself abandoned
        # (stream event limit, idle or elapsed deadline) are part of the
        # harness under test, so they count as task outcomes, not reruns.
        invalid.append(f"{unexplained} model calls failed without a matching S-Code abort at the proxy")
    record = {
        "schema": RUN_SCHEMA,
        "benchmark": task.benchmark,
        "task_id": task.task_id,
        "arm": arm.name,
        "editing_mode": arm.mode,
        "choice_order": arm.choice_order,
        "model": args.model,
        "tool_set": args.tool_set,
        "fixture_form": args.fixture_form,
        "prompt_sha256": hashlib.sha256(task.prompt.encode("utf-8")).hexdigest(),
        "binary": str(binary),
        "binary_sha256": file_sha256(binary),
        "service_config": service_config_record,
        "process": process,
        "service": service,
        "turn": {"terminal": terminal, "status": summary.get("status"), "error_code": summary.get("error_code")},
        "usage": usage,
        "turn_profile": profile,
        "arm_verified": not problems,
        "tool_calls": calls,
        "edits": edits,
        "ghost_run": ghost,
        "budget_exhausted": budget_exhausted,
        "failed_model_calls": failed_model_calls,
        "proxy_calls": proxy,
        "max_stream_events": args.max_stream_events,
        "invalid_reasons": invalid,
        "grade": grade,
        "passed": bool(grade.get("passed")),
    }
    temporary = output / "run.json.tmp"
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output / "run.json")
    return record


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    result.add_argument("--benchmark", required=True)
    result.add_argument("--task", required=True)
    result.add_argument("--arm", required=True, help="lines | text | patch | choice[:order]")
    result.add_argument("--model", required=True)
    result.add_argument("--s-code", required=True, help="S-Code CLI binary from the experiment copy")
    result.add_argument("--output", required=True, help="new run directory")
    result.add_argument("--tool-set", default="edit", choices=sorted(TOOL_SETS))
    endpoint = result.add_mutually_exclusive_group(required=True)
    endpoint.add_argument("--base-url", help="OpenAI-compatible base URL; {run_id} is replaced by the run directory name")
    endpoint.add_argument("--fixture-form", choices=("lines", "text", "patch", "lines_anchored"), help="offline: scripted fixture model")
    result.add_argument("--timeout", type=int, default=1800, help="matches S-Code's own 1800 s turn limit")
    result.add_argument("--grace-seconds", type=int, default=30)
    result.add_argument("--temperature", type=float, help="override S-Code's fixed 0.0, e.g. the model card's value")
    result.add_argument("--max-stream-events", type=int, default=DEFAULT_MAX_STREAM_EVENTS, help="S-Code stream event limit (shipped: 16384)")
    result.add_argument("--cross-file-ref", action="store_true", help="anchored instructions say @@ref may name another file of the call")
    result.add_argument("--max-tool-calls", type=int, help="raise S-Code's per-turn tool-call limit (default: shipped 64)")
    result.add_argument("--max-model-calls", type=int, help="raise S-Code's per-turn model-call limit (default: shipped 48)")
    result.add_argument("--max-total-tokens", type=int, help="raise S-Code's per-turn token limit (default: shipped 1,000,000)")
    result.add_argument("--detailed-tool-results", type=int, help="tool results kept in full in the history (default: shipped 6)")
    return result


def main(argv: list[str] | None = None) -> int:
    record = run(parser().parse_args(argv))
    print(
        json.dumps(
            {
                "task": record["task_id"],
                "arm": record["arm"],
                "passed": record["passed"],
                "arm_verified": record["arm_verified"],
                "invalid_reasons": record["invalid_reasons"],
                "edits": record["edits"],
            },
            sort_keys=True,
        )
    )
    return 0 if record["arm_verified"] and not record["invalid_reasons"] else 2


if __name__ == "__main__":
    sys.exit(main())
