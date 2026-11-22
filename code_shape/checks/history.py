"""What git history says about locality of change (the idea behind code-maat / CodeScene).

- commit spread: how many files and areas a typical commit touches
- change coupling: pairs of files that keep changing in the same commits
- hotspots: big files that also change often (where shape problems cost the most)
"""

from __future__ import annotations

import subprocess
from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from statistics import median

from code_shape.model import Finding, GroupResult, Table
from code_shape.settings import Settings
from code_shape.source import line_count, unit_of


@dataclass(frozen=True)
class Commit:
    sha: str
    date: str
    subject: str
    files: tuple[str, ...]  # source files only, relative to the project root


def commits(settings: Settings) -> list[Commit]:
    """Non-merge commits in the history window that touched source files."""
    git = ["git", "-C", str(settings.root), "-c", "core.quotepath=off"]
    probe = subprocess.run([*git, "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False)
    if probe.returncode != 0:
        return []  # not a git repository
    top = Path(probe.stdout.strip())
    log = subprocess.run(
        [
            *git,
            "log",
            "--no-merges",
            "--no-renames",
            f"--since={int(settings.limits['history_days'])} days ago",
            "--format=%x1e%h%x1f%ad%x1f%s",
            "--date=short",
            "--name-only",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    prefixes = tuple(settings.rel(p) + "/" for p in settings.package_dirs())
    found = []
    for record in log.split("\x1e")[1:]:
        header, *names = record.strip("\n").split("\n")
        sha, date, subject = header.split("\x1f", 2)
        files = tuple(
            rel
            for rel in (settings.rel(top / name) for name in names if name.endswith(".py"))
            if rel.startswith(prefixes)
        )
        if files:
            found.append(Commit(sha, date, subject, files))
    return found


def run(settings: Settings) -> GroupResult:
    history = commits(settings)
    result = GroupResult("history")
    if not history:
        result.skipped = "no git history for the source files (not a git repository?)"
        return result
    _spread(settings, history, result)
    _coupling(settings, history, result)
    _hotspots(settings, history, result)
    return result


def _spread(settings: Settings, history: list[Commit], result: GroupResult) -> None:
    files = sorted(len(c.files) for c in history)
    areas = sorted(len({unit_of(f, settings.packages) for f in c.files}) for c in history)
    result.metrics.update(
        {
            "commits analysed": len(history),
            "source files per commit, median": median(files),
            "areas per commit, median": median(areas),
            "areas per commit, 90th percentile": areas[int(len(areas) * 0.9)],
            "commits touching 3+ areas (%)": round(100 * sum(a >= 3 for a in areas) / len(areas)),
        }
    )


def _coupling(settings: Settings, history: list[Commit], result: GroupResult) -> None:
    limits = settings.limits
    usable = [c for c in history if len(c.files) <= limits["max_changeset_files"]]
    revisions = Counter(f for c in usable for f in c.files)
    shared = Counter(pair for c in usable for pair in combinations(sorted(c.files), 2))
    rows: list[tuple[str, str, int, int, str]] = []
    for (a, b), together in shared.items():
        if together < limits["coupling_min_shared"]:
            continue
        degree = round(100 * together / ((revisions[a] + revisions[b]) / 2))
        same_area = unit_of(a, settings.packages) == unit_of(b, settings.packages)
        rows.append((a, b, together, degree, "yes" if same_area else "NO"))
        if not same_area and degree >= limits["coupling_percent"]:
            result.findings.append(
                Finding(
                    "change-coupling",
                    a,
                    f"changes with {b}",
                    degree,
                    limits["coupling_percent"],
                    detail=f"{together} shared commits",
                )
            )
    rows.sort(key=lambda r: (-r[3], -r[2]))
    result.tables.append(
        Table(
            "Files that change together",
            ["file", "file", "shared commits", "coupling %", "same area?"],
            [list(r) for r in rows[:20]],
            f"coupling % = shared commits / average commits of the two files. Commits touching more than "
            f"{int(limits['max_changeset_files'])} source files are ignored (bulk edits).",
        )
    )


def _hotspots(settings: Settings, history: list[Commit], result: GroupResult) -> None:
    revisions = Counter(f for c in history for f in c.files)
    rows = [
        (rel, count, line_count(settings.root / rel))
        for rel, count in revisions.items()
        if (settings.root / rel).exists()
    ]
    rows.sort(key=lambda r: -r[1] * r[2])
    result.tables.append(
        Table(
            "Hotspots (changed often AND big)",
            ["file", "commits", "lines", "score"],
            [[rel, n, lines, n * lines] for rel, n, lines in rows[:10]],
            "score = commits x lines. Fix shape problems here first.",
        )
    )
