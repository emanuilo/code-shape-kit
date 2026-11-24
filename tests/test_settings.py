import re
from pathlib import Path

import pytest

from code_shape.checks.concepts import _co_changes
from code_shape.checks.history import Commit
from code_shape.settings import load


def project(tmp_path: Path, shape: str) -> Path:
    (tmp_path / "app").mkdir(parents=True)
    (tmp_path / "app" / "__init__.py").write_text("")
    (tmp_path / "pyproject.toml").write_text(f'[tool.shape]\npackages = ["app"]\n{shape}')
    return tmp_path


@pytest.mark.parametrize(
    ("shape", "message"),
    [
        ('gates = ["file-line"]\n', "unknown check `file-line` in gates"),
        ('excludes = ["app/gen/*"]\n', "unknown setting `excludes`"),
        ("[tool.shape.limits]\nfile_line = 300\n", "unknown limit `file_line`"),
        ('logger_objects = ["logger"]\n', "`logger_objects` must list import paths"),
        ("logger_objects = 3\n", "`logger_objects` must list import paths"),
    ],
)
def test_a_typo_in_the_config_is_an_error(tmp_path: Path, shape: str, message: str) -> None:
    with pytest.raises(SystemExit, match=message):
        load(project(tmp_path, shape))


def test_a_missing_config_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="config file not found"):
        load(project(tmp_path, ""), tmp_path / "shape.toml")


def test_short_forms_are_normalized(tmp_path: Path) -> None:
    settings = load(
        project(
            tmp_path,
            '[tool.shape.banned_api]\nrequests = { allowed = "app/http.py" }\n'
            '[tool.shape.concepts]\nrefunds = "refund"\n',
        )
    )
    assert settings.banned_api["requests"]["allowed"] == ["app/http.py"]
    assert settings.banned_api["requests"]["msg"]
    assert settings.concepts["refunds"] == {"terms": ["refund"], "home": ""}  # not r|e|f|u|n|d


def test_packages_are_only_guessed_when_there_is_one(tmp_path: Path) -> None:
    for name in ("app", "tools"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "__init__.py").write_text("")
    with pytest.raises(SystemExit, match="found app, tools"):  # don't quietly check only `app`
        load(tmp_path)
    (tmp_path / "tools" / "__init__.py").unlink()
    assert load(tmp_path).packages == ["app"]


@pytest.mark.parametrize(
    ("shape", "message"),
    [
        ('[tool.shape.concepts]\nbad = ["refund("]\n', "concept `bad`: `refund\\(` is not a valid regex"),
        ('[tool.shape.concepts]\nrefunds = { terms = ["refund"], home = "app/refunds.py" }\n', "does not exist"),
    ],
)
def test_bad_concepts_are_an_error(tmp_path: Path, shape: str, message: str) -> None:
    with pytest.raises(SystemExit, match=message):
        load(project(tmp_path, shape))


def test_a_concept_home_can_be_a_package(tmp_path: Path) -> None:
    root = project(tmp_path, '[tool.shape.concepts]\nrefunds = { terms = ["refund"], home = "app/refunds" }\n')
    (root / "app" / "refunds").mkdir()
    assert load(root).concepts["refunds"]["home"] == "app/refunds"
    history = [
        Commit("1", "2026-01-01", "", ("app/refunds/policy.py", "app/refunds/store.py", "app/cli.py")),
        Commit("2", "2026-01-02", "", ("app/refunds/policy.py",)),
        Commit("3", "2026-01-03", "", ("app/cli.py",)),
    ]
    assert _co_changes("app/refunds", history, 30) == [2, 0.5, "cli.py (1)"]


def test_logger_objects_are_added_to_loguru(tmp_path: Path) -> None:
    assert load(project(tmp_path / "plain", "")).tools.logger_objects == ["loguru.logger"]
    settings = load(project(tmp_path / "own", 'logger_objects = "app.log.logger"\n'))
    assert settings.tools.logger_objects == ["loguru.logger", "app.log.logger"]


@pytest.mark.parametrize(
    ("shape", "message"),
    [
        ('[tool.shape.error_boundaries]\n"app/sync.py:loop" = ""\n', "`app/sync.py:loop` needs a reason"),
        ('[tool.shape.error_boundaries]\n"app/sync.py:loop" = "  "\n', "`app/sync.py:loop` needs a reason"),
        ('[tool.shape.error_boundaries]\n"app/sync.py:loop" = 3\n', "`app/sync.py:loop` needs a reason"),
        ('[tool.shape.error_boundaries]\n"app/sync.py" = "the whole file"\n', "must name one function"),
        ('[tool.shape.error_boundaries]\n"app/sync.py:" = "x"\n', "must name one function"),
        ('[tool.shape.error_boundaries]\n"app/sync.py:Sync.loop()" = "x"\n', "must name one function"),
        ('[tool.shape.error_boundaries]\n"app/gone.py:loop" = "x"\n', "file `app/gone.py` does not exist"),
        ('error_boundaries = ["app/sync.py:loop"]\n', "`error_boundaries` must be a table"),
    ],
)
def test_bad_error_boundaries_are_an_error(tmp_path: Path, shape: str, message: str) -> None:
    root = project(tmp_path, shape)
    (root / "app" / "sync.py").write_text("")
    with pytest.raises(SystemExit, match=re.escape(message)):
        load(root)


def test_error_boundaries_are_read(tmp_path: Path) -> None:
    root = project(tmp_path, '[tool.shape.error_boundaries]\n"app/sync.py:Sync.loop.inner" = " offline often "\n')
    (root / "app" / "sync.py").write_text("")
    assert load(root).tools.error_boundaries == {"app/sync.py:Sync.loop.inner": "offline often"}


def test_a_package_that_does_not_exist_is_one_clear_error(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.shape]\npackages = ["shop", "app.sub"]\n')
    (tmp_path / "app").mkdir()
    with pytest.raises(SystemExit) as error:
        load(tmp_path)
    message = str(error.value)
    assert "package `shop`: folder `shop` does not exist (packages are looked for in the project root" in message
    assert "package `app.sub`: folder `app/sub` does not exist" in message
    (tmp_path / "src" / "shop").mkdir(parents=True)  # the src/ layout: found there, not at the root
    (tmp_path / "pyproject.toml").write_text('[tool.shape]\npackages = ["shop", "lib"]\n')
    with pytest.raises(
        SystemExit, match=re.escape("package `lib`: folder `src/lib` does not exist (packages are looked for in `src/`")
    ):
        load(tmp_path)
