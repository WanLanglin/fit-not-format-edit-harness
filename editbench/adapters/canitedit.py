"""Adapter for CanItEdit (nuprl/CanItEdit dataset, MIT per the dataset card).

Task ids are the dataset's `full_name`, with an optional `@lazy` suffix to use
the lazy instead of the descriptive instruction. The workspace holds the
`before` program as solution.py. Grading appends the hidden tests, as the
original evaluator does, and runs the program in a network-less
python:3.11-slim container. That image has no third-party packages, so the
default task list excludes problems whose taxonomy lists libraries (22 of
105). The `after` program is the fixture script and positive grading control.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

EDITBENCH = Path(__file__).resolve().parents[1]
DATASET = EDITBENCH / "vendor" / "canitedit" / "test.parquet"
BENCHMARK = "canitedit"
SOLUTION = "solution.py"
IMAGE = "python:3.11-slim"
GRADER_TIMEOUT_SECONDS = 180

sys.path.insert(0, str(EDITBENCH))
from runner import Task  # noqa: E402


@lru_cache(maxsize=1)
def rows() -> dict[str, dict[str, Any]]:
    import pandas as pd

    frame = pd.read_parquet(DATASET)
    return {row["full_name"]: row for row in frame.to_dict("records")}


def with_trailing_newline(program: str) -> str:
    """Dataset programs are stored without a final newline; source files in a
    workspace normally end with one. S-Code's patch form cannot match a last
    line that lacks it, so leaving the storage artifact in place would
    penalize the patch arm for reasons unrelated to editing. Normalized
    2026-09-15; grading appends the tests after stripping trailing newlines,
    so behaviour is unchanged."""
    return program if program.endswith("\n") else program + "\n"


def libraries(row: dict[str, Any]) -> list[str]:
    return [str(item) for item in list(row["taxonomy"].get("libraries", []))]


# Problems whose unedited `before` program already passes the hidden tests, so
# a run that changes nothing is graded as solved. Found by the before/after
# grading control on 2026-09-15 (the edit changes performance, not behaviour).
NON_DISCRIMINATING = frozenset({"53_minimax_to_alphabeta"})


def task_ids(include_library_problems: bool = False) -> list[str]:
    return sorted(
        name
        for name, row in rows().items()
        if (include_library_problems or not libraries(row)) and name not in NON_DISCRIMINATING
    )


def grade_workspace(workspace: Path, tests: str) -> dict[str, Any]:
    solution = workspace / SOLUTION
    if not solution.is_file():
        return {"passed": False, "reason": f"{SOLUTION} is missing"}
    with tempfile.TemporaryDirectory(prefix="editbench-canitedit-") as scratch:
        root = Path(scratch)
        program = solution.read_text(encoding="utf-8", errors="replace").rstrip("\n") + "\n\n" + tests
        (root / "program.py").write_text(program, encoding="utf-8")
        root.chmod(0o755)
        try:
            completed = subprocess.run(
                [
                    "docker", "run", "--rm", "--network", "none", "--memory", "1g", "--cpus", "1",
                    "-e", "PYTHONDONTWRITEBYTECODE=1", "-v", f"{root}:/work:ro", "-w", "/work",
                    IMAGE, "python", "program.py",
                ],
                capture_output=True,
                text=True,
                timeout=GRADER_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return {"passed": False, "reason": "grader timed out"}
    output = completed.stdout + completed.stderr
    return {"passed": completed.returncode == 0, "grader_exit_code": completed.returncode, "output_tail": output[-2000:]}


def load(task_id: str) -> Task:
    name, _, variant = task_id.partition("@")
    variant = variant or "descriptive"
    if variant not in ("descriptive", "lazy"):
        raise ValueError(f"unknown instruction variant {variant!r}")
    row = rows().get(name)
    if row is None:
        raise ValueError(f"unknown {BENCHMARK} task {name!r}")
    instruction = row[f"instruction_{variant}"].strip()
    prompt = f"{instruction}\n\nThe code is in `{SOLUTION}`.\n"

    before = with_trailing_newline(row["before"])
    after = with_trailing_newline(row["after"])

    def prepare(workspace: Path) -> None:
        workspace.mkdir()
        (workspace / SOLUTION).write_text(before, encoding="utf-8")

    return Task(
        benchmark=BENCHMARK,
        task_id=task_id,
        prompt=prompt,
        prepare=prepare,
        grade=lambda workspace: grade_workspace(workspace, row["tests"]),
        fixture={"path": SOLUTION, "before": before, "after": after},
    )
