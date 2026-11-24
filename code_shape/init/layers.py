"""Drafts a layers contract from today's imports between the modules directly inside a package.

A module that imports another goes in a higher layer. Modules that don't import each other
can share a layer (`a | b`). Import cycles can't be layered: the modules in a cycle are put
in an order anyway, and the imports that go against it are returned, to be listed under
`ignore_imports` (import-linter's own baseline) and fixed later.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import grimp

Edges = dict[tuple[str, str], list[str]]  # (importer, imported) child -> the module imports behind it


@dataclass
class Draft:
    package: str
    layers: list[list[str]] = field(default_factory=list)  # top layer first; names relative to the package
    against: list[str] = field(default_factory=list)  # "pkg.a.x -> pkg.b.y": imports that break the order

    def describe(self) -> str:
        """api -> orders | inventory -> db"""
        return " -> ".join(" | ".join(layer) for layer in self.layers)


def draft(graph: grimp.ImportGraph, package: str) -> Draft:
    children = sorted(graph.find_children(package))
    edges = _edges(graph, children)
    level = _levels(children, edges)
    by_level: dict[int, list[str]] = defaultdict(list)
    for child in children:
        by_level[level[child]].append(child.rsplit(".", 1)[1])
    against = sorted({line for (a, b), lines in edges.items() if level[a] <= level[b] for line in lines})
    return Draft(package, [sorted(by_level[n]) for n in sorted(by_level, reverse=True)], against)


def _edges(graph: grimp.ImportGraph, children: list[str]) -> Edges:
    """Which child imports which, from the imports of every module inside each child."""
    owner = {child: child for child in children}
    for child in children:
        owner.update(dict.fromkeys(graph.find_descendants(child), child))
    edges: Edges = defaultdict(list)
    for importer, importer_child in owner.items():
        for imported in sorted(graph.find_modules_directly_imported_by(importer)):
            imported_child = owner.get(imported)
            if imported_child and imported_child != importer_child:
                edges[(importer_child, imported_child)].append(f"{importer} -> {imported}")
    return edges


def _levels(children: list[str], edges: Edges) -> dict[str, int]:
    """0 for modules that import none of the others, else one above the highest module they import.

    Within an import cycle the module that imports the most from the others goes highest;
    the imports from a lower module of the cycle up to a higher one are left out here.
    """
    reach = {child: _reachable(child, edges) for child in children}
    rank = {child: _cycle_rank(child, reach, edges) for child in children}
    kept = defaultdict(list)
    for a, b in edges:
        if a not in reach[b] or rank[a] < rank[b]:  # not in a cycle, or downwards within one
            kept[a].append(b)
    level: dict[str, int] = {}

    def visit(child: str) -> int:
        if child not in level:
            level[child] = 1 + max((visit(b) for b in kept[child]), default=-1)
        return level[child]

    for child in children:
        visit(child)
    return level


def _reachable(start: str, edges: Edges) -> set[str]:
    seen: set[str] = set()
    todo = [start]
    while todo:
        node = todo.pop()
        for a, b in edges:
            if a == node and b not in seen:
                seen.add(b)
                todo.append(b)
    return seen


def _cycle_rank(child: str, reach: dict[str, set[str]], edges: Edges) -> tuple[int, str]:
    """Sorts the modules of one cycle: the most imports out (minus imports in) first, then by name."""
    cycle = {other for other in reach[child] if child in reach[other]}
    out = sum(len(lines) for (a, b), lines in edges.items() if a == child and b in cycle)
    into = sum(len(lines) for (a, b), lines in edges.items() if b == child and a in cycle)
    return (into - out, child)
