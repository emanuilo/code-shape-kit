"""`code-shape init`: best guesses written into a project, never over what is there."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from code_shape import __version__
from code_shape.checks import run_all
from code_shape.cli import main
from code_shape.init import plan
from code_shape.settings import load

PYPROJECT = '# my project\n[project]\nname = "shop"\nversion = "0.1.0"\n\n[tool.ruff]\nline-length = 99  # mine\n'

# api -> orders | inventory -> db -> config, and config reads the environment
SHOP = {
    "shop/__init__.py": "",
    "shop/config.py": "import os\n\nURL = os.environ.get('URL', '')\n",
    "shop/db/__init__.py": "",
    "shop/db/store.py": "from shop.config import URL\n\n\ndef save(x: str) -> str:\n    return URL + x\n",
    "shop/orders/__init__.py": "",
    "shop/orders/service.py": "from shop.db.store import save\n\n\ndef place(x: str) -> str:\n    return save(x)\n",
    "shop/inventory/__init__.py": "",
    "shop/inventory/stock.py": "from shop.db import store\n\n\ndef restock(x: str) -> str:\n    return store.save(x)\n",
    "shop/api.py": "from shop.inventory.stock import restock\nfrom shop.orders.service import place\n\n"
    "\ndef handle(x: str) -> list[str]:\n    return [place(x), restock(x)]\n",
}


def make(root: Path, files: dict[str, str], pyproject: str | None = PYPROJECT) -> Path:
    if pyproject is not None:
        (root / "pyproject.toml").write_text(pyproject)
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    return root


def init(root: Path, *flags: str) -> int:
    return main(["init", "--root", str(root), *flags])


def contracts_kept(root: Path) -> None:
    """The written config loads, and import-linter can read and keep the contracts."""
    [result] = run_all(load(root), ["import-linter"])
    assert not result.error, result.error
    assert not result.findings, result.findings
    assert result.metrics["architecture contracts kept"] >= 1


def test_existing_code_gets_layers_from_its_imports(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = make(tmp_path, SHOP)
    assert init(root) == 0
    out = capsys.readouterr().out
    assert "layers in shop: api -> inventory | orders -> db -> config" in out
    assert "code-shape baseline" in out  # existing code: the next step is a baseline
    config = tomllib.loads((root / "pyproject.toml").read_text())
    layers = config["tool"]["importlinter"]["contracts"][0]
    assert layers["layers"] == ["api", "inventory | orders", "db", "config"]
    assert layers["containers"] == ["shop"] and layers["exhaustive"] is True
    assert "ignore_imports" not in layers
    assert len(config["tool"]["importlinter"]["contracts"]) == 1  # the template's other examples are comments
    assert config["tool"]["shape"]["packages"] == ["shop"]
    assert config["tool"]["shape"]["config_modules"] == ["shop/config.py"]
    contracts_kept(root)


def test_an_import_cycle_is_listed_not_hidden(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    files = {
        **SHOP,
        "shop/db/store.py": SHOP["shop/db/store.py"] + "\nfrom shop.orders import service\n",
        "shop/orders/models.py": "from shop.db import store\n",  # orders imports db twice, db imports orders once
    }
    root = make(tmp_path, files)
    init(root)
    out = capsys.readouterr().out
    assert "import cycles: 1 import(s)" in out and "shop.db.store -> shop.orders.service" in out
    layers = tomllib.loads((root / "pyproject.toml").read_text())["tool"]["importlinter"]["contracts"][0]
    assert layers["layers"] == ["api", "inventory | orders", "db", "config"]
    assert layers["ignore_imports"] == ["shop.db.store -> shop.orders.service"]
    contracts_kept(root)


def test_a_new_project_gets_a_skeleton_that_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = make(tmp_path, {"shop/__init__.py": ""})
    init(root)
    out = capsys.readouterr().out
    assert "starter skeleton" in out and "No baseline needed" in out
    config = tomllib.loads((root / "pyproject.toml").read_text())
    layers = config["tool"]["importlinter"]["contracts"][0]["layers"]
    assert layers[0] == "(cli) | (api)"  # optional until the modules exist
    assert "config_modules" not in config["tool"]["shape"]  # a commented example: nothing to pick yet
    assert '# config_modules = ["shop/config.py"]' in (root / "pyproject.toml").read_text()
    contracts_kept(root)


def test_no_package_yet_uses_the_project_name_as_a_placeholder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make(tmp_path, {}, pyproject='[project]\nname = "my-shop"\n')
    result = plan(root)
    assert result.project.packages == ["my_shop"] and not result.project.found
    assert init(root) == 0  # init still writes the config
    assert "Create the package `my_shop` (my_shop/__init__.py)" in capsys.readouterr().out
    assert tomllib.loads((root / "pyproject.toml").read_text())["tool"]["shape"]["packages"] == ["my_shop"]
    with pytest.raises(SystemExit, match=r"package `my_shop`: folder `my_shop` does not exist"):
        load(root)  # check stops with one clear error until the package exists
    (root / "my_shop").mkdir()
    (root / "my_shop/__init__.py").write_text("")
    contracts_kept(root)


ENV = "import os\n\nX = os.getenv('X')\n"


def picked(root: Path, files: dict[str, str]) -> str:
    root.mkdir()
    files = {"shop/__init__.py": "", **{f"shop/{name}": text for name, text in files.items()}}
    return plan(make(root, files)).project.config_module


def test_config_modules_is_only_the_obvious_settings_module(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    files = {
        **SHOP,
        "shop/api.py": SHOP["shop/api.py"] + "\nfrom os import environ\n\nDEBUG = environ.get('DEBUG')\n",
        "shop/c.py": "environ = {}\nZ = environ.get('Z')\n",  # a name, not the environment
        "shop/d.py": "import os\n\nP = os.path.join('a', 'b')\n",
    }
    root = make(tmp_path, files)
    init(root)
    out = capsys.readouterr().out
    assert "config modules:  shop/config.py (named config.py)" in out
    assert "other modules that read the environment (1)" in out and "shop/api.py (1 read(s))" in out
    assert tomllib.loads((root / "pyproject.toml").read_text())["tool"]["shape"]["config_modules"] == ["shop/config.py"]
    [result] = run_all(load(root), ["ruff"])
    assert {(f.check, f.path) for f in result.findings if f.check == "banned-api"} == {("banned-api", "shop/api.py")}


def test_the_settings_module_is_picked_by_name_or_by_clearly_most_reads(tmp_path: Path) -> None:
    assert picked(tmp_path / "a", {"settings.py": "", "b.py": ENV}) == "shop/settings.py"  # by name
    assert picked(tmp_path / "b", {"env.py": ENV, "conf.py": "", "b.py": ENV}) == "shop/env.py"  # the named reader
    assert picked(tmp_path / "c", {"a.py": ENV + "Y = os.environ['Y']\n", "b.py": ENV}) == "shop/a.py"  # 2 > 1
    assert picked(tmp_path / "d", {"a.py": ENV, "b.py": ENV}) == ""  # a tie: no obvious one
    assert picked(tmp_path / "e", {"config.py": ENV, "settings.py": ENV}) == ""  # two named


def test_no_obvious_settings_module_leaves_an_example(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = make(tmp_path, {"shop/__init__.py": "", "shop/a.py": ENV, "shop/b.py": ENV})
    init(root)
    out = capsys.readouterr().out
    assert "none picked: no obvious settings module" in out and "shop/a.py (1 read(s))" in out
    text = (root / "pyproject.toml").read_text()
    assert "config_modules" not in tomllib.loads(text)["tool"]["shape"]
    assert '# config_modules = ["shop/config.py"]  # no obvious settings module' in text


def test_src_layout(tmp_path: Path) -> None:
    root = make(tmp_path, {f"src/{name}": text for name, text in SHOP.items()})
    init(root)
    shape = tomllib.loads((root / "pyproject.toml").read_text())["tool"]["shape"]
    assert shape["src"] == "src" and shape["config_modules"] == ["src/shop/config.py"]
    text = (root / "pyproject.toml").read_text()
    assert '"src/shop/sync.py:Syncer._loop"' in text and '"shop/' not in text  # the examples' paths too
    settings = load(root)
    assert settings.src == root / "src" and settings.packages == ["shop"]
    contracts_kept(root)


def test_never_overwrites(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pyproject = PYPROJECT + '\n[tool.shape]\npackages = ["shop"]  # keep me\n'
    root = make(tmp_path, {**SHOP, ".github/workflows/code-shape.yml": "mine\n", "CODEOWNERS": "* @me\n"}, pyproject)
    init(root)
    out = capsys.readouterr().out
    text = (root / "pyproject.toml").read_text()
    assert text.startswith(pyproject)  # the user's text, comments and all, is untouched
    assert text.count("[tool.shape]") == 1 and "[tool.importlinter]" in text
    assert (root / ".github/workflows/code-shape.yml").read_text() == "mine\n"
    assert not (root / ".github/CODEOWNERS").exists()  # GitHub would read only one of them
    assert "[tool.shape]: already there" in out and "you have CODEOWNERS" in out
    capsys.readouterr()
    init(root)
    assert "Nothing to add" in capsys.readouterr().out
    assert (root / "pyproject.toml").read_text() == text


def test_an_existing_tool_shape_says_where_the_code_is(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pyproject = PYPROJECT + '\n[tool.shape]\nsrc = "lib"\npackages = ["shop"]\n'
    root = make(tmp_path, {f"lib/{name}": text for name, text in SHOP.items()}, pyproject)
    init(root)
    assert "layers in shop: api -> inventory | orders -> db -> config" in capsys.readouterr().out
    importlinter = tomllib.loads((root / "pyproject.toml").read_text())["tool"]["importlinter"]
    assert importlinter["root_package"] == "shop"
    contracts_kept(root)


def test_dry_run_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = make(tmp_path, SHOP)
    assert init(root, "--dry-run") == 0
    out = capsys.readouterr().out
    assert "dry run: nothing written" in out and "----- pyproject.toml (appended to the end) -----" in out
    assert (root / "pyproject.toml").read_text() == PYPROJECT
    assert not (root / ".github").exists()


def test_github_files(tmp_path: Path) -> None:
    root = make(tmp_path, SHOP)
    init(root)
    workflow = (root / ".github/workflows/code-shape.yml").read_text()
    assert f"code-shape-kit@v{__version__}" in workflow and "KIT" not in workflow
    assert workflow.count("pip install -e . ") == 2
    assert workflow.count('python-version: "3.12"') == 2  # no requires-python: the default
    codeowners = (root / ".github/CODEOWNERS").read_text()
    assert "@your-org/architects" in codeowners and "Copy to" not in codeowners
    assert codeowners.startswith('# Turn on "Require review from Code Owners" in the\n# branch protection rules. Then')


@pytest.mark.parametrize(
    ("requires", "python"),
    [
        (">=3.11.4", "3.11"),
        (">=3.13,<4", "3.13"),
        (">=3.8", "3.11"),  # the kit needs 3.11+
        ("~=3.12.1", "3.12"),
        ("==3.14.*", "3.14"),
        (">=3.11, !=3.11.*", "3.12"),
        ("<3.10", "3.12"),  # nothing the kit runs on: the default
        ("bogus", "3.12"),
    ],
)
def test_ci_python_comes_from_requires_python(tmp_path: Path, requires: str, python: str) -> None:
    root = make(tmp_path, SHOP, pyproject=f'[project]\nname = "shop"\nrequires-python = "{requires}"\n')
    result = plan(root)
    workflow = next(w.text for w in result.writes if w.path == ".github/workflows/code-shape.yml")
    assert workflow.count(f'python-version: "{python}"') == 2
    derived = result.project.python_why.startswith("the lowest")
    assert derived == (requires not in ("<3.10", "bogus"))  # the summary says where the version came from


def test_without_pyproject_it_stops(tmp_path: Path) -> None:
    make(tmp_path, SHOP, pyproject=None)
    with pytest.raises(SystemExit, match="no pyproject.toml"):
        init(tmp_path)
    assert list(tmp_path.iterdir()) == [tmp_path / "shop"]


def test_init_options(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="--dry-run works with init only"):
        main(["check", "--dry-run", "--root", str(tmp_path)])
    with pytest.raises(SystemExit, match="init takes only --root"):
        main(["init", "--only", "sizes", "--root", str(tmp_path)])
