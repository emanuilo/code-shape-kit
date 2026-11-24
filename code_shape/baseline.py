"""Baseline + ratchet: an existing project records today's violations; only new ones fail.

The baseline is a JSON file committed to the repo: {group: {finding key: value}}.
  - a finding not in the baseline              -> NEW, fails
  - a finding whose number grew (712 -> 730)   -> WORSE, fails
  - a baseline entry that is gone or shrank    -> IMPROVED, fails until the baseline
    is tightened, so a fixed problem can never quietly come back
  - a copied block now in fewer files          -> IMPROVED too (its key names fewer files)
`tighten` only removes or lowers entries. `baseline` (re)records everything and is the
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
    return {r.name: _worst_per_key([f for f in r.findings if f.check in gates]) for r in results if r.ok}


def _worst_per_key(findings: list[Finding]) -> list[Finding]:
    """One finding per key, the one with the biggest number.

    Two places can share a key, e.g. a property's getter and setter (both `Order.total`).
    Keeping the worst makes the recorded and compared number independent of the order
    the tool listed them in.
    """
    worst: dict[str, Finding] = {}
    for f in findings:
        old = worst.get(f.key)
        if old is None or (f.value or 0) > (old.value or 0):
            worst[f.key] = f
    return list(worst.values())


def baselineable(finding: Finding) -> bool:
    return CATALOG.get(finding.check, {}).get("baseline", True)


def record(results: list[GroupResult], gates: list[str]) -> Entries:
    entries: Entries = {}
    for group, findings in gated(results, gates).items():
        keep = {f.key: f.value for f in findings if baselineable(f)}
        if keep:
            entries[group] = dict(sorted(keep.items()))
    return entries


def rebaseline(results: list[GroupResult], gates: list[str], baseline: Entries) -> Entries:
    """Record today's findings, keeping the entries of groups that did not run this time
    (left out with --only, or crashed), so a partial run can't wipe them."""
    ran = _ran(results)
    return {**{group: known for group, known in baseline.items() if group not in ran}, **record(results, gates)}


def _ran(results: list[GroupResult]) -> set[str]:
    return {r.name for r in results if r.ok}


def load(path: Path) -> Entries:
    return parse(path.read_text(encoding="utf-8")) if path.exists() else {}


def parse(text: str) -> Entries:
    return json.loads(text)["entries"]


def save(path: Path, entries: Entries) -> None:
    payload = {
        "version": 1,
        "about": "Known shape violations. Shrink it with `code-shape tighten`; never edit by hand to add.",
        "entries": entries,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def compare(results: list[GroupResult], gates: list[str], baseline: Entries) -> Comparison:
    out = Comparison()
    for group, findings in gated(results, gates).items():
        known = baseline.get(group, {})
        seen = set()
        shrunk = _shrunk(findings, known)
        for f in findings:
            if f.key in shrunk:
                seen.add(shrunk[f.key])
                out.improved.append(f"{shrunk[f.key]} is now only {f.key}")
                continue
            seen.add(f.key)
            _compare_one(f, known, out)
        grown = [_copies(f.key) for f in out.new if f.check == "duplicate-code"]
        out.improved += [f"{key} is fixed" for key in known if key not in seen and not _grown(key, grown)]
    return out


def _grown(key: str, new_copies: list[set[str]]) -> bool:
    """Is `key` a copied block that is NEW now under a longer key, because it was copied once more?

    Its old key isn't fixed then; the NEW finding already says what happened.
    """
    copies = _copies(key)
    return bool(copies) and any(copies < files for files in new_copies)


def _shrunk(findings: list[Finding], known: dict[str, float | None]) -> dict[str, str]:
    """New duplicate-code keys that are a baselined copied block left in fewer files: new key -> old key.

    Removing one of three copies changes the key ('a.py|same code as b.py + c.py' becomes
    'b.py|same code as c.py'). That is a fix, not new debt, as long as the block is in a subset
    of the old files and is no longer. Each old entry accounts for one new key at most.
    """
    now = {f.key for f in findings}
    gone = sorted((key for key in known if key not in now and _copies(key)), key=lambda k: (len(_copies(k)), k))
    shrunk: dict[str, str] = {}
    for f in findings:
        files = _copies(f.key)
        if f.key in known or not files or not baselineable(f):
            continue
        old = next((key for key in gone if files < _copies(key) and not _grew(f.value, known[key])), None)
        if old:
            shrunk[f.key] = old
            gone.remove(old)
    return shrunk


def _grew(value: float | None, old: float | None) -> bool:
    return value is not None and old is not None and value > old


def _copies(key: str) -> set[str]:
    """The files a duplicate-code key names ('duplicate-code|a.py|same code as b.py + c.py'), else none."""
    check, path, symbol = key.split("|", 2)
    if check != "duplicate-code":
        return set()
    return {path, *symbol.removeprefix("same code as ").split(" + ")}


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
    current = gated(results, gates)
    ran = _ran(results)
    tightened: Entries = {}
    for group, known in baseline.items():
        if group not in ran:  # tool didn't run this time: keep its entries untouched
            tightened[group] = known
            continue
        findings = [f for f in current.get(group, []) if baselineable(f)]
        now = {f.key: f.value for f in findings}
        kept = {key: _lower(old, now[key]) for key, old in known.items() if key in now}
        # a copied block left in fewer files is recorded under its new, shorter key
        kept |= {new: _lower(known[old], now[new]) for new, old in _shrunk(findings, known).items()}
        if kept:
            tightened[group] = kept
    return tightened


def _lower(old: float | None, new: float | None) -> float | None:
    return min(old, new) if old is not None and new is not None else old
