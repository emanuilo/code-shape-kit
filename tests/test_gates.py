"""Proves the gates fail when they should: inject a violation into the example project,
see `code-shape check` fail with a clear message, revert, see it pass again.

Needs the tools installed: pip install -e ".[tools,dev]"
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).parents[1] / "examples" / "tidy_app"

COMPLEX = """

def classify(a: int, b: int, c: int) -> str:
    if a > 0:
        if b > 0:
            if c > 0:
                return "all"
            elif c < -10:
                return "far"
        elif b < 0 and c > 0 or a > 100:
            return "mixed"
    for i in range(a):
        if i % 2 and b or c:
            while c > i:
                c -= 1
                if c == 3:
                    break
                if c == 5:
                    continue
            if b == 7:
                return "seven"
    return "none"


print(classify(1, 2, 3))
"""

DUPLICATE = """

def summarize(names: list[str]) -> str:
    total = 0
    longest = ""
    for name in names:
        total += len(name)
        if len(name) > len(longest):
            longest = name
    average = total / len(names) if names else 0
    words = sum(len(n.split()) for n in names)
    first = names[0] if names else ""
    last = names[-1] if names else ""
    return f"{total} {longest} {average} {words} {first} {last}"


print(summarize([]))
"""

# name -> (file to change, text to append, what the failure must say)
VIOLATIONS = {
    "file too long": ("tidy_app/inventory/service.py", "\n" + "# filler\n" * 520, "[file-lines]"),
    "complex function": ("tidy_app/cli.py", COMPLEX, "[function-complexity]"),
    "hard-to-read function": ("tidy_app/cli.py", COMPLEX, "[cognitive-complexity]"),
    "env var outside config": (
        "tidy_app/cli.py",
        "\nimport os\n\nDEBUG = os.environ.get('DEBUG')\nprint(DEBUG)\n",
        "Read settings through the config module",
    ),
    "adapter bypassed": (
        "tidy_app/inventory/service.py",
        "\nimport json\n\nprint(json.dumps([]))\n",
        "Only tidy_app/inventory/store.py reads/writes the stock file",
    ),
    "layer broken": (
        "tidy_app/config.py",
        "\nfrom tidy_app.inventory import Inventory\n\nprint(Inventory)\n",
        "[import-contracts]",
    ),
    "dead code": ("tidy_app/inventory/service.py", "\n\ndef never_called() -> int:\n    return 1\n", "[dead-code]"),
    "type error": (
        "tidy_app/config.py",
        "\n\ndef port() -> int:\n    return 'x'\n\n\nprint(port())\n",
        "[type-errors]",
    ),
    "private member used": (
        "tidy_app/cli.py",
        "\n\nclass Box:\n    _secret = 1\n\n\nprint(Box._secret)\n",
        "[private-access]",
    ),
    "too many arguments": (
        "tidy_app/cli.py",
        "\n\ndef wide(a, b, c, d, e, f, g):\n    return a\n\n\nprint(wide(*range(7)))\n",
        "[too-many-args]",
    ),
}


def shape(project: Path, mode: str = "check", *extra: str) -> tuple[int, str]:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        [sys.executable, "-m", "code_shape", mode, "--root", str(project), *extra],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr


@pytest.fixture
def project(tmp_path: Path) -> Path:
    target = tmp_path / "tidy_app"
    shutil.copytree(EXAMPLE, target)
    return target


def test_clean_project_passes(project: Path) -> None:
    code, out = shape(project)
    assert code == 0, out


@pytest.mark.parametrize("name", VIOLATIONS)
def test_violation_fails_with_clear_message_then_passes_after_revert(project: Path, name: str) -> None:
    file, text, expected = VIOLATIONS[name]
    path = project / file
    original = path.read_text()
    path.write_text(original + text)
    code, out = shape(project)
    assert code == 1, out
    assert expected in out, out
    assert "fix:" in out  # every failure tells the agent what to do instead
    path.write_text(original)
    assert shape(project)[0] == 0


def test_too_many_modules_in_one_folder(project: Path) -> None:
    for i in range(13):
        (project / "tidy_app" / "inventory" / f"part{i}.py").write_text(f'"""Part {i}."""\n')
    code, out = shape(project, "check", "--only", "sizes")
    assert code == 1 and "[package-files]" in out, out


def test_copy_paste_fails(project: Path) -> None:
    for file in ("tidy_app/cli.py", "tidy_app/inventory/service.py"):
        (project / file).write_text((project / file).read_text() + DUPLICATE)
    code, out = shape(project, "check", "--only", "pylint")
    assert code == 1 and "[duplicate-code]" in out, out


# Loaded by the tools the kit runs (their PYTHONPATH is the project), it makes directory
# listings come back sorted or reversed: macOS and Linux list folders in different orders.
FAKE_FS_ORDER = """
import os

_ORDER = os.environ.get("FAKE_FS_ORDER")
if _ORDER:
    _scandir, _listdir = os.scandir, os.listdir

    class _Listing:
        def __init__(self, path="."):
            with _scandir(path) as entries:
                self._entries = sorted(entries, key=lambda e: e.name, reverse=_ORDER == "reverse")

        def __iter__(self):
            return iter(self._entries)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def close(self):
            pass

    os.scandir = _Listing
    os.listdir = lambda path=".": sorted(_listdir(path), reverse=_ORDER == "reverse")
"""


def test_copy_paste_findings_do_not_depend_on_file_order(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # One block copied into three files; two copies also share the line before it, so
    # the three pairs match over different lengths. pylint then reports two of the
    # three pairs, and which two depended on the order it found the files in.
    block = "".join(f"    v{i} = len(names) * {i} + sum(map(len, names[{i}:]))\n" for i in range(12))
    block += "    return " + " + ".join(f"v{i}" for i in range(12)) + "\n"
    folder = project / "tidy_app" / "copies"
    folder.mkdir()
    (folder / "__init__.py").write_text("")
    shared = "    names = sorted(set(names))\n"
    for name, before in (("first", ""), ("second", shared), ("third", shared)):
        (folder / f"{name}.py").write_text(f"def {name}(names: list[str]) -> int:\n{before}{block}")
    (project / "sitecustomize.py").write_text(FAKE_FS_ORDER)

    monkeypatch.setenv("FAKE_FS_ORDER", "sorted")  # e.g. the laptop that recorded the baseline
    shape(project, "baseline", "--only", "pylint")
    recorded = (project / ".code-shape-baseline.json").read_text()
    assert recorded.count("duplicate-code|") == 2, recorded

    monkeypatch.setenv("FAKE_FS_ORDER", "reverse")  # e.g. CI on another OS
    code, out = shape(project, "check", "--only", "pylint")
    assert code == 0, out


def test_dead_code_whitelist_silences_a_false_positive(project: Path) -> None:
    service = project / "tidy_app" / "inventory" / "service.py"
    service.write_text(service.read_text() + "\n\nclass Server:\n    should_exit = False\n\n\nprint(Server)\n")
    code, out = shape(project, "check", "--only", "vulture")
    assert code == 1 and "[dead-code]" in out and "should_exit" in out, out

    (project / "vulture_whitelist.py").write_text("Server.should_exit  # set by the framework\n")
    pyproject = project / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text().replace(
            "[tool.shape]\n", '[tool.shape]\ndead_code_whitelist = ["vulture_whitelist.py"]\n'
        )
    )
    code, out = shape(project, "check", "--only", "vulture")  # resolved from --root, not the cwd
    assert code == 0, out


def test_baseline_ratchet(project: Path) -> None:
    service = project / "tidy_app" / "inventory" / "service.py"
    original = service.read_text()
    service.write_text(original + "# filler\n" * 520)  # existing debt: ~550 lines
    assert shape(project, "check", "--only", "sizes")[0] == 1

    shape(project, "baseline", "--only", "sizes")  # record today's debt
    assert shape(project, "check", "--only", "sizes")[0] == 0  # known debt passes

    service.write_text(service.read_text() + "# more\n" * 10)  # debt grows
    code, out = shape(project, "check", "--only", "sizes")
    assert code == 1 and "WORSE" in out, out

    service.write_text(original + "# filler\n" * 510)  # debt shrinks
    code, out = shape(project, "check", "--only", "sizes")
    assert code == 1 and "IMPROVED" in out and "code-shape tighten" in out, out
    shape(project, "tighten", "--only", "sizes")
    assert shape(project, "check", "--only", "sizes")[0] == 0

    service.write_text(original + "# filler\n" * 520)  # can't slide back to the old number
    assert shape(project, "check", "--only", "sizes")[0] == 1

    service.write_text(original)  # fully fixed
    shape(project, "tighten", "--only", "sizes")
    assert shape(project, "check", "--only", "sizes")[0] == 0
    service.write_text(original + "# filler\n" * 520)  # and it can never come back
    code, out = shape(project, "check", "--only", "sizes")
    assert code == 1 and "NEW" in out, out


def test_report_never_fails_and_lists_offenders(project: Path) -> None:
    (project / "tidy_app" / "cli.py").write_text((project / "tidy_app" / "cli.py").read_text() + COMPLEX)
    out_file = project / "report.md"
    code, out = shape(project, "report", "--out", str(out_file))
    assert code == 0, out
    text = out_file.read_text()
    assert "## Worst offenders" in text and "classify" in text
