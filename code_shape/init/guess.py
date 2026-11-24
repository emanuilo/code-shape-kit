"""What `code-shape init` can tell about a project from its files: packages, src layout,
its settings module, and a draft of its layers."""

from __future__ import annotations

import ast
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from code_shape.checks import graph as import_graph
from code_shape.init.layers import Draft, draft
from code_shape.init.requires import DEFAULT, ci_python
from code_shape.settings import default_src, find_packages

ENVIRONMENT = {"environ", "getenv", "putenv"}  # the os names [tool.shape] banned_api bans outside config_modules
SETTINGS_NAMES = {"config", "settings", "conf", "env"}  # what a settings module is usually called


@dataclass
class Project:
    root: Path
    src: Path
    packages: list[str]
    found: bool  # False: no package yet, `packages` holds a placeholder name
    python: str = DEFAULT  # for CI: the lowest Python the project allows
    python_why: str = "the default: no usable requires-python"
    config_module: str = ""  # the settings module (relative to the root), "" when none is obvious
    config_why: str = ""  # how it was picked
    env_reads: dict[str, int] = field(default_factory=dict)  # module -> os.environ / getenv uses
    drafts: list[Draft] = field(default_factory=list)  # one per package that has modules inside
    graph_error: str = ""  # why the imports could not be read

    @property
    def has_code(self) -> bool:
        return any(d.layers for d in self.drafts) or bool(self.graph_error)

    @property
    def other_env_readers(self) -> list[str]:
        """The modules that read the environment outside the settings module: check flags them."""
        return [path for path in self.env_reads if path != self.config_module]

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


def guess(root: Path, pyproject: dict) -> Project:
    shape = pyproject.get("tool", {}).get("shape", {})  # an existing [tool.shape] says where the code is
    src = root / shape["src"] if "src" in shape else default_src(root)
    packages = list(shape.get("packages") or find_packages(src))
    project = Project(root, src, packages or [_placeholder(pyproject)], found=bool(packages))
    requires = pyproject.get("project", {}).get("requires-python")
    if python := ci_python(requires):
        project.python, project.python_why = python, f"the lowest 3.11+ that requires-python {requires!r} allows"
    files = [path for name in packages for path in sorted((src / name.replace(".", "/")).rglob("*.py"))]
    if not files:
        return project
    reads = {project.rel(path): _environment_reads(path) for path in files}
    project.env_reads = {path: count for path, count in reads.items() if count}
    project.config_module, project.config_why = _settings_module(list(reads), project.env_reads)
    try:
        graph = import_graph.build(src, packages)
    except ValueError as exc:
        project.graph_error = str(exc)
        return project
    project.drafts = [draft(graph, name) for name in packages]
    return project


def _placeholder(pyproject: dict) -> str:
    """The package name a new project will likely use: its [project] name, else `myapp`."""
    name = re.sub(r"\W+", "_", str(pyproject.get("project", {}).get("name", ""))).strip("_").lower()
    return name if name.isidentifier() else "myapp"


def _settings_module(modules: list[str], reads: dict[str, int]) -> tuple[str, str]:
    """The one obvious settings module, and why: by its name (config.py, settings.py...), else
    the module with clearly the most environment reads. ("", "") when no single one stands out."""
    named = [path for path in modules if Path(path).stem in SETTINGS_NAMES]
    readers = [path for path in named if path in reads]
    if len(readers) == 1 or (len(named) == 1 and not readers):
        found = (readers or named)[0]
        return found, f"named {Path(found).name}"
    if named:  # several: config.py and settings.py both there, say
        return "", ""
    ranked = sorted(reads.items(), key=lambda item: -item[1])
    if ranked and (len(ranked) == 1 or ranked[0][1] > ranked[1][1]):
        return ranked[0][0], f"the most environment reads ({ranked[0][1]})"
    return "", ""


def _environment_reads(path: Path) -> int:
    """How often the file uses os.environ / os.getenv / os.putenv (also via `from os import environ`)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:  # the import graph reports it; one unreadable file is no settings module
        return 0
    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "os"
        for alias in node.names
        if alias.name in ENVIRONMENT
    }
    return sum(
        (isinstance(node, ast.Attribute) and node.attr in ENVIRONMENT and _is_os(node.value))
        or (isinstance(node, ast.Name) and node.id in imported)
        for node in ast.walk(tree)
    )


def _is_os(node: ast.expr) -> bool:
    return isinstance(node, ast.Name) and node.id == "os"


def read_pyproject(path: Path) -> tuple[str, dict]:
    text = path.read_text(encoding="utf-8")
    return text, tomllib.loads(text)
