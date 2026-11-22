"""Reads [tool.shape] from pyproject.toml (or a separate TOML file) and fills in defaults.

The defaults below are the kit's recommended limits; templates/shape.toml
explains why each number was chosen.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

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

DEFAULT_BANNED_API = {
    "os.environ": "Read settings through the config module instead of the environment.",
    "os.getenv": "Read settings through the config module instead of the environment.",
    "os.putenv": "Read settings through the config module instead of the environment.",
}

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
]


@dataclass
class Settings:
    root: Path
    packages: list[str]
    src: Path
    tests: Path
    limits: dict[str, float]
    gates: list[str]
    banned_api: dict[str, dict]
    skip: list[str]
    exclude: list[str]
    concepts: dict[str, list[str] | dict]  # name -> terms, or {terms, home}
    config_file: Path
    extra_args: dict[str, list[str]] = field(default_factory=dict)

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


def load(root: Path, config: Path | None = None) -> Settings:
    root = root.resolve()
    config_file = config or root / "pyproject.toml"
    data = tomllib.loads(config_file.read_text(encoding="utf-8")) if config_file.exists() else {}
    shape = data.get("tool", {}).get("shape", {})
    src = root / shape.get("src", "src" if (root / "src").is_dir() else ".")
    packages = shape.get("packages") or [_guess_package(src)]
    banned = {
        name: {"msg": msg, "allowed": shape.get("config_modules", [])} for name, msg in DEFAULT_BANNED_API.items()
    }
    for name, rule in shape.get("banned_api", {}).items():
        banned[name] = rule if isinstance(rule, dict) else {"msg": rule, "allowed": []}
    return Settings(
        root=root,
        packages=packages,
        src=src,
        tests=root / shape.get("tests", "tests"),
        limits={**DEFAULT_LIMITS, **shape.get("limits", {})},
        gates=shape.get("gates", DEFAULT_GATES),
        banned_api=banned,
        skip=shape.get("skip", []),
        exclude=shape.get("exclude", []),
        concepts=shape.get("concepts", {}),
        config_file=config_file,
        extra_args=shape.get("extra_args", {}),
    )


def _guess_package(src: Path) -> str:
    found = sorted(p.parent.name for p in src.glob("*/__init__.py") if p.parent.name != "tests")
    if found:
        return found[0]
    raise SystemExit('code-shape: set [tool.shape] packages = ["yourpackage"] in pyproject.toml')
