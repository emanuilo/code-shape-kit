"""Baseline + ratchet: an existing project records today's violations; only new ones fail.

The baseline is a JSON file committed to the repo: {group: {finding key: value}}.
  - a finding not in the baseline              -> NEW, fails
  - a finding whose number grew (712 -> 730)   -> WORSE, fails
  - a baseline entry that is gone or shrank    -> IMPROVED, fails until the baseline
    is tightened, so a fixed problem can never quietly come back
`tighten` only removes or lowers entries. `init` (re)records everything and is the
one deliberate way to accept new debt - it shows up in the PR diff.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from code_shape.model import CATALOG, Finding, GroupResult

Entries = dict[str, dict[str, float | None]]


@dataclass
class Comparison:
    new: list[Finding] = field(default_factory=list)
    worse: list[tuple[Finding, float]] = field(default_factory=list)
    improved: list[str] = field(default_factory=list)  # human-readable descriptions


def gated(results: list[GroupResult], gates: list[str]) -> dict[str, list[Finding]]:
    return {r.name: [f for f in r.findings if f.check in gates] for r in results if r.ok}


def baselineable(finding: Finding) -> bool:
    return CATALOG.get(finding.check, {}).get("baseline", True)


def record(results: list[GroupResult], gates: list[str]) -> Entries:
    entries: Entries = {}
    for group, findings in gated(results, gates).items():
        keep = {f.key: f.value for f in findings if baselineable(f)}
        if keep:
            entries[group] = dict(sorted(keep.items()))
    return entries


def load(path: Path) -> Entries:
    return json.loads(path.read_text(encoding="utf-8"))["entries"] if path.exists() else {}


def save(path: Path, entries: Entries) -> None:
    payload = {
        "version": 1,
        "about": "Known shape violations. Shrink it with `code-shape tighten`; never edit by hand to add.",
        "entries": entries,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def compare(results: list[GroupResult], gates: list[str], baseline: Entries) -> Comparison:
    out = Comparison()
    for group, findings in gated(results, gates).items():
        known = baseline.get(group, {})
        seen = set()
        for f in findings:
            seen.add(f.key)
            _compare_one(f, known, out)
        out.improved += [f"{key} is fixed" for key in known if key not in seen]
    return out


def _compare_one(f: Finding, known: dict[str, float | None], out: Comparison) -> None:
    if not baselineable(f) or f.key not in known:
        out.new.append(f)
        return
    old = known[f.key]
    if f.value is None or old is None:
        return
    if f.value > old:
        out.worse.append((f, old))
    elif f.value < old:
        out.improved.append(f"{f.key} went from {old:g} to {f.value:g}")


def tighten(results: list[GroupResult], gates: list[str], baseline: Entries) -> Entries:
    current = record(results, gates)
    ran = {r.name for r in results if r.ok}
    tightened: Entries = {}
    for group, known in baseline.items():
        if group not in ran:  # tool didn't run this time: keep its entries untouched
            tightened[group] = known
            continue
        now = current.get(group, {})
        kept = {key: _lower(old, now[key]) for key, old in known.items() if key in now}
        if kept:
            tightened[group] = kept
    return tightened


def _lower(old: float | None, new: float | None) -> float | None:
    return min(old, new) if old is not None and new is not None else old
