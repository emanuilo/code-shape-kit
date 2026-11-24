"""Trend: re-runs the fast checks on a few past commits (read-only, via `git archive`)."""

from __future__ import annotations

import dataclasses
import io
import subprocess
import tarfile
import tempfile
from pathlib import Path

from code_shape.checks import FAST_GROUPS, run_all
from code_shape.model import GroupResult, Table
from code_shape.settings import Settings

COLUMNS = [
    "when",
    "commit",
    "files",
    "lines",
    "biggest file",
    "files over limit",
    "functions over cyclomatic limit",
    "functions over cognitive limit",
]


def trend(settings: Settings, samples: int, current: list[GroupResult]) -> Table:
    top = Path(_git(["git", "-C", str(settings.root)], "rev-parse", "--show-toplevel").strip()).resolve()
    git = ["git", "-C", str(top)]  # the paths below are relative to the repository, not to the project
    paths = [p.relative_to(top).as_posix() for p in settings.package_dirs()]
    history = _git(git, "log", "--format=%h %ad", "--date=short", "--", *paths).splitlines()[::-1]
    picked = history[:: max(1, len(history) // samples)][-samples:]
    rows = []
    for line in picked:
        sha, when = line.split()
        rows.append([when, sha, *_numbers(_run_at(settings, git, top, paths, sha))])
    rows.append(["now", "working tree", *_numbers([r for r in current if r.name in FAST_GROUPS])])
    return Table(
        "shape over time", COLUMNS, rows, f"Fast checks re-run on {len(picked)} past commits with today's limits."
    )


def _run_at(settings: Settings, git: list[str], top: Path, paths: list[str], sha: str) -> list[GroupResult]:
    """Extract the package folders as they were at `sha` into a temp dir and check them there."""
    # `git archive` fails on a path that is missing at sha, e.g. a package added later.
    present = [p for p in _git(git, "ls-tree", "-z", "--name-only", sha, "--", *paths).split("\0") if p]
    with tempfile.TemporaryDirectory(prefix="code-shape-trend-") as tmp:
        archive = subprocess.run(
            [*git, "archive", "--format=tar", sha, "--", *present], capture_output=True, check=True
        ).stdout
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(tmp, filter="data")
        root = Path(tmp) / settings.root.relative_to(top)
        # Today's error boundaries may name functions the old code doesn't have; the trend doesn't count them.
        tools = dataclasses.replace(settings.tools, error_boundaries={})
        old = dataclasses.replace(settings, root=root, src=root / settings.src.relative_to(settings.root), tools=tools)
        return run_all(old, FAST_GROUPS)


def _numbers(results: list[GroupResult]) -> list:
    metrics = {k: v for r in results for k, v in r.metrics.items()}
    count = {
        check: sum(1 for r in results for f in r.findings if f.check == check)
        for check in ("file-lines", "function-complexity", "cognitive-complexity")
    }
    return [
        metrics.get("python files", 0),
        metrics.get("total lines", 0),
        metrics.get("biggest file (lines)", 0),
        count["file-lines"],
        count["function-complexity"],
        count["cognitive-complexity"],
    ]


def _git(git: list[str], *args: str) -> str:
    return subprocess.run([*git, *args], capture_output=True, text=True, check=True).stdout
