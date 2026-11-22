"""All check groups, in report order.

A group is either an established tool (wrapped in linters.py) or a small custom
check for a gap no tool covers. Disable groups with [tool.shape] skip = [...].
"""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from code_shape.checks import concepts, graph, history, linters, sizes, tests_mirror
from code_shape.model import GroupResult
from code_shape.settings import Settings

TOOL_GROUPS: dict[str, Callable[[Settings, Path], GroupResult]] = {
    "ruff": linters.ruff,
    "complexipy": linters.complexipy,
    "pylint": linters.pylint,
    "import-linter": linters.import_linter,
    "vulture": linters.vulture,
    "deptry": linters.deptry,
    "mypy": linters.mypy,
}
CUSTOM_GROUPS: dict[str, Callable[[Settings], GroupResult]] = {
    "sizes": sizes.run,
    "graph": graph.run,
    "history": history.run,
    "concepts": concepts.run,
    "tests": tests_mirror.run,
}
ALL_GROUPS = [
    "sizes",
    "ruff",
    "complexipy",
    "pylint",
    "import-linter",
    "graph",
    "vulture",
    "deptry",
    "mypy",
    "history",
    "concepts",
    "tests",
]
FAST_GROUPS = ["sizes", "ruff", "complexipy"]  # used for the git-history trend


def run_all(settings: Settings, groups: list[str] | None = None) -> list[GroupResult]:
    results = []
    with tempfile.TemporaryDirectory(prefix="code-shape-") as tmp:
        for name in groups or ALL_GROUPS:
            if name in settings.skip:
                results.append(GroupResult(name, skipped="disabled in [tool.shape] skip"))
                continue
            try:
                if name in TOOL_GROUPS:
                    results.append(TOOL_GROUPS[name](settings, Path(tmp)))
                else:
                    results.append(CUSTOM_GROUPS[name](settings))
            except (linters.ToolError, subprocess.SubprocessError, OSError, ValueError) as exc:
                results.append(GroupResult(name, error=str(exc)))
    return results
