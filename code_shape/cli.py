"""The single entry command.

code-shape report    run everything, write a markdown report, never fail
code-shape check     CI gate: fail on violations that are not in the baseline
code-shape baseline  record today's violations (start of an existing project)
code-shape tighten   lock in improvements: drop fixed entries from the baseline
code-shape init      set the kit up in a project: best guesses to review (--dry-run shows them)

With --base REF, check and report also list the rules loosened since REF (a warning).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from code_shape import baseline as bl
from code_shape import init, loosening, report
from code_shape.checks import ALL_GROUPS, run_all
from code_shape.checks.linters import BOUNDARIES
from code_shape.init import summary as init_summary
from code_shape.model import CATALOG, Finding, GroupResult, Table, title
from code_shape.settings import Settings, load
from code_shape.trend import trend

FOOTER = """\
To pass, fix the code. Don't re-run `code-shape baseline`, add suppression comments (# noqa,
# type: ignore, # pylint: disable...) or edit [tool.shape], import-linter contracts or the
dead-code whitelist to get this green: those changes need a human's approval."""


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.mode == "init" or args.dry_run:
        return _init(args)
    if (args.base or args.summary) and args.mode not in ("check", "report"):
        raise SystemExit("code-shape: --base and --summary work with check and report only")
    settings = load(Path(args.root), Path(args.config) if args.config else None)
    results = run_all(settings, _groups(args, settings))
    loosened = loosening.since(settings, args.base, _flag_path(args.baseline)) if args.base else None
    code = _report(args, settings, results, loosened) if args.mode == "report" else _gate(args, settings, results)
    if loosened:
        print("\n" + loosened.text(), end="")
        if args.summary:
            with Path(args.summary).open("a", encoding="utf-8") as summary:
                summary.write(loosened.markdown())
    return code


def _init(args: argparse.Namespace) -> int:
    """Writes the setup, or with --dry-run shows it. Takes no other option than --root."""
    other = [flag for flag in ("config", "baseline", "out", "trend", "only", "base", "summary") if getattr(args, flag)]
    if args.mode != "init" or other:
        raise SystemExit("code-shape: --dry-run works with init only, and init takes only --root and --dry-run")
    plan = init.plan(Path(args.root))
    print(init_summary.describe(plan, dry_run=args.dry_run), end="")
    if args.dry_run:
        print("\n" + init_summary.preview(plan), end="")
    else:
        plan.apply()
    return 0


def _groups(args: argparse.Namespace, settings: Settings) -> list[str]:
    groups = args.only.split(",") if args.only else ALL_GROUPS
    unknown = sorted(set(groups + settings.skip) - set(ALL_GROUPS))
    if unknown:  # a typo must not quietly switch a check off
        raise SystemExit(f"code-shape: unknown check group(s) {unknown}; known: {', '.join(ALL_GROUPS)}")
    if args.mode != "report":  # only the groups that produce a gated check matter (history ones usually don't)
        gated = {CATALOG[check]["tool"] for check in settings.gate.checks}
        groups = [g for g in groups if g in gated]
    return groups


def _flag_path(value: str | None) -> Path | None:
    return Path(value) if value else None


def _report(
    args: argparse.Namespace, settings: Settings, results: list[GroupResult], loosened: loosening.Loosened | None
) -> int:
    table = _trend(settings, args.trend, results) if args.trend else None
    out = Path(args.out) if args.out else settings.root / "code-shape-report.md"
    warning = loosened.markdown() if loosened else ""
    out.write_text(report.render(settings, results, table, warning), encoding="utf-8")
    print(f"code-shape: report written to {out}")
    return 0


def _gate(args: argparse.Namespace, settings: Settings, results: list[GroupResult]) -> int:
    """check, baseline and tighten."""
    path = _flag_path(args.baseline) or settings.gate.baseline
    crashed = [r for r in results if r.error]
    if crashed:  # a gate that could not run must not pass silently
        print("code-shape: these checks could not run:\n  " + "\n  ".join(f"{r.name}: {r.error}" for r in crashed))
    if args.mode == "check":
        _boundaries(results)
        failed = bool(crashed) or _check(results, settings.gate.checks, bl.load(path))
        if failed:
            print("\n" + FOOTER)
        return 1 if failed else 0
    update = bl.rebaseline if args.mode == "baseline" else bl.tighten
    bl.save(path, update(results, settings.gate.checks, bl.load(path)))
    done = "written" if args.mode == "baseline" else "tightened"
    if crashed:  # the entries of those groups were kept as they were
        names = ", ".join(r.name for r in crashed)
        print(
            f"code-shape: baseline {done} at {path} for the checks that ran; the entries for {names} were kept "
            f"unchanged. Fix what stopped them and run `code-shape {args.mode}` again."
        )
        return 1
    print(f"code-shape: baseline {done} at {path}. Commit it.")
    return 0


def _trend(settings: Settings, samples: int, results: list[GroupResult]) -> Table | None:
    try:
        return trend(settings, samples, results)
    except (subprocess.SubprocessError, OSError) as exc:  # e.g. not a git repository
        detail = getattr(exc, "stderr", "") or str(exc)
        print(f"code-shape: no trend, git history could not be read: {detail.strip()}")
        return None


def _check(results: list[GroupResult], gates: list[str], baseline: bl.Entries) -> bool:
    """Print what is new, worse or improved; True if the check fails."""
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
    return failed


def _boundaries(results: list[GroupResult]) -> None:
    """The catch-alls accepted by [tool.shape] error_boundaries, so a reviewer sees them in the CI log."""
    rows = [row for r in results for t in r.tables if t.title == BOUNDARIES for row in t.rows]
    if rows:
        print("Accepted error boundaries ([tool.shape] error_boundaries, reviewed by a human):")
        print("".join(f"  - {at}: {count} accepted - {reason}\n" for at, reason, count in rows), end="")


def _explain(label: str, finding: Finding) -> None:
    meta = CATALOG.get(finding.check, {})
    print(f"{label}: [{finding.check}] {title(finding.check)}\n  at {finding.describe()}")
    print(f"  why: {meta.get('protects', '')}\n  fix: {meta.get('fix', '')}\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="code-shape", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("mode", choices=["report", "check", "baseline", "tighten", "init"])
    parser.add_argument("--root", default=".", help="project root (default: current folder)")
    parser.add_argument("--config", help="TOML file with [tool.shape] (default: <root>/pyproject.toml)")
    parser.add_argument(
        "--baseline", help="baseline file (default: [tool.shape] baseline, else <root>/.code-shape-baseline.json)"
    )
    parser.add_argument("--out", help="report file (default: <root>/code-shape-report.md)")
    parser.add_argument("--trend", type=int, default=0, metavar="N", help="report: also sample N past commits")
    parser.add_argument("--only", help="comma-separated check groups to run, e.g. sizes,ruff")
    parser.add_argument(
        "--base",
        metavar="REF",
        help="check/report: also list the rules loosened since this git ref, e.g. origin/main (a warning only)",
    )
    parser.add_argument(
        "--summary",
        metavar="FILE",
        help="with --base: append that list as markdown to FILE, e.g. $GITHUB_STEP_SUMMARY",
    )
    parser.add_argument("--dry-run", action="store_true", help="init: show what would be written, change nothing")
    return parser


if __name__ == "__main__":
    sys.exit(main())
