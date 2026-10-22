"""Adapter for RefactorBench (microsoft/RefactorBench, ICLR 2025; MIT-licensed harness files).

Each task asks for one multi-file refactor of a vendored open-source Python
repository. The workspace is a copy of that repository. The prompt is the
task's descriptive instruction, verbatim. Grading runs the task's AST test
file, as released, from a directory one level below the repository root,
because the tests open files through paths such as `../src/flask/app.py`.
A run passes when every test in the file passes; that is the benchmark's own
criterion. The reference solutions are not released.

Tasks whose test requires a file to be gone are left out of `task_ids()`: the
editing tools under study can create and rewrite files but not delete them.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from functools import cache
from pathlib import Path
from typing import Any

EDITBENCH = Path(__file__).resolve().parents[1]
ROOT = EDITBENCH / "vendor" / "RefactorBench"
BENCHMARK = "refactorbench"
GRADER_TIMEOUT_SECONDS = 120
# A test that asserts a path no longer exists needs a deletion.
DELETION = re.compile(r"assertFalse\(\s*os\.path\.(exists|isfile)|not os\.path\.(exists|isfile)")

sys.path.insert(0, str(EDITBENCH))
from runner import Task  # noqa: E402


@cache
def mapping() -> dict[str, tuple[Path, Path, Path]]:
    """task id -> (repository, test file, descriptive instruction)."""
    namespace: dict[str, Any] = {}
    exec((ROOT / "scripts" / "descriptive_mapping.py").read_text(encoding="utf-8"), namespace)
    tasks = {}
    for test_ref, problem_ref in namespace["file_mapping"].items():
        test = ROOT / os.path.normpath(test_ref.removeprefix("../"))
        problem = ROOT / os.path.normpath(problem_ref.removeprefix("../"))
        repository = ROOT / "repositories" / test.parent.name
        if not (test.is_file() and problem.is_file() and repository.is_dir()):
            raise ValueError(f"RefactorBench mapping entry does not resolve: {test_ref}")
        task_id = f"{test.parent.name.removesuffix('_refactor')}__{test.stem.removesuffix('-test')}"
        if task_id in tasks:
            raise ValueError(f"duplicate RefactorBench task id {task_id}")
        tasks[task_id] = (repository, test, problem)
    return tasks


def needs_deletion(task_id: str) -> bool:
    return bool(DELETION.search(mapping()[task_id][1].read_text(encoding="utf-8")))


def task_ids() -> list[str]:
    return sorted(task_id for task_id in mapping() if not needs_deletion(task_id))


def grade_workspace(workspace: Path, test: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="editbench-refactorbench-") as scratch:
        copy = Path(scratch) / "repository"
        shutil.copytree(workspace, copy, symlinks=True)
        evaluation = copy / "_refactorbench_eval"
        evaluation.mkdir()
        shutil.copy2(test, evaluation / "rb_test.py")
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "unittest", "-v", "rb_test"],
                cwd=evaluation,
                env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True,
                text=True,
                timeout=GRADER_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return {"passed": False, "reason": "grader timed out"}
    output = completed.stdout + completed.stderr
    ran = re.search(r"^Ran (\d+) tests?", output, re.M)
    tests_run = int(ran.group(1)) if ran else 0
    failed = re.search(r"FAILED \(([^)]*)\)", output)
    return {
        "passed": completed.returncode == 0 and tests_run > 0,
        "grader_exit_code": completed.returncode,
        "tests_run": tests_run,
        "failed": failed.group(1) if failed else "",
        "test_file": str(test.relative_to(ROOT)),
        "output_tail": output[-2000:],
    }


def load(task_id: str) -> Task:
    if task_id not in mapping():
        raise ValueError(f"unknown {BENCHMARK} task {task_id!r}")
    repository, test, problem = mapping()[task_id]
    prompt = problem.read_text(encoding="utf-8").strip() + "\n"

    def prepare(workspace: Path) -> None:
        shutil.copytree(repository, workspace, symlinks=True)

    return Task(
        benchmark=BENCHMARK,
        task_id=task_id,
        prompt=prompt,
        prepare=prepare,
        grade=lambda workspace: grade_workspace(workspace, test),
        fixture=None,
    )
