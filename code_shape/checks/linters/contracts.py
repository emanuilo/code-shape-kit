"""import-linter: the architecture contracts, with the imports that break them."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from code_shape.checks.linters.running import ToolError, run
from code_shape.model import Finding, GroupResult, Table
from code_shape.settings import Settings

CONTRACT_RESULT = re.compile(r"^(.+) (KEPT|BROKEN)(?: \(.*\))?$")  # "Name BROKEN (3 ignored imports)"
CONTRACT_SUMMARY = re.compile(r"^Contracts: (\d+) kept, (\d+) broken\.$", re.MULTILINE)


def import_linter(settings: Settings, tmp: Path) -> GroupResult:
    if not settings.contracts:
        return GroupResult("import-linter", skipped="no import-linter contracts (see templates/importlinter.toml)")
    output = run(settings, tmp, ["lint-imports", str(settings.contracts), "--no-cache", "--no-logo"])
    kept, broken = _contract_verdicts(output)
    report = output.split("Broken contracts", 1)[-1]
    lines = [line.strip() for line in report.splitlines() if line.strip() and not set(line.strip()) <= {"-"}]
    sections = _contract_sections(report, broken)
    guidance = _contract_guidance(settings.contracts)
    result = GroupResult("import-linter")
    for name in broken:  # the offending imports are the "- a -> b (l.12)" lines under the contract's name
        offenders = [line.strip()[2:] for line in sections.get(name, "").splitlines() if line.strip().startswith("- ")]
        more = f" (+{len(offenders) - 5} more)" if len(offenders) > 5 else ""
        detail = "broken by: " + "; ".join(offenders[:5]) + more if offenders else ""
        if guidance.get(name):
            detail += f"{' - ' if detail else ''}contract says: {' '.join(guidance[name].split())}"
        result.findings.append(Finding("import-contracts", settings.rel(settings.contracts), name, detail=detail))
    if broken:
        result.tables.append(Table("Broken architecture contracts", ["lint-imports output"], [[x] for x in lines[:40]]))
    result.metrics = {"architecture contracts kept": len(kept), "architecture contracts broken": len(broken)}
    return result


def _contract_verdicts(output: str) -> tuple[list[str], list[str]]:
    """The names of the kept and the broken contracts, from the result lines above the summary."""
    summary = CONTRACT_SUMMARY.search(output)
    head = output[: summary.start()] if summary else ""
    verdicts = [m.groups() for m in map(CONTRACT_RESULT.match, head.splitlines()) if m]
    kept = [name for name, verdict in verdicts if verdict == "KEPT"]
    broken = [name for name, verdict in verdicts if verdict == "BROKEN"]
    if not summary or [len(kept), len(broken)] != [int(n) for n in summary.groups()]:
        # a config error (e.g. a contract names a module that no longer exists), or output we can't read
        raise ToolError(
            "lint-imports could not check the contracts (run `lint-imports` to see why, e.g. a "
            f"contract names a module that no longer exists). Output: {output.strip()[-500:]}"
        )
    return kept, broken


def _contract_sections(report: str, broken: list[str]) -> dict[str, str]:
    """The text under each broken contract's heading: its name underlined with dashes."""
    heading = re.compile("^(" + "|".join(map(re.escape, broken)) + r")\n-+\n", re.MULTILINE)
    parts = heading.split(report) if broken else []
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def _contract_guidance(config: Path) -> dict[str, str]:
    """Each contract's broken_contract_guidance (TOML configs only), by contract name."""
    if config.suffix != ".toml":
        return {}
    contracts = tomllib.loads(config.read_text(encoding="utf-8"))["tool"]["importlinter"].get("contracts", [])
    return {c.get("name", ""): c.get("broken_contract_guidance", "") for c in contracts}
