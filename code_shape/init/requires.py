"""The Python version the CI workflow sets up: the lowest the project allows (`requires-python`)
that the kit runs on, so CI checks the oldest Python the project promises to support."""

from __future__ import annotations

import re

DEFAULT = "3.12"  # without a usable requires-python
MINORS = range(11, 16)  # the 3.x versions the kit runs on (3.11+)
CLAUSE = re.compile(r"^(~=|===|==|!=|<=|>=|<|>)\s*(\d+(?:\.\d+)*)(\.\*)?$")


def ci_python(requires: object) -> str:
    """'3.11' for '>=3.11.4', '3.13' for '>=3.13,<4'; "" when it can't tell (use DEFAULT)."""
    clauses = [CLAUSE.match(part.strip()) for part in str(requires or "").split(",") if part.strip()]
    if not clauses or not all(clauses):
        return ""
    for minor in MINORS:
        if any(all(_allows(m, (3, minor, patch)) for m in clauses if m) for patch in range(30)):
            return f"3.{minor}"
    return ""


def _allows(clause: re.Match[str], version: tuple[int, ...]) -> bool:
    op, wanted, star = clause.group(1), tuple(int(n) for n in clause.group(2).split(".")), clause.group(3)
    if star or op == "~=":  # a prefix: ==3.11.* or the release series of ~=3.11.2
        prefix = wanted if star else wanted[:-1]
        inside = version[: len(prefix)] == prefix
        if op == "~=":
            return inside and version >= _padded(wanted)
        return inside if op == "==" else not inside
    other = _padded(wanted)
    return {
        "==": version == other,
        "===": version == other,
        "!=": version != other,
        "<=": version <= other,
        ">=": version >= other,
        "<": version < other,
        ">": version > other,
    }[op]


def _padded(version: tuple[int, ...]) -> tuple[int, ...]:
    return (version + (0, 0, 0))[:3]
