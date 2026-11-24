"""Proves the gates fail when they should: inject a violation into the example project,
see `code-shape check` fail with a clear message, revert, see it pass again.

Needs the tools installed: pip install -e ".[tools,dev]"
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
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
    assert "To pass, fix the code" in out and "need a human's approval" in out  # and not to loosen the rules
    path.write_text(original)
    assert shape(project)[0] == 0


# name -> (text appended to tidy_app/inventory/service.py, the check that must fail)
RUFF_VIOLATIONS = {
    "swallowed error": (
        "\n\ndef risky() -> None:\n    try:\n        risky()\n    except Exception:\n        pass\n",
        "[swallowed-errors]",
    ),
    "blanket ignore": ("\nLIMIT = 3  # type: ignore\n", "[blanket-suppression]"),
    "commented-out code": ("\n# total = sum(stock.values())\n", "[commented-out-code]"),
    "print in a library module": ("\nprint('debug')\n", "[print-call]"),
    "mutable default": (
        "\n\ndef collect(items: list[str] = []) -> list[str]:\n    return items\n",
        "[mutable-default]",
    ),
    "wildcard import": ("\nfrom pathlib import *\n", "[wildcard-import]"),
    "eval": ("\n\ndef run(code: str) -> None:\n    eval(code)\n", "[security-risk]"),
    "shell=True": (
        "\nimport subprocess\n\nsubprocess.run('ls', shell=True, check=False)\n",
        "[security-risk]",
    ),
    "boolean flag": (
        "\n\ndef save(data: str, force: bool = False) -> str:\n    return data if force else ''\n",
        "[boolean-flag-args]",
    ),
}


@pytest.mark.parametrize("name", RUFF_VIOLATIONS)
def test_risky_habits_fail(project: Path, name: str) -> None:
    text, expected = RUFF_VIOLATIONS[name]
    service = project / "tidy_app" / "inventory" / "service.py"
    service.write_text(service.read_text() + text)
    code, out = shape(project, "check", "--only", "ruff")
    assert code == 1 and expected in out and "fix:" in out, out


def test_print_is_allowed_where_output_modules_say(project: Path) -> None:
    # tidy_app/cli.py prints its output and passes; a print in the service fails until it is allowed there
    service = project / "tidy_app" / "inventory" / "service.py"
    service.write_text(service.read_text() + "\nprint('debug')\n")
    assert shape(project, "check", "--only", "ruff")[0] == 1
    pyproject = project / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text().replace("[tool.shape]\n", '[tool.shape]\noutput_modules = ["*/cli.py", "*/service.py"]\n')
    )
    code, out = shape(project, "check", "--only", "ruff")
    assert code == 0, out


def test_one_more_swallowed_error_in_a_function_is_worse(project: Path) -> None:
    service = project / "tidy_app" / "inventory" / "service.py"
    once = "\n\ndef risky() -> None:\n    try:\n        risky()\n    except Exception:\n        pass\n"
    service.write_text(service.read_text() + once)
    shape(project, "baseline", "--only", "ruff")
    assert shape(project, "check", "--only", "ruff")[0] == 0
    service.write_text(service.read_text() + "    try:\n        risky()\n    except Exception:\n        pass\n")
    code, out = shape(project, "check", "--only", "ruff")
    assert code == 1 and "WORSE (was 1)" in out and "S110 in risky" in out, out


LOGGED = """

def keep_going(log_from: str) -> None:
    while True:
        try:
            keep_going(log_from)
        except Exception as e:
            {call}
"""


@pytest.mark.parametrize(
    ("logger", "call", "passes"),
    [
        ("from loguru import logger", 'logger.exception("sync failed")', True),  # keeps the traceback
        ("from loguru import logger", 'logger.error(f"sync failed: {e}")', False),  # loses it
        ("import logging\n\nlogger = logging.getLogger()", 'logger.error("sync failed", exc_info=True)', True),
    ],
)
def test_catching_everything_and_logging_the_traceback_passes(
    project: Path, logger: str, call: str, passes: bool
) -> None:
    service = project / "tidy_app" / "inventory" / "service.py"
    service.write_text(service.read_text() + f"\n{logger}\n" + LOGGED.format(call=call))
    code, out = shape(project, "check", "--only", "ruff")
    assert (code == 0) == passes, out
    if not passes:
        assert "[swallowed-errors]" in out and "logger.exception(...)" in out, out


def test_a_project_logger_passes_once_listed_in_logger_objects(project: Path) -> None:
    (project / "tidy_app" / "log.py").write_text("import logging\n\nlogger = logging.getLogger()\n")
    service = project / "tidy_app" / "inventory" / "service.py"
    call = 'logger.exception("sync failed")'
    service.write_text(service.read_text() + "\nfrom tidy_app.log import logger\n" + LOGGED.format(call=call))
    code, out = shape(project, "check", "--only", "ruff")
    assert code == 1 and "[swallowed-errors]" in out, out
    pyproject = project / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text().replace("[tool.shape]\n", '[tool.shape]\nlogger_objects = ["tidy_app.log.logger"]\n')
    )
    code, out = shape(project, "check", "--only", "ruff")
    assert code == 0, out


def test_suppression_comments_are_counted(project: Path) -> None:
    service = project / "tidy_app" / "inventory" / "service.py"
    original = service.read_text()
    service.write_text(original + '\nMARKER = "# noqa"  # a string is not a suppression\n')
    assert shape(project, "check", "--only", "suppressions")[0] == 0

    service.write_text(original + "\nLIMIT = 3  # noqa: E501\n")
    code, out = shape(project, "check", "--only", "suppressions")
    assert code == 1 and "NEW: [inline-suppression]" in out and "noqa in <module>" in out, out
    assert "only a human approves a suppression" in out, out

    shape(project, "baseline", "--only", "suppressions")  # a human accepted that one
    assert shape(project, "check", "--only", "suppressions")[0] == 0
    service.write_text(service.read_text() + "LOWER = 1  # noqa: E501\n")  # one more of the same kind
    code, out = shape(project, "check", "--only", "suppressions")
    assert code == 1 and "WORSE (was 1)" in out, out


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("\n\ndef untyped():\n    return 1 + 'a'\n\n\nprint(untyped())\n", "untyped [operator]"),
        ("\nCOUNT: int = 1  # type: ignore[assignment]\n", "[unused-ignore]"),
        ("\nCOUNT: int = 'a'  # type: ignore\n", "[ignore-without-code]"),
    ],
)
def test_type_check_covers_untyped_functions_and_ignores(project: Path, text: str, expected: str) -> None:
    config = project / "tidy_app" / "config.py"
    config.write_text(config.read_text() + text)
    code, out = shape(project, "check", "--only", "mypy")
    assert code == 1 and "[type-errors]" in out and expected in out, out


def test_layer_broken_shows_the_contract_guidance(project: Path) -> None:
    file, text, _ = VIOLATIONS["layer broken"]
    (project / file).write_text((project / file).read_text() + text)
    code, out = shape(project, "check", "--only", "import-linter")
    assert code == 1 and "contract says: A lower layer imported a higher one" in out, out


def test_contract_with_ignored_imports_still_fails(project: Path) -> None:
    # With ignore_imports, lint-imports prints "<name> BROKEN (1 ignored import)".
    pyproject = project / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text().replace(
            "exhaustive = true\n", 'exhaustive = true\nignore_imports = ["tidy_app.cli -> tidy_app.config"]\n'
        )
    )
    assert shape(project, "check", "--only", "import-linter")[0] == 0
    file, text, _ = VIOLATIONS["layer broken"]
    (project / file).write_text((project / file).read_text() + text)
    code, out = shape(project, "check", "--only", "import-linter")
    assert code == 1 and "[import-contracts]" in out and "Layers: entry point" in out, out


def test_contract_message_lists_every_group_of_offending_imports(project: Path) -> None:
    # lint-imports prints one group per illegal pair of layers; all of them must reach the agent
    config = project / "tidy_app" / "config.py"
    config.write_text(
        config.read_text()
        + "\nfrom tidy_app import cli\nfrom tidy_app.inventory import Inventory\n\nprint(cli, Inventory)\n"
    )
    code, out = shape(project, "check", "--only", "import-linter")
    assert code == 1 and "tidy_app.config -> tidy_app.cli" in out and "tidy_app.config -> tidy_app.inventory" in out, (
        out
    )


def test_a_type_error_swapped_for_another_is_new(project: Path) -> None:
    config = project / "tidy_app" / "config.py"
    original = config.read_text()
    config.write_text(original + "\n\ndef port() -> int:\n    return 'x'\n\n\nprint(port())\n")
    shape(project, "baseline", "--only", "mypy")
    assert shape(project, "check", "--only", "mypy")[0] == 0
    # fix that one, break another function in the same file: still one error in config.py
    config.write_text(original + "\n\ndef host() -> str:\n    return 1\n\n\nprint(host())\n")
    code, out = shape(project, "check", "--only", "mypy")
    assert code == 1 and "NEW: [type-errors]" in out and "host [return-value]" in out, out
    assert "Incompatible return value type" in out, out  # the agent sees what is wrong


def test_one_more_type_error_shows_the_new_one(project: Path) -> None:
    config = project / "tidy_app" / "config.py"
    body = "\n\ndef port(flag: bool) -> int:\n    if flag:\n        return 'x'\n{}    return 1\n\n\nprint(port(True))\n"
    config.write_text(config.read_text() + body.format(""))
    shape(project, "baseline", "--only", "mypy")
    config.write_text(config.read_text().replace("    return 1\n", "    return b'new'\n"))
    code, out = shape(project, "check", "--only", "mypy")
    assert code == 1 and "WORSE (was 1)" in out, out
    assert 'got "bytes", expected "int"' in out and 'got "str", expected "int"' in out, out


@pytest.mark.parametrize(
    "setting",
    [
        "[tool.mypy]\nignore_errors = true\n",
        '[tool.mypy]\ndisable_error_code = ["return-value"]\n',
        '[tool.mypy]\nexclude = ["config\\\\.py$"]\n',
        '[[tool.mypy.overrides]]\nmodule = "tidy_app.*"\nignore_errors = true\n',
        '[[tool.mypy.overrides]]\nmodule = "tidy_app.config"\ndisable_error_code = ["return-value"]\n',
    ],
)
def test_mypy_settings_that_hide_errors_are_left_out(project: Path, setting: str) -> None:
    pyproject = project / "pyproject.toml"
    pyproject.write_text(pyproject.read_text() + "\n" + setting)
    file, text, expected = VIOLATIONS["type error"]
    (project / file).write_text((project / file).read_text() + text)
    code, out = shape(project, "check", "--only", "mypy")
    assert code == 1 and expected in out and "port [return-value]" in out, out


@pytest.mark.parametrize("group", ["sizes", "ruff", "complexipy", "pylint", "graph", "vulture", "suppressions"])
def test_a_file_the_tool_cannot_parse_fails_the_check(project: Path, group: str) -> None:
    config = project / "tidy_app" / "config.py"
    config.write_text(config.read_text() + "\n\ndef broken(:\n    pass\n")
    code, out = shape(project, "check", "--only", group)
    assert code == 1 and "could not run" in out and "config.py" in out, out


def test_excluded_files_are_left_out_of_every_check(project: Path) -> None:
    generated = project / "tidy_app" / "inventory" / "generated_tables.py"
    generated.write_text(COMPLEX + "\n\ndef never_called() -> int:\n    return 1\n")
    assert shape(project)[0] == 1
    pyproject = project / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text().replace("[tool.shape]\n", '[tool.shape]\nexclude = ["tidy_app/*/generated_*"]\n')
    )
    code, out = shape(project)
    assert code == 0, out


def test_unknown_check_group_is_an_error(project: Path) -> None:
    code, out = shape(project, "check", "--only", "sizes,pylnt")
    assert code == 1 and "unknown check group(s) ['pylnt']" in out, out


def test_a_tracked_check_put_in_gates_is_enforced(project: Path) -> None:
    pyproject = project / "pyproject.toml"
    shape_config = '[tool.shape]\ngates = ["concept-spread"]\n'
    concepts = '[tool.shape.concepts]\nstock = ["stock"]\n[tool.shape.limits]\nconcept_files = 1\n'
    pyproject.write_text(pyproject.read_text().replace("[tool.shape]\n", shape_config) + concepts)
    code, out = shape(project)
    assert code == 1 and "[concept-spread]" in out, out


def test_trend_of_a_project_in_a_subfolder_of_the_repository(tmp_path: Path) -> None:
    project = tmp_path / "apps" / "tidy_app"
    shutil.copytree(EXAMPLE, project)
    pyproject = project / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace('packages = ["tidy_app"]', 'packages = ["tidy_app", "extra"]'))
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q"], check=True)
    for message in ("one", "two"):
        if message == "two":  # a second package that is newer than the first commit
            (project / "extra").mkdir()
            (project / "extra" / "__init__.py").write_text("")
        (project / "tidy_app" / "config.py").write_text((project / "tidy_app" / "config.py").read_text() + "\n")
        subprocess.run([*git, "add", "."], check=True)
        subprocess.run([*git, "commit", "-qm", message], check=True)
    out_file = tmp_path / "report.md"
    code, out = shape(project, "report", "--only", "sizes", "--trend", "2", "--out", str(out_file))
    assert code == 0, out
    assert "re-run on 2 past commits" in out_file.read_text(), out


def test_too_many_modules_in_one_folder(project: Path) -> None:
    for i in range(13):
        (project / "tidy_app" / "inventory" / f"part{i}.py").write_text(f'"""Part {i}."""\n')
    code, out = shape(project, "check", "--only", "sizes")
    assert code == 1 and "[package-files]" in out, out


def test_copy_paste_fails_and_says_where_each_copy_is(project: Path) -> None:
    starts = {}
    for file in ("tidy_app/cli.py", "tidy_app/inventory/service.py"):
        text = (project / file).read_text()
        starts[file] = text.count("\n") + 4  # the line of `total = 0`, the first copied line
        (project / file).write_text(text + DUPLICATE)
    code, out = shape(project, "check", "--only", "pylint")
    assert code == 1 and "[duplicate-code]" in out, out
    for file, start in starts.items():
        assert f"{file}:{start}-" in out, out


def test_a_known_copy_pasted_block_copied_once_more_fails(project: Path) -> None:
    # pylint itself lists only two of the files once a block is in three or more
    for file in ("tidy_app/cli.py", "tidy_app/inventory/service.py"):
        (project / file).write_text((project / file).read_text() + DUPLICATE)
    shape(project, "baseline", "--only", "pylint")
    assert shape(project, "check", "--only", "pylint")[0] == 0
    store = project / "tidy_app" / "inventory" / "store.py"
    store.write_text(store.read_text() + DUPLICATE)
    code, out = shape(project, "check", "--only", "pylint")
    assert code == 1 and "NEW: [duplicate-code]" in out and "store.py" in out, out
    assert "is fixed" not in out, out  # the old pair isn't fixed: it got one more copy


def test_removing_one_of_three_known_copies_is_an_improvement(project: Path) -> None:
    files = ("tidy_app/cli.py", "tidy_app/inventory/service.py", "tidy_app/inventory/store.py")
    originals = {file: (project / file).read_text() for file in files}
    for file in files:
        (project / file).write_text(originals[file] + DUPLICATE)
    shape(project, "baseline", "--only", "pylint")
    (project / files[0]).write_text(originals[files[0]])  # fix one copy: the key now names two files
    code, out = shape(project, "check", "--only", "pylint")
    assert code == 1 and "NEW" not in out and "IMPROVED" in out and "is now only" in out, out
    shape(project, "tighten", "--only", "pylint")
    assert shape(project, "check", "--only", "pylint")[0] == 0
    (project / files[1]).write_text(originals[files[1]])  # one copy left: no copy at all
    code, out = shape(project, "check", "--only", "pylint")
    assert code == 1 and "NEW" not in out and "is fixed" in out, out


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
    assert "uses it by name at runtime" in out and "If nothing does, delete it" in out, out
    assert "ask a human to approve a dead-code whitelist entry" in out, out

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


def test_baseline_location_setting_is_used_by_baseline_check_and_tighten(project: Path) -> None:
    pyproject = project / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text().replace("[tool.shape]\n", '[tool.shape]\nbaseline = "shape/known.json"\n')
    )
    service = project / "tidy_app" / "inventory" / "service.py"
    original = service.read_text()
    service.write_text(original + "# filler\n" * 520)

    shape(project, "baseline", "--only", "sizes")  # creates the missing folder
    configured = project / "shape" / "known.json"
    assert configured.exists() and not (project / ".code-shape-baseline.json").exists()
    assert shape(project, "check", "--only", "sizes")[0] == 0

    before = configured.read_text()
    service.write_text(original + "# filler\n" * 510)
    shape(project, "tighten", "--only", "sizes")
    assert configured.read_text() != before  # tightened in place
    assert shape(project, "check", "--only", "sizes")[0] == 0

    code, out = shape(project, "check", "--only", "sizes", "--baseline", str(project / "other.json"))
    assert code == 1 and "NEW" in out, out  # the command-line flag wins over the setting


def test_import_cycle_lists_the_imports_in_it(project: Path) -> None:
    inventory = project / "tidy_app" / "inventory"
    (inventory / "left.py").write_text("from tidy_app.inventory import right\n\nprint(right)\n")
    (inventory / "right.py").write_text("\nfrom tidy_app.inventory import left\n\nprint(left)\n")
    code, out = shape(project, "check", "--only", "graph")
    assert code == 1 and "[import-cycles]" in out, out
    assert "tidy_app.inventory.left -> tidy_app.inventory.right (l.1)" in out, out
    assert "tidy_app.inventory.right -> tidy_app.inventory.left (l.2)" in out, out


def test_fan_out_lists_the_imports(project: Path) -> None:
    pyproject = project / "pyproject.toml"
    pyproject.write_text(pyproject.read_text() + "\n[tool.shape.limits]\nfan_out = 1\n")
    code, out = shape(project, "check", "--only", "graph")
    assert code == 1 and "[fan-out]" in out and "imports tidy_app.config, tidy_app.inventory" in out, out


def test_baseline_keeps_the_entries_of_a_check_that_could_not_run_and_fails(project: Path) -> None:
    service = project / "tidy_app" / "inventory" / "service.py"
    service.write_text(service.read_text() + "\n\ndef never_called() -> int:\n    return 1\n")
    shape(project, "baseline", "--only", "vulture")
    recorded = project / ".code-shape-baseline.json"
    assert "never_called" in recorded.read_text()

    pyproject = project / "pyproject.toml"  # now vulture can't run: its whitelist is missing
    pyproject.write_text(
        pyproject.read_text().replace("[tool.shape]\n", '[tool.shape]\ndead_code_whitelist = ["gone.py"]\n')
    )
    code, out = shape(project, "baseline", "--only", "sizes,vulture")
    assert code == 1 and "could not run" in out and "entries for vulture were kept unchanged" in out, out
    assert "never_called" in recorded.read_text()


def test_python_version_supports_tar_filter() -> None:
    # trend.py extracts with tarfile's filter="data", added in Python 3.11.4
    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert pyproject["project"]["requires-python"].startswith(">=3.11.4")
