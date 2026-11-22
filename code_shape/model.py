"""The data every check produces: findings, metrics and report tables."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CATALOG: dict[str, dict] = tomllib.loads((Path(__file__).parent / "catalog.toml").read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Finding:
    """One place where the code breaks a shape rule.

    `path` + `symbol` identify the place without line numbers, so the
    baseline survives unrelated edits. `value` is the measured number (None
    for yes/no findings); the ratchet fails if it grows.
    """

    check: str
    path: str
    symbol: str = ""
    value: float | None = None
    limit: float | None = None
    line: int | None = None
    detail: str = ""

    @property
    def key(self) -> str:
        return f"{self.check}|{self.path}|{self.symbol}"

    def describe(self) -> str:
        where = self.path + (f"::{self.symbol}" if self.symbol else "")
        if self.line:
            where = f"{self.path}:{self.line}" + (f" ({self.symbol})" if self.symbol else "")
        unit = CATALOG.get(self.check, {}).get("unit", "")
        amount = ""
        if self.value is not None:
            amount = f" - {fmt(self.value)} {unit}".rstrip()
            if self.limit is not None:
                amount += f" (limit {fmt(self.limit)})"
        return f"{where}{amount}" + (f" - {self.detail}" if self.detail else "")


@dataclass
class Table:
    title: str
    columns: list[str]
    rows: list[list]
    note: str = ""


@dataclass
class GroupResult:
    """Output of one tool or custom check group."""

    name: str
    findings: list[Finding] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    tables: list[Table] = field(default_factory=list)
    error: str = ""  # tool crashed or is missing: findings are incomplete
    skipped: str = ""  # deliberately not run (not configured / disabled)

    @property
    def ok(self) -> bool:
        return not self.error and not self.skipped


def fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.2f}"


def title(check: str) -> str:
    return CATALOG.get(check, {}).get("title", check)
