"""Locality of change per concept.

You name the project's concepts in [tool.shape.concepts] with a few words or
regexes each, e.g.  refunds = ["refund", "RefundPolicy"], or with an explicit
home module or package:  refunds = {terms = ["refund"], home = "shop/refunds.py"}.
For every concept the check reports:
  - code: source files that mention it (a proxy for "files you touch to change it")
  - home: the module or package that owns it (default: the file that mentions it most)
  - history: when the home file changed, how many other source files changed in
    the same commit, and which ones most often
A localized concept lives in a few files in a few nearby areas.
"""

from __future__ import annotations

import re
from collections import Counter
from statistics import median

from code_shape.checks.history import Commit, commits
from code_shape.model import Finding, GroupResult, Table
from code_shape.settings import Settings
from code_shape.source import python_files, unit_of


def run(settings: Settings) -> GroupResult:
    if not settings.concepts:
        return GroupResult("concepts", skipped="no [tool.shape.concepts] configured")
    limit, max_areas = settings.limits["concept_files"], settings.limits["concept_areas"]
    texts = {settings.rel(p): p.read_text(encoding="utf-8", errors="replace") for p in python_files(settings)}
    history = commits(settings)
    result = GroupResult("concepts")
    rows = []
    for name, spec in settings.concepts.items():
        pattern = re.compile("|".join(spec["terms"]), re.IGNORECASE)
        hits = Counter({rel: len(pattern.findall(text)) for rel, text in texts.items() if pattern.search(text)})
        areas = sorted({unit_of(f, settings.packages) for f in hits})
        home = spec["home"] or (hits.most_common(1)[0][0] if hits else "")
        verdict = "localized" if len(hits) <= limit and len(areas) <= max_areas else "scattered"
        rows.append(
            [
                name,
                len(hits),
                len(areas),
                ", ".join(a.split("/")[-1] for a in areas),
                home,
                *_co_changes(home, history, settings.limits["max_changeset_files"]),
                verdict,
            ]
        )
        if verdict == "scattered":
            result.findings.append(
                Finding(
                    "concept-spread",
                    "concepts",
                    name,
                    len(hits),
                    limit,
                    detail=f"{len(areas)} areas: {', '.join(areas)}",
                )
            )
    result.tables.append(
        Table(
            "Concepts: where each one lives",
            [
                "concept",
                "files mentioning it",
                "areas",
                "which areas",
                "home",
                "commits to home",
                "other files per such commit (median)",
                "most often changed with home",
                "verdict",
            ],
            rows,
            f"localized = at most {int(limit)} files in at most {int(max_areas)} areas (an area is a sub-package "
            "or a top-level module). 'Mentioning' is a proxy: it counts every file that names the concept, "
            "including callers.",
        )
    )
    return result


def _co_changes(home: str, history: list[Commit], max_files: float) -> list:
    """How the home (a module, or a package folder) changes: with how many other files, and which."""
    folder = home.rstrip("/") + "/"

    def inside(rel: str) -> bool:
        return rel == home or rel.startswith(folder)

    touching = [c for c in history if any(map(inside, c.files)) and len(c.files) <= max_files]
    if not touching:
        return [0, 0, ""]
    others = Counter(f for c in touching for f in c.files if not inside(f))
    spread = median(sum(not inside(f) for f in c.files) for c in touching)
    top = ", ".join(f"{f.rsplit('/', 1)[-1]} ({n})" for f, n in others.most_common(3))
    return [len(touching), spread, top]
