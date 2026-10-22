"""Adapter for Aider's refactor benchmark (Aider-AI/refactor-benchmark, Apache-2.0).

Each task asks for one method to become a top-level function, with every
call updated. The workspace holds only the source file. The task's test, which
carries the expected AST node counts, is added to a copy of the workspace at
grading time. It imports `benchmark.refactor_tools`, which is served from a
vendored copy of Aider's benchmark/refactor_tools.py with the unused
`aider.dump` import removed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

EDITBENCH = Path(__file__).resolve().parents[1]
TASKS = EDITBENCH / "vendor" / "refactor-benchmark" / "refactor-benchmark"
REFACTOR_TOOLS = EDITBENCH / "vendor" / "aider-benchmark" / "refactor_tools.py"
BENCHMARK = "aider-refactor"
GRADER_TIMEOUT_SECONDS = 120
# Verbatim from Aider's benchmark/prompts.py (instructions_addendum), which
# benchmark.py appends to every exercise's instructions.
AIDER_INSTRUCTIONS_ADDENDUM = """
####

Use the above instructions to modify the supplied files: {file_list}
Don't change the names of existing functions or classes, as they may be referenced from other code like unit tests, etc.
Only use standard libraries, don't suggest installing any packages.
"""

sys.path.insert(0, str(EDITBENCH))
from runner import Task  # noqa: E402


def task_ids() -> list[str]:
    return sorted(path.name for path in TASKS.iterdir() if path.is_dir())


def task_files(directory: Path) -> tuple[Path, Path]:
    tests = sorted(directory.glob("*_test.py"))
    if len(tests) != 1:
        raise ValueError(f"{directory.name}: expected one *_test.py, found {len(tests)}")
    source = directory / tests[0].name.removesuffix("_test.py").__add__(".py")
    if not source.is_file():
        raise ValueError(f"{directory.name}: missing source {source.name}")
    return source, tests[0]


def verifier_package(root: Path) -> None:
    package = root / "benchmark"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    text = REFACTOR_TOOLS.read_text(encoding="utf-8")
    unused_import = "from aider.dump import dump  # noqa: F401\n"
    if unused_import not in text:
        raise ValueError("vendored refactor_tools.py no longer has the expected aider.dump import")
    (package / "refactor_tools.py").write_text(text.replace(unused_import, ""), encoding="utf-8")


def grade_workspace(workspace: Path, source_name: str, test: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="editbench-refactor-") as scratch:
        root = Path(scratch)
        verifier_package(root)
        copy = root / "workspace"
        shutil.copytree(workspace, copy)
        shutil.copy2(test, copy / test.name)
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "unittest", "-v", test.stem],
                cwd=copy,
                env={"PYTHONPATH": str(root), "PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True,
                text=True,
                timeout=GRADER_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return {"passed": False, "reason": "grader timed out"}
    return {
        "passed": completed.returncode == 0,
        "grader_exit_code": completed.returncode,
        "source": source_name,
        "output_tail": (completed.stdout + completed.stderr)[-2000:],
    }


def load(task_id: str) -> Task:
    directory = TASKS / task_id
    if not directory.is_dir() or directory.parent != TASKS:
        raise ValueError(f"unknown {BENCHMARK} task {task_id!r}")
    source, test = task_files(directory)
    # Built as Aider's run_test_real does: instructions.md, then the addendum.
    instructions = (directory / ".docs" / "instructions.md").read_text(encoding="utf-8")
    prompt = instructions + AIDER_INSTRUCTIONS_ADDENDUM.format(file_list=source.name)

    def prepare(workspace: Path) -> None:
        workspace.mkdir()
        shutil.copy2(source, workspace / source.name)

    return Task(
        benchmark=BENCHMARK,
        task_id=task_id,
        prompt=prompt,
        prepare=prepare,
        grade=lambda workspace: grade_workspace(workspace, source.name, test),
        fixture=None,
    )
