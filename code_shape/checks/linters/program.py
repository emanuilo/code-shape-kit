"""vulture, deptry and mypy: checks over the whole program (dead code, dependencies, types)."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, time
from pathlib import Path

from code_shape.checks.linters.running import ToolError, pkg_dirs, reading, run
from code_shape.model import Finding, GroupResult, Table
from code_shape.settings import Settings
from code_shape.source import symbol_at

# [tool.mypy] settings (also in [[tool.mypy.overrides]]) that take code out of the type check.
# The kit's mypy run drops them, as it runs ruff and pylint without the project's lint config;
# the rest (plugins, python_version, stricter flags, ignore_missing_imports) still applies.
MYPY_WEAKENING = (
    "ignore_errors",
    "disable_error_code",
    "follow_imports",
    "follow_imports_for_stubs",
    "check_untyped_defs",
    "warn_unused_ignores",
    "exclude",
)
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
        *pkg_dirs(settings),
        *map(str, whitelists),
        "--min-confidence",
        str(int(settings.limits["dead_code_confidence"])),
    ]
    if settings.pyproject:
        cmd += ["--config", str(settings.pyproject)]
    result = GroupResult("vulture")
    # vulture exits 3 when it found dead code, 1 when it could not read a file (e.g. a syntax error)
    for line in run(settings, tmp, cmd, ok_codes=(0, 3)).splitlines():
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
    # deptry finds the project's own packages only directly in ".", so with the src/ layout it
    # took them for undeclared dependencies. The flag replaces [tool.deptry] known_first_party,
    # so that list is passed on too.
    for name in dict.fromkeys([*_known_first_party(settings), *(p.split(".")[0] for p in settings.packages)]):
        cmd += ["--known-first-party", name]
    run(settings, tmp, cmd, cwd=settings.root)  # deptry's excludes are relative to the cwd; it writes nothing
    found: dict[str, Finding] = {}
    with reading("deptry"):
        for item in json.loads(out.read_text()) if out.exists() else []:
            code, message = item["error"]["code"], item["error"]["message"]
            path = settings.rel(settings.root / item["location"]["file"])
            finding = Finding(
                "dependencies", path, f"{code} {item['module']}", line=item["location"]["line"], detail=message
            )
            found.setdefault(finding.key, finding)  # one finding per file and package
    return GroupResult("deptry", list(found.values()))


def _known_first_party(settings: Settings) -> list[str]:
    if not settings.pyproject:
        return []
    deptry_config = tomllib.loads(settings.pyproject.read_text()).get("tool", {}).get("deptry", {})
    return list(deptry_config.get("known_first_party", []))


def mypy(settings: Settings, tmp: Path) -> GroupResult:
    cmd = [
        "mypy",
        *pkg_dirs(settings),
        "--cache-dir",
        str(tmp / "mypy-cache"),
        "--output",
        "json",
        "--no-error-summary",
        "--python-executable",
        sys.executable,
        # Dropping a function's annotations must not take it out of the type check, and a
        # `# type: ignore` must name the error it hides and still be needed.
        "--check-untyped-defs",
        "--warn-unused-ignores",
        "--enable-error-code",
        "ignore-without-code",
    ]
    output = run(settings, tmp, [*cmd, "--config-file", str(_mypy_config(settings, tmp))])
    result = GroupResult("mypy")
    with reading("mypy"):
        items = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
        errors = [item for item in items if item.get("severity") == "error"]
        # One finding per function and kind of error, counted: swapping one error for another kind, or
        # fixing one function while breaking another, is new.
        result.findings = _mypy_findings(settings, tmp, errors)
    files = {f.path for f in result.findings}
    result.metrics = {"type errors": len(errors), "files with type errors": len(files)}
    codes = Counter(e.get("code") or "other" for e in errors)
    if codes:
        rows = [list(c) for c in codes.most_common(8)]
        result.tables.append(Table("Type errors by kind", ["mypy code", "count"], rows))
    return result


def _mypy_findings(settings: Settings, tmp: Path, errors: list[dict]) -> list[Finding]:
    """One finding per function and error code. Its text lists every error, as the baseline only
    holds their number: when there is one more, the agent must see the new one too."""
    found: dict[str, tuple[Finding, list[str]]] = {}
    for error in errors:
        path = tmp / error["file"]  # `/` keeps absolute paths as they are
        symbol = f"{symbol_at(path, error['line']) or '<module>'} [{error.get('code') or 'other'}]"
        finding = Finding("type-errors", settings.rel(path), symbol, 0, line=error["line"])
        found.setdefault(finding.key, (finding, []))[1].append(f"line {error['line']}: {error['message']}")
    shown = 5
    return [
        replace(
            finding,
            value=len(texts),
            detail="; ".join(texts[:shown]) + (f" (+{len(texts) - shown} more)" if len(texts) > shown else ""),
        )
        for finding, texts in found.values()
    ]


def _mypy_config(settings: Settings, tmp: Path) -> Path:
    """The project's [tool.mypy] without MYPY_WEAKENING, written to the scratch folder, with the
    other [tool.*] tables (mypy plugins read their settings there). Always given to mypy, so it
    never falls back to a mypy.ini or a user config instead."""
    pyproject = settings.pyproject
    tools = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("tool", {}) if pyproject else {}
    config = {key: value for key, value in tools.get("mypy", {}).items() if key not in MYPY_WEAKENING}
    if "overrides" in config:
        config["overrides"] = [{k: v for k, v in o.items() if k not in MYPY_WEAKENING} for o in config["overrides"]]
    if "plugins" in config:
        config["plugins"] = [_plugin_path(plugin, settings.root) for plugin in _names(config["plugins"])]
    tools = {**tools, "mypy": _in_project(config, str(settings.root))}
    path = tmp / "mypy-config.toml"
    path.write_text("[tool]\n" + "".join(f"{json.dumps(k)} = {_toml(v)}\n" for k, v in tools.items()), "utf-8")
    return path


def _in_project(value: object, root: str) -> object:
    """`$MYPY_CONFIG_FILE_DIR` in a setting is the project root, not the scratch folder."""
    if isinstance(value, dict):
        return {key: _in_project(item, root) for key, item in value.items()}
    if isinstance(value, list):
        return [_in_project(item, root) for item in value]
    if isinstance(value, str):
        return value.replace("${MYPY_CONFIG_FILE_DIR}", root).replace("$MYPY_CONFIG_FILE_DIR", root)
    return value


def _names(value: str | list[str]) -> list[str]:
    return [name.strip() for name in value.split(",") if name.strip()] if isinstance(value, str) else value


def _plugin_path(plugin: str, root: Path) -> str:
    """A plugin file ("plugins/check.py", or "plugins/check.py:entry") is relative to the project root."""
    path, colon, entry = plugin.rpartition(":") if ":" in Path(plugin).name else (plugin, "", "")
    return str(root / path) + colon + entry if path.endswith(".py") and not Path(path).is_absolute() else plugin


def _toml(value: object) -> str:
    """`value` as a TOML value; tables become inline tables (enough for a file only mypy reads)."""
    if isinstance(value, dict):
        return "{" + ", ".join(f"{json.dumps(str(k))} = {_toml(v)}" for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(map(_toml, value)) + "]"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    return json.dumps(value) if isinstance(value, str) else repr(value)
