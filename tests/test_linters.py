"""How the kit reads tool output that the example-project tests can't easily produce."""

import tomllib
from pathlib import Path

import pytest

from code_shape.checks import run_all
from code_shape.checks.linters import ToolError, program, pylint_checks
from code_shape.checks.linters.contracts import _contract_sections, _contract_verdicts
from code_shape.settings import load

EXAMPLE = Path(__file__).parents[1] / "examples" / "tidy_app"

LINT_IMPORTS = """
---------
Contracts
---------

Analyzed 7 files, 7 dependencies.
---------------------------------

Layers BROKEN (1 ignored import)
Layers for the api KEPT (2 ignored imports, 1 warning)

Contracts: 1 kept, 1 broken.


----------------
Broken contracts
----------------

Layers
------

app.config is not allowed to import app.cli:

- app.config -> app.cli (l.3)


Move the shared code down a layer.

"""


def test_contract_results_with_ignored_imports_are_read() -> None:
    # import-linter adds "(N ignored imports)" to the result line once ignore_imports is used
    assert _contract_verdicts(LINT_IMPORTS) == (["Layers for the api"], ["Layers"])
    sections = _contract_sections(LINT_IMPORTS.split("Broken contracts", 1)[-1], ["Layers"])
    assert "- app.config -> app.cli (l.3)" in sections["Layers"]


def test_contract_results_that_do_not_add_up_are_an_error() -> None:
    with pytest.raises(ToolError):
        _contract_verdicts(LINT_IMPORTS.replace("Layers BROKEN (1 ignored import)", "Layers BROKEN?"))
    with pytest.raises(ToolError):
        _contract_verdicts("Contract options are invalid")


def test_tool_output_in_an_unexpected_format_is_a_check_that_could_not_run(monkeypatch: pytest.MonkeyPatch) -> None:
    # e.g. another pylint version: the group reports an error instead of crashing the whole run
    monkeypatch.setattr(pylint_checks, "run", lambda *args, **kwargs: '{"messages": [{"kind": "new"}]}')
    [result] = run_all(load(EXAMPLE), ["pylint"])
    assert "pylint output is not in the format the kit expects" in result.error


def test_mypy_config_keeps_the_project_settings_that_do_not_hide_errors(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[tool.shape]\npackages = ["app"]\n'
        '[tool.mypy]\nstrict = true\nignore_errors = true\nplugins = ["pydantic.mypy", "tools/plugin.py:hook"]\n'
        'mypy_path = "$MYPY_CONFIG_FILE_DIR/stubs"\n'
        '[[tool.mypy.overrides]]\nmodule = ["lib.*"]\nignore_missing_imports = true\nignore_errors = true\n'
        "[tool.pydantic-mypy]\ninit_typed = true\n"
    )
    config = tomllib.loads(program._mypy_config(load(tmp_path), tmp_path).read_text())["tool"]
    assert config["mypy"] == {
        "strict": True,
        "plugins": ["pydantic.mypy", f"{tmp_path}/tools/plugin.py:hook"],
        "mypy_path": f"{tmp_path}/stubs",
        "overrides": [{"module": ["lib.*"], "ignore_missing_imports": True}],
    }
    assert config["pydantic-mypy"] == {"init_typed": True}  # plugins read their settings from the same file
