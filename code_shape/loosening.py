"""Rules loosened since a base git ref (`--base REF`): a warning for a human, never a failure.

The lazy way to get a red gate green is to change the rules instead of the code: record
the problem in the baseline, raise a limit, drop a gate, skip a check, widen an allowance,
weaken an import-linter contract, grow the dead-code whitelist, or add a suppression
comment. Each is a line in the diff; this lists them in one place, so a human approves them.
"""

from __future__ import annotations

import os
import subprocess
import tomllib
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from code_shape import baseline as bl
from code_shape.checks.suppressions import markers
from code_shape.model import fmt
from code_shape.settings import LOWER_IS_LOOSER, ConfigError, Settings, parse
from code_shape.source import python_files

# Contract lists where a new entry allows more; in every other list a removed entry allows more.
ALLOWANCES = ("ignore_imports", "allowed_importers", "exhaustive_ignores")
# Lists in the tools' own config (passed on to them) where a new entry lets more through.
TOOL_ALLOWANCES = {
    "vulture": ("ignore_names", "ignore_decorators", "exclude"),
    "deptry": ("ignore", "exclude", "extend_exclude", "known_first_party"),
}


@dataclass
class Loosened:
    ref: str
    changes: list[str] = field(default_factory=list)
    note: str = ""  # why the rules could not be compared

    def text(self) -> str:
        if self.note:
            return f"code-shape: rules not compared with {self.ref}: {self.note}\n"
        if not self.changes:
            return f"code-shape: no rules loosened since {self.ref}.\n"
        head = f"RULES LOOSENED since {self.ref} - needs human approval (a warning; it does not fail the check):"
        return head + "\n" + "".join(f"  - {change}\n" for change in self.changes)

    def markdown(self) -> str:
        if self.note:
            return f"_Rules not compared with `{self.ref}`: {self.note}_\n"
        if not self.changes:
            return f"_No rules loosened since `{self.ref}`._\n"
        lines = [
            f"## Rules loosened since `{self.ref}` - needs human approval",
            "",
            "These changes make the shape gates easier to pass. They don't fail the build, but a human "
            "should approve each one: the usual fix is to change the code, not the rules.",
            "",
        ]
        return "\n".join(lines + [f"- {change}" for change in self.changes]) + "\n"


def since(settings: Settings, ref: str, baseline: Path | None) -> Loosened:
    """What got looser between `ref` and the working tree. `baseline`: the --baseline file, if given."""
    try:
        return _compare(settings, ref, baseline)
    except (subprocess.SubprocessError, OSError) as exc:  # e.g. git is not installed
        return Loosened(ref, note=f"git failed: {exc}")
    except (ConfigError, ValueError, KeyError) as exc:  # bad TOML or JSON is a ValueError
        return Loosened(ref, note=f"its config or baseline could not be read: {exc}")


def _compare(settings: Settings, ref: str, baseline: Path | None) -> Loosened:
    git = _Git(settings.root, ref)
    problem = git.problem()
    if problem:
        return Loosened(ref, note=problem)
    base = parse(settings.root, settings.config_file, git.show(settings.config_file) or "")
    old_entries = bl.parse(git.show(baseline or base.gate.baseline) or '{"entries": {}}')
    new_entries = bl.load(baseline or settings.gate.baseline)
    changes = _baseline(old_entries, new_entries) + _settings(base, settings)
    changes += _contracts(git, settings) + _tool_configs(git, settings) + _whitelists(git, settings)
    changes += _suppressions(git, settings)
    return Loosened(ref, changes)


class _Git:
    def __init__(self, root: Path, ref: str) -> None:
        self.root, self.ref = root, ref

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True, check=False)

    def problem(self) -> str:
        if self.run("rev-parse", "--git-dir").returncode != 0:
            return "this folder is not in a git repository"
        if self.run("rev-parse", "--verify", "--quiet", f"{self.ref}^{{commit}}").returncode != 0:
            return f"git ref `{self.ref}` not found (in CI, fetch it first, e.g. actions/checkout with fetch-depth: 0)"
        return ""

    def show(self, path: Path) -> str | None:
        """The file as it was at the ref, or None if it wasn't there."""
        proc = self.run("show", f"{self.ref}:./{Path(os.path.relpath(path, self.root)).as_posix()}")
        return proc.stdout if proc.returncode == 0 else None

    def changed(self) -> set[str]:
        """Files (relative to the project root) that differ from the ref, including untracked ones."""
        diff = self.run("diff", "--name-only", "--relative", self.ref).stdout.splitlines()
        return set(diff) | set(self.run("ls-files", "--others", "--exclude-standard").stdout.splitlines())


def _baseline(old: bl.Entries, new: bl.Entries) -> list[str]:
    found = []
    for group, entries in sorted(new.items()):
        known = old.get(group, {})
        for key, value in sorted(entries.items()):
            was = known.get(key)
            if key not in known:
                found.append(f"baseline: new entry `{key}`" + (f" ({fmt(value)})" if value is not None else ""))
            elif value is not None and was is not None and value > was:
                found.append(f"baseline: `{key}` raised from {fmt(was)} to {fmt(value)}")
    return found


def _settings(old: Settings, new: Settings) -> list[str]:
    found = [_limit(name, old.limits[name], value) for name, value in new.limits.items()]
    found = [change for change in found if change]
    found += _removed("[tool.shape] gates", old.gate.checks, new.gate.checks)
    found += _removed("[tool.shape] packages", old.packages, new.packages)
    found += _added("[tool.shape] skip", old.skip, new.skip)
    found += _added("[tool.shape] exclude", old.exclude, new.exclude)
    found += _added("[tool.shape] dead_code_whitelist", old.tools.dead_code_whitelist, new.tools.dead_code_whitelist)
    found += _added("[tool.shape] output_modules (may print)", old.tools.output_modules, new.tools.output_modules)
    found += _added(
        "[tool.shape] logger_objects (their logger.exception passes swallowed-errors)",
        old.tools.logger_objects,
        new.tools.logger_objects,
    )
    found += _added(
        "[tool.shape] error_boundaries (their catch-alls pass swallowed-errors)",
        list(old.tools.error_boundaries),
        list(new.tools.error_boundaries),
    )
    for tool, args in sorted(new.tools.extra_args.items()):
        found += _added(f"[tool.shape.extra_args] {tool}", old.tools.extra_args.get(tool, []), args)
    widened: dict[str, list[str]] = {}  # pattern -> the restricted APIs it may now use
    for name, rule in old.banned_api.items():
        if name not in new.banned_api:
            found.append(f"`{name}` is no longer restricted ([tool.shape.banned_api])")
            continue
        for pattern in new.banned_api[name]["allowed"]:
            if pattern not in rule["allowed"]:
                widened.setdefault(pattern, []).append(name)
    found += [
        f"`{pattern}` may now use {', '.join(names)} ([tool.shape] config_modules / banned_api allowed)"
        for pattern, names in sorted(widened.items())
    ]
    return found


def _limit(name: str, old: float, new: float) -> str:
    """The change, if the limit now lets more through ("" if not)."""
    lower_is_looser = name in LOWER_IS_LOOSER
    if new == old or (new < old) != lower_is_looser:
        return ""
    return f"[tool.shape.limits] `{name}` {'lowered' if lower_is_looser else 'raised'} from {fmt(old)} to {fmt(new)}"


def _added(what: str, old: list[str], new: list[str]) -> list[str]:
    more = [item for item in new if item not in old]
    return [f"{what}: added {', '.join(f'`{item}`' for item in more)}"] if more else []


def _contracts(git: _Git, settings: Settings) -> list[str]:
    old = {_contract_id(c): c for c in _importlinter(git.show, settings).get("contracts", [])}
    new = {_contract_id(c): c for c in _importlinter(_read, settings).get("contracts", [])}
    found = [f"import-linter contract `{name}` removed" for name in old if name not in new]
    for name, contract in old.items():
        if name in new:
            found += [f"import-linter contract `{name}`: {change}" for change in _weaker(contract, new[name])]
    return found


def _weaker(old: dict, new: dict) -> list[str]:
    found = []
    if old.get("type") != new.get("type"):
        found.append(f"type changed from `{old.get('type')}` to `{new.get('type')}`")
    for key in sorted(set(old) | set(new)):
        was, now = old.get(key, []), new.get(key, [])
        if key == "layers" and isinstance(was, list) and isinstance(now, list):
            found += _layers(was, now)
        elif isinstance(was, list) and isinstance(now, list):
            found += _added(key, was, now) if key in ALLOWANCES else _removed(key, was, now)
    if old.get("exhaustive") and not new.get("exhaustive"):
        found.append("exhaustive switched off")
    if new.get("allow_indirect_imports") and not old.get("allow_indirect_imports"):
        found.append("allow_indirect_imports switched on")
    alerting = [c.get("unmatched_ignore_imports_alerting", "error") for c in (old, new)]
    if alerting[0] != alerting[1]:
        found.append(f"unmatched_ignore_imports_alerting changed from `{alerting[0]}` to `{alerting[1]}`")
    return found


def _layers(old: list, new: list) -> list[str]:
    """What a layers contract allows now that it didn't: a module dropped, or an import it forbade.

    Compared module by module, so a layer that gains a module (`a | b` -> `a | b | c`) is not
    reported; moving a layer up, merging two layers or splitting `a | b` into two layers is.
    """
    before, after = _parse_layers(old), _parse_layers(new)
    kept = {m for modules, _ in after for m in modules}
    gone = sorted({m for modules, _ in before for m in modules} - kept)
    found = [f"layers: no longer lists {', '.join(f'`{m}`' for m in gone)}"] if gone else []
    allowed = sorted((a, b) for a, b in _forbidden(before) - _forbidden(after) if a in kept and b in kept)
    if allowed:
        shown = ", ".join(f"`{a}` may now import `{b}`" for a, b in allowed[:10])
        found.append(f"layers: {shown}" + (f" (+{len(allowed) - 10} more)" if len(allowed) > 10 else ""))
    return found


def _parse_layers(layers: list) -> list[tuple[list[str], bool]]:
    """Each layer's modules, top layer first, and whether they are independent (`a | b`, not `a : b`)."""
    return [
        ([m.strip().strip("()").strip() for m in layer.replace(":", "|").split("|")], ":" not in layer)
        for layer in map(str, layers)
    ]


def _forbidden(layers: list[tuple[list[str], bool]]) -> set[tuple[str, str]]:
    """The (importer, imported) pairs a layers contract forbids: a lower layer importing a higher
    one, and modules of an independent layer importing each other."""
    pairs: set[tuple[str, str]] = set()
    for i, (modules, independent) in enumerate(layers):
        if independent:
            pairs |= {(a, b) for a in modules for b in modules if a != b}
        pairs |= {(low, high) for lower, _ in layers[i + 1 :] for low in lower for high in modules}
    return pairs


def _removed(what: str, old: list, new: list) -> list[str]:
    gone = [item for item in old if item not in new]
    return [f"{what}: no longer lists {', '.join(f'`{item}`' for item in gone)}"] if gone else []


def _contract_id(contract: dict) -> str:
    return contract.get("name") or contract.get("id", "")


def _importlinter(read: Callable[[Path], str | None], settings: Settings) -> dict:
    """[tool.importlinter] from the config file or pyproject.toml (TOML only), as `read` returns them."""
    for path in dict.fromkeys((settings.config_file, settings.root / "pyproject.toml")):
        section = _section(read(path), "importlinter")
        if section:
            return section
    return {}


def _section(text: str | None, tool: str) -> dict:
    return tomllib.loads(text).get("tool", {}).get(tool, {}) if text else {}


def _read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _tool_configs(git: _Git, settings: Settings) -> list[str]:
    """Exceptions in the tools' own sections of pyproject.toml, which the kit passes on to them."""
    pyproject = settings.root / "pyproject.toml"
    old, new = (tomllib.loads(text or "").get("tool", {}) for text in (git.show(pyproject), _read(pyproject)))
    found = []
    for tool, keys in TOOL_ALLOWANCES.items():
        was, now = old.get(tool, {}), new.get(tool, {})
        found += [
            change for key in keys for change in _added(f"[tool.{tool}] {key}", was.get(key, []), now.get(key, []))
        ]
    was, now = (config.get("deptry", {}).get("per_rule_ignores", {}) for config in (old, new))
    for code, packages in sorted(now.items()):
        found += _added(f"[tool.deptry] per_rule_ignores {code}", was.get(code, []), packages)
    return found + _mypy(old.get("mypy", {}), new.get("mypy", {}))


def _mypy(old: dict, new: dict) -> list[str]:
    """The [tool.mypy] settings that hide type errors and that the kit's mypy run keeps (it drops the others)."""
    found = ["[tool.mypy] strict switched off"] if old.get("strict") and not new.get("strict") else []
    if new.get("ignore_missing_imports") and not old.get("ignore_missing_imports"):
        found.append("[tool.mypy] ignore_missing_imports switched on")
    return found + _added("[tool.mypy] ignore_missing_imports for", _unchecked_imports(old), _unchecked_imports(new))


def _unchecked_imports(config: dict) -> list[str]:
    """The module patterns of the [[tool.mypy.overrides]] that set ignore_missing_imports."""
    found: list[str] = []
    for override in config.get("overrides", []):
        if override.get("ignore_missing_imports"):
            module = override.get("module", [])
            found += [module] if isinstance(module, str) else module
    return found


def _whitelists(git: _Git, settings: Settings) -> list[str]:
    found = []
    for name in settings.tools.dead_code_whitelist:
        path = settings.root / name
        old, new = (Counter(_names(text)) for text in (git.show(path) or "", _read(path) or ""))
        more = list((new - old).elements())
        if more:
            shown = ", ".join(f"`{line}`" for line in more[:10]) + (
                f" (+{len(more) - 10} more)" if len(more) > 10 else ""
            )
            found.append(f"dead-code whitelist {name}: added {shown}")
    return found


def _names(text: str) -> list[str]:
    return [line.split("#", 1)[0].strip() for line in text.splitlines() if line.split("#", 1)[0].strip()]


def _suppressions(git: _Git, settings: Settings) -> list[str]:
    """Suppression comments added in the files that changed."""
    changed = git.changed()
    found = []
    for path in python_files(settings):
        rel = settings.rel(path)
        if rel in changed:
            old, new = _kinds(git.show(path) or ""), _kinds(path.read_text(encoding="utf-8", errors="replace"))
            found += [f"{rel}: {n} more `# {kind}`" for kind, n in sorted((new - old).items())]
    return found


def _kinds(text: str) -> Counter[str]:
    try:
        return Counter(kind for _, kind in markers(text))
    except ValueError:  # the file can't be tokenized: nothing to compare (the checks report the file itself)
        return Counter()
