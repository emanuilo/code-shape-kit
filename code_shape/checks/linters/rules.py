"""ruff and complexipy: per-function rules (size, complexity, risky calls) and cognitive complexity."""

from __future__ import annotations

import json
import re
from fnmatch import fnmatch
from pathlib import Path

from code_shape.checks.linters.running import RATIO, ToolError, merge, pkg_dirs, reading, run
from code_shape.model import Finding, GroupResult, Table
from code_shape.settings import ConfigError, Settings
from code_shape.source import definitions, excluded, symbol_at


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
# The swallowed-errors rules that mean "catches every error": a bare except, `except Exception`,
# and such an except that only passes or continues (S110/S112 only fire for those). In a function
# listed in [tool.shape] error_boundaries they are accepted. TRY203 (an except that only re-raises)
# is not one: it catches nothing for good, it is a useless clause, so it still counts there.
CATCH_ALL = ("E722", "BLE001", "S110", "S112")
BOUNDARIES = "Error boundaries (reviewed catch-alls)"


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
        "--config",  # so `except Exception: logger.exception(...)` passes swallowed-errors for these loggers too
        f"lint.logger-objects = {json.dumps(settings.tools.logger_objects)}",  # a JSON list of strings is valid TOML
    ]
    for _, limit, setting in RUFF_RULES.values():
        if limit and setting:
            cmd += ["--config", f"{setting} = {int(settings.limits[limit])}"]
    output = run(settings, tmp, cmd)
    with reading("ruff"):
        found = [_ruff_finding(settings, item) for item in json.loads(output or "[]")]
    findings = [f for f in found if f]
    findings, boundaries = _error_boundaries(settings, findings)
    plain = [f for f in findings if f.check not in COUNTED]
    return GroupResult("ruff", plain + merge([f for f in findings if f.check in COUNTED]), tables=boundaries)


def _error_boundaries(settings: Settings, findings: list[Finding]) -> tuple[list[Finding], list[Table]]:
    """Drop the catch-alls of the functions listed in [tool.shape] error_boundaries; list what was accepted.

    An entry that names no function, or whose function no longer catches everything, is a config
    error: a stale exception must not stay in the config, ready to accept the next catch-all.
    """
    listed = settings.tools.error_boundaries
    if not listed:
        return findings, []
    accepted = dict.fromkeys(listed, 0)
    kept = []
    for f in findings:
        code, _, where = f.symbol.partition(" in ")
        at = f"{f.path}:{where}"
        if f.check == "swallowed-errors" and code in CATCH_ALL and at in accepted:
            accepted[at] += 1
        else:
            kept.append(f)
    problems = [problem for at, count in accepted.items() if (problem := _boundary_problem(settings, at, count))]
    if problems:
        raise ConfigError("code-shape: bad [tool.shape] config: " + "; ".join(problems))
    rows = [[at, listed[at], count] for at, count in sorted(accepted.items())]
    note = (
        "Functions allowed to catch every error ([tool.shape] error_boundaries), with the reason a human "
        "approved. Every other finding in them still counts."
    )
    return kept, [Table(BOUNDARIES, ["function", "reason", "catch-alls accepted"], rows, note)]


def _boundary_problem(settings: Settings, at: str, accepted: int) -> str:
    file, _, name = at.partition(":")
    path = settings.root / file
    checked = any(path.resolve().is_relative_to(pkg.resolve()) for pkg in settings.package_dirs())
    if not checked or excluded(settings, path):
        return f"error_boundaries `{at}`: `{file}` is not in the checked packages (or it is excluded)"
    found = [d for d in definitions(path) if d.name == name]
    if not found:
        return f"error_boundaries `{at}`: no function `{name}` in `{file}`"
    if all(d.is_class for d in found):
        return f"error_boundaries `{at}`: `{name}` is a class; list the function or method that catches"
    if not accepted:
        return (
            f"error_boundaries `{at}`: the function no longer catches every error (no bare `except:` or "
            "`except Exception` left in it); remove the entry"
        )
    return ""


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
