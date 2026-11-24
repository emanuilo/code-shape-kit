"""pylint: nesting, locals, class size, and copy-pasted code (looked up in every file)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from code_shape.checks.linters.running import RATIO, ToolError, merge, reading, run
from code_shape.model import Finding, GroupResult
from code_shape.settings import Settings
from code_shape.source import excluded, module_path


def _module_files(settings: Settings) -> list[str]:
    """The modules pylint would find in the package folders, as a sorted list of files.

    Given a folder, pylint lists it in file-system order, which differs between macOS
    and Linux. Its duplicate-code check depends on that order: when one block is copied
    into three files, the order decides which pairs of files get reported. A sorted list
    gives the same findings everywhere. Like pylint, folders without an __init__.py
    inside a regular package are skipped, and so are excluded files (so they are never
    reported as copies).
    """
    files: list[str] = []
    for pkg in settings.package_dirs():
        if not pkg.is_dir():
            files.append(str(pkg))  # let pylint report the bad path itself
            continue
        namespace = not (pkg / "__init__.py").exists()
        for path in sorted(p for p in pkg.rglob("*") if p.suffix in (".py", ".pyi") and p.is_file()):
            folders = path.relative_to(pkg).parents  # path's folders below pkg, and "."
            if (namespace or all((pkg / d / "__init__.py").exists() for d in folders)) and not excluded(settings, path):
                files.append(str(path))
    return files


PYLINT_CHECKS = {
    "too-many-nested-blocks": ("nesting", "nesting", "--max-nested-blocks"),
    "too-many-locals": ("too-many-locals", "locals", "--max-locals"),
    "too-many-boolean-expressions": ("bool-expressions", "bool_expressions", "--max-bool-expr"),
    "too-many-instance-attributes": ("class-attributes", "class_attributes", "--max-attributes"),
    "too-many-public-methods": ("public-methods", "public_methods", "--max-public-methods"),
    "duplicate-code": ("duplicate-code", "duplicate_lines", "--min-similarity-lines"),
}
DUPLICATE = re.compile(r"^==([\w.]+):\[(\d+):(\d+)\]", re.MULTILINE)


def pylint(settings: Settings, tmp: Path) -> GroupResult:
    rcfile = tmp / "empty-pylintrc"
    rcfile.write_text("")
    files = _module_files(settings)
    cmd = [
        "pylint",
        *files,
        f"--rcfile={rcfile}",
        "--persistent=n",
        "--score=n",
        "--output-format=json2",
        "--disable=all",
        f"--enable={','.join(PYLINT_CHECKS)}",
        "--ignore-imports=y",
        "--ignore-docstrings=y",
        "--ignore-comments=y",
        "--ignore-signatures=y",
    ]
    cmd += [f"{option}={int(settings.limits[limit])}" for _, limit, option in PYLINT_CHECKS.values()]
    output = run(settings, tmp, cmd, ok_codes=tuple(range(32)))
    texts = {settings.rel(f): Path(f).read_text(encoding="utf-8", errors="replace") for f in files if Path(f).is_file()}
    sources = {rel: _code_lines(text) for rel, text in texts.items()}
    with reading("pylint"):
        findings = [_pylint_finding(settings, msg, sources) for msg in json.loads(output or "{}").get("messages", [])]
    duplicates = merge([f for f in findings if f.check == "duplicate-code"])
    result = GroupResult("pylint", [f for f in findings if f.check != "duplicate-code"] + duplicates)
    result.metrics["duplicated lines (approx.)"] = sum(f.value or 0 for f in duplicates)
    return result


def _pylint_finding(settings: Settings, msg: dict, sources: dict[str, list[tuple[int, str]]]) -> Finding:
    if msg["symbol"] not in PYLINT_CHECKS:  # e.g. syntax-error or astroid-error: the file was not checked
        raise ToolError(f"pylint could not check {msg['path']}:{msg['line']}: {msg['message']}")
    check, limit, _ = PYLINT_CHECKS[msg["symbol"]]
    if check == "duplicate-code":
        return _duplicate_finding(settings, msg["message"], sources)
    match = RATIO.search(msg["message"])
    value = int(match.group(1)) if match else None
    return Finding(check, settings.rel(msg["path"]), msg["obj"], value, settings.limits[limit], msg["line"])


def _duplicate_finding(settings: Settings, message: str, sources: dict[str, list[tuple[int, str]]]) -> Finding:
    """One message per copied block: the files that hold it, then the block itself.

    pylint lists only two files when a block is in three or more (once a copy is part of a
    reported group, it drops the pairs that copy forms with further files). So the block is
    also looked up in every file: a third copy of a known copy-paste must count as new.
    """
    blocks = list(DUPLICATE.finditer(message))
    code = [line for _, line in _code_lines(message[blocks[-1].end() :])] if blocks else []
    # pylint's [start:end] counts from 0 and leaves out `end`, so it is lines start+1 to end
    where = {module_path(settings, b.group(1)): (int(b.group(2)) + 1, int(b.group(3))) for b in blocks}
    for rel, lines in sources.items():
        found = _find(lines, code)
        if found and rel not in where:
            where[rel] = found
    first, *others = sorted(where)
    length = int(blocks[0].group(3)) - int(blocks[0].group(2)) if blocks else 0
    limit = settings.limits["duplicate_lines"]
    copies = "copies at " + ", ".join(f"{rel}:{start}-{end}" for rel, (start, end) in sorted(where.items()))
    return Finding(
        "duplicate-code", first, f"same code as {' + '.join(others) or 'itself'}", length, limit, None, copies
    )


def _code_lines(text: str) -> list[tuple[int, str]]:
    """(line number, line) as compared for copies: stripped, without blank and comment-only lines."""
    stripped = ((number, raw.strip()) for number, raw in enumerate(text.splitlines(), 1))
    return [(number, line) for number, line in stripped if line and not line.startswith("#")]


def _find(lines: list[tuple[int, str]], block: list[str]) -> tuple[int, int] | None:
    """First and last line of `block` in `lines`, if it is there."""
    size, text = len(block), [line for _, line in lines]
    for i in range(len(text) - size + 1):
        if block and text[i] == block[0] and text[i : i + size] == block:
            return lines[i][0], lines[i + size - 1][0]
    return None
