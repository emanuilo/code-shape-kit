"""Counts the comments that silence a tool: `# noqa`, `# type: ignore`, `# pylint: disable`...

Each one hides a problem a tool found, and an agent can add one in a second to get a red
check green. They are counted per function (or module) and kind, so one more is new.
Only real comments count (found with tokenize), not the same text inside a string.
"""

from __future__ import annotations

import io
import re
import tokenize
from collections import Counter

from code_shape.model import Finding, GroupResult
from code_shape.settings import Settings
from code_shape.source import definitions, python_files, symbol_at

# kind -> how a comment (or the part of it after another `#`) starts
KINDS = {
    "noqa": re.compile(r"((ruff|flake8):\s*)?noqa\b", re.IGNORECASE),
    "type: ignore": re.compile(r"(type|mypy|pyright):\s*ignore", re.IGNORECASE),
    "pylint: disable": re.compile(r"pylint:\s*(disable|skip-file)", re.IGNORECASE),
    "pragma: no cover": re.compile(r"pragma:\s*no\s*(cover|branch)", re.IGNORECASE),
    "complexipy: ignore": re.compile(r"complexipy:\s*ignore", re.IGNORECASE),
    "nosec": re.compile(r"nosec\b", re.IGNORECASE),
}
COMMENT_PART = re.compile(r"(?:^|\s)#")


def markers(text: str) -> list[tuple[int, str]]:
    """(line, kind) for every suppression in the comments of `text`."""
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError) as exc:
        raise ValueError(f"could not read the comments: {exc}") from exc
    found = []
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        # One comment can hold several, each starting with a `#` after a space. A `#` inside
        # backticks or a word (a comment that only talks about a marker) doesn't start one.
        for part in COMMENT_PART.split(token.string)[1:]:
            found += [(token.start[0], kind) for kind, pattern in KINDS.items() if pattern.match(part.strip())]
    return found


def run(settings: Settings) -> GroupResult:
    counts: Counter[tuple[str, str]] = Counter()
    first_line: dict[tuple[str, str], int] = {}
    for path in python_files(settings):
        definitions(path)  # a file that doesn't parse fails the check, even without a suppression in it
        rel = settings.rel(path)
        for line, kind in markers(path.read_text(encoding="utf-8", errors="replace")):
            key = (rel, f"{kind} in {symbol_at(path, line) or '<module>'}")
            counts[key] += 1
            first_line.setdefault(key, line)
    result = GroupResult(
        "suppressions",
        [
            Finding("inline-suppression", rel, symbol, n, line=first_line[rel, symbol])
            for (rel, symbol), n in counts.items()
        ],
    )
    by_kind = Counter(symbol.split(" in ", 1)[0] for _, symbol in counts.elements())
    result.metrics = {f"suppression comments: {kind}": n for kind, n in sorted(by_kind.items())}
    return result
