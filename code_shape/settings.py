"""Reads [tool.shape] from pyproject.toml (or a separate TOML file) and fills in defaults.

The defaults below are the kit's recommended limits; templates/shape.toml
explains why each number was chosen.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from code_shape.model import CATALOG

DEFAULT_LIMITS = {
    "file_lines": 500,
    "class_lines": 300,
    "package_files": 12,
    "package_lines": 4000,
    "package_depth": 4,
    "cyclomatic": 10,
    "cognitive": 15,
    "args": 6,
    "positional_args": 5,
    "branches": 12,
    "returns": 6,
    "statements": 50,
    "nesting": 4,
    "locals": 15,
    "bool_expressions": 5,
    "class_attributes": 12,
    "public_methods": 20,
    "duplicate_lines": 10,
    "fan_out": 12,
    "dead_code_confidence": 60,
    "concept_files": 5,
    "concept_areas": 3,
    "coupling_percent": 50,
    "coupling_min_shared": 3,
    "max_changeset_files": 30,
    "history_days": 365,
}
# Limits where a lower number lets more through: fewer commits are read, so fewer files look
# coupled. For every other limit a higher number is looser (e.g. dead_code_confidence: 90 reports
# less than 60; duplicate_lines: only longer copies count).
LOWER_IS_LOOSER = {"max_changeset_files", "history_days"}

DEFAULT_BANNED_API = {
    "os.environ": "Read settings through the config module instead of the environment.",
    "os.getenv": "Read settings through the config module instead of the environment.",
    "os.putenv": "Read settings through the config module instead of the environment.",
}

DEFAULT_BASELINE = ".code-shape-baseline.json"  # relative to the project root

# The modules that may print: a command line's output is its job; anywhere else a print is
# leftover debugging, or output that belongs in the entry point (or a logger).
DEFAULT_OUTPUT_MODULES = ["*/cli.py", "*/__main__.py"]

# Loggers ruff treats like `logging`'s, so `except Exception: logger.exception(...)` passes
# swallowed-errors (the traceback is kept). [tool.shape] logger_objects adds to these.
DEFAULT_LOGGER_OBJECTS = ["loguru.logger"]

# Every key [tool.shape] may have.
KNOWN_KEYS = {"packages", "src", "tests", "config_modules", "gates", "skip", "exclude", "baseline"}
KNOWN_KEYS |= {"dead_code_whitelist", "limits", "banned_api", "concepts", "extra_args", "output_modules"}
KNOWN_KEYS |= {"logger_objects"}

# Checks that fail ENFORCE mode by default. Everything else is a tracked metric.
DEFAULT_GATES = [
    "file-lines",
    "class-lines",
    "package-files",
    "package-lines",
    "package-depth",
    "function-complexity",
    "cognitive-complexity",
    "too-many-args",
    "too-many-positional",
    "too-many-branches",
    "too-many-returns",
    "too-many-statements",
    "nesting",
    "too-many-locals",
    "bool-expressions",
    "class-attributes",
    "public-methods",
    "global-state",
    "banned-api",
    "private-access",
    "duplicate-code",
    "import-contracts",
    "import-cycles",
    "fan-out",
    "dead-code",
    "dependencies",
    "type-errors",
    "inline-suppression",
    "swallowed-errors",
    "blanket-suppression",
    "commented-out-code",
    "print-call",
    "mutable-default",
    "wildcard-import",
    "security-risk",
    "boolean-flag-args",
]


@dataclass
class ToolOptions:
    """Per-tool settings that are not limits."""

    extra_args: dict[str, list[str]] = field(default_factory=dict)  # tool -> extra command-line arguments
    dead_code_whitelist: list[str] = field(default_factory=list)  # vulture whitelist files, relative to root
    output_modules: list[str] = field(default_factory=lambda: list(DEFAULT_OUTPUT_MODULES))  # may print
    logger_objects: list[str] = field(default_factory=lambda: list(DEFAULT_LOGGER_OBJECTS))  # e.g. "myapp.log.logger"


@dataclass
class GateOptions:
    """What `code-shape check` enforces, and the baseline file it compares against."""

    checks: list[str]  # check ids that fail the build
    baseline: Path  # absolute; [tool.shape] baseline is relative to the project root


@dataclass
class Settings:
    root: Path
    packages: list[str]
    src: Path
    tests: Path
    limits: dict[str, float]
    gate: GateOptions
    banned_api: dict[str, dict]
    skip: list[str]
    exclude: list[str]
    concepts: dict[str, dict]  # name -> {terms: [...], home: "path or ''"}
    config_file: Path
    tools: ToolOptions = field(default_factory=ToolOptions)

    @property
    def pyproject(self) -> Path | None:
        path = self.root / "pyproject.toml"
        return path if path.exists() else None

    @property
    def contracts(self) -> Path | None:
        """The file holding [tool.importlinter] contracts, if any."""
        for path in (self.config_file, self.pyproject):
            if path and path.exists() and "importlinter" in tomllib.loads(path.read_text()).get("tool", {}):
                return path.resolve()
        return self.root / ".importlinter" if (self.root / ".importlinter").exists() else None

    def package_dirs(self) -> list[Path]:
        return [self.src / name.replace(".", "/") for name in self.packages]

    def rel(self, path: str | Path) -> str:
        """Path relative to the project root, with forward slashes."""
        p = Path(path)
        if p.is_absolute():
            try:
                p = p.resolve().relative_to(self.root)
            except ValueError:
                return p.as_posix()
        return p.as_posix()


class ConfigError(SystemExit):
    """The configuration can't be used; stops the command with this message."""


def load(root: Path, config: Path | None = None) -> Settings:
    root = root.resolve()
    if config and not config.is_file():
        raise ConfigError(f"code-shape: config file not found: {config}")
    config_file = config or root / "pyproject.toml"
    text = config_file.read_text(encoding="utf-8") if config_file.exists() else ""
    settings = parse(root, config_file, text)
    missing = [
        f"concept `{name}`: home `{spec['home']}` does not exist (a file or folder, relative to the project root)"
        for name, spec in settings.concepts.items()
        if spec["home"] and not (root / spec["home"]).exists()
    ]
    if missing:
        raise ConfigError("code-shape: bad [tool.shape] config: " + "; ".join(missing))
    return settings


def parse(root: Path, config_file: Path, text: str) -> Settings:
    """Settings from the text of a config file (e.g. as it was at another git commit)."""
    shape = tomllib.loads(text).get("tool", {}).get("shape", {})
    _validate(shape)
    src = root / shape.get("src", "src" if (root / "src").is_dir() else ".")
    packages = shape.get("packages") or [_guess_package(src)]
    banned = {
        name: {"msg": msg, "allowed": shape.get("config_modules", [])} for name, msg in DEFAULT_BANNED_API.items()
    }
    for name, rule in shape.get("banned_api", {}).items():
        rule = rule if isinstance(rule, dict) else {"msg": rule}
        banned[name] = {
            "msg": rule.get("msg", f"`{name}` is restricted."),
            "allowed": _as_list(rule.get("allowed", [])),
        }
    return Settings(
        root=root,
        packages=packages,
        src=src,
        tests=root / shape.get("tests", "tests"),
        limits={**DEFAULT_LIMITS, **shape.get("limits", {})},
        gate=GateOptions(
            checks=shape.get("gates", DEFAULT_GATES),
            baseline=root / shape.get("baseline", DEFAULT_BASELINE),
        ),
        banned_api=banned,
        skip=shape.get("skip", []),
        exclude=shape.get("exclude", []),
        concepts={name: _concept(spec) for name, spec in shape.get("concepts", {}).items()},
        config_file=config_file,
        tools=ToolOptions(
            extra_args=shape.get("extra_args", {}),
            dead_code_whitelist=_as_list(shape.get("dead_code_whitelist", [])),
            output_modules=_as_list(shape.get("output_modules", DEFAULT_OUTPUT_MODULES)),
            logger_objects=list(dict.fromkeys(DEFAULT_LOGGER_OBJECTS + _as_list(shape.get("logger_objects", [])))),
        ),
    )


def _validate(shape: dict) -> None:
    """A typo in [tool.shape] must not quietly switch a rule off."""
    problems = [f"unknown setting `{key}`" for key in sorted(set(shape) - KNOWN_KEYS)]
    problems += [f"unknown limit `{key}`" for key in sorted(set(shape.get("limits", {})) - set(DEFAULT_LIMITS))]
    problems += [f"unknown check `{check}` in gates" for check in shape.get("gates", []) if check not in CATALOG]
    if not _dotted_names(shape.get("logger_objects", [])):
        problems.append('`logger_objects` must list import paths of logger objects, e.g. "myapp.log.logger"')
    for name, spec in shape.get("concepts", {}).items():
        for term in _concept(spec)["terms"]:
            try:
                re.compile(term)
            except re.error as exc:
                problems.append(f"concept `{name}`: `{term}` is not a valid regex ({exc})")
    if problems:
        raise ConfigError("code-shape: bad [tool.shape] config: " + "; ".join(problems))


def _concept(spec: str | list[str] | dict) -> dict:
    spec = spec if isinstance(spec, dict) else {"terms": spec}
    return {"terms": _as_list(spec.get("terms", [])), "home": spec.get("home", "")}


def _dotted_names(value: object) -> bool:
    """A string or list of strings, each an import path (`module.name`)."""
    names = [value] if isinstance(value, str) else value
    return isinstance(names, list) and all(isinstance(name, str) and "." in name.strip(".") for name in names)


def _as_list(value: str | list[str]) -> list[str]:
    return [value] if isinstance(value, str) else list(value)


def _guess_package(src: Path) -> str:
    found = sorted(p.parent.name for p in src.glob("*/__init__.py") if p.parent.name != "tests")
    if len(found) == 1:
        return found[0]
    # With several candidates, picking one would quietly leave the others unchecked.
    which = f" (found {', '.join(found)})" if found else ""
    raise ConfigError(f'code-shape: set [tool.shape] packages = ["yourpackage"] in pyproject.toml{which}')
