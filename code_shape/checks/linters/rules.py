"""ruff and complexipy: per-function rules (size, complexity, risky calls) and cognitive complexity."""

from __future__ import annotations

import json
import re
from fnmatch import fnmatch
from pathlib import Path

from code_shape.checks.linters.running import RATIO, ToolError, merge, pkg_dirs, reading, run
from code_shape.model import Finding, GroupResult
from code_shape.settings import Settings
from code_shape.source import symbol_at


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
# Rules without a limit: each use is counted, per function and ruff code (see COUNTED).
RUFF_RULES |= {code: ("swallowed-errors", None, None) for code in ("E722", "BLE001", "S110", "S112", "TRY203")}
RUFF_RULES |= {code: ("blanket-suppression", None, None) for code in ("PGH003", "PGH004")}
RUFF_RULES |= {"ERA001": ("commented-out-code", None, None)}
RUFF_RULES |= {code: ("print-call", None, None) for code in ("T201", "T203")}
RUFF_RULES |= {code: ("mutable-default", None, None) for code in ("B006", "B008")}
RUFF_RULES |= {code: ("wildcard-import", None, None) for code in ("F403", "F405")}
RUFF_RULES |= {
    code: ("security-risk", None, None) for code in ("S602", "S604", "S608", "S105", "S106", "S107", "S307", "S102")
}
RUFF_RULES |= {code: ("boolean-flag-args", None, None) for code in ("FBT001", "FBT002")}
# value = number of uses in that function. These three are keyed by the name used (an API, a
# global, a private member); the others by the ruff code.
NAMED = ("banned-api", "global-state", "private-access")
COUNTED = {check for check, limit, _ in RUFF_RULES.values() if limit is None}


def ruff(settings: Settings, tmp: Path) -> GroupResult:
    banned = ", ".join(
        f"{_toml_str(name)} = {{msg = {_toml_str(rule['msg'])}}}" for name, rule in settings.banned_api.items()
    )
    cmd = [
        "ruff",
        "check",
        *pkg_dirs(settings),
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
    output = run(settings, tmp, cmd)
    with reading("ruff"):
        found = [_ruff_finding(settings, item) for item in json.loads(output or "[]")]
    findings = [f for f in found if f]
    plain = [f for f in findings if f.check not in COUNTED]
    return GroupResult("ruff", plain + merge([f for f in findings if f.check in COUNTED]))


def _ruff_finding(settings: Settings, item: dict) -> Finding | None:
    path, row = Path(item["filename"]), item["location"]["row"]
    if item["code"] not in RUFF_RULES:  # e.g. invalid-syntax: the file could not be checked
        raise ToolError(f"ruff could not check {settings.rel(path)}:{row}: {item['message']}")
    check, limit, _ = RUFF_RULES[item["code"]]
    rel, where = settings.rel(path), symbol_at(path, row) or "<module>"
    if check not in COUNTED:
        match = RATIO.search(item["message"])
        value = int(match.group(1)) if match else None
        return Finding(check, rel, symbol_at(path, row), value, settings.limits[limit] if limit else None, row)
    if check == "print-call" and any(fnmatch(rel, pattern) for pattern in settings.tools.output_modules):
        return None
    if check not in NAMED:
        return Finding(check, rel, f"{item['code']} in {where}", 1, None, row, item["message"])
    api = re.search(r"`([^`]+)`", item["message"])
    name = api.group(1) if api else ""
    rule = settings.banned_api.get(name, {}) if check == "banned-api" else {}
    if any(fnmatch(rel, pattern) for pattern in rule.get("allowed", [])):
        return None
    return Finding(check, rel, f"{name} in {where}", 1, None, row, rule.get("msg", ""))


def complexipy(settings: Settings, tmp: Path) -> GroupResult:
    out = tmp / "complexipy.json"
    limit = settings.limits["cognitive"]
    run(
        settings,
        tmp,
        [
            "complexipy",
            *pkg_dirs(settings),
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
        failed_if="Failed to process",  # e.g. a syntax error; the exit code is 1 either way
    )
    items = json.loads(out.read_text()) if out.exists() else []
    result = GroupResult("complexipy")
    with reading("complexipy"):
        scores = sorted(item["complexity"] for item in items)
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
