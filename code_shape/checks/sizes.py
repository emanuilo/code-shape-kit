"""Custom size checks no linter covers: file/class length and package (folder) size and depth."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from code_shape.model import Finding, GroupResult, Table
from code_shape.settings import Settings
from code_shape.source import definitions, line_count, python_files


def run(settings: Settings) -> GroupResult:
    lines = {path: line_count(path) for path in python_files(settings)}
    folders: dict[Path, list[Path]] = defaultdict(list)
    for path in lines:
        folders[path.parent].append(path)
    result = GroupResult("sizes", _file_findings(settings, lines) + _folder_findings(settings, folders, lines))
    sizes = sorted(lines.values())
    result.metrics = {
        "python files": len(sizes),
        "total lines": sum(sizes),
        "packages (folders)": len(folders),
        "biggest file (lines)": sizes[-1] if sizes else 0,
        "median file (lines)": sizes[len(sizes) // 2] if sizes else 0,
        "most modules in one folder": max((len(_modules(m)) for m in folders.values()), default=0),
    }
    rows = [
        [
            settings.rel(folder) + "/",
            len(_modules(members)),
            sum(lines[m] for m in members),
            max(members, key=lines.__getitem__).name,
        ]
        for folder, members in sorted(folders.items())
    ]
    result.tables.append(Table("Folders (packages)", ["folder", "modules", "lines", "biggest file"], rows))
    return result


def _modules(members: list[Path]) -> list[Path]:
    return [m for m in members if m.name != "__init__.py"]


def _file_findings(settings: Settings, lines: dict[Path, int]) -> list[Finding]:
    limits = settings.limits
    found = [
        Finding("file-lines", settings.rel(path), value=count, limit=limits["file_lines"])
        for path, count in lines.items()
        if count > limits["file_lines"]
    ]
    for path in lines:
        for d in definitions(path):
            size = d.end - d.start + 1
            if d.is_class and size > limits["class_lines"]:
                found.append(Finding("class-lines", settings.rel(path), d.name, size, limits["class_lines"], d.start))
    return found


def _folder_findings(settings: Settings, folders: dict[Path, list[Path]], lines: dict[Path, int]) -> list[Finding]:
    limits = settings.limits
    found = []
    for folder, members in sorted(folders.items()):
        rel = settings.rel(folder) + "/"
        measured = {
            "package-files": (len(_modules(members)), limits["package_files"]),
            "package-lines": (sum(lines[m] for m in members), limits["package_lines"]),
            "package-depth": (len(folder.relative_to(settings.src).parts), limits["package_depth"]),
        }
        found += [
            Finding(check, rel, value=value, limit=limit) for check, (value, limit) in measured.items() if value > limit
        ]
    return found
