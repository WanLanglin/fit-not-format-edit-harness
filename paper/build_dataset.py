#!/usr/bin/env python3
"""Build the two tables every figure and number in the paper is computed from.

    build_dataset.py            ->  data/runs.csv, data/edit_calls.csv, data/manifest.json

One row per valid run in runs.csv; one row per edit tool call in edit_calls.csv.
SOURCES fixes which run directory supplies which (benchmark, model, arm).
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

RUNS = Path(__file__).resolve().parents[1] / "editbench" / "runs"
OUT = Path(__file__).resolve().parent / "data"
EDIT_TOOLS = ("edit_lines", "edit_text", "apply_patch")

MODELS = {
    "openai/gpt-5.6-luna": ("GPT-5.6-luna", "OpenAI"),
    "z-ai/glm-5.3": ("GLM-5.3", "Zhipu"),
    "deepseek/deepseek-v4-flash": ("DeepSeek-V4-Flash", "DeepSeek"),
    "xiaomi/mimo-v2.5-pro": ("MiMo-v2.5-Pro", "Xiaomi"),
    "qwen/qwen3.8-flash": ("Qwen3.8-Flash", "Alibaba"),
    "anthropic/claude-sonnet-5": ("Claude-Sonnet-5", "Anthropic"),
}

# (directory, arms taken from it, batch label). "main" is the primary table;
# "ablation" is the contemporaneous packaging batch.
SOURCES = [
    ("canitedit-luna-4arms", ("text", "patch", "lines", "choice"), "main"),
    ("canitedit-luna-guided", ("guided",), "main"),
    ("canitedit-luna-tools-ablation", ("text", "choice", "guided", "tools", "tools_guided"), "ablation"),
    ("canitedit-glm-3formats", ("text", "patch", "lines"), "main"),
    ("canitedit-glm-choice", ("choice",), "main"),
    ("canitedit-glm-guided", ("guided",), "main"),
    ("canitedit-deepseek-4arms", ("text", "patch", "lines", "choice"), "main"),
    ("canitedit-deepseek-guided", ("guided",), "main"),
    ("canitedit-mimo-7arms", ("text", "patch", "lines", "choice", "guided", "tools", "tools_guided"), "main"),
    ("canitedit-qwen-5arms", ("text", "patch", "lines", "tools", "tools_guided"), "main"),
    ("refactor-luna-5arms", ("text", "patch", "lines", "choice", "guided"), "main"),
    ("refactor-mimo-3arms", ("text", "patch", "lines"), "main"),
    # Claude Sonnet 5, added later on CanItEdit only; its own batch keeps every main-study number unchanged.
    ("canitedit-claude-sonnet5-2arms", ("text", "lines"), "claude"),
]

ERROR_CLASSES = (  # first match wins; wording is the executor's own
    ("patch: duplicated envelope / unsupported operation", r"supported patch operations"),
    ("patch: missing Begin/End markers", r"Begin Patch and End Patch"),
    ("patch: non-bare @@ header", r"requires bare @@"),
    ("patch: context-only hunk", r"each update hunk needs"),
    ("patch: sent without revisions", r"patch requires only patch and revisions"),
    ("patch: malformed hunk", r"patch lines require|update hunk must contain|only adds lines|missing revision for|Add File|Update File requires an existing|revisions must"),
    ("text: old_text matched 0 times", r"matched 0 times"),
    ("text: old_text matched 2+ times", r"matched \d+ times"),
    ("text: empty old_text", r"empty old_text"),
    ("lines: range outside file / overlap", r"line edit range|must not overlap"),
    ("stale revision", r"expected_revision does not match|expected_sha256"),
    ("argument shape", r"cannot be combined|exactly one editing form|exactly one of content|unknown field|invalid type|missing field|editing paths|one mode consistently|at most|1 to 32|accepts only|existing UTF-8"),
)
ERROR_RES = [(label, re.compile(pattern)) for label, pattern in ERROR_CLASSES]


def decode(value):
    if isinstance(value, dict) and "hex" in value:
        return bytes.fromhex(value["hex"]).decode(errors="replace")
    return value or ""


def form_of(call) -> str:
    forms = call.get("edit_forms") or []
    names = [k for k, v in forms.items() if v] if isinstance(forms, dict) else list(forms)
    return "+".join(sorted(names)) or "unknown"


def classify(error: str) -> str:
    for label, pattern in ERROR_RES:
        if pattern.search(error):
            return label
    return "other"


def header_style(patch: str) -> str:
    """Style of the first non-bare @@ line: what the reference parser would see."""
    for line in patch.splitlines():
        if line.startswith("@@") and line.strip() != "@@":
            text = line[2:].strip()
            if re.match(r"^[-+]?\d", text):
                return "git line numbers"
            if text.endswith("@@"):
                return "text wrapped in @@ ... @@"
            return "codex-style"
    return ""


def model_call_metrics(run_dir: Path):
    calls = []
    path = run_dir / "model_calls.jsonl"
    if path.is_file():
        for line in path.read_text(errors="replace").splitlines():
            try:
                calls.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    ok = sorted((c for c in calls if c.get("status") == 200 and c.get("usage")), key=lambda c: c.get("started_at") or "")
    cost = sum(c.get("cost_usd") or 0 for c in calls)
    malformed = sum(1 for c in calls if c.get("finish_reason") == "error")
    reasoning = lambda c: ((c["usage"].get("completion_tokens_details") or {}).get("reasoning_tokens")) or 0
    index = next((i for i, c in enumerate(ok) if any(t.get("name") in EDIT_TOOLS for t in c.get("tool_calls") or [])), None)
    pre = {}
    if index is not None:
        before, first = ok[:index], ok[index]
        names = Counter(t.get("name") for c in before for t in c.get("tool_calls") or [])
        pre = {
            "pre_model_calls": index,
            "pre_reads": names["read_file"],
            "pre_searches": names["search_text"],
            "pre_reasoning_tokens": sum(reasoning(c) for c in before),
            "edit_prompt_tokens": first["usage"].get("prompt_tokens") or 0,
            "edit_reasoning_tokens": reasoning(first),
            "edit_visible_tokens": (first["usage"].get("completion_tokens") or 0) - reasoning(first),
        }
    # All output the model generated in the run, reasoning included: the priced side of a call.
    pre["output_tokens"] = sum(c["usage"].get("completion_tokens") or 0 for c in ok)
    return cost, malformed, pre


def header_styles(run_dir: Path) -> dict[str, str]:
    """arguments sha256 -> header style, for patch calls rejected for a non-bare header."""
    styles = {}
    path = run_dir / "events.jsonl"
    if not path.is_file():
        return styles
    for line in path.read_text(errors="replace").splitlines():
        if '"experiment.tool_call"' not in line:
            continue
        try:
            payload = json.loads(line)["payload"]
        except (json.JSONDecodeError, KeyError):
            continue
        if "requires bare @@" not in decode(payload.get("error")):
            continue
        try:
            patch = json.loads(decode(payload["arguments"])).get("patch")
        except (json.JSONDecodeError, AttributeError):
            continue
        if isinstance(patch, str):
            styles[payload["arguments"].get("sha256")] = header_style(patch)
    return styles


def main() -> None:
    OUT.mkdir(exist_ok=True)
    run_rows, call_rows, manifest = [], [], []
    for directory, arms, batch in SOURCES:
        taken = Counter(); skipped = Counter()
        for record_path in sorted((RUNS / directory).glob("*__r0/run.json")):
            try:
                record = json.loads(record_path.read_text())
            except json.JSONDecodeError:
                continue
            arm = record["arm"].split(":")[0]
            if arm not in arms:
                continue
            if record.get("invalid_reasons") or not record.get("arm_verified"):
                skipped[arm] += 1
                continue
            model, family = MODELS[record["model"]]
            run_dir = record_path.parent
            edit_calls = [c for c in record["tool_calls"] if c["tool"] in EDIT_TOOLS]
            sequence = [(c["tool"], form_of(c), not c.get("error")) for c in edit_calls]
            targeted = [ok for _, form, ok in sequence if form != "content"]
            cost, malformed, pre = model_call_metrics(run_dir)
            styles = header_styles(run_dir) if any("requires bare @@" in str(c.get("error")) for c in edit_calls) else {}
            usage = record.get("usage") or {}
            edits = record["edits"]
            run_rows.append({
                "benchmark": record["benchmark"], "model": model, "family": family, "arm": arm, "batch": batch,
                "task": record["task_id"], "choice_order": record.get("choice_order") or "",
                "passed": int(bool(record["passed"])),
                "first_edit_ok": int(bool(edits["first_edit_succeeded"])),
                "first_targeted_ok": "" if not targeted else int(targeted[0]),
                "first_form": sequence[0][1] if sequence else "",
                "first_tool": sequence[0][0] if sequence else "",
                "edit_calls": edits["edit_calls"], "edit_failures": edits["edit_failures"],
                "content_any": int(any(form == "content" for _, form, _ in sequence)),
                "content_first": int(bool(sequence) and sequence[0][1] == "content"),
                "forms_used": "+".join(sorted({form for _, form, _ in sequence if form not in ("content", "unknown")})),
                "model_calls": usage.get("model_calls") or "", "tokens": usage.get("total_units") or "",
                "cost_usd": round(cost, 6), "elapsed_s": record["process"]["elapsed_seconds"],
                "malformed_calls": malformed, "turn_completed": int(record["turn"]["status"] == "completed"),
                **{key: pre.get(key, "") for key in ("pre_model_calls", "pre_reads", "pre_searches", "pre_reasoning_tokens", "edit_prompt_tokens", "edit_reasoning_tokens", "edit_visible_tokens", "output_tokens")},
                "source": directory,
            })
            for position, call in enumerate(edit_calls):
                error = str(call.get("error") or "")
                error_class = classify(error) if error else ""
                call_rows.append({
                    "benchmark": record["benchmark"], "model": model, "arm": arm, "batch": batch, "task": record["task_id"],
                    "position": position, "tool": call["tool"], "form": form_of(call), "ok": int(not error),
                    "error_class": error_class,
                    "header_style": styles.get(call.get("arguments_sha256"), "") if error_class == "patch: non-bare @@ header" else "",
                    "source": directory,
                })
            taken[arm] += 1
        manifest.append({"directory": directory, "batch": batch, "valid_runs": dict(taken), "excluded_invalid": dict(skipped)})
    for name, rows in (("runs.csv", run_rows), ("edit_calls.csv", call_rows)):
        with (OUT / name).open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"runs.csv {len(run_rows)} rows; edit_calls.csv {len(call_rows)} rows")
    unclassified = Counter(r["error_class"] for r in call_rows if r["error_class"] == "other")
    print("unclassified errors:", sum(unclassified.values()))
    for entry in manifest:
        print(f"  {entry['directory']:34} {entry['batch']:9} {entry['valid_runs']}  excluded {entry['excluded_invalid'] or '-'}")


if __name__ == "__main__":
    main()
