"""The single entry command.

code-shape report    run everything, write a markdown report, never fail
code-shape check     CI gate: fail on violations that are not in the baseline
code-shape baseline  record today's violations (start of an existing project)
code-shape tighten   lock in improvements: drop fixed entries from the baseline
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from code_shape import baseline as bl
from code_shape import report
from code_shape.checks import ALL_GROUPS, run_all
from code_shape.model import CATALOG, Finding, title
from code_shape.settings import load
from code_shape.trend import trend


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = load(Path(args.root), Path(args.config) if args.config else None)
    groups = args.only.split(",") if args.only else ALL_GROUPS
    if args.mode == "check":  # history-based checks are tracked metrics, never gates
        groups = [g for g in groups if g not in ("history", "concepts")]
    results = run_all(settings, groups)
    baseline_path = Path(args.baseline) if args.baseline else settings.root / ".code-shape-baseline.json"

    if args.mode == "report":
        table = trend(settings, args.trend, results) if args.trend else None
        out = Path(args.out) if args.out else settings.root / "code-shape-report.md"
        out.write_text(report.render(settings, results, table), encoding="utf-8")
        print(f"code-shape: report written to {out}")
        return 0
    failures = [f"{r.name}: {r.error}" for r in results if r.error]
    if failures:  # a gate that could not run must not pass silently
        print("code-shape: these checks could not run:\n  " + "\n  ".join(failures))
        if args.mode == "check":
            return 1
    if args.mode == "baseline":
        bl.save(baseline_path, bl.record(results, settings.gates))
        print(f"code-shape: baseline written to {baseline_path}. Commit it.")
        return 0
    if args.mode == "tighten":
        bl.save(baseline_path, bl.tighten(results, settings.gates, bl.load(baseline_path)))
        print(f"code-shape: baseline tightened at {baseline_path}. Commit it.")
        return 0
    return _check(results, settings.gates, bl.load(baseline_path))


def _check(results, gates: list[str], baseline: bl.Entries) -> int:
    comparison = bl.compare(results, gates, baseline)
    for finding in comparison.new:
        _explain("NEW", finding)
    for finding, old in comparison.worse:
        _explain(f"WORSE (was {old:g})", finding)
    if comparison.improved:
        print("IMPROVED - lock it in with `code-shape tighten` and commit the baseline:")
        print("".join(f"  - {line}\n" for line in comparison.improved), end="")
    failed = bool(comparison.new or comparison.worse or comparison.improved)
    status = "FAILED" if failed else "passed"
    print(
        f"code-shape check {status}: {len(comparison.new)} new, {len(comparison.worse)} worse, "
        f"{len(comparison.improved)} improved-but-not-locked-in."
    )
    return 1 if failed else 0


def _explain(label: str, finding: Finding) -> None:
    meta = CATALOG.get(finding.check, {})
    print(f"{label}: [{finding.check}] {title(finding.check)}\n  at {finding.describe()}")
    print(f"  why: {meta.get('protects', '')}\n  fix: {meta.get('fix', '')}\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="code-shape", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("mode", choices=["report", "check", "baseline", "tighten"])
    parser.add_argument("--root", default=".", help="project root (default: current folder)")
    parser.add_argument("--config", help="TOML file with [tool.shape] (default: <root>/pyproject.toml)")
    parser.add_argument("--baseline", help="baseline file (default: <root>/.code-shape-baseline.json)")
    parser.add_argument("--out", help="report file (default: <root>/code-shape-report.md)")
    parser.add_argument("--trend", type=int, default=0, metavar="N", help="report: also sample N past commits")
    parser.add_argument("--only", help="comma-separated check groups to run, e.g. sizes,ruff")
    return parser


if __name__ == "__main__":
    sys.exit(main())
