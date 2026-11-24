"""Import-graph numbers (via grimp, the engine behind import-linter): cycles, fan-in, fan-out.

fan-in  = how many project modules import this one (high = many things break if it changes)
fan-out = how many project modules this one imports (high = it breaks when any of them changes)
instability = fan-out / (fan-in + fan-out): 0 = everyone leans on it, 1 = nobody does.
"""

from __future__ import annotations

import sys
from pathlib import Path

import grimp

from code_shape.model import Finding, GroupResult, Table
from code_shape.settings import Settings
from code_shape.source import module_path


def build(src: Path, packages: list[str]) -> grimp.ImportGraph:
    """The import graph of the packages found in `src`; ValueError if it can't be built."""
    sys.path.insert(0, str(src))
    try:
        return grimp.build_graph(*packages, cache_dir=None)
    except grimp.exceptions.GrimpException as exc:  # e.g. a syntax error: the graph would be incomplete
        raise ValueError(f"grimp could not build the import graph: {exc}") from exc
    finally:
        sys.path.remove(str(src))


def run(settings: Settings) -> GroupResult:
    graph = build(settings.src, settings.packages)
    modules = sorted(graph.modules)
    imports = {m: graph.find_modules_directly_imported_by(m) for m in modules}
    importers = {m: graph.find_modules_that_directly_import(m) for m in modules}
    result = GroupResult("graph")
    fan_out_limit = settings.limits["fan_out"]

    for module in modules:
        if len(imports[module]) > fan_out_limit:
            detail = "imports " + ", ".join(sorted(imports[module]))
            path = module_path(settings, module)
            result.findings.append(Finding("fan-out", path, module, len(imports[module]), fan_out_limit, detail=detail))
    cycles = _cycles(graph, modules)
    for cycle in cycles:
        names = sorted(cycle)
        detail = "imports in the cycle: " + "; ".join(_imports_within(graph, names))
        result.findings.append(
            Finding("import-cycles", module_path(settings, names[0]), " <-> ".join(names), len(names), detail=detail)
        )

    result.tables.append(_connections(modules, imports, importers))
    edges = sum(len(v) for v in imports.values())
    result.metrics = {
        "modules in import graph": len(modules),
        "internal imports (edges)": edges,
        "modules in import cycles": sum(len(c) for c in cycles),
        "max fan-out": max((len(v) for v in imports.values()), default=0),
        "max fan-in": max((len(v) for v in importers.values()), default=0),
    }
    return result


def _connections(modules: list[str], imports: dict[str, set[str]], importers: dict[str, set[str]]) -> Table:
    ranked = sorted(modules, key=lambda m: -(len(importers[m]) + len(imports[m])))
    rows = []
    for module in ranked[:15]:
        fan_in, fan_out = len(importers[module]), len(imports[module])
        rows.append([module, fan_in, fan_out, f"{fan_out / (fan_in + fan_out) if fan_in + fan_out else 0:.2f}"])
    return Table(
        "Most connected modules",
        ["module", "fan-in (imported by)", "fan-out (imports)", "instability"],
        rows,
        "Hubs with both high fan-in and high fan-out are the riskiest to change.",
    )


def _imports_within(graph: grimp.ImportGraph, modules: list[str]) -> list[str]:
    """Each import between the given modules, as "a -> b (l.3)": the ones to break up."""
    found = []
    for importer in modules:
        for imported in sorted(graph.find_modules_directly_imported_by(importer) & set(modules)):
            lines = sorted({d["line_number"] for d in graph.get_import_details(importer=importer, imported=imported)})
            where = f" (l.{', '.join(map(str, lines))})" if lines else ""
            found.append(f"{importer} -> {imported}{where}")
    return found


def _cycles(graph: grimp.ImportGraph, modules: list[str]) -> list[set[str]]:
    """Groups of modules that (directly or indirectly) import each other."""
    seen: set[str] = set()
    groups = []
    for module in modules:
        if module in seen:
            continue
        group = graph.find_upstream_modules(module) & graph.find_downstream_modules(module)
        if group:
            group.add(module)
            seen |= group
            groups.append(group)
    return groups
