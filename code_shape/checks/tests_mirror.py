"""Do the tests mirror the source tree?  pkg/a/b.py  <->  tests/a/test_b.py"""

from __future__ import annotations

from code_shape.model import Finding, GroupResult, Table
from code_shape.settings import Settings
from code_shape.source import python_files


def run(settings: Settings) -> GroupResult:
    if not settings.tests.is_dir():
        return GroupResult("tests", skipped=f"no tests folder at {settings.rel(settings.tests)}")
    tests = {p.relative_to(settings.tests).as_posix() for p in settings.tests.rglob("test_*.py")}
    by_name = {t.rsplit("/", 1)[-1] for t in tests}
    result = GroupResult("tests")
    mirrored = elsewhere = missing = 0
    stems = set()
    for path in python_files(settings):
        if path.name.startswith("__"):
            continue
        inside = path.relative_to(settings.src).parts[1:]  # drop the top package name
        expected = "/".join([*inside[:-1], f"test_{path.stem}.py"])
        stems.add(path.stem)
        if expected in tests:
            mirrored += 1
        elif f"test_{path.stem}.py" in by_name:
            elsewhere += 1
            detail = f"tests exist but not at tests/{expected}"
            result.findings.append(Finding("test-mirror", settings.rel(path), detail=detail))
        else:
            missing += 1
            result.findings.append(Finding("test-mirror", settings.rel(path), detail=f"no tests/{expected}"))
    total = mirrored + elsewhere + missing
    orphans = sorted(t for t in tests if t.rsplit("/", 1)[-1][5:-3] not in stems)
    result.metrics = {
        "modules with a mirrored test file (%)": round(100 * mirrored / total) if total else 0,
        "modules with no test file (%)": round(100 * missing / total) if total else 0,
    }
    if orphans:
        result.tables.append(
            Table(
                "Test files named after no module (fine for cross-cutting tests)",
                ["test file"],
                [[f"{settings.rel(settings.tests)}/{t}"] for t in orphans],
            )
        )
    return result
