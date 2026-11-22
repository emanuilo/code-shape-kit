"""Renders results as one readable markdown report (REPORT mode)."""

from __future__ import annotations

from datetime import date

from code_shape.model import CATALOG, Finding, GroupResult, Table, fmt
from code_shape.settings import Settings

TOP = 10


def render(settings: Settings, results: list[GroupResult], trend: Table | None = None) -> str:
    by_group = {r.name: r for r in results}
    findings = [f for r in results for f in r.findings]
    out = [
        f"# Code shape report: {settings.root.name}",
        "",
        f"_Generated {date.today().isoformat()} by code-shape-kit. REPORT mode: this never fails a build. "
        f"Packages: {', '.join(settings.packages)}._",
        "",
        "## Summary",
        "",
        "Gate = fails `code-shape check` (CI) for new violations. Tracked = shown here only.",
        "",
        _table(["check", "what it protects", "found", "limit", "gate?"], _summary_rows(settings, by_group, findings)),
        "## Numbers",
        "",
        _table(["metric", "value"], [[k, fmt(v)] for r in results for k, v in r.metrics.items()]),
    ]
    if trend:
        out += [f"## Trend: {trend.title}", "", trend.note, "", _table(trend.columns, trend.rows)]
    out += ["## Worst offenders", "", *_offenders(findings)]
    for table in (t for r in results for t in r.tables):
        note = [table.note, ""] if table.note else []
        out += [f"## {table.title}", "", *note, _table(table.columns, table.rows)]
    problems = [r for r in results if not r.ok]
    if problems:
        out += ["## Not run", ""] + [f"- **{r.name}**: {r.error or r.skipped}" for r in problems] + [""]
    return "\n".join(out)


def _offenders(findings: list[Finding]) -> list[str]:
    out = []
    for check, meta in CATALOG.items():
        # Ties broken by key, so the report reads the same whatever order the tools listed findings in.
        hits = sorted((f for f in findings if f.check == check), key=lambda f: (-(f.value or 0), f.key))
        if hits:
            out += [f"### {meta['title']} ({len(hits)})", "", f"{meta['protects']} **Fix:** {meta['fix']}", ""]
            out += [f"- {f.describe()}" for f in hits[:TOP]]
            out += [f"- ...and {len(hits) - TOP} more" if len(hits) > TOP else "", ""]
    return out


def _summary_rows(settings: Settings, by_group: dict[str, GroupResult], findings: list[Finding]) -> list[list]:
    rows = []
    for check, meta in CATALOG.items():
        group = by_group.get(meta["tool"])
        count = sum(1 for f in findings if f.check == check)
        found = str(count) if group and group.ok else "not run"
        limit = fmt(settings.limits[meta["limit"]]) if "limit" in meta else ""
        mark = "gate" if check in settings.gates else "tracked"
        rows.append([meta["title"], meta["protects"], found, limit, mark])
    return rows


def _table(columns: list[str], rows: list[list]) -> str:
    if not rows:
        return "_(nothing)_\n"
    clean = [[str(cell).replace("|", "\\|").replace("\n", " ") for cell in row] for row in rows]
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    lines += ["| " + " | ".join(row) + " |" for row in clean]
    return "\n".join(lines) + "\n"
