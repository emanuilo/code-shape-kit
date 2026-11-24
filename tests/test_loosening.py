"""`--base REF`: every rule loosened since REF is listed for a human, and never changes the exit code."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from test_gates import EXAMPLE, shape

from code_shape.loosening import _settings, _weaker
from code_shape.settings import parse

LOOSENED = "RULES LOOSENED since HEAD - needs human approval"
LIMITS = '[tool.shape]\npackages = ["app"]\n[tool.shape.limits]\n'


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """The example project, committed to a fresh git repository."""
    project = tmp_path / "tidy_app"
    shutil.copytree(EXAMPLE, project)
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    commit(project, "start")
    return project


def commit(project: Path, message: str) -> None:
    git = ["git", "-C", str(project), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", message], check=True)


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new, 1))


def test_nothing_loosened(repo: Path) -> None:
    code, out = shape(repo, "check", "--only", "sizes", "--base", "HEAD")
    assert code == 0 and "no rules loosened since HEAD" in out, out


def test_loosened_config_is_listed_and_does_not_change_the_exit_code(repo: Path) -> None:
    pyproject = repo / "pyproject.toml"
    shape_keys = (
        '[tool.shape]\nskip = ["mypy"]\nexclude = ["tidy_app/gen/*"]\ngates = ["file-lines"]\n'
        'dead_code_whitelist = ["whitelist.py"]\n'
    )
    edit(pyproject, "[tool.shape]\n", shape_keys)
    tables = (
        '\n[tool.shape.limits]\nfile_lines = 900\n[tool.shape.extra_args]\nvulture = ["--ignore-names", "x"]\n'
        "[tool.vulture]\nignore_names = ['on_*']\n"
    )
    pyproject.write_text(pyproject.read_text() + tables)
    edit(
        pyproject,
        'config_modules = ["tidy_app/config.py"]',
        'config_modules = ["tidy_app/config.py", "tidy_app/cli.py"]',
    )
    edit(pyproject, 'allowed = ["tidy_app/inventory/store.py"]', 'allowed = ["tidy_app/inventory/*"]')
    edit(pyproject, "exhaustive = true\n", 'exhaustive = false\nignore_imports = ["tidy_app.cli -> tidy_app.config"]\n')
    edit(
        pyproject, '[[tool.importlinter.contracts]]\nid = "store-private"', '[[tool.importlinter.contracts]]\nid = "x"'
    )
    edit(pyproject, 'name = "Only the inventory package talks to the storage adapter"', 'name = "Renamed"')
    (repo / "whitelist.py").write_text("Server.should_exit\n")
    service = repo / "tidy_app" / "inventory" / "service.py"
    service.write_text(service.read_text() + "\nLIMIT = 3  # noqa: E501\n")

    code, out = shape(repo, "check", "--only", "sizes", "--base", "HEAD")
    assert code == 0, out  # a warning only
    for expected in (
        LOOSENED,
        "`file_lines` raised from 500 to 900",
        "gates: no longer lists `class-lines`, `package-files`",
        "skip: added `mypy`",
        "exclude: added `tidy_app/gen/*`",
        "dead_code_whitelist: added `whitelist.py`",
        "dead-code whitelist whitelist.py: added `Server.should_exit`",
        "extra_args] vulture: added `--ignore-names`, `x`",
        "[tool.vulture] ignore_names: added `on_*`",
        "`tidy_app/cli.py` may now use os.environ, os.getenv, os.putenv",
        "`tidy_app/inventory/*` may now use json",
        "contract `Layers: entry point -> features -> config`: exhaustive switched off",
        "ignore_imports: added `tidy_app.cli -> tidy_app.config`",
        "contract `Only the inventory package talks to the storage adapter` removed",
        "tidy_app/inventory/service.py: 1 more `# noqa`",
    ):
        assert expected in out, f"{expected!r} missing in:\n{out}"


def test_new_and_raised_baseline_entries_are_listed(repo: Path) -> None:
    service = repo / "tidy_app" / "inventory" / "service.py"
    service.write_text(service.read_text() + "# filler\n" * 520)
    shape(repo, "baseline", "--only", "sizes")
    code, out = shape(repo, "check", "--only", "sizes", "--base", "HEAD")
    assert code == 0 and "baseline: new entry `file-lines|tidy_app/inventory/service.py|` (546)" in out, out

    commit(repo, "accept the debt")
    service.write_text(service.read_text() + "# more\n" * 10)
    shape(repo, "baseline", "--only", "sizes")
    code, out = shape(repo, "check", "--only", "sizes", "--base", "HEAD")
    assert code == 0 and "`file-lines|tidy_app/inventory/service.py|` raised from 546 to 556" in out, out


def test_a_failing_check_still_shows_the_warning_and_fails(repo: Path) -> None:
    pyproject = repo / "pyproject.toml"
    edit(pyproject, "[tool.shape]\n", '[tool.shape]\nskip = ["mypy"]\n')
    service = repo / "tidy_app" / "inventory" / "service.py"
    service.write_text(service.read_text() + "# filler\n" * 520)
    code, out = shape(repo, "check", "--only", "sizes", "--base", "HEAD")
    assert code == 1 and "[file-lines]" in out and "skip: added `mypy`" in out, out


def test_summary_file_and_report_get_the_warning(repo: Path) -> None:
    edit(repo / "pyproject.toml", "[tool.shape]\n", '[tool.shape]\nskip = ["mypy"]\n')
    summary = repo / "summary.md"
    code, out = shape(repo, "check", "--only", "sizes", "--base", "HEAD", "--summary", str(summary))
    assert code == 0, out
    assert "## Rules loosened since `HEAD` - needs human approval" in summary.read_text()
    report = repo / "report.md"
    shape(repo, "report", "--only", "sizes", "--base", "HEAD", "--out", str(report))
    assert "- [tool.shape] skip: added `mypy`" in report.read_text()


def test_no_git_or_unknown_ref_is_a_note(tmp_path: Path, repo: Path) -> None:
    code, out = shape(repo, "check", "--only", "sizes", "--base", "no-such-branch")
    assert code == 0 and "git ref `no-such-branch` not found" in out, out
    plain = tmp_path / "plain"
    shutil.copytree(EXAMPLE, plain)
    code, out = shape(plain, "check", "--only", "sizes", "--base", "origin/main")
    assert code == 0 and "not in a git repository" in out, out


def test_base_is_only_for_check_and_report(repo: Path) -> None:
    code, out = shape(repo, "baseline", "--base", "HEAD")
    assert code == 1 and "--base and --summary work with check and report only" in out, out


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ({"type": "layers", "layers": ["a", "b"]}, {"type": "layers", "layers": ["a"]}, "layers: no longer lists `b`"),
        ({"type": "layers"}, {"type": "independence"}, "type changed from `layers` to `independence`"),
        ({"type": "forbidden"}, {"type": "forbidden", "allow_indirect_imports": True}, "allow_indirect_imports"),
        ({"allowed_importers": ["a"]}, {"allowed_importers": ["a", "b"]}, "allowed_importers: added `b`"),
        ({}, {"unmatched_ignore_imports_alerting": "none"}, "changed from `error` to `none`"),
        ({"layers": ["a", "b | c"]}, {"layers": ["a", "b"]}, "layers: no longer lists `c`"),
        ({"layers": ["a", "b"]}, {"layers": ["b", "a"]}, "layers: `b` may now import `a`"),
        ({"layers": ["a", "b | c"]}, {"layers": ["a", "b : c"]}, "`b` may now import `c`, `c` may now import `b`"),
        ({"layers": ["a", "b | c"]}, {"layers": ["a", "b", "c"]}, "layers: `b` may now import `c`"),
        ({"layers": ["a", "b"]}, {"layers": ["a : b"]}, "layers: `b` may now import `a`"),
    ],
)
def test_weaker_contracts(old: dict, new: dict, expected: str) -> None:
    assert any(expected in change for change in _weaker(old, new)), _weaker(old, new)


def test_stricter_contracts_are_not_listed() -> None:
    old = {"type": "layers", "layers": ["a"], "ignore_imports": ["a -> b"], "exhaustive": False}
    new = {"type": "layers", "layers": ["a", "b"], "ignore_imports": [], "exhaustive": True}
    assert _weaker(old, new) == []


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (["api", "services | reports", "db"], ["api", "services | reports | reports_part2", "db"]),
        (["api", "services : reports"], ["api", "services | reports"]),  # now independent
        (["api", "services | reports"], ["api", "(services) | reports", "extra"]),
        (["a", "b"], ["a | b"]),  # b still may not import a, and a may no longer import b
    ],
)
def test_a_layer_that_gains_a_module_or_a_constraint_is_not_listed(old: list[str], new: list[str]) -> None:
    assert _weaker({"type": "layers", "layers": old}, {"type": "layers", "layers": new}) == []


def test_looser_tool_configs_are_listed(repo: Path) -> None:
    pyproject = repo / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text()
        + '\n[tool.mypy]\nignore_missing_imports = true\n[[tool.mypy.overrides]]\nmodule = ["lib.*"]\n'
        'ignore_missing_imports = true\n[tool.vulture]\nexclude = ["tidy_app/cli.py"]\n'
        '[tool.deptry]\nignore = ["DEP002"]\nper_rule_ignores = {DEP001 = ["requests"]}\n'
    )
    code, out = shape(repo, "check", "--only", "sizes", "--base", "HEAD")
    assert code == 0, out
    for expected in (
        "[tool.mypy] ignore_missing_imports switched on",
        "[tool.mypy] ignore_missing_imports for: added `lib.*`",
        "[tool.vulture] exclude: added `tidy_app/cli.py`",
        "[tool.deptry] ignore: added `DEP002`",
        "[tool.deptry] per_rule_ignores DEP001: added `requests`",
    ):
        assert expected in out, f"{expected!r} missing in:\n{out}"


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("file_lines = 500", "file_lines = 900", "`file_lines` raised from 500 to 900"),
        ("dead_code_confidence = 60", "dead_code_confidence = 90", "`dead_code_confidence` raised from 60 to 90"),
        ("duplicate_lines = 10", "duplicate_lines = 20", "`duplicate_lines` raised from 10 to 20"),
        ("coupling_min_shared = 3", "coupling_min_shared = 5", "`coupling_min_shared` raised from 3 to 5"),
        # fewer commits read is fewer coupled files: lower is looser here
        ("history_days = 365", "history_days = 30", "`history_days` lowered from 365 to 30"),
        ("max_changeset_files = 30", "max_changeset_files = 5", "`max_changeset_files` lowered from 30 to 5"),
        # stricter, not looser
        ("file_lines = 500", "file_lines = 400", None),
        ("history_days = 365", "history_days = 730", None),
        ("max_changeset_files = 30", "max_changeset_files = 60", None),
    ],
)
def test_only_looser_limits_are_listed(tmp_path: Path, old: str, new: str, expected: str | None) -> None:
    config = tmp_path / "pyproject.toml"
    before, after = (parse(tmp_path, config, f"{LIMITS}{limit}\n") for limit in (old, new))
    assert _settings(before, after) == ([f"[tool.shape.limits] {expected}"] if expected else [])


def test_a_new_logger_object_is_listed(tmp_path: Path) -> None:
    config = tmp_path / "pyproject.toml"
    before = parse(tmp_path, config, '[tool.shape]\npackages = ["app"]\n')
    after = parse(tmp_path, config, '[tool.shape]\npackages = ["app"]\nlogger_objects = ["app.log.logger"]\n')
    assert _settings(before, after) == [
        "[tool.shape] logger_objects (their logger.exception passes swallowed-errors): added `app.log.logger`"
    ]
    assert _settings(after, before) == []  # dropping one is stricter
