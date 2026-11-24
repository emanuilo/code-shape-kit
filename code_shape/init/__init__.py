"""`code-shape init`: sets the kit up in a project, with best guesses for a human (or agent) to review.

It adds [tool.shape] and [tool.importlinter] to pyproject.toml (as text, so the file's own
comments and formatting stay), and the CI workflow and CODEOWNERS to .github/. It never
overwrites: a section or file that is already there is left alone. Without a pyproject.toml it
stops: which build backend and metadata a project needs is not the kit's guess to make.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from code_shape.init import sections
from code_shape.init.guess import Project, guess, read_pyproject
from code_shape.settings import ConfigError

WORKFLOW = ".github/workflows/code-shape.yml"
CODEOWNERS = ".github/CODEOWNERS"
OTHER_CODEOWNERS = ("CODEOWNERS", "docs/CODEOWNERS")  # GitHub reads the first one it finds


@dataclass
class Write:
    path: str  # relative to the root
    text: str
    append: bool  # added to the end of an existing file, else a new file
    what: str  # e.g. "[tool.shape] and [tool.importlinter]"


@dataclass
class Plan:
    root: Path
    project: Project
    writes: list[Write] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def apply(self) -> None:
        for write in self.writes:
            path = self.root / write.path
            path.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if write.append else "x"  # "x": never overwrite a file that appeared meanwhile
            with path.open(mode, encoding="utf-8") as handle:
                handle.write(write.text)


def plan(root: Path) -> Plan:
    root = root.resolve()
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        raise ConfigError(
            f"code-shape init: no pyproject.toml in {root}. Create one for your project first "
            "(e.g. with `uv init` or your build tool), then run `code-shape init` again."
        )
    try:
        text, config = read_pyproject(pyproject)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"code-shape init: pyproject.toml is not valid TOML ({exc}); fix it first.") from exc
    result = Plan(root, guess(root, config))
    result.writes += _pyproject(result, text, config)
    _add_file(result, WORKFLOW, sections.workflow(result.project), "the CI gate")
    if any((root / other).exists() for other in OTHER_CODEOWNERS):
        found = next(other for other in OTHER_CODEOWNERS if (root / other).exists())
        result.skipped.append(f"{CODEOWNERS}: you have {found}; add the lines from the kit's CODEOWNERS template to it")
    else:
        _add_file(result, CODEOWNERS, sections.codeowners(), "human review for the rules")
    return result


def _pyproject(result: Plan, text: str, config: dict) -> list[Write]:
    tool = config.get("tool", {})
    added, names = [], []
    if "shape" in tool:
        result.skipped.append("pyproject.toml [tool.shape]: already there, left as it is")
    else:
        added.append(sections.shape(result.project))
        names.append("[tool.shape]")
    if "importlinter" in tool or (result.root / ".importlinter").exists():
        where = "[tool.importlinter]" if "importlinter" in tool else ".importlinter"
        result.skipped.append(f"pyproject.toml [tool.importlinter]: you have {where} already, left as it is")
    else:
        added.append(sections.importlinter(result.project))
        names.append("[tool.importlinter]")
    if not added:
        return []
    addition = ("\n" if text.endswith("\n") or not text else "\n\n") + sections.HEADER + "\n" + "\n".join(added)
    try:
        tomllib.loads(text + addition)
    except tomllib.TOMLDecodeError as exc:  # e.g. the file already defines a table the template adds
        raise ConfigError(f"code-shape init: adding to pyproject.toml would make it invalid TOML ({exc})") from exc
    return [Write("pyproject.toml", addition, append=True, what=" and ".join(names))]


def _add_file(result: Plan, path: str, text: str, what: str) -> None:
    if (result.root / path).exists():
        result.skipped.append(f"{path}: already there, left as it is")
    else:
        result.writes.append(Write(path, text, append=False, what=what))
