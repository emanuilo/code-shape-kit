"""Finding source files and naming the function/class that contains a line."""

from __future__ import annotations

import ast
import fnmatch
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

from code_shape.settings import Settings


class Definition(NamedTuple):
    start: int  # first line, including decorators
    end: int
    name: str  # qualified, e.g. "Order.total"
    is_class: bool


def python_files(settings: Settings) -> list[Path]:
    return [
        path for pkg in settings.package_dirs() for path in sorted(pkg.rglob("*.py")) if not excluded(settings, path)
    ]


def excluded(settings: Settings, path: str | Path) -> bool:
    """Is the file left out by [tool.shape] exclude? (patterns are relative to the project root)"""
    return any(fnmatch.fnmatch(settings.rel(path), pattern) for pattern in settings.exclude)


def line_count(path: Path) -> int:
    with path.open(encoding="utf-8", errors="replace") as handle:
        return sum(1 for _ in handle)


@lru_cache(maxsize=512)
def definitions(path: Path) -> tuple[Definition, ...]:
    """Every def/class in the file, outermost first.

    A file that doesn't parse is an error (ValueError), not a file without functions:
    a check that can't read a file must not pass it.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError as exc:
        raise ValueError(f"could not parse {path}:{exc.lineno}: {exc.msg}") from exc
    found: list[Definition] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{child.name}"
                start = min([child.lineno] + [d.lineno for d in child.decorator_list])
                end = child.end_lineno or child.lineno
                found.append(Definition(start, end, name, isinstance(child, ast.ClassDef)))
                visit(child, name + ".")
            else:
                visit(child, prefix)

    visit(tree, "")
    return tuple(found)


def symbol_at(path: Path, line: int) -> str:
    """Innermost function or class around `line`, e.g. 'Order.total'; '' at module level."""
    best = ""
    for d in definitions(path):
        if d.start <= line <= d.end:
            best = d.name
    return best


def module_path(settings: Settings, dotted: str) -> str:
    """'pkg.sub.mod' -> 'pkg/sub/mod.py' (or the package's __init__.py)."""
    base = settings.src / dotted.replace(".", "/")
    candidate = base.with_suffix(".py")
    if not candidate.exists():
        candidate = base / "__init__.py"
    return settings.rel(candidate)


def unit_of(rel_path: str, packages: list[str]) -> str:
    """The 'area' a file belongs to: its first sub-package, or the top-level module.

    myapp/payments/stripe.py -> myapp/payments ; myapp/cli.py -> myapp/cli.py
    """
    parts = rel_path.split("/")
    for pkg in packages:
        pkg_parts = pkg.split(".")
        for i in range(len(parts) - len(pkg_parts)):
            if parts[i : i + len(pkg_parts)] == pkg_parts:
                return "/".join(parts[: i + len(pkg_parts) + 1])
    return parts[0]
