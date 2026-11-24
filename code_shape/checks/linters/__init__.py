"""Runs the established tools and turns their output into Findings, one module per tool family.

Limits come from [tool.shape.limits] and are passed on the command line, so
the shape rules don't depend on (or clash with) the project's normal lint setup.
ruff's `# noqa` and complexipy's ignore comments are ignored on purpose: the
baseline file is the one visible place to record exceptions. pylint, vulture and mypy
have no such switch, so their inline comments (`# pylint: disable`, `# noqa`,
`# type: ignore`) still silence them; the suppressions check counts those comments.
mypy reads the project's [tool.mypy] without the settings that take code out of the check.

  running.py        runs a tool from a scratch folder; shared output helpers
  rules.py          ruff and complexipy: per-function rules and complexity
  pylint_checks.py  pylint: nesting, locals, class size, and copy-pasted code
  contracts.py      import-linter: the architecture contracts
  program.py        vulture, deptry, mypy: dead code, dependencies, types
"""

from __future__ import annotations

from code_shape.checks.linters.contracts import import_linter
from code_shape.checks.linters.program import deptry, mypy, vulture
from code_shape.checks.linters.pylint_checks import pylint
from code_shape.checks.linters.rules import complexipy, ruff
from code_shape.checks.linters.running import ToolError

__all__ = ["ToolError", "complexipy", "deptry", "import_linter", "mypy", "pylint", "ruff", "vulture"]
