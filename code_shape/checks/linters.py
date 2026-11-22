"""Runs the established tools and turns their output into Findings.

Limits come from [tool.shape.limits] and are passed on the command line, so
the shape rules don't depend on (or clash with) the project's normal lint setup.
Inline suppressions (`# noqa`, complexipy ignores) are ignored on purpose: the
baseline file is the one visible place to record exceptions.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import replace
from fnmatch import fnmatch
from pathlib import Path

from code_shape.model import Finding, GroupResult, Table
from code_shape.settings import Settings
from code_shape.source import module_path, symbol_at

RATIO = re.compile(r"\((\d+)\s*[>/]\s*(\d+)\)")  # "(12 > 10)" or "(17/15)"


class ToolError(Exception):
    pass


def _exe(name: str) -> str:
    found = shutil.which(name, path=str(Path(sys.executable).parent)) or shutil.which(name)
    if not found:
        raise ToolError(f"`{name}` is not installed (pip install 'code-shape-kit[tools]')")
    return found


def _run(settings: Settings, tmp: Path, cmd: list[str], ok_codes=(0, 1), cwd: Path | None = None) -> str:
    """Run a tool from a scratch folder (so caches land there, not in the project)."""
    tool = cmd[0]
    cmd = [_exe(tool), *cmd[1:], *settings.tools.extra_args.get(tool, [])]
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(settings.src),
        "COLUMNS": "10000",
        "NO_COLOR": "1",
    }
    proc = subprocess.run(cmd, cwd=cwd or tmp, env=env, capture_output=True, text=True, timeout=900, check=False)
    if proc.returncode not in ok_codes:
        raise ToolError(f"{tool} exited with {proc.returncode}: {(proc.stderr or proc.stdout)[-800:]}")
    return proc.stdout


def _pkg_dirs(settings: Settings) -> list[str]:
    return [str(p) for p in settings.package_dirs()]


def _toml_str(text: str) -> str:
    return json.dumps(text)  # a JSON string is a valid TOML basic string


# ruff code -> (check id, limit name, ruff setting)
RUFF_RULES = {
    "C901": ("function-complexity", "cyclomatic", "lint.mccabe.max-complexity"),
    "PLR0913": ("too-many-args", "args", "lint.pylint.max-args"),
    "PLR0917": ("too-many-positional", "positional_args", "lint.pylint.max-positional-args"),
    "PLR0912": ("too-many-branches", "branches", "lint.pylint.max-branches"),
    "PLR0911": ("too-many-returns", "returns", "lint.pylint.max-returns"),
    "PLR0915": ("too-many-statements", "statements", "lint.pylint.max-statements"),
    "PLW0603": ("global-state", None, None),
    "TID251": ("banned-api", None, None),
    "SLF001": ("private-access", None, None),
}
COUNTED = ("banned-api", "global-state", "private-access")  # value = number of uses in that function


def ruff(settings: Settings, tmp: Path) -> GroupResult:
    banned = ", ".join(
        f"{_toml_str(name)} = {{msg = {_toml_str(rule['msg'])}}}" for name, rule in settings.banned_api.items()
    )
    cmd = [
        "ruff",
        "check",
        *_pkg_dirs(settings),
        "--isolated",
        "--no-cache",
        "--ignore-noqa",
        "--output-format",
        "json",
        "--select",
        ",".join(RUFF_RULES),
        "--config",
        f"lint.flake8-tidy-imports.banned-api = {{{banned}}}",
    ]
    for _, limit, setting in RUFF_RULES.values():
        if limit and setting:
            cmd += ["--config", f"{setting} = {int(settings.limits[limit])}"]
    found = [_ruff_finding(settings, item) for item in json.loads(_run(settings, tmp, cmd) or "[]")]
    findings = [f for f in found if f]
    plain = [f for f in findings if f.check not in COUNTED]
    return GroupResult("ruff", plain + _merge([f for f in findings if f.check in COUNTED]))


def _ruff_finding(settings: Settings, item: dict) -> Finding | None:
    check, limit, _ = RUFF_RULES[item["code"]]
    path, row = Path(item["filename"]), item["location"]["row"]
    rel, symbol = settings.rel(path), symbol_at(path, row)
    if check in COUNTED:
        api = re.search(r"`([^`]+)`", item["message"])
        rule = settings.banned_api.get(api.group(1) if api else "", {})
        if check == "banned-api" and any(fnmatch(rel, pattern) for pattern in rule.get("allowed", [])):
            return None
        name = api.group(1) if api else ""
        return Finding(check, rel, f"{name} in {symbol or '<module>'}", 1, None, row, rule.get("msg", ""))
    match = RATIO.search(item["message"])
    value = int(match.group(1)) if match else None
    return Finding(check, rel, symbol, value, settings.limits[limit] if limit else None, row)


def _merge(findings: list[Finding]) -> list[Finding]:
    """Findings with the same key become one, with their values added up."""
    merged: dict[str, Finding] = {}
    for f in findings:
        old = merged.get(f.key)
        merged[f.key] = f if old is None else replace(old, value=(old.value or 0) + (f.value or 0))
    return list(merged.values())


def complexipy(settings: Settings, tmp: Path) -> GroupResult:
    out = tmp / "complexipy.json"
    limit = settings.limits["cognitive"]
    _run(
        settings,
        tmp,
        [
            "complexipy",
            *_pkg_dirs(settings),
            "--output-format",
            "json",
            "--output",
            str(out),
            "--cache-dir",
            str(tmp / "complexipy-cache"),
            "--no-ignore",
            "--max-complexity-allowed",
            str(int(limit)),
            "-q",
        ],
    )
    items = json.loads(out.read_text()) if out.exists() else []
    scores = sorted(item["complexity"] for item in items)
    result = GroupResult("complexipy")
    result.findings = [
        Finding(
            "cognitive-complexity",
            settings.rel(item["path"]),
            item["function_name"].replace("::", "."),
            item["complexity"],
            limit,
            item["line_start"],
        )
        for item in items
        if item["complexity"] > limit
    ]
    if scores:
        result.metrics = {
            "functions": len(scores),
            "cognitive complexity, median": scores[len(scores) // 2],
            "cognitive complexity, 90th percentile": scores[int(len(scores) * 0.9)],
            "cognitive complexity, max": scores[-1],
        }
    return result


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
    cmd = [
        "pylint",
        *_pkg_dirs(settings),
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
    output = json.loads(_run(settings, tmp, cmd, ok_codes=tuple(range(32))) or "{}")
    findings = [_pylint_finding(settings, msg) for msg in output.get("messages", [])]
    duplicates = _merge([f for f in findings if f.check == "duplicate-code"])
    result = GroupResult("pylint", [f for f in findings if f.check != "duplicate-code"] + duplicates)
    result.metrics["duplicated lines (approx.)"] = sum(f.value or 0 for f in duplicates)
    return result


def _pylint_finding(settings: Settings, msg: dict) -> Finding:
    check, limit, _ = PYLINT_CHECKS[msg["symbol"]]
    if check == "duplicate-code":  # one message per copied block; the path field is meaningless
        blocks = DUPLICATE.findall(msg["message"])
        paths = sorted({module_path(settings, module) for module, _, _ in blocks})
        length = int(blocks[0][2]) - int(blocks[0][1]) if blocks else 0
        others = " + ".join(paths[1:]) or "itself"
        return Finding(check, paths[0], f"same code as {others}", length, settings.limits[limit])
    match = RATIO.search(msg["message"])
    value = int(match.group(1)) if match else None
    return Finding(check, settings.rel(msg["path"]), msg["obj"], value, settings.limits[limit], msg["line"])


VULTURE_LINE = re.compile(r"^(.+?):(\d+): (.+?) \((\d+)% confidence")


def vulture(settings: Settings, tmp: Path) -> GroupResult:
    # Whitelist files are extra paths for vulture: the names they mention count as used.
    # Resolved from the project root here, because vulture itself runs from a scratch folder.
    whitelists = [settings.root / name for name in settings.tools.dead_code_whitelist]
    missing = [settings.rel(path) for path in whitelists if not path.is_file()]
    if missing:
        raise ToolError(f"dead_code_whitelist file not found (paths are relative to the project root): {missing}")
    cmd = [
        "vulture",
        *_pkg_dirs(settings),
        *map(str, whitelists),
        "--min-confidence",
        str(int(settings.limits["dead_code_confidence"])),
    ]
    if settings.pyproject:
        cmd += ["--config", str(settings.pyproject)]
    result = GroupResult("vulture")
    for line in _run(settings, tmp, cmd, ok_codes=(0, 1, 3)).splitlines():
        match = VULTURE_LINE.match(line)
        if not match:
            continue
        path, row, message, _ = match.groups()
        name = re.search(r"'([^']+)'", message)
        where = symbol_at(Path(path), int(row)) or "<module>"
        result.findings.append(
            Finding(
                "dead-code",
                settings.rel(path),
                f"{where}: {name.group(1) if name else message}",
                line=int(row),
                detail=message,
            )
        )
    return result


def deptry(settings: Settings, tmp: Path) -> GroupResult:
    out = tmp / "deptry.json"
    cmd = ["deptry", ".", "--json-output", str(out), "--no-ansi"]
    if settings.pyproject:
        cmd += ["--config", str(settings.pyproject)]
    _run(settings, tmp, cmd, cwd=settings.root)  # deptry's excludes are relative to the cwd; it writes nothing
    found: dict[str, Finding] = {}
    for item in json.loads(out.read_text()) if out.exists() else []:
        code, message = item["error"]["code"], item["error"]["message"]
        path = settings.rel(settings.root / item["location"]["file"])
        finding = Finding(
            "dependencies", path, f"{code} {item['module']}", line=item["location"]["line"], detail=message
        )
        found.setdefault(finding.key, finding)  # one finding per file and package
    return GroupResult("deptry", list(found.values()))


def mypy(settings: Settings, tmp: Path) -> GroupResult:
    cmd = [
        "mypy",
        *_pkg_dirs(settings),
        "--cache-dir",
        str(tmp / "mypy-cache"),
        "--output",
        "json",
        "--no-error-summary",
        "--python-executable",
        sys.executable,
    ]
    if settings.pyproject:
        cmd += ["--config-file", str(settings.pyproject)]
    errors = []
    for line in _run(settings, tmp, cmd).splitlines():
        if line.startswith("{"):
            item = json.loads(line)
            if item.get("severity") == "error":
                errors.append(item)
    per_file = Counter(settings.rel(tmp / e["file"]) for e in errors)  # `/` keeps absolute paths as they are
    result = GroupResult("mypy")
    result.findings = [Finding("type-errors", path, value=n) for path, n in per_file.items()]
    result.metrics = {"type errors": len(errors), "files with type errors": len(per_file)}
    codes = Counter(e.get("code") or "other" for e in errors)
    if codes:
        rows = [list(c) for c in codes.most_common(8)]
        result.tables.append(Table("Type errors by kind", ["mypy code", "count"], rows))
    return result


def import_linter(settings: Settings, tmp: Path) -> GroupResult:
    if not settings.contracts:
        return GroupResult("import-linter", skipped="no import-linter contracts (see templates/importlinter.toml)")
    output = _run(settings, tmp, ["lint-imports", str(settings.contracts), "--no-cache", "--no-logo"])
    kept = [line[:-5] for line in output.splitlines() if line.endswith(" KEPT")]
    broken = [line[:-7] for line in output.splitlines() if line.endswith(" BROKEN")]
    if not kept and not broken:  # config error, e.g. a contract names a module that no longer exists
        raise ToolError(
            "lint-imports could not check the contracts (run `lint-imports` to see why, e.g. a "
            f"contract names a module that no longer exists). Output: {output.strip()[-500:]}"
        )
    report = output.split("Broken contracts", 1)[-1]
    lines = [line.strip() for line in report.splitlines() if line.strip() and not set(line.strip()) <= {"-"}]
    result = GroupResult("import-linter")
    for name in broken:  # the offending imports are the "- a -> b (l.12)" lines under the contract's name
        section = report.split(name, 1)[-1].split("\n\n\n", 1)[0]
        offenders = [line.strip()[2:] for line in section.splitlines() if line.strip().startswith("- ")]
        detail = "broken by: " + "; ".join(offenders[:5]) if offenders else ""
        result.findings.append(Finding("import-contracts", settings.rel(settings.contracts), name, detail=detail))
    if broken:
        result.tables.append(Table("Broken architecture contracts", ["lint-imports output"], [[x] for x in lines[:40]]))
    result.metrics = {"architecture contracts kept": len(kept), "architecture contracts broken": len(broken)}
    return result
